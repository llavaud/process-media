"""Shared dataclasses passed between the main process and workers.

These objects must be picklable to be shipped to ``ProcessPoolExecutor``.
``FormatSpec`` (a Pydantic model) is picklable out of the box.
"""

from __future__ import annotations

from dataclasses import dataclass
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
    format_spec: "FormatSpec"
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
