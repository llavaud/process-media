"""Tests for the Typer CLI surface."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from process_media.cli import app


runner_ = CliRunner()


def _make_minimal_photo_config(tmp_path: Path, output_dir: str = "out") -> Path:
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(
        "global:\n"
        "  max_threads: 1\n"
        "formats:\n"
        "  f1:\n"
        "    type: photo\n"
        f"    output_dir: {output_dir}\n"
    )
    return cfg


def test_help_exits_zero() -> None:
    result = runner_.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Process media" in result.stdout


def test_missing_config_exits_2(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    (media / "x.jpg").write_bytes(b"x")
    result = runner_.invoke(app, [str(media), "-b", "-c", str(tmp_path / "nope.yaml")])
    assert result.exit_code == 2


def test_no_matching_format_exits_2(tmp_path: Path) -> None:
    """Asking for a media type that no format covers must error out cleanly."""
    cfg = _make_minimal_photo_config(tmp_path)
    media = tmp_path / "media"
    media.mkdir()
    (media / "x.jpg").write_bytes(b"x")
    # Only photo formats exist; the user asks for videos only.
    result = runner_.invoke(app, [str(media), "-t", "video", "-b", "-c", str(cfg)])
    assert result.exit_code == 2


def test_no_media_files_exits_zero(tmp_path: Path) -> None:
    """Empty directory should be a successful no-op."""
    cfg = _make_minimal_photo_config(tmp_path)
    media = tmp_path / "media"
    media.mkdir()
    result = runner_.invoke(app, [str(media), "-b", "-c", str(cfg)])
    assert result.exit_code == 0


def test_dry_run_does_not_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``--dry-run`` must list jobs and exit without creating any output."""
    cfg = _make_minimal_photo_config(tmp_path)
    media = tmp_path / "media"
    media.mkdir()
    (media / "x.jpg").write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)
    # Bypass the real exiftool/ffmpeg dependency checks for unit testing.
    monkeypatch.setattr("process_media.cli.batch_exif_dates", lambda paths: {p: None for p in paths})
    monkeypatch.setattr("process_media.cli.ensure_tools", lambda **kw: None)
    result = runner_.invoke(app, [str(media), "-b", "-n", "-c", str(cfg)])
    assert result.exit_code == 0, result.stdout
    assert not (media / "out").exists()


def test_missing_path_argument_exits_nonzero() -> None:
    result = runner_.invoke(app, [])
    assert result.exit_code != 0
