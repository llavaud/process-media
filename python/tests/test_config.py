"""Tests for the YAML loader and pydantic models."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from process_media.config import Config, FormatSpec, GlobalOptions, load_config


def test_load_new_style(tmp_path: Path) -> None:
    cfg = {
        "global": {"max_threads": 2, "tzoffset": -3600},
        "formats": {
            "a": {"type": "photo", "output_dir": "out", "rotate": "auto"},
        },
    }
    p = tmp_path / "cfg.yaml"
    p.write_text(yaml.safe_dump(cfg))

    c = load_config(p)
    assert c.global_options.max_threads == 2
    assert c.global_options.tzoffset == -3600
    assert "a" in c.formats
    assert c.formats["a"].type == "photo"


def test_load_legacy_multidoc(tmp_path: Path) -> None:
    p = tmp_path / "legacy.yaml"
    p.write_text(
        "---\n"
        "max_threads: 1\n"
        "verbose: true\n"
        "---\n"
        "b:\n"
        "  type: video\n"
        "  output_dir: vout\n"
        "  reencode: true\n"
        "  vcodec: x264\n",
    )
    c = load_config(p)
    assert c.global_options.max_threads == 1
    assert c.global_options.verbose is True
    assert "b" in c.formats
    assert c.formats["b"].vcodec == "x264"


def test_load_reference_legacy_yaml(tmp_path: Path) -> None:
    """The historic two-document file from the Perl repo must still load."""
    p = tmp_path / "process-media.yaml"
    p.write_text(
        "---\n"
        "max_threads: 0\n"
        "verbose: false\n"
        "keep_name: false\n"
        "overwrite: false\n"
        "tzoffset: 0\n"
        "---\n"
        "archive_photo:\n"
        "  type: photo\n"
        "  rotate: auto\n"
        "  output_dir: archive\n"
        "web_photo:\n"
        "  type: photo\n"
        "  rotate: auto\n"
        "  resize: 1920\n"
        "  compress: 90\n"
        "  progressive: true\n"
        "  strip: true\n"
        "  strip_exclude: orientation\n"
        "  output_dir: web\n"
        "web_video:\n"
        "  type: video\n"
        "  rotate: auto\n"
        "  reencode: true\n"
        "  resize: 1024\n"
        "  strip: true\n"
        "  thumbnail: true\n"
        "  output_dir: web/videos\n",
    )
    c = load_config(p)
    assert {"archive_photo", "web_photo", "web_video"} <= set(c.formats)
    assert c.formats["web_photo"].strip_exclude == ["orientation"]
    assert c.formats["web_video"].thumbnail is True


def test_invalid_rotate() -> None:
    with pytest.raises(ValidationError):
        FormatSpec(type="photo", rotate="45", output_dir="x")  # type: ignore[arg-type]


def test_invalid_compress() -> None:
    with pytest.raises(ValidationError):
        FormatSpec(type="photo", compress=150, output_dir="x")


def test_video_only_options_rejected_for_photo() -> None:
    with pytest.raises(ValidationError):
        FormatSpec(type="photo", reencode=True, output_dir="x")


def test_photo_only_options_rejected_for_video() -> None:
    with pytest.raises(ValidationError):
        FormatSpec(type="video", progressive=True, output_dir="x")


def test_strip_exclude_accepts_csv_string() -> None:
    spec = FormatSpec(
        type="photo",
        strip=True,
        strip_exclude="gps,orientation",  # type: ignore[arg-type]
        output_dir="x",
    )
    assert spec.strip_exclude == ["gps", "orientation"]


def test_missing_config_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yaml")


def test_global_options_defaults() -> None:
    g = GlobalOptions()
    assert g.max_threads == 0
    assert g.tzoffset == 0
    assert g.verbose is False
