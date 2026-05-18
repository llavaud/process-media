"""Process pool orchestration for media jobs."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Callable

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


_DISPATCH: dict[str, Callable[[MediaJob], JobResult]] = {
    "photo": process_photo,
    "video": process_video,
}


def _worker_init(log_level: int) -> None:
    """Configure logging inside each worker process.

    ``ProcessPoolExecutor`` spawns fresh interpreters (or forks before the
    main process configured logging on some platforms), so warnings and
    exception tracebacks emitted from worker code would otherwise be lost.
    """
    # Ignore SIGINT in workers: the main process orchestrates cancellation
    # by killing children explicitly. Without this, every worker would
    # raise KeyboardInterrupt and pollute the logs.
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
    handler = _DISPATCH.get(job.media_type)
    if handler is None:
        return JobResult(
            job=job,
            success=False,
            error=f"unknown media_type {job.media_type!r}",
        )
    try:
        return handler(job)
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
    """Forcefully terminate all worker processes (and their ffmpeg children)."""
    procs = getattr(executor, "_processes", None) or {}
    for proc in list(procs.values()):
        try:
            # SIGTERM the worker; subprocess.run() inside it has the ffmpeg
            # child in the same process group, which receives SIGTERM too
            # on Linux thanks to ``start_new_session=False`` (the default).
            os.kill(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass


def _reset_tty() -> None:
    """Run ``stty sane`` when attached to a TTY.

    ffmpeg sometimes leaves the terminal in an odd state (echo off, raw mode)
    after being interrupted. The Perl tool ran this after every ffmpeg call
    and inside its SIGINT handler.
    """
    if not sys.stdin.isatty():
        return
    try:
        subprocess.run(
            ["stty", "sane"], check=False, stdin=None, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=2,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
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

    logger.error(
        "[%s] %s failed: %s", job.format_name, job.source.name, result.error
    )
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
