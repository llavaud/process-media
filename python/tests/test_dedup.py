"""Tests for duplicate-target deduplication."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from process_media.config import FormatSpec, GlobalOptions
from process_media.naming import build_jobs, dedupe_targets


def test_dedupe_helper_per_media_type() -> None:
    """``dedupe_targets`` numbers photos and videos independently."""
    jobs = [
        {"target_name": "X", "media_type": "photo"},
        {"target_name": "X", "media_type": "photo"},
        {"target_name": "X", "media_type": "video"},
        {"target_name": "X", "media_type": "video"},
    ]
    out = dedupe_targets(jobs)
    # First entry of each media_type keeps its name (matches Perl semantics).
    photos = [j for j in out if j["media_type"] == "photo"]
    videos = [j for j in out if j["media_type"] == "video"]
    assert photos[0]["target_name"] == "X"
    assert photos[1]["target_name"] == "X-001"
    assert videos[0]["target_name"] == "X"
    assert videos[1]["target_name"] == "X-001"


def test_build_jobs_dedup_two_photos_same_target(tmp_path: Path) -> None:
    """Two photos with identical EXIF dates -> both targets receive a suffix."""
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    a.write_text("")
    b.write_text("")
    dt = datetime(2024, 5, 18, 12, 0, 0)
    spec = FormatSpec(type="photo", output_dir="web")

    jobs = build_jobs(
        files=[(a, "photo"), (b, "photo")],
        formats={"web_photo": spec},
        global_opts=GlobalOptions(),
        exif_dates={a: dt, b: dt},
    )
    names = sorted(j.target.name for j in jobs)
    # All members of the colliding group get a suffix.
    assert names == ["20240518-120000-001.jpg", "20240518-120000-002.jpg"]


def test_build_jobs_dedup_independent_across_types(tmp_path: Path) -> None:
    photo = tmp_path / "p.jpg"
    video = tmp_path / "v.mp4"
    photo.write_text("")
    video.write_text("")
    dt = datetime(2024, 5, 18, 12, 0, 0)
    formats = {
        "web_photo": FormatSpec(type="photo", output_dir="web"),
        "web_video": FormatSpec(type="video", output_dir="web"),
    }
    jobs = build_jobs(
        files=[(photo, "photo"), (video, "video")],
        formats=formats,
        global_opts=GlobalOptions(),
        exif_dates={photo: dt, video: dt},
    )
    # Same base name but different extensions AND different media types ->
    # no collision triggered.
    by_type = {j.media_type: j for j in jobs}
    assert by_type["photo"].target.name == "20240518-120000.jpg"
    assert by_type["video"].target.name == "20240518-120000.mp4"


def test_build_jobs_no_dedup_when_distinct(tmp_path: Path) -> None:
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    a.write_text("")
    b.write_text("")
    spec = FormatSpec(type="photo", output_dir="web")

    jobs = build_jobs(
        files=[(a, "photo"), (b, "photo")],
        formats={"web_photo": spec},
        global_opts=GlobalOptions(),
        exif_dates={
            a: datetime(2024, 5, 18, 12, 0, 0),
            b: datetime(2024, 5, 18, 13, 0, 0),
        },
    )
    names = sorted(j.target.name for j in jobs)
    assert names == ["20240518-120000.jpg", "20240518-130000.jpg"]
