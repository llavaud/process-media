# Changelog

## 2.0.1

- Infer a date from the file name when EXIF metadata is missing
  (Samsung `YYYYMMDD_HHMMSS`, iPhone `IMG_…`, screenshots
  `Screenshot_YYYY-MM-DD-HH-MM-SS`, WhatsApp `IMG-YYYYMMDD-…`, ISO-like
  variants). Falls back to the original stem with a clear `WARNING`
  log so the reason is obvious.
- Always log how the base name was resolved (debug for EXIF, info for
  filename parsing, warning for the stem fallback).
- Recognise `.png` as a valid photo extension.
- Debian package: switch the changelog `Distribution:` to `unstable`,
  add `make deb-lint` (runs `lintian --profile debian` on the most
  recent `.changes`).

## 2.0.0

Python 3.11+ implementation. Highlights:

- Relies on system-installed `ffmpeg`, `ffprobe`, `exiftool` (and
  optionally `jpeginfo`); no bundled binaries.
- Pillow-based photo pipeline: auto-orient, forced rotation, resize
  without upscaling, progressive JPEG, atomic writes.
- Direct `exiftool` subprocess calls for metadata stripping with
  whitelist support (`gps`, `orientation`) and JSON-based EXIF date
  reading — no Python `pyexiftool` wrapper required.
- ffmpeg pipeline for video (libx264 / libx265 reencode, ffmetadata
  round-trip for selective strip, thumbnail generation, integrity
  check). Output container is normalised to MP4.
- Pydantic v2 configuration with strict validation; supports a
  single-document YAML (`global:` + `formats:`) or the two-document
  layout (global options, formats separated by `---`).
- `ProcessPoolExecutor`-based parallel runner with Rich progress bar.
- Typer-based CLI (`--type`, `--format`, `--config`, `--max-threads`,
  `--tzoffset`, `--keep-name`, `--verbose`, `--overwrite`, `--batch`,
  `--dry-run`, `--recursive`).
- Optional HEIC / HEIF support via the `[heic]` extra (pillow-heif).
- `PROCESS_MEDIA_CONFIG` environment variable for configuration path.
- Docker image based on `python:3.12-slim`.
- MIT license (was inconsistently declared as GPL-3 / MIT before).
- Debian/Ubuntu packaging (`debian/` tree, `make deb`, lintian-clean)
  and APT repository automation (`make apt-publish`, `make apt-push`).
