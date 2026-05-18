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


def test_load_full_realistic_config(tmp_path: Path) -> None:
    """End-to-end load of a realistic two-document YAML covering every option."""
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
        "archive_video:\n"
        "  type: video\n"
        "  rotate: auto\n"
        "  reencode: true\n"
        "  vcodec: x264\n"
        "  output_dir: archive/videos\n"
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

    assert c.global_options.max_threads == 0
    assert c.global_options.verbose is False
    assert c.global_options.keep_name is False
    assert c.global_options.overwrite is False
    assert c.global_options.tzoffset == 0

    assert set(c.formats) == {"archive_photo", "web_photo", "archive_video", "web_video"}

    web_photo = c.formats["web_photo"]
    assert web_photo.resize == 1920
    assert web_photo.compress == 90
    assert web_photo.progressive is True
    assert web_photo.strip is True
    assert web_photo.strip_exclude == ["orientation"]

    archive_video = c.formats["archive_video"]
    assert archive_video.reencode is True
    assert archive_video.vcodec == "x264"

    web_video = c.formats["web_video"]
    assert web_video.resize == 1024
    assert web_video.thumbnail is True


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


def test_output_dir_rejects_parent_traversal() -> None:
    with pytest.raises(ValidationError):
        FormatSpec(type="photo", output_dir="../escape")
    with pytest.raises(ValidationError):
        FormatSpec(type="photo", output_dir="sub/../escape")


def test_output_dir_allows_dotted_subdir() -> None:
    # A leading dot or embedded dot is fine — only ``..`` is forbidden.
    spec = FormatSpec(type="photo", output_dir=".archive/2024")
    assert spec.output_dir == ".archive/2024"


def test_config_rejects_unknown_root_key(tmp_path: Path) -> None:
    """``Config(extra=forbid)`` catches typos like ``globals:`` at the top level."""
    p = tmp_path / "typo.yaml"
    p.write_text(
        "globals:\n"  # should be "global"
        "  max_threads: 1\n"
        "formats: {}\n"
    )
    with pytest.raises(ValidationError):
        load_config(p)


def test_load_config_from_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "from-env.yaml"
    p.write_text(
        "global:\n"
        "  max_threads: 3\n"
        "formats:\n"
        "  fmt:\n"
        "    type: photo\n"
        "    output_dir: out\n"
    )
    monkeypatch.setenv("PROCESS_MEDIA_CONFIG", str(p))
    # Use an isolated cwd so the cwd fallback can't accidentally match.
    monkeypatch.chdir(tmp_path)
    c = load_config()
    assert c.global_options.max_threads == 3
    assert "fmt" in c.formats


def test_env_var_overridden_by_explicit_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_cfg = tmp_path / "env.yaml"
    env_cfg.write_text("global: {max_threads: 1}\nformats: {}\n")
    explicit_cfg = tmp_path / "explicit.yaml"
    explicit_cfg.write_text("global: {max_threads: 9}\nformats: {}\n")
    monkeypatch.setenv("PROCESS_MEDIA_CONFIG", str(env_cfg))
    c = load_config(explicit_cfg)
    assert c.global_options.max_threads == 9
