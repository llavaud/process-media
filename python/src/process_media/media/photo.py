"""Photo (JPEG) processing pipeline."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageOps

from ..tools import ToolError, run, which
from .base import JobResult, MediaJob


logger = logging.getLogger("process_media.photo")

# Mapping from CW degrees (the convention used by the legacy Perl tool)
# to Pillow rotate counter-clockwise.
_CW_TO_PIL = {"90": -90, "180": 180, "270": 90}


def process_photo(job: MediaJob) -> JobResult:
    """Execute one photo job end-to-end."""
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

        needs_transform = (
            spec.rotate != "auto"  # forced rotation always re-encodes
            or spec.resize is not None
            or spec.compress is not None
            or spec.progressive
        )

        if not needs_transform and not spec.strip:
            shutil.copy2(job.source, job.target)
            return JobResult(job=job, success=True, duration=time.monotonic() - start)

        with Image.open(job.source) as im:
            # Pillow defers loading; force it before we close the file.
            im.load()
            img = _apply_rotation(im, spec.rotate)
            if spec.resize is not None:
                img.thumbnail(
                    (spec.resize, spec.resize),
                    resample=Image.Resampling.LANCZOS,
                )

            save_kwargs: dict = {
                "format": "JPEG",
                "optimize": True,
                "progressive": bool(spec.progressive),
            }
            if spec.compress is not None:
                save_kwargs["quality"] = int(spec.compress)
            else:
                # Preserve perceived quality when no explicit compression
                # was requested.
                save_kwargs["quality"] = 90

            _atomic_save(img, job.target, save_kwargs)

        if spec.strip:
            _strip_metadata(
                target=job.target,
                source=job.source,
                strip_exclude=list(spec.strip_exclude),
            )

        _integrity_check(job.target)

        return JobResult(job=job, success=True, duration=time.monotonic() - start)
    except Exception as exc:
        logger.exception("Photo job failed: %s", job.source)
        return JobResult(
            job=job,
            success=False,
            error=str(exc),
            duration=time.monotonic() - start,
        )


def _apply_rotation(img: Image.Image, rotate: str) -> Image.Image:
    if rotate == "auto":
        oriented = ImageOps.exif_transpose(img)
        return oriented if oriented is not None else img
    angle = _CW_TO_PIL.get(rotate)
    if angle is None:
        return img
    return img.rotate(angle, expand=True)


def _atomic_save(img: Image.Image, target: Path, save_kwargs: dict) -> None:
    fd, tmp = tempfile.mkstemp(
        dir=str(target.parent),
        prefix=".process-media_",
        suffix=target.suffix or ".jpg",
    )
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        img.save(tmp_path, **save_kwargs)
        os.replace(tmp_path, target)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _strip_metadata(*, target: Path, source: Path, strip_exclude: list[str]) -> None:
    """Wipe all metadata then re-import the explicitly excluded tags."""
    exiftool = which("exiftool")
    if exiftool is None:
        logger.warning("exiftool unavailable; metadata stripping skipped on %s", target)
        return

    args: list[str] = [exiftool, "-overwrite_original", "-all="]
    for tag in strip_exclude:
        if tag == "gps":
            args += ["-tagsfromfile", str(source), "-GPS:all"]
        elif tag == "orientation":
            args += ["-tagsfromfile", str(source), "-EXIF:Orientation"]
    args.append(str(target))
    run(args)


def _integrity_check(target: Path) -> None:
    jpeginfo = which("jpeginfo")
    if not jpeginfo:
        return
    try:
        run([jpeginfo, "-c", str(target)])
    except ToolError as exc:
        logger.warning("jpeginfo reports issues on %s: %s", target, exc)
