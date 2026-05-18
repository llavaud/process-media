"""Video processing pipeline based on ``ffmpeg`` and ``ffprobe``."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path

from PIL import Image

from ..config import FormatSpec
from ..tools import ToolError, probe_audio_codec, run, which
from .base import MediaJob, job_runner

logger = logging.getLogger("process_media.video")

_THUMB_QUALITY = 90


@job_runner
def process_video(job: MediaJob) -> None:
    """Execute one video job end-to-end.

    The pipeline is **atomic**: we work on a temporary file living next to
    the final target and only ``os.replace`` it into place after every
    step completed successfully. Any crash (ffmpeg failure, interruption)
    leaves the existing target intact and the temp file is cleaned up.
    The thumbnail (if requested) is generated after the atomic swap so
    it can sit next to the now-final video.
    """
    spec = job.format_spec
    ffmpeg = which("ffmpeg")
    if ffmpeg is None:
        raise ToolError("ffmpeg binary is required but was not found")

    needs_pipeline = spec.reencode or spec.strip
    if not needs_pipeline:
        # Pure rename / copy: still go through a tempfile so a crashed
        # ``shutil.copy2`` cannot leave a half-written target.
        with _tempfile(job.target.parent, suffix=".mp4") as tmp:
            shutil.copy2(job.source, tmp)
            os.replace(tmp, job.target)
    else:
        # Pipeline: build the new file in ``working``, swap to ``job.target``
        # only when every step succeeded.
        with _tempfile(job.target.parent, suffix=".mp4") as working:
            shutil.copy2(job.source, working)
            if spec.reencode:
                _reencode(ffmpeg, working, spec, job.verbose)
            if spec.strip:
                _strip_metadata(ffmpeg, working, spec, job.verbose)
            os.replace(working, job.target)

    if spec.thumbnail:
        _generate_thumbnail(ffmpeg, job)

    _integrity_check(ffmpeg, job.target)


# ---------------------------------------------------------------------------
# Re-encode
# ---------------------------------------------------------------------------


def _reencode(ffmpeg: str, working: Path, spec: FormatSpec, verbose: bool) -> None:
    """Reencode ``working`` in place.

    Reads ``working``, writes to a sibling tempfile and ``os.replace`` it
    back onto ``working`` only on ffmpeg success.
    """
    audio_codec = probe_audio_codec(working)
    cmd: list[str] = _ffmpeg_base(verbose)

    is_forced_rotation = spec.rotate in {"90", "180", "270"}
    if is_forced_rotation:
        # Disable ffmpeg's auto-rotation so our transpose stays predictable.
        cmd.append("-noautorotate")

    cmd += ["-i", str(working)]

    # Video codec.
    if spec.vcodec == "x265":
        cmd += ["-codec:v", "libx265"]
        params = spec.vcodec_params or ""
        joined = f"{params}:log-level=error" if params else "log-level=error"
        cmd += ["-x265-params", joined]
    else:
        cmd += ["-codec:v", "libx264"]
        if spec.vcodec_params:
            cmd += ["-x264-params", spec.vcodec_params]

    # Audio passthrough when already AAC.
    if audio_codec == "aac":
        cmd += ["-codec:a", "copy"]
    else:
        cmd += ["-codec:a", "aac", "-b:a", "160k"]

    cmd += ["-map_metadata", "0"]

    # Filtergraph: rotation + scale.
    vfs = _build_vf(spec)
    if vfs:
        cmd += ["-vf", ",".join(vfs)]
    if is_forced_rotation:
        cmd += ["-metadata:s:v", "rotate=0"]

    with _tempfile(working.parent, suffix=".mp4") as tmp:
        cmd += ["-flags", "+global_header", "-f", "mp4", str(tmp)]
        run(cmd)
        os.replace(tmp, working)


def _ffmpeg_base(verbose: bool) -> list[str]:
    log_level = "warning" if verbose else "error"
    return ["ffmpeg", "-nostdin", "-hide_banner", "-y", "-loglevel", log_level]


def _build_vf(spec: FormatSpec) -> list[str]:
    filters: list[str] = []
    if spec.rotate in {"90", "180", "270"}:
        count = int(spec.rotate) // 90
        filters.extend(["transpose=1"] * count)
    if spec.resize is not None:
        w = spec.resize
        # Scale longer edge to ``W`` while
        # preserving aspect ratio. Commas are escaped because they appear
        # inside the filter expression.
        filters.append(f"scale=iw*min(1\\,min({w}/iw\\,{w}/ih)):-1")
    return filters


# ---------------------------------------------------------------------------
# Strip metadata
# ---------------------------------------------------------------------------


def _strip_metadata(ffmpeg: str, working: Path, spec: FormatSpec, verbose: bool) -> None:
    """Strip metadata from ``working`` in place, preserving the whitelist.

    1. If a whitelist is configured, extract ffmetadata from the current
       file and filter it.
    2. Strip every metadata tag from the video.
    3. Re-inject the filtered whitelist (if any).

    All temp files (filtered ffmetadata + intermediate videos) live next
    to ``working`` and are cleaned up unconditionally — even when ffmpeg
    fails midway. ``working`` is updated via ``os.replace`` so it always
    points to a complete file or its previous content.
    """
    work_dir = working.parent

    # Step 1: capture the whitelist into ``preserved_meta`` (or ``None``).
    preserved_meta: Path | None = None
    try:
        if spec.strip_exclude:
            with _tempfile(work_dir, suffix=".ffmeta", delete=False) as raw_meta:
                extract_cmd = _ffmpeg_base(verbose) + [
                    "-i",
                    str(working),
                    "-f",
                    "ffmetadata",
                    str(raw_meta),
                ]
                run(extract_cmd)
                preserved_meta = _filter_ffmetadata(raw_meta, set(spec.strip_exclude))
                # ``_filter_ffmetadata`` may unlink the file if nothing was
                # kept; normalise to None in that case.
                if not preserved_meta.exists():
                    preserved_meta = None

        # Step 2: strip every metadata tag from the video.
        with _tempfile(work_dir, suffix=".mp4") as stripped:
            strip_cmd = _ffmpeg_base(verbose) + [
                "-i",
                str(working),
                "-codec",
                "copy",
                "-map_metadata",
                "-1",
                "-map_metadata:s:v",
                "-1",
                "-map_metadata:s:a",
                "-1",
                "-f",
                "mp4",
                str(stripped),
            ]
            run(strip_cmd)
            os.replace(stripped, working)

        # Step 3: re-inject the preserved metadata, if any.
        if preserved_meta is not None:
            with _tempfile(work_dir, suffix=".mp4") as merged:
                merge_cmd = _ffmpeg_base(verbose) + [
                    "-i",
                    str(working),
                    "-i",
                    str(preserved_meta),
                    "-map_metadata",
                    "1",
                    "-codec",
                    "copy",
                    "-f",
                    "mp4",
                    str(merged),
                ]
                run(merge_cmd)
                os.replace(merged, working)
    finally:
        if preserved_meta is not None:
            preserved_meta.unlink(missing_ok=True)


def _filter_ffmetadata(raw_path: Path, keep: set[str]) -> Path:
    """Keep only the FFMETADATA header plus the whitelisted entries.

    Returns the path of the filtered file (overwrites ``raw_path``).
    """
    lines_kept: list[str] = []
    for raw_line in raw_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(";FFMETADATA"):
            lines_kept.append(raw_line)
            continue
        if "gps" in keep and line.startswith("location"):
            lines_kept.append(raw_line)
            continue
        if "orientation" in keep and line.startswith("rotate"):
            lines_kept.append(raw_line)
            continue

    # Only retain the file if we have real entries beyond the header.
    if len(lines_kept) <= 1:
        raw_path.unlink(missing_ok=True)
        return raw_path  # caller checks .exists()
    raw_path.write_text("\n".join(lines_kept) + "\n", encoding="utf-8")
    return raw_path


# ---------------------------------------------------------------------------
# Thumbnail
# ---------------------------------------------------------------------------


def _generate_thumbnail(ffmpeg: str, job: MediaJob) -> None:
    thumb = job.target.with_suffix(".jpg")
    cmd = _ffmpeg_base(job.verbose) + ["-i", str(job.target), "-vframes", "1", str(thumb)]
    run(cmd)
    # Re-save with Pillow to drop ancillary chunks and force progressive JPEG.
    try:
        with Image.open(thumb) as im:
            im.load()
            im.save(
                thumb,
                format="JPEG",
                quality=_THUMB_QUALITY,
                progressive=True,
                optimize=True,
            )
    except Exception as exc:
        logger.warning("Failed to post-process thumbnail %s: %s", thumb, exc)


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------


def _integrity_check(ffmpeg: str, target: Path) -> None:
    cmd = _ffmpeg_base(False) + ["-i", str(target), "-f", "null", "-"]
    try:
        run(cmd)
    except ToolError as exc:
        logger.warning("ffmpeg integrity check failed on %s: %s", target, exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _tempfile:
    """Context manager yielding a unique temp ``Path`` next to the target.

    The file is deleted on exit unless ``delete=False``. We don't keep the
    underlying file handle open: ffmpeg refuses to write to an open file
    on some platforms.
    """

    def __init__(self, directory: Path, *, suffix: str, delete: bool = True) -> None:
        self._directory = directory
        self._suffix = suffix
        self._delete = delete
        self._path: Path | None = None

    def __enter__(self) -> Path:
        fd, name = tempfile.mkstemp(
            dir=str(self._directory),
            prefix="process-media_tmp.",
            suffix=self._suffix,
        )
        os.close(fd)
        self._path = Path(name)
        return self._path

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._delete and self._path is not None and self._path.exists():
            try:
                self._path.unlink()
            except OSError:
                pass


# Note: the small custom _tempfile context manager intentionally keeps behavior
# consistent across platforms (mkstemp + close + Path). It is simple and
# reliable; using NamedTemporaryFile with delete=False would be an alternative,
# but this class exists to control the exact naming/location semantics.
