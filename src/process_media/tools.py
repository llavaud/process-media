from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import logging
from typing import Sequence
from functools import lru_cache

logger = logging.getLogger("process_media.tools")


class ToolError(RuntimeError):
    pass


@lru_cache(maxsize=32)
def which(name: str) -> str | None:
    return shutil.which(name)


_jpeginfo_warned = False


def ensure_tools(needs_ffmpeg: bool, needs_exiftool: bool) -> None:
    missing = []
    if needs_ffmpeg and not which("ffmpeg"):
        missing.append("ffmpeg")
    if needs_ffmpeg and not which("ffprobe"):
        missing.append("ffprobe")
    if needs_exiftool and not which("exiftool"):
        missing.append("exiftool")
    global _jpeginfo_warned
    if not which("jpeginfo") and not _jpeginfo_warned:
        logger.warning("jpeginfo not found; JPEG integrity checks will be skipped")
        _jpeginfo_warned = True
    if missing:
        raise RuntimeError(f"Missing required tools: {', '.join(missing)}")


def run(cmd: Sequence[str], check: bool = True, timeout: int | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
    logger.debug("Running command: %s", cmd)
    try:
        cp = subprocess.run(list(cmd), check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, cwd=str(cwd) if cwd else None)
    except Exception as e:
        raise ToolError(str(e))
    if check and cp.returncode != 0:
        stderr = cp.stderr.decode(errors="ignore")[:2000]
        raise ToolError(f"Command {cmd!r} failed (rc={cp.returncode}): {stderr}")
    return cp


def probe_audio_codec(path: Path) -> str | None:
    ffprobe = which("ffprobe")
    if not ffprobe:
        return None
    cmd = [ffprobe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path)]
    try:
        cp = run(cmd, check=False)
        out = cp.stdout.decode().strip()
        return out.splitlines()[0] if out else None
    except Exception:
        return None
