from __future__ import annotations

from pathlib import Path
from concurrent.futures import Future
from types import SimpleNamespace

import pytest

from process_media.media.base import JobResult, MediaJob


class InlineExecutor:
    def __init__(self, *a, **kw):
        pass

    def submit(self, fn, *args, **kw):
        f = Future()
        try:
            f.set_result(fn(*args, **kw))
        except Exception as e:
            f.set_exception(e)
        return f

    def shutdown(self, **kw):
        pass

    @property
    def _processes(self):
        return {}


def _make_job(tmp_path, name="x.jpg", media_type="photo"):
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    s = src / name
    s.write_bytes(b"fake")
    return MediaJob(
        source=s,
        target=tmp_path / "out" / name,
        format_name="dummy",
        format_spec=SimpleNamespace(),
        media_type=("photo" if media_type == "photo" else "video"),
    )


def test_run_jobs_empty_returns_zero_zero():
    from process_media.runner import run_jobs

    assert run_jobs([]) == (0, 0)


def test_run_jobs_all_success(tmp_path, monkeypatch):
    from process_media import runner

    jobs = [_make_job(tmp_path, f"f{i}.jpg") for i in range(3)]
    monkeypatch.setattr(runner, "ProcessPoolExecutor", InlineExecutor)
    monkeypatch.setattr(runner, "_execute", lambda job: JobResult(job=job, success=True, duration=0.01))
    ok, err = runner.run_jobs(jobs, max_workers=2, batch=True)
    assert (ok, err) == (3, 0)


def test_run_jobs_mixed_outcomes(tmp_path, monkeypatch):
    from process_media import runner

    jobs = [_make_job(tmp_path, f"f{i}.jpg") for i in range(3)]

    def stub(job):
        if job.source.name == "f1.jpg":
            return JobResult(job=job, success=False, error="boom")
        return JobResult(job=job, success=True, duration=0.01)

    monkeypatch.setattr(runner, "ProcessPoolExecutor", InlineExecutor)
    monkeypatch.setattr(runner, "_execute", stub)
    ok, err = runner.run_jobs(jobs, max_workers=2, batch=True)
    assert (ok, err) == (2, 1)


def test_run_jobs_skipped_counts_as_ok(tmp_path, monkeypatch):
    from process_media import runner

    jobs = [_make_job(tmp_path)]
    monkeypatch.setattr(runner, "ProcessPoolExecutor", InlineExecutor)
    monkeypatch.setattr(runner, "_execute", lambda job: JobResult(job=job, success=True, skipped=True, duration=0.0))
    ok, err = runner.run_jobs(jobs, max_workers=1, batch=True)
    assert (ok, err) == (1, 0)


def test_max_workers_capped_to_jobs_count(tmp_path, monkeypatch):
    from process_media import runner

    captured = {}

    class SpyExecutor(InlineExecutor):
        def __init__(self, max_workers=None, *a, **kw):
            captured["mw"] = max_workers

    monkeypatch.setattr(runner, "ProcessPoolExecutor", SpyExecutor)
    monkeypatch.setattr(runner, "_execute", lambda job: JobResult(job=job, success=True, duration=0.0))
    jobs = [_make_job(tmp_path, f"f{i}.jpg") for i in range(2)]
    runner.run_jobs(jobs, max_workers=10, batch=True)
    assert captured["mw"] == 2


def test_clean_stale_tempfiles_wipes_orphans(tmp_path):
    """Leftover tempfiles in target dirs are removed before submitting jobs."""
    from process_media.runner import _clean_stale_tempfiles

    out = tmp_path / "out"
    out.mkdir()
    stale1 = out / "process-media_tmp.aaa.mp4"
    stale2 = out / "process-media_tmp.bbb.ffmeta"
    keep = out / "process-media_kept.mp4"  # different prefix, must not be touched
    stale1.write_bytes(b"x")
    stale2.write_bytes(b"y")
    keep.write_bytes(b"z")

    job = MediaJob(
        source=tmp_path / "src.mp4",
        target=out / "result.mp4",
        format_name="dummy",
        format_spec=SimpleNamespace(),
        media_type="video",
    )
    _clean_stale_tempfiles([job])

    assert not stale1.exists()
    assert not stale2.exists()
    assert keep.exists()


def test_clean_stale_tempfiles_ignores_missing_target_dir(tmp_path):
    """A target dir that doesn't exist yet must not raise."""
    from process_media.runner import _clean_stale_tempfiles

    job = MediaJob(
        source=tmp_path / "src.mp4",
        target=tmp_path / "nope" / "result.mp4",
        format_name="dummy",
        format_spec=SimpleNamespace(),
        media_type="video",
    )
    _clean_stale_tempfiles([job])  # must not raise
