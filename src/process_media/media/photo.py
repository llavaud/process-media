"""Photo (JPEG) processing pipeline."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

from ..tools import ToolError, run, which
from .base import MediaJob, job_runner

logger = logging.getLogger("process_media.photo")

# Register HEIF/HEIC support if pillow-heif is installed. It is an
# optional dependency (heavy native libheif requirement); when missing,
# .heic/.heif files will raise an UnidentifiedImageError downstream and
# the job will be reported as failed with a clear error message.
try:
    from pillow_heif import register_heif_opener  # type: ignore[import-not-found]

    register_heif_opener()
except ImportError:  # pragma: no cover - depends on optional install
    pass

# Mapping from clockwise degrees (the configuration convention) to
# Pillow's counter-clockwise rotate argument.
_CW_TO_PIL = {"90": -90, "180": 180, "270": 90}


@job_runner
def process_photo(job: MediaJob) -> None:
    """Execute one photo job end-to-end. The decorator wraps timing/skip/exception handling."""
    spec = job.format_spec

    needs_transform = (
        spec.rotate != "auto"  # forced rotation always re-encodes
        or spec.resize is not None
        or spec.compress is not None
        or spec.progressive
    )

    if not needs_transform and not spec.strip:
        shutil.copy2(job.source, job.target)
        return

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
        # When rotation was applied (auto or forced), the pixels are
        # already upright: re-importing the source Orientation would
        # cause EXIF-aware viewers to rotate the image a second time.
        rotation_applied = spec.rotate in {"auto", "90", "180", "270"}
        _strip_metadata(
            target=job.target,
            source=job.source,
            strip_exclude=list(spec.strip_exclude),
            rotation_applied=rotation_applied,
        )

    _integrity_check(job.target)


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


def _strip_metadata(
    *,
    target: Path,
    source: Path,
    strip_exclude: list[str],
    rotation_applied: bool,
) -> None:
    """Wipe all metadata then re-import the explicitly excluded tags.

    When ``rotation_applied`` is true, ``orientation`` in the exclude list
    is honoured by forcing ``EXIF:Orientation=1`` instead of copying the
    original (now incorrect) value from the source.
    """
    exiftool = which("exiftool")
    if exiftool is None:
        logger.warning("exiftool unavailable; metadata stripping skipped on %s", target)
        return

    # ``-overwrite_original_in_place`` writes via a tempfile + atomic rename.
    args: list[str] = [exiftool, "-overwrite_original_in_place", "-all="]
    for tag in strip_exclude:
        if tag == "gps":
            args += ["-tagsfromfile", str(source), "-GPS:all"]
        elif tag == "orientation":
            if rotation_applied:
                # Use ``#`` to force numeric interpretation: without it,
                # exiftool treats ``=1`` as a string lookup and can write
                # the wrong value (observed in exiftool 13.x).
                args += ["-IFD0:Orientation#=1"]
            else:
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
