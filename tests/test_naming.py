"""Tests for filesystem scanning and EXIF-driven renaming."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from process_media.config import FormatSpec, GlobalOptions
from process_media.naming import (
    ExifDate,
    build_jobs,
    exif_date_to_name,
    fallback_name,
    scan_media,
)


def test_exif_date_basic() -> None:
    dt = datetime.strptime("2024:05:18 12:34:56", "%Y:%m:%d %H:%M:%S")
    assert exif_date_to_name(dt) == "20240518-123456"


def test_exif_date_tzoffset_crosses_day() -> None:
    dt = datetime.strptime("2024:05:18 23:59:00", "%Y:%m:%d %H:%M:%S")
    assert exif_date_to_name(dt, tzoffset=120).startswith("20240519")


def test_fallback_name(tmp_path: Path) -> None:
    p = tmp_path / "IMG_00123.JPG"
    p.write_text("")
    assert fallback_name(p) == "IMG_00123"


def test_scan_media_filters(tmp_path: Path) -> None:
    (tmp_path / "a.jpg").write_text("")
    (tmp_path / "B.JPEG").write_text("")
    (tmp_path / ".hidden.jpg").write_text("")
    (tmp_path / "clip.mp4").write_text("")
    (tmp_path / "note.txt").write_text("")
    (tmp_path / "sub").mkdir()  # ignored: non-recursive

    res = dict(scan_media(tmp_path))
    names = {p.name: t for p, t in res.items()}
    assert names.get("a.jpg") == "photo"
    assert names.get("B.JPEG") == "photo"
    assert names.get("clip.mp4") == "video"
    assert ".hidden.jpg" not in names
    assert "note.txt" not in names


def test_scan_media_single_file(tmp_path: Path) -> None:
    f = tmp_path / "x.mp4"
    f.write_text("")
    assert scan_media(f) == [(f, "video")]


def test_build_jobs_renames_with_exif(tmp_path: Path) -> None:
    src = tmp_path / "DSC_001.jpg"
    src.write_text("")
    spec = FormatSpec(type="photo", output_dir="web")
    dt = datetime(2024, 5, 18, 12, 34, 56)

    jobs = build_jobs(
        files=[(src, "photo")],
        formats={"web_photo": spec},
        global_opts=GlobalOptions(),
        exif_dates={src: dt},
    )
    assert len(jobs) == 1
    job = jobs[0]
    assert job.target.name == "20240518-123456.jpg"
    # Relative output_dir anchored to source's parent.
    assert job.target.parent == src.parent / "web"


def test_build_jobs_keep_name(tmp_path: Path) -> None:
    src = tmp_path / "DSC_001.jpg"
    src.write_text("")
    spec = FormatSpec(type="photo", output_dir="web")

    jobs = build_jobs(
        files=[(src, "photo")],
        formats={"web_photo": spec},
        global_opts=GlobalOptions(keep_name=True),
        exif_dates={src: datetime(2024, 5, 18, 12, 0, 0)},
    )
    assert jobs[0].target.name == "DSC_001.jpg"


def test_build_jobs_no_exif_falls_back_to_stem(tmp_path: Path) -> None:
    src = tmp_path / "DSC_001.jpg"
    src.write_text("")
    spec = FormatSpec(type="photo", output_dir="web")

    jobs = build_jobs(
        files=[(src, "photo")],
        formats={"web_photo": spec},
        global_opts=GlobalOptions(),
        exif_dates={src: None},
    )
    assert jobs[0].target.name == "DSC_001.jpg"


def test_build_jobs_only_matches_format_type(tmp_path: Path) -> None:
    photo = tmp_path / "p.jpg"
    photo.write_text("")
    video = tmp_path / "v.mp4"
    video.write_text("")

    formats = {
        "web_photo": FormatSpec(type="photo", output_dir="web"),
        "web_video": FormatSpec(type="video", output_dir="web/videos"),
    }
    jobs = build_jobs(
        files=[(photo, "photo"), (video, "video")],
        formats=formats,
        global_opts=GlobalOptions(),
        exif_dates={},
    )
    assert len(jobs) == 2
    formats_by_source = {j.source.name: j.format_name for j in jobs}
    assert formats_by_source["p.jpg"] == "web_photo"
    assert formats_by_source["v.mp4"] == "web_video"


def test_build_jobs_video_quicktime_tzoffset_auto_local(
    tmp_path: Path, monkeypatch
) -> None:
    """QuickTime stamps (UTC) get local-tz compensation when tzoffset=0.

    When no explicit ``--tzoffset`` is passed, ``QuickTime:CreateDate``
    (stored in UTC) is shifted to local time so the resulting filename
    matches what the user expects from their wall clock.
    """
    import time as _time

    # Pretend we run on a UTC+2 machine (7200s east of UTC).
    class _FakeTime:
        tm_gmtoff = 7200

    monkeypatch.setattr(_time, "localtime", lambda *a, **k: _FakeTime())

    src = tmp_path / "clip.mp4"
    src.write_text("")
    spec = FormatSpec(type="video", output_dir="archive")

    jobs = build_jobs(
        files=[(src, "video")],
        formats={"archive_video": spec},
        global_opts=GlobalOptions(tzoffset=0),
        exif_dates={
            src: ExifDate(
                dt=datetime(2024, 5, 18, 10, 0, 0),
                tag="QuickTime:CreateDate",
            )
        },
    )
    # 10:00 UTC + 2h = 12:00 local.
    assert jobs[0].target.name == "20240518-120000.mp4"


def test_build_jobs_photo_exif_no_quicktime_shift(tmp_path: Path) -> None:
    """Photos with EXIF tags never get the QuickTime auto-shift."""
    src = tmp_path / "p.jpg"
    src.write_text("")
    spec = FormatSpec(type="photo", output_dir="web")
    jobs = build_jobs(
        files=[(src, "photo")],
        formats={"web_photo": spec},
        global_opts=GlobalOptions(tzoffset=0),
        exif_dates={
            src: ExifDate(
                dt=datetime(2024, 5, 18, 12, 34, 56),
                tag="EXIF:DateTimeOriginal",
            )
        },
    )
    assert jobs[0].target.name == "20240518-123456.jpg"


def test_build_jobs_video_extension_normalised_to_mp4(tmp_path: Path) -> None:
    """B2: videos always come out as ``.mp4`` regardless of source container."""
    src = tmp_path / "clip.mkv"
    src.write_text("")
    spec = FormatSpec(type="video", output_dir="archive")
    jobs = build_jobs(
        files=[(src, "video")],
        formats={"archive_video": spec},
        global_opts=GlobalOptions(keep_name=True),
        exif_dates={},
    )
    assert jobs[0].target.name == "clip.mp4"


def test_build_jobs_absolute_output_dir(tmp_path: Path) -> None:
    src = tmp_path / "p.jpg"
    src.write_text("")
    abs_dir = tmp_path / "absolute_out"
    spec = FormatSpec(type="photo", output_dir=str(abs_dir))

    jobs = build_jobs(
        files=[(src, "photo")],
        formats={"x": spec},
        global_opts=GlobalOptions(),
        exif_dates={},
    )
    assert jobs[0].target.parent == abs_dir
