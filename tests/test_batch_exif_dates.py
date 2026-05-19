"""Tests for :func:`process_media.naming.batch_exif_dates`.

Cover the matching logic between exiftool's ``SourceFile`` and the input
paths (resolved-path index plus the unique-basename fallback). The
``exiftool`` invocation is mocked so these tests do not require the
binary on the test host.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


@pytest.fixture
def fake_exiftool():
    """Patch ``_run_exiftool_json`` so we control its raw JSON output."""
    with patch("process_media.naming._run_exiftool_json") as mocked:
        mocked.return_value = []
        yield mocked


def _set_records(mocked: Any, records: list[dict[str, Any]]) -> None:
    mocked.return_value = records


def test_returns_empty_dict_on_empty_input() -> None:
    from process_media.naming import batch_exif_dates

    assert batch_exif_dates([]) == {}


def test_matches_by_resolved_path(tmp_path: Path, fake_exiftool: Any) -> None:
    from process_media.naming import batch_exif_dates

    photo = tmp_path / "IMG_001.jpg"
    photo.write_bytes(b"")
    _set_records(
        fake_exiftool,
        [{"SourceFile": str(photo), "EXIF:DateTimeOriginal": "2024:05:18 12:34:56"}],
    )

    out = batch_exif_dates([photo])
    assert out[photo] is not None
    assert out[photo].dt.strftime("%Y%m%d-%H%M%S") == "20240518-123456"
    assert out[photo].tag == "EXIF:DateTimeOriginal"


def test_falls_back_to_unique_basename(tmp_path: Path, fake_exiftool: Any) -> None:
    """When ``SourceFile`` cannot be resolved, fall back to the basename."""
    from process_media.naming import batch_exif_dates

    photo = tmp_path / "IMG_001.jpg"
    photo.write_bytes(b"")
    _set_records(
        fake_exiftool,
        [
            {
                # Path that does not resolve to the real one.
                "SourceFile": "/nonexistent/IMG_001.jpg",
                "EXIF:CreateDate": "2024:05:18 09:00:00",
            }
        ],
    )

    out = batch_exif_dates([photo])
    assert out[photo] is not None
    assert out[photo].dt.strftime("%Y%m%d-%H%M%S") == "20240518-090000"


def test_duplicate_basenames_do_not_get_misattributed(
    tmp_path: Path, fake_exiftool: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """Two files sharing a basename: the basename fallback MUST NOT kick in.

    This is the regression test for review item B3 — without the
    safeguard, exiftool's record would be attributed to whichever file
    appears first in the list, silently corrupting the rename.
    """
    from process_media.naming import batch_exif_dates

    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    photo_a = tmp_path / "a" / "IMG_001.jpg"
    photo_b = tmp_path / "b" / "IMG_001.jpg"
    photo_a.write_bytes(b"")
    photo_b.write_bytes(b"")
    _set_records(
        fake_exiftool,
        [
            {
                "SourceFile": "/elsewhere/IMG_001.jpg",
                "EXIF:DateTimeOriginal": "2024:05:18 12:34:56",
            }
        ],
    )

    with caplog.at_level("WARNING", logger="process_media.naming"):
        out = batch_exif_dates([photo_a, photo_b])

    assert out == {photo_a: None, photo_b: None}
    assert any("Could not match" in m for m in caplog.messages)


def test_picks_first_available_tag(tmp_path: Path, fake_exiftool: Any) -> None:
    """``DateTimeOriginal`` wins over ``CreateDate`` / ``QuickTime:CreateDate``."""
    from process_media.naming import batch_exif_dates

    photo = tmp_path / "video.mp4"
    photo.write_bytes(b"")
    _set_records(
        fake_exiftool,
        [
            {
                "SourceFile": str(photo),
                "EXIF:CreateDate": "2024:05:18 09:00:00",
                "QuickTime:CreateDate": "2024:05:18 07:00:00",
            }
        ],
    )

    out = batch_exif_dates([photo])
    assert out[photo] is not None
    assert out[photo].tag == "EXIF:CreateDate"


def test_skips_null_timestamp(tmp_path: Path, fake_exiftool: Any) -> None:
    from process_media.naming import batch_exif_dates

    photo = tmp_path / "no_date.jpg"
    photo.write_bytes(b"")
    _set_records(
        fake_exiftool,
        [
            {
                "SourceFile": str(photo),
                "EXIF:DateTimeOriginal": "0000:00:00 00:00:00",
            }
        ],
    )

    assert batch_exif_dates([photo]) == {photo: None}


def test_parses_negative_timezone_offset(tmp_path: Path, fake_exiftool: Any) -> None:
    """Regression test for review item B2 (negative TZ in EXIF strings)."""
    from process_media.naming import batch_exif_dates

    photo = tmp_path / "img.jpg"
    photo.write_bytes(b"")
    _set_records(
        fake_exiftool,
        [
            {
                "SourceFile": str(photo),
                "EXIF:DateTimeOriginal": "2024:05:18 12:34:56-08:00",
            }
        ],
    )

    out = batch_exif_dates([photo])
    assert out[photo] is not None
    # Timezone handling is centralised elsewhere; the parser only needs
    # to extract the wall-clock value.
    assert out[photo].dt.strftime("%Y%m%d-%H%M%S") == "20240518-123456"


# ---------------------------------------------------------------------------
# Tests for the thin subprocess wrapper
# ---------------------------------------------------------------------------


class TestRunExiftoolJson:
    """Direct coverage of :func:`process_media.naming._run_exiftool_json`."""

    def test_raises_when_binary_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from process_media.naming import _run_exiftool_json
        from process_media.tools import ToolError

        monkeypatch.setattr("process_media.naming.which", lambda _name: None)
        with pytest.raises(ToolError, match="exiftool binary"):
            _run_exiftool_json([Path("/tmp/whatever.jpg")])

    def test_parses_json_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from subprocess import CompletedProcess

        from process_media.naming import _run_exiftool_json

        monkeypatch.setattr("process_media.naming.which", lambda _name: "/usr/bin/exiftool")
        payload = b'[{"SourceFile":"/x.jpg","EXIF:DateTimeOriginal":"2024:01:02 03:04:05"}]'
        monkeypatch.setattr(
            "process_media.naming.run",
            lambda *_args, **_kwargs: CompletedProcess(
                args=[], returncode=0, stdout=payload, stderr=b""
            ),
        )
        out = _run_exiftool_json([Path("/x.jpg")])
        assert out == [{"SourceFile": "/x.jpg", "EXIF:DateTimeOriginal": "2024:01:02 03:04:05"}]

    def test_invalid_json_raises_toolerror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from subprocess import CompletedProcess

        from process_media.naming import _run_exiftool_json
        from process_media.tools import ToolError

        monkeypatch.setattr("process_media.naming.which", lambda _name: "/usr/bin/exiftool")
        monkeypatch.setattr(
            "process_media.naming.run",
            lambda *_args, **_kwargs: CompletedProcess(
                args=[], returncode=0, stdout=b"not json", stderr=b""
            ),
        )
        with pytest.raises(ToolError, match="invalid JSON"):
            _run_exiftool_json([Path("/x.jpg")])

    def test_empty_stdout_returns_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """exiftool prints nothing on stdout when *all* files lack the tag."""
        from subprocess import CompletedProcess

        from process_media.naming import _run_exiftool_json

        monkeypatch.setattr("process_media.naming.which", lambda _name: "/usr/bin/exiftool")
        monkeypatch.setattr(
            "process_media.naming.run",
            lambda *_args, **_kwargs: CompletedProcess(
                args=[], returncode=1, stdout=b"", stderr=b""
            ),
        )
        assert _run_exiftool_json([Path("/x.jpg")]) == []
