"""Tests for the filename-based date fallback (used when EXIF is missing).

These two helpers (``parse_date_from_filename`` and ``resolve_base_name``)
together turn camera/screenshot filenames such as
``Visiophone_connecté_20251019_132023.png`` into the canonical
``YYYYMMDD-HHMMSS`` naming, and explicitly log when no plausible date
could be inferred.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from process_media.naming import (
    ExifDate,
    parse_date_from_filename,
    resolve_base_name,
)


class TestParseDateFromFilename:
    @pytest.mark.parametrize(
        ("stem", "expected"),
        [
            # Samsung / Android camera apps.
            ("20251019_132023", datetime(2025, 10, 19, 13, 20, 23)),
            ("Visiophone_connecté_20251019_132023", datetime(2025, 10, 19, 13, 20, 23)),
            # iOS / iPhone exports.
            ("IMG_20240118_091500", datetime(2024, 1, 18, 9, 15, 0)),
            # Screenshot tools using dashes.
            ("Screenshot_2025-10-19-13-20-23", datetime(2025, 10, 19, 13, 20, 23)),
            ("Screenshot-2025-10-19_13-20-23", datetime(2025, 10, 19, 13, 20, 23)),
            # ISO-like.
            ("photo-2024-05-18T12.34.56", datetime(2024, 5, 18, 12, 34, 56)),
            # WhatsApp / iCloud (date only).
            ("IMG-20251019-WA0001", datetime(2025, 10, 19)),
            # Date in the middle of the name.
            ("vacation 2024_07_15 sunset", datetime(2024, 7, 15)),
        ],
    )
    def test_parses_known_patterns(self, stem: str, expected: datetime) -> None:
        assert parse_date_from_filename(stem) == expected

    @pytest.mark.parametrize(
        "stem",
        [
            "",
            "random_name_no_date",
            "IMG_1234",
            "DSC_0001",
            "2025",                 # year only
            "20251332_999999",      # impossible month/day
        ],
    )
    def test_returns_none_when_no_match(self, stem: str) -> None:
        assert parse_date_from_filename(stem) is None

    def test_invalid_time_falls_back_to_date_only(self) -> None:
        # Time portion is impossible but the date alone is fine — the
        # optional regex group naturally skips the bogus time.
        assert parse_date_from_filename("20251019_259999") == datetime(2025, 10, 19)

    def test_rejects_invalid_calendar_date(self) -> None:
        # February 30 is syntactically OK in the regex but invalid as a
        # calendar date — ``datetime`` raises ValueError.
        assert parse_date_from_filename("20250230_120000") is None


class TestResolveBaseName:
    def _src(self, tmp_path: Path, name: str) -> Path:
        p = tmp_path / name
        p.write_bytes(b"")
        return p

    def test_uses_exif_when_present(self, tmp_path: Path) -> None:
        src = self._src(tmp_path, "IMG_001.jpg")
        entry = ExifDate(dt=datetime(2024, 5, 18, 12, 34, 56), tag="EXIF:DateTimeOriginal")
        assert resolve_base_name(src, entry, "photo", tzoffset=0) == "20240518-123456"

    def test_parses_filename_when_exif_is_missing(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        src = self._src(tmp_path, "Visiophone_connecté_20251019_132023.png")
        with caplog.at_level("INFO", logger="process_media.naming"):
            base = resolve_base_name(src, None, "photo", tzoffset=0)
        assert base == "20251019-132023"
        assert any("parsed from filename" in m for m in caplog.messages)

    def test_keeps_stem_and_warns_when_no_date_found(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        src = self._src(tmp_path, "random_picture.jpg")
        with caplog.at_level("WARNING", logger="process_media.naming"):
            base = resolve_base_name(src, None, "photo", tzoffset=0)
        assert base == "random_picture"
        assert any("no EXIF date" in m for m in caplog.messages)

    def test_tzoffset_applied_to_filename_date(self, tmp_path: Path) -> None:
        src = self._src(tmp_path, "20251019_232023.png")
        # +120 seconds → 23:22:23
        assert resolve_base_name(src, None, "photo", tzoffset=120) == "20251019-232223"
