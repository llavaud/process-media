# Changelog

## 2.0.0 — Python rewrite

Full Python 3.11+ rewrite of the original Perl tool. Same CLI surface and
configuration semantics, with the following changes:

- Drops the bundled ffmpeg/ffprobe binaries — relies on system `ffmpeg`,
  `ffprobe`, `exiftool`, and optionally `jpeginfo`.
- Pillow-based photo pipeline (auto-orient, resize, progressive JPEG,
  atomic writes).
- pyexiftool integration for metadata stripping with whitelist support.
- ffmpeg pipeline for video (libx264/libx265 reencode, ffmetadata
  round-trip for selective strip, thumbnail generation, integrity check).
- Pydantic v2 config validation; supports both the legacy two-document
  YAML layout and a new single-document layout (`global:` + `formats:`).
- ProcessPoolExecutor-based parallel runner with Rich progress bar.
- Typer-based CLI with the same flags as the Perl version.
- Docker image based on `python:3.12-slim`.
