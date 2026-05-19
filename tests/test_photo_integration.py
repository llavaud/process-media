"""End-to-end integration tests for the photo pipeline.

These tests exercise the real Pillow read/write path on tiny generated
JPEGs. ``exiftool`` (the binary) is mocked because we don't want to
require it for unit tests and we already cover its argument shape in
``test_photo_strip``. ``jpeginfo`` is silently no-op when the binary
isn't on PATH thanks to the existing ``which`` lookup.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from process_media.config import FormatSpec
from process_media.media import photo as photo_mod
from process_media.media.base import MediaJob


def _make_source(tmp_path: Path, size: tuple[int, int] = (200, 100)) -> Path:
    """Generate a tiny RGB JPEG that Pillow can round-trip without surprises."""
    src = tmp_path / "in.jpg"
    img = Image.new("RGB", size, color=(120, 50, 200))
    img.save(src, format="JPEG", quality=95)
    return src


def _make_job(*, source: Path, target: Path, spec: FormatSpec, overwrite: bool = False) -> MediaJob:
    return MediaJob(
        source=source,
        target=target,
        format_name="test",
        format_spec=spec,
        media_type="photo",
        overwrite=overwrite,
    )


@pytest.fixture(autouse=True)
def _stub_external_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend exiftool and jpeginfo are unavailable so we exercise pure Pillow."""
    photo_mod.which.cache_clear()
    monkeypatch.setattr(photo_mod, "which", lambda _name: None)


def test_copy_fast_path_preserves_bytes(tmp_path: Path) -> None:
    """When no transform is requested, source bytes must reach the target unchanged."""
    src = _make_source(tmp_path)
    target = tmp_path / "out" / "copy.jpg"
    spec = FormatSpec(type="photo", output_dir="out")

    result = photo_mod.process_photo(_make_job(source=src, target=target, spec=spec))

    assert result.success
    assert not result.skipped
    assert target.exists()
    assert target.read_bytes() == src.read_bytes()


def test_resize_shrinks_longer_edge(tmp_path: Path) -> None:
    src = _make_source(tmp_path, size=(2000, 1000))
    target = tmp_path / "out" / "small.jpg"
    spec = FormatSpec(type="photo", output_dir="out", resize=500)

    result = photo_mod.process_photo(_make_job(source=src, target=target, spec=spec))

    assert result.success
    with Image.open(target) as img:
        assert max(img.size) == 500
        # Aspect ratio preserved.
        assert img.size == (500, 250)


def test_no_upscale_when_smaller_than_resize(tmp_path: Path) -> None:
    src = _make_source(tmp_path, size=(100, 50))
    target = tmp_path / "out" / "kept.jpg"
    spec = FormatSpec(type="photo", output_dir="out", resize=500)

    photo_mod.process_photo(_make_job(source=src, target=target, spec=spec))

    with Image.open(target) as img:
        assert img.size == (100, 50)


def test_progressive_jpeg_emitted_when_requested(tmp_path: Path) -> None:
    src = _make_source(tmp_path)
    target = tmp_path / "out" / "prog.jpg"
    spec = FormatSpec(type="photo", output_dir="out", compress=80, progressive=True)

    photo_mod.process_photo(_make_job(source=src, target=target, spec=spec))

    with Image.open(target) as img:
        assert img.info.get("progressive") or img.info.get("progression")


def test_skip_when_target_exists_and_no_overwrite(tmp_path: Path) -> None:
    src = _make_source(tmp_path)
    target = tmp_path / "out" / "exists.jpg"
    target.parent.mkdir()
    target.write_bytes(b"placeholder")

    spec = FormatSpec(type="photo", output_dir="out", resize=50)
    result = photo_mod.process_photo(_make_job(source=src, target=target, spec=spec))

    assert result.success
    assert result.skipped
    # Target untouched.
    assert target.read_bytes() == b"placeholder"


def test_overwrite_replaces_existing_target(tmp_path: Path) -> None:
    src = _make_source(tmp_path)
    target = tmp_path / "out" / "exists.jpg"
    target.parent.mkdir()
    target.write_bytes(b"placeholder")

    spec = FormatSpec(type="photo", output_dir="out", resize=50)
    job = _make_job(source=src, target=target, spec=spec, overwrite=True)
    result = photo_mod.process_photo(job)

    assert result.success
    assert not result.skipped
    # Target is a real JPEG now, not the placeholder.
    with Image.open(target) as img:
        assert img.format == "JPEG"
        assert max(img.size) <= 50


def test_target_parent_created_automatically(tmp_path: Path) -> None:
    src = _make_source(tmp_path)
    target = tmp_path / "deep" / "nested" / "tree" / "out.jpg"
    spec = FormatSpec(type="photo", output_dir="ignored")
    job = _make_job(source=src, target=target, spec=spec)

    result = photo_mod.process_photo(job)

    assert result.success
    assert target.exists()


def test_failure_leaves_no_tempfile_behind(tmp_path: Path) -> None:
    """If Pillow.save explodes, no ``.process-media_*`` file is left in target dir."""
    src = _make_source(tmp_path)
    target = tmp_path / "out" / "fail.jpg"
    spec = FormatSpec(type="photo", output_dir="out", resize=50)

    with patch.object(Image.Image, "save", side_effect=RuntimeError("boom")):
        result = photo_mod.process_photo(_make_job(source=src, target=target, spec=spec))

    assert not result.success
    assert result.error is not None
    assert "boom" in result.error
    # Target was never written.
    assert not target.exists()
    # No leftover temp files in the output directory.
    assert not list(target.parent.glob(".process-media_*"))
