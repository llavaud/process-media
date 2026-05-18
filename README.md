# process-media (Python)

Modern Python rewrite of the original Perl tool. Renames media files from
their EXIF capture date and processes them through one or more named output
formats (rotation, resize, JPEG quality, video reencoding, metadata stripping,
thumbnail generation, integrity check).

The Python port targets Python 3.11+ and uses **system-installed** ffmpeg /
exiftool — the bundled binaries from the original repo are no longer needed.

## Features

- Pillow-based JPEG processing (auto-orient via EXIF, forced rotation, resize
  without upscaling, progressive output, atomic writes).
- exiftool wrapper (via `pyexiftool`) to strip metadata while optionally
  preserving GPS or orientation.
- ffmpeg-based reencoding (libx264 / libx265), audio kept as-is when already
  AAC, rotated/scaled via standard filters.
- ffmetadata round-trip to strip media while keeping a whitelist of tags
  (`location*`, `rotate*`).
- Parallel processing via `ProcessPoolExecutor`, Rich progress bar in
  interactive mode, clean SIGINT handling.
- Pydantic v2 config with validation; supports the legacy two-document YAML
  layout (with the `---` separator) and a new single-document layout.

## Installation

```bash
python -m venv .venv
.venv/bin/pip install -e .
```

System tools (must be on `$PATH`):

- `ffmpeg`, `ffprobe` (required for video formats)
- `exiftool` (required for photo metadata stripping)
- `jpeginfo` (optional, used for JPEG integrity check)

On Debian/Ubuntu:

```bash
sudo apt install ffmpeg libimage-exiftool-perl jpeginfo
```

## Usage

```bash
process-media /path/to/files [options]
```

Options (all optional, defaults from config):

| Flag                       | Description                                                |
| -------------------------- | ---------------------------------------------------------- |
| `-t, --type photo,video`   | Media types to process (default: both).                    |
| `-f, --format name1,name2` | Restrict to specific format names from config.             |
| `-c, --config FILE`        | Path to config file.                                       |
| `-m, --max-threads N`      | Worker count (0 = CPU count).                              |
| `--tzoffset SECONDS`       | Apply timezone offset when renaming.                       |
| `-k, --keep-name`          | Skip EXIF-based renaming.                                  |
| `-v, --verbose`            | Verbose logging.                                           |
| `-o, --overwrite`          | Overwrite existing targets.                                |
| `-b, --batch`              | Don't prompt for confirmation.                             |

Config resolution order: `--config` > `./process-media.yaml` >
`/etc/process-media.yaml`.

## Config

New layout (recommended):

```yaml
global:
  max_threads: 0
  verbose: false
  keep_name: false
  overwrite: false
  tzoffset: 0
formats:
  archive_photo:
    type: photo
    rotate: auto
    output_dir: archive
  web_photo:
    type: photo
    rotate: auto
    resize: 1920
    compress: 90
    progressive: true
    strip: true
    strip_exclude: [orientation]
    output_dir: web
  archive_video:
    type: video
    rotate: auto
    reencode: true
    vcodec: x264
    output_dir: archive/videos
  web_video:
    type: video
    rotate: auto
    reencode: true
    resize: 1024
    strip: true
    thumbnail: true
    output_dir: web/videos
```

The legacy two-document YAML format from the Perl version (global options in
doc 1, formats in doc 2 separated by `---`) is still accepted.

### Format options

Photo (`type: photo`):

- `rotate`: `auto` (use EXIF Orientation) or `90`/`180`/`270` (clockwise).
- `resize`: integer (longest side, no upscaling).
- `compress`: 0-100 (JPEG quality).
- `progressive`: bool.
- `strip`: bool — remove all EXIF.
- `strip_exclude`: `gps`, `orientation`, or both.
- `output_dir`: relative (anchored on source dir) or absolute. Defaults to the
  format name.

Video (`type: video`):

- `rotate`: same as above (`auto` keeps source rotation tag).
- `reencode`: bool.
- `vcodec`: `x264` or `x265`.
- `vcodec_params`: raw `-x264-params` / `-x265-params` string.
- `resize`: integer (longest side, no upscaling, via `scale` filter).
- `strip`: bool — round-trip through ffmetadata.
- `thumbnail`: bool — write a JPEG next to the output video.
- `output_dir`: same semantics as photo.

## Duplicate handling

When several source files would yield the same target name (after EXIF
renaming), they all receive a numerical suffix `-001`, `-002`, … per output
format. Dedup is independent for photos and videos.

## Development

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q
```

## Docker

A `Dockerfile` is provided that installs ffmpeg / exiftool / jpeginfo and the
Python package:

```bash
docker build -t process-media .
docker run --rm -v "$PWD:/data" process-media /data -b
```
