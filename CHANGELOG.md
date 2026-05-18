# Changelog

## 2.0.0

Python 3.11+ implementation. Highlights:

- Relies on system-installed `ffmpeg`, `ffprobe`, `exiftool` (and
  optionally `jpeginfo`); no bundled binaries.
- Pillow-based photo pipeline: auto-orient, forced rotation, resize
  without upscaling, progressive JPEG, atomic writes.
- `pyexiftool` integration for metadata stripping with whitelist
  support (`gps`, `orientation`).
- ffmpeg pipeline for video (libx264 / libx265 reencode, ffmetadata
  round-trip for selective strip, thumbnail generation, integrity
  check). Output container is normalised to MP4.
- Pydantic v2 configuration with strict validation; supports a
  single-document YAML (`global:` + `formats:`) or the two-document
  layout (global options, formats separated by `---`).
- `ProcessPoolExecutor`-based parallel runner with Rich progress bar.
- Typer-based CLI (`--type`, `--format`, `--config`, `--max-threads`,
  `--tzoffset`, `--keep-name`, `--verbose`, `--overwrite`, `--batch`,
  `--dry-run`).
- `PROCESS_MEDIA_CONFIG` environment variable for configuration path.
- Docker image based on `python:3.12-slim`.
