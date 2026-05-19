"""Tests for :func:`process_media.naming.batch_exif_dates`.

Cover the matching logic between exiftool's ``SourceFile`` and the input
paths (resolved-path index plus the unique-basename fallback). The
ExifTool subprocess is mocked so these tests do not require the binary
on the test host.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def fake_exiftool(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Install a minimal ``exiftool`` module exposing ``ExifToolHelper``."""
    helper = MagicMock(name="ExifToolHelper")
    instance = helper.return_value.__enter__.return_value
    module = types.ModuleType("exiftool")
    module.ExifToolHelper = helper  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "exiftool", module)
    return instance


def _set_records(helper_instance: MagicMock, records: list[dict[str, Any]]) -> None:
    helper_instance.get_tags.return_value = records


def test_returns_empty_dict_on_empty_input() -> None:
    from process_media.naming import batch_exif_dates

    assert batch_exif_dates([]) == {}


def test_matches_by_resolved_path(tmp_path: Path, fake_exiftool: MagicMock) -> None:
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


def test_falls_back_to_unique_basename(tmp_path: Path, fake_exiftool: MagicMock) -> None:
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
    tmp_path: Path, fake_exiftool: MagicMock, caplog: pytest.LogCaptureFixture
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


def test_picks_first_available_tag(tmp_path: Path, fake_exiftool: MagicMock) -> None:
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


def test_skips_null_timestamp(tmp_path: Path, fake_exiftool: MagicMock) -> None:
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


def test_parses_negative_timezone_offset(tmp_path: Path, fake_exiftool: MagicMock) -> None:
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
