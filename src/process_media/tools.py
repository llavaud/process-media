"""Process discovery, subprocess wrapper and codec probing helpers."""

from __future__ import annotations

import logging
import shutil
import subprocess
from collections.abc import Sequence
from functools import cache
from pathlib import Path

logger = logging.getLogger("process_media.tools")


class ToolError(RuntimeError):
    """Raised whenever an external binary cannot be launched or exits non-zero."""


@cache
def which(name: str) -> str | None:
    """Cached :func:`shutil.which`. The cache covers a tiny set of tools."""
    return shutil.which(name)


@cache
def _warn_jpeginfo_missing() -> None:
    """Emit the missing-jpeginfo warning exactly once per process."""
    logger.warning("jpeginfo not found; JPEG integrity checks will be skipped")


def ensure_tools(needs_ffmpeg: bool, needs_exiftool: bool) -> None:
    """Verify that the requested binaries are available, raise if not."""
    missing: list[str] = []
    if needs_ffmpeg and not which("ffmpeg"):
        missing.append("ffmpeg")
    if needs_ffmpeg and not which("ffprobe"):
        missing.append("ffprobe")
    if needs_exiftool and not which("exiftool"):
        missing.append("exiftool")
    if not which("jpeginfo"):
        _warn_jpeginfo_missing()
    if missing:
        raise ToolError(f"Missing required tools: {', '.join(missing)}")


def run(
    cmd: Sequence[str],
    check: bool = True,
    timeout: int | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Wrap ``subprocess.run`` with project-wide defaults.

    - Captures stdout and stderr (returned via ``CompletedProcess``).
    - Closes stdin (``DEVNULL``) so child processes cannot block on input.
    - Raises :class:`ToolError` on non-zero exit when ``check=True``.
    - Forwards ``timeout`` so callers can bound long-running commands;
      a timeout converts to ``ToolError`` like any other failure.
    """
    logger.debug("Running command: %s", cmd)
    try:
        cp = subprocess.run(
            list(cmd),
            check=False,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            cwd=str(cwd) if cwd else None,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"Command {cmd!r} timed out after {exc.timeout}s") from exc
    except (OSError, FileNotFoundError) as exc:
        raise ToolError(f"Failed to execute {cmd!r}: {exc}") from exc
    if check and cp.returncode != 0:
        stderr = cp.stderr.decode(errors="ignore")[:2000]
        raise ToolError(f"Command {cmd!r} failed (rc={cp.returncode}): {stderr}")
    return cp


def probe_audio_codec(path: Path) -> str | None:
    """Return the audio codec name of ``path`` or ``None`` if undetectable."""
    ffprobe = which("ffprobe")
    if not ffprobe:
        return None
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=codec_name",
        "-of",
        "csv=p=0",
        str(path),
    ]
    try:
        cp = run(cmd, check=False)
    except ToolError as exc:
        logger.debug("ffprobe audio codec lookup failed for %s: %s", path, exc)
        return None
    out = cp.stdout.decode(errors="ignore").strip()
    return out.splitlines()[0] if out else None
