"""Filesystem scanning, EXIF date extraction and target name building."""

from __future__ import annotations

import logging
import mimetypes
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from .config import FormatSpec, GlobalOptions
from .media.base import MediaJob, MediaType


@dataclass(frozen=True)
class ExifDate:
    """A creation date parsed from EXIF, with the tag it came from.

    Knowing the originating tag lets us apply the right timezone correction
    for video files whose ``QuickTime:CreateDate`` is stored in UTC.
    """

    dt: datetime
    tag: str

    @property
    def is_quicktime(self) -> bool:
        return self.tag.startswith("QuickTime:")


logger = logging.getLogger("process_media.naming")


PHOTO_EXTS = frozenset({".jpg", ".jpeg", ".heic", ".heif"})
VIDEO_EXTS = frozenset({".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".3gp"})

# Output extensions are normalised: every encoded video is muxed as MP4
# regardless of source container, photos always go out as JPEG.
PHOTO_OUTPUT_EXT = ".jpg"
VIDEO_OUTPUT_EXT = ".mp4"

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
    """Return the media type for ``path`` or ``None`` if unsupported.

    The extension check (above) handles every format we explicitly
    support and is the fast path. The :mod:`mimetypes` fallback is a
    safety net for related extensions we haven't enumerated (e.g.
    less common video containers, tooling-specific spellings of HEIC
    like ``.heifs``). It deliberately stays permissive so a downstream
    pipeline error makes the limitation explicit rather than silently
    skipping the file.
    """
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


def scan_media(path: Path, *, recursive: bool = False) -> list[tuple[Path, MediaType]]:
    """Walk ``path`` (file or directory) and classify supported media files.

    When ``recursive`` is true, descend into subdirectories. Hidden files
    and directories (leading dot) are always skipped — including any
    subtree rooted on a hidden directory.
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

    if recursive:
        entries = (
            p
            for p in path.rglob("*")
            # Skip files whose any path segment (relative to root) is hidden.
            if not any(part.startswith(".") for part in p.relative_to(path).parts)
        )
    else:
        entries = (p for p in path.iterdir() if not p.name.startswith("."))

    for entry in sorted(entries):
        if not entry.is_file():
            continue
        kind = _classify(entry)
        if kind is not None:
            results.append((entry, kind))
    return results


def exif_date_to_name(dt: datetime, tzoffset: int = 0) -> str:
    """Format a datetime as ``YYYYMMDD-HHMMSS`` after applying ``tzoffset``.

    ``tzoffset`` is added (in seconds) to the input value before formatting.
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


def batch_exif_dates(paths: list[Path]) -> dict[Path, ExifDate | None]:
    """Read creation dates for ``paths`` using a single ``exiftool`` process.

    Falls back to ``DateTimeOriginal`` → ``EXIF:CreateDate`` →
    ``QuickTime:CreateDate``. Returns ``None`` per file when no usable tag.
    The returned :class:`ExifDate` carries the tag it was read from, which
    is required to apply timezone compensation for QuickTime stamps.
    """
    if not paths:
        return {}

    # Local import keeps the dependency optional for unit tests that
    # don't go through the full pipeline.
    from exiftool import ExifToolHelper

    # Index by resolved path so we can match ExifTool's SourceFile reliably.
    by_resolved: dict[Path, Path] = {p.resolve(): p for p in paths}
    out: dict[Path, ExifDate | None] = {p: None for p in paths}

    with ExifToolHelper() as et:
        records = et.get_tags([str(p) for p in paths], tags=list(_DATE_TAGS))

    for record in records:
        raw_src = record.get("SourceFile", "")
        if not raw_src:
            continue
        try:
            resolved = Path(raw_src).resolve()
        except OSError:
            resolved = Path(raw_src)
        src = by_resolved.get(resolved)
        if src is None:
            # Fallback: match by name within the original set.
            for p in paths:
                if p.name == Path(raw_src).name:
                    src = p
                    break
        if src is None:
            continue
        for tag in _DATE_TAGS:
            value = record.get(tag)
            if value:
                dt = _parse_exif_timestamp(str(value))
                if dt is not None:
                    out[src] = ExifDate(dt=dt, tag=tag)
                    break
    return out


def _adjust_for_media(date: ExifDate, media_type: MediaType, tzoffset: int) -> datetime:
    """Apply the right timezone correction before formatting the name.

    An explicit ``--tzoffset`` always wins; when ``tzoffset == 0`` and the
    timestamp comes from QuickTime (UTC), the local timezone offset is
    applied so the name reflects local time.
    """
    if tzoffset:
        return date.dt + timedelta(seconds=tzoffset)
    if media_type == "video" and date.is_quicktime:
        local_offset = time.localtime().tm_gmtoff
        if local_offset:
            return date.dt + timedelta(seconds=local_offset)
    return date.dt


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
    # Videos always go out as MP4 — the ffmpeg pipeline muxes ``-f mp4``.
    return VIDEO_OUTPUT_EXT


def build_jobs(
    files: Iterable[tuple[Path, MediaType]],
    formats: dict[str, FormatSpec],
    global_opts: GlobalOptions,
    exif_dates: dict[Path, ExifDate | datetime | None],
) -> list[MediaJob]:
    """Build the full ``MediaJob`` list (cartesian product, deduped).

    ``exif_dates`` accepts either :class:`ExifDate` (preferred, carries the
    tag origin for timezone handling) or a bare :class:`datetime` for
    backward compatibility with tests.
    """
    jobs: list[MediaJob] = []
    for source, media_type in files:
        for fname, spec in formats.items():
            if spec.type != media_type:
                continue
            entry = exif_dates.get(source)
            if not global_opts.keep_name and entry is not None:
                if isinstance(entry, ExifDate):
                    adjusted = _adjust_for_media(entry, media_type, global_opts.tzoffset)
                else:
                    # Bare datetime: apply only the explicit tzoffset.
                    adjusted = entry + timedelta(seconds=global_opts.tzoffset)
                base = adjusted.strftime("%Y%m%d-%H%M%S")
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
    don't share counters. ALL colliding jobs receive a suffix so every
    member of the duplicate group is renamed consistently.
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
