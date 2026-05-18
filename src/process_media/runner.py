"""Process pool orchestration for media jobs."""

from __future__ import annotations

import logging
import os
import signal
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Callable

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


def _execute(job: MediaJob) -> JobResult:
    """Worker entry point: must live at module level so it's picklable."""
    handler = _DISPATCH.get(job.media_type)
    if handler is None:
        return JobResult(
            job=job,
            success=False,
            error=f"unknown media_type {job.media_type!r}",
        )
    return handler(job)


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

    executor = ProcessPoolExecutor(max_workers=max_workers)
    previous_handler = signal.getsignal(signal.SIGINT)

    def _on_sigint(_signum, _frame) -> None:
        logger.warning("Interrupted by user, cancelling pending jobs…")
        executor.shutdown(wait=False, cancel_futures=True)
        # Restore previous handler so a second Ctrl+C kills the process.
        signal.signal(signal.SIGINT, previous_handler)
        raise KeyboardInterrupt

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
        executor.shutdown(wait=True)
        signal.signal(signal.SIGINT, previous_handler)

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
