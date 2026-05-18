"""Process pool orchestration for media jobs."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from rich.logging import RichHandler
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from .media.base import JobResult, MediaJob
from .media.photo import process_photo
from .media.video import process_video

logger = logging.getLogger("process_media.runner")


def _worker_init(log_level: int) -> None:
    """Configure each worker process.

    Three things happen here:

    1. The worker starts its own process group via ``os.setsid()``. This
       guarantees that any subprocess we launch later (ffmpeg, exiftool)
       inherits the same PGID, which lets the parent kill the **whole
       group** with ``os.killpg`` on Ctrl+C. Without this, sending
       SIGTERM to the worker would leave ffmpeg orphaned and running.
    2. SIGINT is ignored: the main process orchestrates cancellation by
       signalling the worker explicitly. Without this every worker would
       raise ``KeyboardInterrupt`` and pollute the logs.
    3. Logging is configured from scratch (``ProcessPoolExecutor`` spawns
       fresh interpreters, or forks before the main process configured
       logging on some platforms), so warnings and exception tracebacks
       emitted from worker code reach the user.
    """
    try:
        os.setsid()
    except (PermissionError, OSError):
        # Already a session leader (rare) or unsupported platform — keep going.
        pass

    signal.signal(signal.SIGINT, signal.SIG_IGN)

    root = logging.getLogger()
    # Reset any inherited config (Linux fork).
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = RichHandler(
        rich_tracebacks=True,
        show_path=False,
        show_time=False,
        markup=False,
    )
    handler.setLevel(log_level)
    root.addHandler(handler)
    root.setLevel(log_level)


def _execute(job: MediaJob) -> JobResult:
    """Worker entry point: must live at module level so it's picklable."""
    try:
        if job.media_type == "photo":
            return process_photo(job)
        elif job.media_type == "video":
            return process_video(job)
        else:
            return JobResult(job=job, success=False, error=f"unknown media_type {job.media_type!r}")
    except Exception as exc:  # pragma: no cover - defensive
        # Bake the traceback into the result so it survives pickling back
        # to the parent. ``logger.exception`` in the worker also emits it.
        logging.getLogger("process_media.worker").exception(
            "Unhandled error in %s job for %s", job.media_type, job.source
        )
        return JobResult(
            job=job,
            success=False,
            error=f"{exc}\n{traceback.format_exc()}",
        )


def _kill_pool(executor: ProcessPoolExecutor) -> None:
    """Forcefully terminate every worker **and its subprocess descendants**.

    Each worker calls ``os.setsid`` in :func:`_worker_init`, so the worker
    PID equals the PGID of every process it spawns (ffmpeg, exiftool…).
    Sending SIGTERM to that process group brings down ffmpeg cleanly
    instead of leaving it orphaned at full CPU after a Ctrl+C.
    """
    procs = getattr(executor, "_processes", None) or {}
    for proc in list(procs.values()):
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            # Worker may have already exited; fall back to per-PID kill.
            try:
                os.kill(proc.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass


def _reset_tty() -> None:
    """Run ``stty sane`` when attached to a TTY.

    ffmpeg sometimes leaves the terminal in an odd state (echo off, raw mode)
    after being interrupted, so we restore a sane terminal mode at the end
    of a run and inside the SIGINT handler.
    """
    if not sys.stdin.isatty():
        return
    try:
        subprocess.run(
            ["stty", "sane"],
            check=False,
            stdin=None,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def _clean_stale_tempfiles(jobs: list[MediaJob]) -> None:
    """Remove ``process-media_tmp.*`` files left over by a previous crash.

    The video pipeline writes through ``_tempfile`` context managers that
    normally unlink their files on exit. A hard kill (SIGTERM, SIGKILL,
    machine power-off) interrupts that cleanup, leaving stray temp files
    next to the eventual target. They never overwrite the real target so
    they are not a correctness issue — just clutter that we clear up here.
    """
    seen: set[Path] = set()
    for job in jobs:
        parent = job.target.parent
        if parent in seen:
            continue
        seen.add(parent)
        if not parent.is_dir():
            continue
        for stale in parent.glob("process-media_tmp.*"):
            try:
                stale.unlink()
                logger.debug("Removed stale tempfile %s", stale)
            except OSError:
                pass


def run_jobs(
    jobs: list[MediaJob],
    *,
    max_workers: int = 0,
    batch: bool = False,
) -> tuple[int, int]:
    """Submit all ``jobs`` to a process pool, return ``(ok_count, error_count)``."""
    if not jobs:
        return (0, 0)

    _clean_stale_tempfiles(jobs)

    if max_workers <= 0:
        max_workers = os.cpu_count() or 1
    max_workers = min(max_workers, len(jobs))

    ok = 0
    err = 0

    log_level = logging.getLogger().getEffectiveLevel()
    executor = ProcessPoolExecutor(
        max_workers=max_workers,
        initializer=_worker_init,
        initargs=(log_level,),
    )
    previous_handler = signal.getsignal(signal.SIGINT)
    interrupted = False

    def _on_sigint(_signum, _frame) -> None:
        nonlocal interrupted
        if interrupted:
            # Second Ctrl+C: restore default and let it propagate.
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            os.kill(os.getpid(), signal.SIGINT)
            return
        interrupted = True
        logger.warning("Interrupted by user, terminating workers…")
        _kill_pool(executor)
        # cancel pending tasks (won't touch running ones, but we just killed those)
        try:
            executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

    signal.signal(signal.SIGINT, _on_sigint)

    try:
        futures = {executor.submit(_execute, job): job for job in jobs}

        if batch:
            for future in as_completed(futures):
                ok, err = _collect(future, futures[future], ok, err)
        else:
            with _progress() as progress:
                task = progress.add_task("Processing", total=len(futures))
                for future in as_completed(futures):
                    ok, err = _collect(future, futures[future], ok, err)
                    progress.advance(task)
    finally:
        signal.signal(signal.SIGINT, previous_handler)
        # If we were interrupted, workers are gone — don't wait.
        executor.shutdown(wait=not interrupted)
        _reset_tty()
        if interrupted:
            raise KeyboardInterrupt

    return (ok, err)


def _collect(future, job: MediaJob, ok: int, err: int) -> tuple[int, int]:
    try:
        result = future.result()
    except Exception as exc:
        logger.error("Job %s crashed: %s", job.source, exc)
        return (ok, err + 1)

    if result.success:
        if result.skipped:
            logger.info("[%s] skipped %s", job.format_name, job.target.name)
        else:
            logger.info(
                "[%s] %s -> %s (%.2fs)",
                job.format_name,
                job.source.name,
                job.target,
                result.duration,
            )
        return (ok + 1, err)

    logger.error("[%s] %s failed: %s", job.format_name, job.source.name, result.error)
    return (ok, err + 1)


def _progress() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        transient=False,
    )
