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

    real_init = runner.ProcessPoolExecutor

    class SpyExecutor(InlineExecutor):
        def __init__(self, max_workers=None, *a, **kw):
            captured["mw"] = max_workers

    monkeypatch.setattr(runner, "ProcessPoolExecutor", SpyExecutor)
    monkeypatch.setattr(runner, "_execute", lambda job: JobResult(job=job, success=True, duration=0.0))
    jobs = [_make_job(tmp_path, f"f{i}.jpg") for i in range(2)]
    runner.run_jobs(jobs, max_workers=10, batch=True)
    assert captured["mw"] == 2
