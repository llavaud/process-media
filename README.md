# process-media

Renames media files from their EXIF capture date and processes them through
one or more named output formats (rotation, resize, JPEG quality, video
reencoding, metadata stripping, thumbnail generation, integrity check).

Targets Python 3.11+ and uses **system-installed** ffmpeg / exiftool.

## Features

- Pillow-based JPEG processing (auto-orient via EXIF, forced rotation, resize
  without upscaling, progressive output, atomic writes).
- Direct `exiftool` calls (no Python wrapper) to strip metadata while
  optionally preserving GPS or orientation, and to batch-read creation
  dates as JSON.
- ffmpeg-based reencoding (libx264 / libx265), audio kept as-is when already
  AAC, rotated/scaled via standard filters.
- ffmetadata round-trip to strip media while keeping a whitelist of tags
  (`location*`, `rotate*`).
- Parallel processing via `ProcessPoolExecutor`, Rich progress bar in
  interactive mode, clean SIGINT handling.
- Pydantic v2 config with validation; supports a single-document YAML
  layout (recommended) and a two-document layout (global options + formats
  separated by `---`).

## Installation

### From the APT repository (Debian trixie / Ubuntu 25.04+)

```bash
# Trust the signing key
curl -fsSL https://llavaud.github.io/process-media/apt/conf/gpg.key \
    | sudo gpg --dearmor -o /usr/share/keyrings/process-media-archive-keyring.gpg

# Add the repository
echo "deb [signed-by=/usr/share/keyrings/process-media-archive-keyring.gpg] \
https://llavaud.github.io/process-media/apt stable main" \
    | sudo tee /etc/apt/sources.list.d/process-media.list

sudo apt update
sudo apt install process-media
```

The package pulls every runtime dependency from the distribution
(`python3-typer`, `python3-pydantic`, `python3-pil`, `python3-rich`,
`python3-yaml`, `ffmpeg`, `libimage-exiftool-perl`, …) so you get a
working `/usr/bin/process-media` out of the box.

### For development

```bash
make install
```

This creates `.venv/` and installs the package in editable mode together
with the dev extras (pytest, ruff, mypy, pillow-heif). See `make help`
for the full list of available targets.

If you'd rather drive things by hand:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

For HEIC / HEIF (Apple) photo support only (without the dev tooling):

```bash
.venv/bin/pip install -e ".[heic]"
```

System tools (must be on `$PATH`):

- `ffmpeg`, `ffprobe` (required for video formats)
- `exiftool` (required for photo metadata stripping)
- `jpeginfo` (optional, used for JPEG integrity check)

On Debian/Ubuntu (the `exiftool` package is named `libimage-exiftool-perl`
upstream — that's just how it's distributed, not a project dependency):

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
| `-n, --dry-run`            | List `source -> target` mappings without writing anything. |
| `-r, --recursive`          | Descend into subdirectories (hidden subtrees skipped).     |

Config resolution order: `--config` > `$PROCESS_MEDIA_CONFIG` >
`./process-media.yaml` > `/etc/process-media.yaml`.

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

A two-document layout (global options in doc 1, formats in doc 2 separated
by `---`) is also accepted.

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

Common workflows are wired through the Makefile:

```bash
make test       # run pytest
make lint       # ruff check
make format     # ruff format
make check      # lint + tests
make clean      # wipe .venv and caches
```

## Docker

A `Dockerfile` is provided that installs ffmpeg / exiftool / jpeginfo and the
Python package:

```bash
docker build -t process-media .
docker run --rm -v "$PWD:/data" process-media /data -b
```

## Packaging (Debian / Ubuntu)

### Build a `.deb` locally

```bash
make deb        # produces ../process-media_<version>-1_all.deb
```

The build runs in a clean environment (the developer `.venv` is masked
out), uses `pybuild + pyproject` and runs the full pytest suite. Build
dependencies are listed in `debian/control`:

```bash
sudo apt install debhelper dh-python pybuild-plugin-pyproject \
                 python3-hatchling python3-all python3-pytest \
                 python3-pil python3-pydantic python3-rich \
                 python3-typer python3-yaml
```

### Publish to the APT repository (`gh-pages`)

The APT repository is hosted on GitHub Pages from the `gh-pages` branch
and managed by `reprepro`. A worktree is automatically created at
`./.gh-pages` so you never need to leave your working branch.

```bash
# Build, ingest, sign and commit the package on the local gh-pages worktree.
make apt-publish

# Inspect what's about to be published.
make apt-status

# Push the result to GitHub.
make apt-push
```

`make apt-publish` is idempotent: it refuses to re-ingest a version
that's already in the repository — bump `debian/changelog` and rebuild
to release a new revision.

### Releasing a new version

1. Update `debian/changelog` (`dch -i` or manual edit; set the
   distribution to `UNRELEASED` while iterating).
2. Run `make check` to ensure tests / linter pass.
3. Run `make deb` and inspect with `lintian ../process-media_*.changes`.
4. Run `make apt-publish && make apt-push`.

Requirements: `reprepro`, `gnupg`, and access to the GPG signing key
referenced in `apt/conf/distributions` on the `gh-pages` branch.
