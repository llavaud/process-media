"""Tests for the pure helper functions in the video pipeline."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from process_media.media.video import _build_vf, _filter_ffmetadata


class TestBuildVf:
    def test_no_rotation_no_resize_returns_empty_list(self) -> None:
        spec = SimpleNamespace(rotate="auto", resize=None)
        assert _build_vf(spec) == []

    def test_rotate_90_transpose(self) -> None:
        spec = SimpleNamespace(rotate="90", resize=None)
        assert _build_vf(spec) == ["transpose=1"]

    def test_rotate_180_two_transposes(self) -> None:
        spec = SimpleNamespace(rotate="180", resize=None)
        assert _build_vf(spec) == ["transpose=1", "transpose=1"]

    def test_rotate_270_three_transposes(self) -> None:
        spec = SimpleNamespace(rotate="270", resize=None)
        assert _build_vf(spec) == ["transpose=1", "transpose=1", "transpose=1"]

    def test_resize_only_uses_min_scale(self) -> None:
        spec = SimpleNamespace(rotate="auto", resize=1024)
        vf = _build_vf(spec)
        assert vf and any("scale=" in f and "1024" in f for f in vf)

    def test_rotation_and_resize_combined(self) -> None:
        spec = SimpleNamespace(rotate="90", resize=1024)
        vf = _build_vf(spec)
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
