# process-media

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](pyproject.toml)
[![APT repo](https://img.shields.io/badge/apt-llavaud.github.io-orange.svg)](https://llavaud.github.io/process-media/)

`process-media` renames photos and videos to `YYYYMMDD-HHMMSS` based on
their capture date, then runs one or more user-defined pipelines
(resize, rotate, strip metadata, re-encode, thumbnail) in parallel.

It's the tool you reach for when you want to clean up a holiday folder
in one command instead of clicking through every file.

## Why use it?

- **Sensible names**: `IMG_3401.jpg` → `20250819-143205.jpg`, sortable
  chronologically across devices.
- **One source, many outputs**: archive originals at full quality *and*
  produce a web-sized resized + stripped version in the same run.
- **Robust to missing EXIF**: falls back to dates parsed from the file
  name (Samsung, iPhone, screenshots, WhatsApp…), then warns you
  loudly when even that fails — so you always know what happened.
- **Fast**: process pool with one worker per CPU, atomic writes, never
  leaves a half-written target on Ctrl+C.

---

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

### From source (Python 3.11+)

```bash
make install                              # creates .venv + dev extras
# or, manually:
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"         # editable + pytest/ruff/mypy
.venv/bin/pip install -e ".[heic]"        # add Apple HEIC/HEIF support
```

System tools (must be on `$PATH`):

| Tool | Required for | Debian/Ubuntu package |
|------|--------------|-----------------------|
| `exiftool` | every photo job (reading EXIF dates, stripping metadata) | `libimage-exiftool-perl` |
| `ffmpeg`, `ffprobe` | every video job | `ffmpeg` |
| `jpeginfo` | optional JPEG integrity check | `jpeginfo` |

```bash
sudo apt install ffmpeg libimage-exiftool-perl jpeginfo
```

---

## Quickstart

```bash
# 1. Drop a config next to your media (or in /etc/process-media.yaml).
cat > ~/Photos/2025/process-media.yaml <<'EOF'
formats:
  archive:
    type: photo
    output_dir: archive
EOF

# 2. Preview what would happen (no file is written).
process-media -r -n ~/Photos/2025

# 3. Once happy, run for real and skip the confirmation prompt.
process-media -r -b ~/Photos/2025
```

A `--dry-run` output looks like:

```
[archive] IMG_3401.jpg          -> archive/20250819-143205.jpg
[archive] Screenshot_20250820_103015.png -> archive/20250820-103015.jpg
[archive] random_picture.jpg    -> archive/random_picture.jpg     # WARNING: no date
```

---

## Usage

```bash
process-media PATH [OPTIONS]
process-media -r -n ~/Photos/2025          # recursive dry-run
process-media -t photo -f web_photo ~/in   # only the 'web_photo' format
```

| Flag                       | Description                                                |
| -------------------------- | ---------------------------------------------------------- |
| `-t, --type photo,video`   | Media types to process (default: both).                    |
| `-f, --format name1,name2` | Restrict to specific format names from config.             |
| `-c, --config FILE`        | Path to config file.                                       |
| `-m, --max-threads N`      | Worker count (0 = CPU count).                              |
| `--tzoffset SECONDS`       | Apply timezone offset when renaming.                       |
| `-k, --keep-name`          | Skip EXIF-based renaming, keep the original stems.         |
| `-v, --verbose`            | Verbose logging.                                           |
| `-o, --overwrite`          | Overwrite existing targets.                                |
| `-b, --batch`              | Don't prompt for confirmation.                             |
| `-n, --dry-run`            | List `source -> target` mappings without writing anything. |
| `-r, --recursive`          | Descend into subdirectories (hidden subtrees skipped).     |

### Supported inputs

| Type  | Accepted extensions                              | Output extension |
|-------|--------------------------------------------------|------------------|
| Photo | `.jpg`, `.jpeg`, `.png`, `.heic`, `.heif`        | `.jpg`           |
| Video | `.mp4`, `.mov`, `.m4v`, `.avi`, `.mkv`, `.webm`, `.3gp` | `.mp4`     |

Outputs are always normalised to JPEG / MP4 (a `.png` screenshot ends
up as `.jpg`, a `.mov` is muxed to `.mp4`).

### How names are resolved

For each file, the base name is computed by trying the following
sources in order:

1. **EXIF / QuickTime metadata** (`DateTimeOriginal`, `CreateDate`,
   `QuickTime:CreateDate`). QuickTime stamps are stored in UTC and are
   automatically converted to local time unless you set an explicit
   `--tzoffset`.
2. **A date embedded in the file name** — covers the formats produced
   by Samsung / Android (`20251019_132023`), iPhone exports
   (`IMG_20240118_091500`), screenshot tools
   (`Screenshot_2025-10-19-13-20-23`), WhatsApp / iCloud
   (`IMG-20251019-WA0001`), and ISO-like names. An `INFO` log line
   tells you when this fallback kicks in.
3. **The original stem** — last resort. A `WARNING` log line tells you
   no date was found, so you know why the file kept its original name.

Use `-k / --keep-name` to skip the whole renaming logic and just run
the pipelines on the existing filenames.

### Duplicate handling

When several source files would yield the same target name (after EXIF
renaming), they all receive a numerical suffix `-001`, `-002`, … per
output format. Dedup is independent for photos and videos.

---

## Configuration

The configuration file is looked up in this order (first hit wins):

1. The `--config` argument.
2. The `$PROCESS_MEDIA_CONFIG` environment variable.
3. `<source_path>/process-media.yaml` — alongside the media you are
   processing (parent directory when `PATH` is a file). This lets you
   drop a config in a holiday folder without worrying about your
   current working directory.
4. `./process-media.yaml` (current working directory).
5. `/etc/process-media.yaml`.

### Example

```yaml
global:
  max_threads: 0       # 0 = use all CPU cores
  verbose: false
  keep_name: false
  overwrite: false
  tzoffset: 0
formats:
  archive_photo:
    type: photo
    rotate: auto
    output_dir: archive          # relative paths are anchored on the source dir
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

A two-document YAML layout (global options in doc 1, formats in doc 2
separated by `---`) is also accepted for backward compatibility.

### Format options

Photo (`type: photo`):

- `rotate`: `auto` (apply EXIF Orientation) or `90` / `180` / `270`
  (clockwise; integers or strings both accepted).
- `resize`: integer (longest side, no upscaling).
- `compress`: `0`-`100` (JPEG quality).
- `progressive`: bool.
- `strip`: bool — remove all metadata via `exiftool`.
- `strip_exclude`: any of `gps`, `orientation` (single value or list).
- `output_dir`: relative (anchored on the source dir) or absolute.
  Defaults to the format name.

Video (`type: video`):

- `rotate`: same as photo (`auto` keeps the source rotation tag).
- `reencode`: bool.
- `vcodec`: `x264` or `x265`.
- `vcodec_params`: raw `-x264-params` / `-x265-params` string.
- `resize`: integer (longest side, no upscaling, via `scale` filter).
- `strip`: bool — round-trip through ffmetadata.
- `thumbnail`: bool — write a JPEG next to the output video.
- `output_dir`: same semantics as photo.

---

## Troubleshooting

**A file keeps its original name.** Check the logs for a
`WARNING [filename] no EXIF date and no recognisable timestamp in the
filename` line. Use `--verbose` to also see which tag was used when
the rename did succeed.

**My `compress: 0` is rejected on a video format.** `compress` is a
photo-only option (it maps to JPEG quality). Drop it from video formats.

**I want to preview without writing anything.** Use `-n / --dry-run`;
it prints every planned `source -> target` mapping and exits.

**Filenames with non-ASCII characters look mangled.** The file names
themselves are passed through verbatim; if your terminal can't display
them, that's a locale/encoding issue (try `LC_ALL=fr_FR.UTF-8`).

---

## Development

```bash
make help       # list every target
make test       # run pytest
make lint       # ruff check
make format     # ruff format
make check      # lint + tests
make clean      # wipe .venv and caches
```

## Docker

A `Dockerfile` is provided that installs ffmpeg / exiftool / jpeginfo
and the Python package:

```bash
docker build -t process-media .
docker run --rm -v "$PWD:/data" process-media /data -b
```

---

## Packaging (Debian / Ubuntu)

### Build a `.deb` locally

```bash
make deb        # produces ../process-media_*.deb
make deb-lint   # lintian --profile debian on the most recent .changes
```

The build runs in a clean environment (the developer `.venv` is masked
out), uses `pybuild + pyproject` and runs the full pytest suite. Build
dependencies are declared in `debian/control`; the easiest way to
install them is:

```bash
sudo apt build-dep .
```

### Publish to the APT repository (`gh-pages`)

The APT repository is hosted on GitHub Pages from the `gh-pages` branch
and managed by `reprepro`. A worktree is automatically created at
`./.gh-pages` so you never need to leave your working branch.

```bash
make apt-publish   # build, ingest, sign and commit on the local gh-pages worktree
make apt-status    # inspect what is about to be published
make apt-push      # push the gh-pages worktree to origin
```

`make apt-publish` is idempotent: it refuses to re-ingest a version
that's already in the repository — bump `debian/changelog` and rebuild
to release a new revision.

### Releasing a new version

1. Bump `__version__`, `pyproject.toml` and `debian/process-media.1`.
2. Run `dch -i` (or edit `debian/changelog`); set the distribution to
   `UNRELEASED` while iterating, `unstable` for the actual release.
3. `make check` (tests + lint).
4. `make deb && make deb-lint`.
5. `make apt-publish && make apt-push`.

Requirements: `reprepro`, `gnupg`, and access to the GPG signing key
referenced in `apt/conf/distributions` on the `gh-pages` branch.

---

## License

MIT — see [LICENSE](LICENSE).
