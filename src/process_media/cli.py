"""Command-line entry point for ``process-media``."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer
import yaml
from pydantic import ValidationError
from rich.prompt import Confirm

from .config import Config, FormatSpec, resolve_and_load_config
from .logging_setup import setup_logging
from .media.base import MediaJob, MediaType
from .naming import ExifDate, batch_exif_dates, build_jobs, scan_media
from .runner import run_jobs
from .tools import ToolError, ensure_tools

logger = logging.getLogger("process_media")
app = typer.Typer(add_completion=False, help="Process photos and videos.")


def _setup_logging(verbose: bool) -> None:
    setup_logging(logging.DEBUG if verbose else logging.INFO)


def _split_csv(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip() for item in value.split(",") if item.strip()}


def _load_config(config_path: Path | None, source_path: Path) -> tuple[Config, Path]:
    """Resolve and parse the YAML configuration, turning errors into ``Exit``."""
    try:
        return resolve_and_load_config(config_path, source_path=source_path)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        raise typer.Exit(code=2) from exc
    except (ValidationError, yaml.YAMLError) as exc:
        logger.error("Invalid configuration: %s", exc)
        raise typer.Exit(code=2) from exc


def _select_formats(
    cfg: Config,
    wanted_types: set[MediaType],
    wanted_formats: set[str],
) -> dict[str, FormatSpec]:
    """Keep only the formats matching the ``--type`` / ``--format`` selection."""
    formats = {
        name: spec
        for name, spec in cfg.formats.items()
        if spec.type in wanted_types and (not wanted_formats or name in wanted_formats)
    }
    if not formats:
        logger.error("No format matches the requested --type/--format selection.")
        raise typer.Exit(code=2)
    return formats


def _collect_exif_dates(
    files: list[tuple[Path, MediaType]],
    *,
    keep_name: bool,
    dry_run: bool,
) -> dict[Path, ExifDate | None]:
    """Run the EXIF batch unless we can short-circuit (keep-name or dry-run)."""
    if keep_name or dry_run:
        return {}
    try:
        return batch_exif_dates([p for p, _ in files])
    except OSError as exc:
        logger.warning("EXIF extraction failed (%s); falling back to original names.", exc)
        return {}


def _emit_dry_run(jobs: list[MediaJob]) -> None:
    for job in jobs:
        logger.info("[dry-run] [%s] %s -> %s", job.format_name, job.source, job.target)
    logger.info("Dry-run complete: %d job(s) would run, nothing was written.", len(jobs))


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
        str | None,
        typer.Option(
            "--format",
            "-f",
            help="Comma-separated format names from the config.",
        ),
    ] = None,
    config_path: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to the YAML configuration file.",
        ),
    ] = None,
    max_threads: Annotated[
        int | None,
        typer.Option(
            "--max-threads",
            "-m",
            help="Worker count (0 = number of CPUs).",
        ),
    ] = None,
    tzoffset: Annotated[
        int | None,
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

    cfg, cfg_source = _load_config(config_path, path)
    logger.info("Loaded configuration from %s", cfg_source)

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

    raw_types = _split_csv(type_filter) or {"photo", "video"}
    # Narrow to the ``MediaType`` literal so downstream calls (build_jobs,
    # filtering) keep precise typing.
    wanted_types: set[MediaType] = {t for t in ("photo", "video") if t in raw_types}
    wanted_formats = _split_csv(format_filter)

    formats = _select_formats(cfg, wanted_types, wanted_formats)

    # In dry-run mode we never touch the disk, so we don't enforce the
    # presence of ffmpeg/exiftool. A user can preview a plan on a machine
    # that doesn't have the binaries installed yet.
    if not dry_run:
        needs_ffmpeg = any(spec.type == "video" for spec in formats.values())
        needs_exiftool = any(spec.type == "photo" for spec in formats.values())
        try:
            ensure_tools(needs_ffmpeg=needs_ffmpeg, needs_exiftool=needs_exiftool)
        except ToolError as exc:
            logger.error("%s", exc)
            raise typer.Exit(code=3) from exc

    files: list[tuple[Path, MediaType]] = scan_media(path, recursive=recursive)
    if not files:
        logger.warning("No supported media file found under %s", path)
        raise typer.Exit(code=0)

    files = [(p, mt) for p, mt in files if mt in wanted_types]
    if not files:
        logger.warning("No file matched the --type filter.")
        raise typer.Exit(code=0)

    logger.info("Found %d media file(s) under %s", len(files), path)

    exif_dates = _collect_exif_dates(
        files,
        keep_name=cfg.global_options.keep_name,
        dry_run=dry_run,
    )

    jobs = build_jobs(files, formats, cfg.global_options, exif_dates)
    logger.info("Built %d job(s) across %d format(s).", len(jobs), len(formats))

    if dry_run:
        _emit_dry_run(jobs)
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
