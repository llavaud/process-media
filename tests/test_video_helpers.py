from process_media.media.video import _build_vf, _filter_ffmetadata
from types import SimpleNamespace
from pathlib import Path


class TestBuildVf:
    def test_no_rotation_no_resize_returns_empty_list(self):
        spec = SimpleNamespace(rotate="auto", resize=None)
        out = _build_vf(spec)
        assert out == []

    def test_rotate_90_transpose(self):
        spec = SimpleNamespace(rotate="90", resize=None)
        assert "transpose=1" in (",".join(_build_vf(spec)) or "")

    def test_rotate_180_two_transposes(self):
        spec = SimpleNamespace(rotate="180", resize=None)
        assert _build_vf(spec) == ["transpose=1", "transpose=1"]

    def test_rotate_270_three_transposes(self):
        spec = SimpleNamespace(rotate="270", resize=None)
        assert _build_vf(spec) == ["transpose=1", "transpose=1", "transpose=1"]

    def test_resize_only_uses_min_scale(self):
        spec = SimpleNamespace(rotate="auto", resize=1024)
        vf = _build_vf(spec)
        assert vf and any("scale=" in f and "1024" in f for f in vf)

    def test_rotation_and_resize_combined(self):
        spec = SimpleNamespace(rotate="90", resize=1024)
        vf = _build_vf(spec)
        assert any("transpose=1" in f for f in vf)
        assert any("scale=" in f and "1024" in f for f in vf)


class TestFilterFfmetadata:
    HEADER = ";FFMETADATA1\n"

    def _write_and_call(self, text: str, keep: list[str]) -> str:
        p = Path("tmp_ffmeta_test.ffmeta")
        try:
            p.write_text(text)
            out = _filter_ffmetadata(p, set(keep))
            return p.read_text() if p.exists() else ""
        finally:
            p.unlink(missing_ok=True)

    def test_strips_everything_except_header_when_no_exclude(self):
        text = self.HEADER + "title=foo\nartist=bar\nlocation=42.0\nrotate=90\n"
        result = self._write_and_call(text, [])
        # When nothing is preserved beyond the header, the implementation
        # deletes the file and returns an empty string.
        assert result == ""

    def test_keeps_location_when_gps_excluded(self):
        text = self.HEADER + "title=foo\nlocation=42.0\nrotate=90\n"
        result = self._write_and_call(text, ["gps"])
        assert "location=42.0" in result
        assert "title" not in result
        assert "rotate" not in result

    def test_keeps_rotate_when_orientation_excluded(self):
        text = self.HEADER + "title=foo\nlocation=42.0\nrotate=90\n"
        result = self._write_and_call(text, ["orientation"])
        assert "rotate=90" in result
        assert "location" not in result
        assert "title" not in result

    def test_keeps_both_gps_and_orientation(self):
        text = self.HEADER + "title=foo\nlocation=42.0\nrotate=90\nartist=baz\n"
        result = self._write_and_call(text, ["gps", "orientation"])
        assert "location=42.0" in result
        assert "rotate=90" in result
        assert "title" not in result
        assert "artist" not in result
