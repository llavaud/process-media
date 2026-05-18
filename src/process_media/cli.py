"""Command-line entry point for ``process-media``."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Annotated, Optional, cast

import typer
from rich.logging import RichHandler
from rich.prompt import Confirm

from .config import FormatSpec, load_config
from .media.base import MediaType
from .naming import batch_exif_dates, build_jobs, scan_media
from .runner import run_jobs
from .tools import ensure_tools


logger = logging.getLogger("process_media")
app = typer.Typer(add_completion=False, help="Process photos and videos.")


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    # Reset handlers so calling _setup_logging twice doesn't duplicate output.
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = RichHandler(rich_tracebacks=True, show_path=False)
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="%H:%M:%S",
        handlers=[handler],
    )


def _split_csv(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip() for item in value.split(",") if item.strip()}


@app.command()
def main(
    path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            readable=True,
            help="File or directory to scan (use --recursive to descend).",
        ),
    ],
    type_filter: Annotated[
        str,
        typer.Option(
            "--type",
            "-t",
            help="Comma-separated media types to process.",
        ),
    ] = "photo,video",
    format_filter: Annotated[
        Optional[str],
        typer.Option(
            "--format",
            "-f",
            help="Comma-separated format names from the config.",
        ),
    ] = None,
    config_path: Annotated[
        Optional[Path],
        typer.Option(
            "--config",
            "-c",
            help="Path to the YAML configuration file.",
        ),
    ] = None,
    max_threads: Annotated[
        Optional[int],
        typer.Option(
            "--max-threads",
            "-m",
            help="Worker count (0 = number of CPUs).",
        ),
    ] = None,
    tzoffset: Annotated[
        Optional[int],
        typer.Option(
            "--tzoffset",
            help="Seconds added to EXIF timestamps before renaming.",
        ),
    ] = None,
    keep_name: Annotated[
        bool,
        typer.Option("--keep-name", "-k", help="Do not rename files from EXIF."),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable debug logging."),
    ] = False,
    overwrite: Annotated[
        bool,
        typer.Option("--overwrite", "-o", help="Overwrite existing targets."),
    ] = False,
    batch: Annotated[
        bool,
        typer.Option("--batch", "-b", help="Non-interactive (skip y/n prompt)."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            "-n",
            help="List the planned source -> target mappings without writing anything.",
        ),
    ] = False,
    recursive: Annotated[
        bool,
        typer.Option(
            "--recursive",
            "-r",
            help="Scan PATH recursively (descend into subdirectories).",
        ),
    ] = False,
) -> None:
    """Process media in PATH according to the configuration file."""
    _setup_logging(verbose)

    try:
        cfg = load_config(config_path)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        raise typer.Exit(code=2)
    except Exception as exc:  # ValidationError, yaml errors…
        logger.error("Invalid configuration: %s", exc)
        raise typer.Exit(code=2)

    # CLI overrides take precedence over the config file.
    if max_threads is not None:
        cfg.global_options.max_threads = max_threads
    if tzoffset is not None:
        cfg.global_options.tzoffset = tzoffset
    if keep_name:
        cfg.global_options.keep_name = True
    if overwrite:
        cfg.global_options.overwrite = True
    if verbose:
        cfg.global_options.verbose = True

    # Re-apply log level in case the config bumped verbose.
    _setup_logging(cfg.global_options.verbose)

    wanted_types: set[str] = _split_csv(type_filter) or {"photo", "video"}
    wanted_formats = _split_csv(format_filter)

    formats: dict[str, FormatSpec] = {
        name: spec
        for name, spec in cfg.formats.items()
        if spec.type in wanted_types
        and (not wanted_formats or name in wanted_formats)
    }
    if not formats:
        logger.error("No format matches the requested --type/--format selection.")
        raise typer.Exit(code=2)

    # In dry-run mode we never touch the disk, so we don't enforce the
    # presence of ffmpeg/exiftool. A user can preview a plan on a machine
    # that doesn't have the binaries installed yet.
    if not dry_run:
        needs_ffmpeg = any(spec.type == "video" for spec in formats.values())
        needs_exiftool = any(spec.type == "photo" for spec in formats.values())
        try:
            ensure_tools(needs_ffmpeg=needs_ffmpeg, needs_exiftool=needs_exiftool)
        except RuntimeError as exc:
            logger.error("%s", exc)
            raise typer.Exit(code=3)

    files = scan_media(path, recursive=recursive)
    if not files:
        logger.warning("No supported media file found under %s", path)
        raise typer.Exit(code=0)

    files = cast(
        "list[tuple[Path, MediaType]]",
        [(p, mt) for p, mt in files if mt in wanted_types],
    )
    if not files:
        logger.warning("No file matched the --type filter.")
        raise typer.Exit(code=0)

    logger.info("Found %d media file(s) under %s", len(files), path)

    exif_dates: dict = {}
    # Skip the (potentially slow) EXIF batch in dry-run too: target names
    # will fall back to source stems, which is good enough for previewing.
    if not cfg.global_options.keep_name and not dry_run:
        try:
            exif_dates = batch_exif_dates([p for p, _ in files])
        except Exception as exc:
            logger.warning("EXIF extraction failed (%s); falling back to original names.", exc)

    jobs = build_jobs(files, formats, cfg.global_options, exif_dates)
    logger.info(
        "Built %d job(s) across %d format(s).", len(jobs), len(formats)
    )

    if dry_run:
        for job in jobs:
            logger.info(
                "[dry-run] [%s] %s -> %s", job.format_name, job.source, job.target
            )
        logger.info(
            "Dry-run complete: %d job(s) would run, nothing was written.", len(jobs)
        )
        raise typer.Exit(code=0)

    if not batch:
        proceed = Confirm.ask("Proceed?", default=False)
        if not proceed:
            logger.info("Aborted by user.")
            raise typer.Exit(code=0)

    ok, err = run_jobs(
        jobs,
        max_workers=cfg.global_options.max_threads,
        batch=batch,
    )
    logger.info("Finished: %d ok, %d error(s)", ok, err)
    if err:
        raise typer.Exit(code=1)


if __name__ == "__main__":  # pragma: no cover
    app()
