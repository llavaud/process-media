"""Tests for the pure helper functions in the video pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from process_media.config import FormatSpec
from process_media.media.video import _build_vf, _filter_ffmetadata


def _spec(*, rotate: str = "auto", resize: int | None = None) -> FormatSpec:
    """Build a real ``FormatSpec`` so validators run on the inputs too."""
    return FormatSpec.model_validate({"type": "video", "rotate": rotate, "resize": resize})


class TestBuildVf:
    @pytest.mark.parametrize(
        ("rotate", "expected"),
        [
            ("auto", []),
            ("90", ["transpose=1"]),
            ("180", ["transpose=1", "transpose=1"]),
            ("270", ["transpose=1", "transpose=1", "transpose=1"]),
        ],
    )
    def test_rotation_only(self, rotate: str, expected: list[str]) -> None:
        assert _build_vf(_spec(rotate=rotate)) == expected

    def test_resize_only_uses_min_scale(self) -> None:
        vf = _build_vf(_spec(resize=1024))
        assert vf
        assert any("scale=" in f and "1024" in f for f in vf)

    def test_scale_filter_forces_even_height(self) -> None:
        # The encoder rejects odd dimensions, so we always end on ``-2``
        # (not ``-1``). See review B1.
        vf = _build_vf(_spec(resize=1024))
        assert vf[-1].endswith(":-2")

    def test_rotation_and_resize_combined(self) -> None:
        vf = _build_vf(_spec(rotate="90", resize=1024))
        assert any("transpose=1" in f for f in vf)
        assert any("scale=" in f and "1024" in f for f in vf)


class TestFilterFfmetadata:
    HEADER = ";FFMETADATA1\n"

    def _write_and_call(self, tmp_path: Path, text: str, keep: list[str]) -> str:
        p = tmp_path / "raw.ffmeta"
        p.write_text(text)
        _filter_ffmetadata(p, set(keep))
        return p.read_text() if p.exists() else ""

    def test_strips_everything_except_header_when_no_exclude(self, tmp_path: Path) -> None:
        text = self.HEADER + "title=foo\nartist=bar\nlocation=42.0\nrotate=90\n"
        # Nothing preserved beyond the header → the file is deleted.
        assert self._write_and_call(tmp_path, text, []) == ""

    def test_keeps_location_when_gps_excluded(self, tmp_path: Path) -> None:
        text = self.HEADER + "title=foo\nlocation=42.0\nrotate=90\n"
        result = self._write_and_call(tmp_path, text, ["gps"])
        assert "location=42.0" in result
        assert "title" not in result
        assert "rotate" not in result

    def test_keeps_rotate_when_orientation_excluded(self, tmp_path: Path) -> None:
        text = self.HEADER + "title=foo\nlocation=42.0\nrotate=90\n"
        result = self._write_and_call(tmp_path, text, ["orientation"])
        assert "rotate=90" in result
        assert "location" not in result
        assert "title" not in result

    def test_keeps_both_gps_and_orientation(self, tmp_path: Path) -> None:
        text = self.HEADER + "title=foo\nlocation=42.0\nrotate=90\nartist=baz\n"
        result = self._write_and_call(tmp_path, text, ["gps", "orientation"])
        assert "location=42.0" in result
        assert "rotate=90" in result
        assert "title" not in result
        assert "artist" not in result
