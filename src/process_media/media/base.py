"""Shared dataclasses passed between the main process and workers.

These objects must be picklable to be shipped to ``ProcessPoolExecutor``.
``FormatSpec`` (a Pydantic model) is picklable out of the box.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ..config import FormatSpec


MediaType = Literal["photo", "video"]


@dataclass
class MediaJob:
    """One unit of work: turn ``source`` into ``target`` using ``format_spec``."""

    source: Path
    target: Path
    format_name: str
    format_spec: FormatSpec
    media_type: MediaType
    overwrite: bool = False
    verbose: bool = False


@dataclass
class JobResult:
    """Outcome of a single :class:`MediaJob` execution."""

    job: MediaJob
    success: bool
    error: str | None = None
    duration: float = 0.0
    skipped: bool = False


def job_runner(func: Callable[[MediaJob], None]) -> Callable[[MediaJob], JobResult]:
    """Wrap a job function with the common boilerplate.

    Responsibilities of the decorator:

    * Create the target's parent directory.
    * Short-circuit when the target already exists and ``overwrite`` is False.
    * Measure execution duration.
    * Convert any exception raised by the body into ``JobResult(success=False)``.

    The decorated function is expected to perform its side-effects and
    return ``None`` on success.
    """

    @wraps(func)
    def wrapper(job: MediaJob) -> JobResult:
        start = time.perf_counter()
        try:
            job.target.parent.mkdir(parents=True, exist_ok=True)
            if job.target.exists() and not job.overwrite:
                return JobResult(
                    job=job,
                    success=True,
                    duration=time.perf_counter() - start,
                    skipped=True,
                )
            func(job)
            return JobResult(
                job=job,
                success=True,
                duration=time.perf_counter() - start,
            )
        except Exception as exc:
            return JobResult(
                job=job,
                success=False,
                error=str(exc),
                duration=time.perf_counter() - start,
            )

    return wrapper
