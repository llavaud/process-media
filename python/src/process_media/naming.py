"""Filesystem scanning, EXIF date extraction and target name building."""

from __future__ import annotations

import logging
import mimetypes
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Literal

from .config import FormatSpec, GlobalOptions
from .media.base import MediaJob, MediaType


logger = logging.getLogger("process_media.naming")


PHOTO_EXTS = frozenset({".jpg", ".jpeg"})
VIDEO_EXTS = frozenset({".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".3gp"})

# Photos are normalised to ``.jpg``; videos keep their container.
PHOTO_OUTPUT_EXT = ".jpg"

# EXIF tags we look at, in order. ``QuickTime:CreateDate`` covers videos.
_DATE_TAGS = (
    "EXIF:DateTimeOriginal",
    "EXIF:CreateDate",
    "QuickTime:CreateDate",
)

# ``ExifTool`` typical timestamp format.
_EXIF_TS_FORMAT = "%Y:%m:%d %H:%M:%S"
_EXIF_NULL = "0000:00:00 00:00:00"


def _classify(path: Path) -> MediaType | None:
    """Return the media type for ``path`` or ``None`` if unsupported."""
    ext = path.suffix.lower()
    if ext in PHOTO_EXTS:
        return "photo"
    if ext in VIDEO_EXTS:
        return "video"
    mime, _ = mimetypes.guess_type(path.name)
    if mime:
        if mime.startswith("image/"):
            return "photo"
        if mime.startswith("video/"):
            return "video"
    return None


def scan_media(path: Path) -> list[tuple[Path, MediaType]]:
    """Walk ``path`` (file or single directory, non-recursive) and classify.

    Hidden files (leading dot) are skipped, matching the Perl behaviour.
    """
    results: list[tuple[Path, MediaType]] = []
    if path.is_file():
        if not path.name.startswith("."):
            kind = _classify(path)
            if kind is not None:
                results.append((path, kind))
        return results

    if not path.is_dir():
        raise FileNotFoundError(f"{path} is neither a file nor a directory")

    for entry in sorted(path.iterdir()):
        if entry.name.startswith(".") or not entry.is_file():
            continue
        kind = _classify(entry)
        if kind is not None:
            results.append((entry, kind))
    return results


def exif_date_to_name(dt: datetime, tzoffset: int = 0) -> str:
    """Format a datetime as ``YYYYMMDD-HHMMSS`` after applying ``tzoffset``.

    ``tzoffset`` is added (in seconds) to the input value before formatting,
    mirroring the original Perl behaviour.
    """
    if tzoffset:
        dt = dt + timedelta(seconds=tzoffset)
    return dt.strftime("%Y%m%d-%H%M%S")


def fallback_name(path: Path) -> str:
    """When EXIF data is missing, keep the original stem."""
    return path.stem


def _parse_exif_timestamp(value: str) -> datetime | None:
    if not value or value.startswith(_EXIF_NULL):
        return None
    # Strip a trailing timezone like "+02:00" if present.
    candidate = value.split("+")[0].split("Z")[0].strip()
    try:
        return datetime.strptime(candidate[:19], _EXIF_TS_FORMAT)
    except ValueError:
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            return None


def batch_exif_dates(paths: list[Path]) -> dict[Path, datetime | None]:
    """Read creation dates for ``paths`` using a single ``exiftool`` process.

    Falls back to ``DateTimeOriginal`` → ``EXIF:CreateDate`` →
    ``QuickTime:CreateDate``. Returns ``None`` per file when no usable tag.
    """
    if not paths:
        return {}

    # Local import keeps the dependency optional for unit tests that
    # don't go through the full pipeline.
    from exiftool import ExifToolHelper

    out: dict[Path, datetime | None] = {p: None for p in paths}
    with ExifToolHelper() as et:
        records = et.get_tags([str(p) for p in paths], tags=list(_DATE_TAGS))

    for record in records:
        src = Path(record.get("SourceFile", ""))
        if src not in out:
            # ExifTool may return absolute/relative paths; try resolving.
            for p in paths:
                if p.resolve() == src.resolve():
                    src = p
                    break
        for tag in _DATE_TAGS:
            value = record.get(tag)
            if value:
                dt = _parse_exif_timestamp(str(value))
                if dt is not None:
                    out[src] = dt
                    break
    return out


def _resolve_output_dir(source: Path, spec: FormatSpec, format_name: str) -> Path:
    """Compute the directory where output for ``format_name`` is written.

    Absolute ``output_dir`` is used as-is. Relative paths are anchored on
    the source's parent directory. When ``output_dir`` is unset, the
    format name itself is used as a sibling subdirectory.
    """
    raw = spec.output_dir or format_name
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate
    return source.parent / candidate


def _target_extension(media_type: MediaType, source: Path) -> str:
    if media_type == "photo":
        return PHOTO_OUTPUT_EXT
    return source.suffix.lower()


def build_jobs(
    files: Iterable[tuple[Path, MediaType]],
    formats: dict[str, FormatSpec],
    global_opts: GlobalOptions,
    exif_dates: dict[Path, datetime | None],
) -> list[MediaJob]:
    """Build the full ``MediaJob`` list (cartesian product, deduped)."""
    jobs: list[MediaJob] = []
    for source, media_type in files:
        for fname, spec in formats.items():
            if spec.type != media_type:
                continue
            dt = exif_dates.get(source)
            if not global_opts.keep_name and dt is not None:
                base = exif_date_to_name(dt, tzoffset=global_opts.tzoffset)
            else:
                base = fallback_name(source)
            ext = _target_extension(media_type, source)
            outdir = _resolve_output_dir(source, spec, fname)
            jobs.append(
                MediaJob(
                    source=source,
                    target=outdir / f"{base}{ext}",
                    format_name=fname,
                    format_spec=spec,
                    media_type=media_type,
                    overwrite=global_opts.overwrite,
                    verbose=global_opts.verbose,
                )
            )
    return _dedupe_jobs(jobs)


def _dedupe_jobs(jobs: list[MediaJob]) -> list[MediaJob]:
    """Append ``-NNN`` suffixes when several sources collide on the same target.

    Numbering happens **per (media_type, target_path)** so photos and videos
    don't share counters. ALL colliding jobs receive a suffix, matching the
    Perl behaviour where every member of the duplicate group is renamed.
    """
    groups: dict[tuple[MediaType, Path], list[MediaJob]] = defaultdict(list)
    for job in jobs:
        groups[(job.media_type, job.target)].append(job)

    for (_mt, target), group in groups.items():
        if len(group) <= 1:
            continue
        for index, job in enumerate(group, start=1):
            stem = target.stem
            ext = target.suffix
            job.target = target.with_name(f"{stem}-{index:03d}{ext}")
    return jobs


# ---------------------------------------------------------------------------
# Backwards-compatible helper used by unit tests written before the refactor.
# ---------------------------------------------------------------------------


def dedupe_targets(items: list[dict]) -> list[dict]:
    """Apply suffixing to a list of plain dicts (testing helper).

    Each item must hold ``target_name`` and ``media_type``. The first
    occurrence within a group keeps its name, the following ones get
    ``-001``, ``-002`` … This mirrors how the Perl ``search_duplicate``
    iterates the duplicate hash.
    """
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for item in items:
        groups[(item["media_type"], item["target_name"])].append(item)

    for (_mt, _name), group in groups.items():
        if len(group) <= 1:
            continue
        # Skip the first entry, suffix the rest 001, 002, ...
        for idx, item in enumerate(group[1:], start=1):
            item["target_name"] = f"{item['target_name']}-{idx:03d}"
    return items
