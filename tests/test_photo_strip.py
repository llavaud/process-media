"""Unit tests for the photo metadata-strip logic (B3)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from process_media.media import photo as photo_mod


def _capture_exiftool_args(
    target: Path, source: Path, *, rotation_applied: bool, strip_exclude: list[str]
):
    captured: list[list[str]] = []

    def _fake_run(cmd, **_kwargs):
        captured.append(list(cmd))
        return None

    with (
        patch.object(photo_mod, "which", return_value="/usr/bin/exiftool"),
        patch.object(photo_mod, "run", side_effect=_fake_run),
    ):
        photo_mod._strip_metadata(
            target=target,
            source=source,
            strip_exclude=strip_exclude,
            rotation_applied=rotation_applied,
        )
    assert len(captured) == 1
    return captured[0]


def test_strip_keeps_orientation_from_source_when_no_rotation(tmp_path: Path) -> None:
    """No rotation applied → import Orientation tag from the source file."""
    src = tmp_path / "in.jpg"
    src.write_text("")
    target = tmp_path / "out.jpg"
    target.write_text("")

    args = _capture_exiftool_args(
        target, src, rotation_applied=False, strip_exclude=["orientation"]
    )
    assert "-tagsfromfile" in args
    assert str(src) in args
    assert "-EXIF:Orientation" in args
    # Must NOT have the forced reset value.
    assert "-IFD0:Orientation=1" not in args


def test_strip_forces_orientation_one_after_rotation(tmp_path: Path) -> None:
    """B3: rotation applied → force Orientation=1 instead of re-importing."""
    src = tmp_path / "in.jpg"
    src.write_text("")
    target = tmp_path / "out.jpg"
    target.write_text("")

    args = _capture_exiftool_args(target, src, rotation_applied=True, strip_exclude=["orientation"])
    assert "-IFD0:Orientation#=1" in args
    # Must NOT re-import the (now stale) source Orientation tag.
    assert "-EXIF:Orientation" not in args


def test_strip_gps_unaffected_by_rotation_flag(tmp_path: Path) -> None:
    """``gps`` exclusion still re-imports GPS regardless of rotation."""
    src = tmp_path / "in.jpg"
    src.write_text("")
    target = tmp_path / "out.jpg"
    target.write_text("")

    args = _capture_exiftool_args(target, src, rotation_applied=True, strip_exclude=["gps"])
    assert "-GPS:all" in args
    assert str(src) in args


def test_strip_uses_atomic_overwrite(tmp_path: Path) -> None:
    """Strip command uses ``-overwrite_original_in_place`` (atomic)."""
    src = tmp_path / "in.jpg"
    src.write_text("")
    target = tmp_path / "out.jpg"
    target.write_text("")

    args = _capture_exiftool_args(target, src, rotation_applied=False, strip_exclude=[])
    assert "-overwrite_original_in_place" in args
    assert "-all=" in args
