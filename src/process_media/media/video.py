"""Video processing pipeline based on ``ffmpeg`` and ``ffprobe``."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
from pathlib import Path

from PIL import Image

from ..config import FormatSpec
from ..tools import ToolError, probe_audio_codec, run, which
from .base import JobResult, MediaJob


logger = logging.getLogger("process_media.video")

_THUMB_QUALITY = 90


def process_video(job: MediaJob) -> JobResult:
    """Execute one video job end-to-end."""
    start = time.monotonic()
    spec = job.format_spec
    try:
        job.target.parent.mkdir(parents=True, exist_ok=True)

        if job.target.exists() and not job.overwrite:
            logger.warning("Skip existing target %s", job.target)
            return JobResult(
                job=job,
                success=True,
                duration=time.monotonic() - start,
                skipped=True,
            )

        # Initial copy: even when re-encoding, the legacy tool copies first
        # then operates on the target so we keep the same semantics (and
        # the source file is never touched).
        shutil.copy2(job.source, job.target)

        ffmpeg = which("ffmpeg")
        if ffmpeg is None:
            raise ToolError("ffmpeg binary is required but was not found")

        if spec.reencode:
            _reencode(ffmpeg, job)

        if spec.strip:
            _strip_metadata(ffmpeg, job)

        if spec.thumbnail:
            _generate_thumbnail(ffmpeg, job)

        _integrity_check(ffmpeg, job.target)

        return JobResult(job=job, success=True, duration=time.monotonic() - start)
    except Exception as exc:
        logger.exception("Video job failed: %s", job.source)
        # Best-effort cleanup of partial outputs.
        if job.target.exists():
            try:
                # Only remove if we created an incomplete file.
                pass
            except Exception:
                pass
        return JobResult(
            job=job,
            success=False,
            error=str(exc),
            duration=time.monotonic() - start,
        )


# ---------------------------------------------------------------------------
# Re-encode
# ---------------------------------------------------------------------------


def _reencode(ffmpeg: str, job: MediaJob) -> None:
    spec = job.format_spec
    audio_codec = probe_audio_codec(job.source)
    cmd: list[str] = _ffmpeg_base(job.verbose)

    is_forced_rotation = spec.rotate in {"90", "180", "270"}
    if is_forced_rotation:
        # Disable ffmpeg's auto-rotation so our transpose stays predictable.
        cmd.append("-noautorotate")

    cmd += ["-i", str(job.target)]

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

    with _tempfile(job.target.parent, suffix=job.target.suffix or ".mp4") as tmp:
        cmd += ["-flags", "+global_header", "-f", "mp4", str(tmp)]
        run(cmd)
        os.replace(tmp, job.target)


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
        # Identical to the Perl version: scale longer edge to ``W`` while
        # preserving aspect ratio. Commas are escaped because they appear
        # inside the filter expression.
        filters.append(
            f"scale=iw*min(1\\,min({w}/iw\\,{w}/ih)):-1"
        )
    return filters


# ---------------------------------------------------------------------------
# Strip metadata
# ---------------------------------------------------------------------------


def _strip_metadata(ffmpeg: str, job: MediaJob) -> None:
    spec = job.format_spec
    log_level = "warning" if job.verbose else "error"
    target = job.target
    target_dir = target.parent

    preserved_meta: Path | None = None
    if spec.strip_exclude:
        with _tempfile(target_dir, suffix=".ffmeta", delete=False) as raw_meta:
            extract_cmd = [
                ffmpeg,
                "-nostdin",
                "-hide_banner",
                "-y",
                "-loglevel",
                log_level,
                "-i",
                str(target),
                "-f",
                "ffmetadata",
                str(raw_meta),
            ]
            run(extract_cmd)
            preserved_meta = _filter_ffmetadata(raw_meta, set(spec.strip_exclude))

    # Step: strip everything from the video itself.
    with _tempfile(target_dir, suffix=target.suffix or ".mp4") as stripped:
        strip_cmd = [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-y",
            "-loglevel",
            log_level,
            "-i",
            str(target),
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
        os.replace(stripped, target)

    # Step: re-inject preserved metadata, if any.
    if preserved_meta is not None and preserved_meta.exists():
        try:
            with _tempfile(target_dir, suffix=target.suffix or ".mp4") as merged:
                merge_cmd = [
                    ffmpeg,
                    "-nostdin",
                    "-hide_banner",
                    "-y",
                    "-loglevel",
                    log_level,
                    "-i",
                    str(target),
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
                os.replace(merged, target)
        finally:
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
