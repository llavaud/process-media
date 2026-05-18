from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from process_media import tools
from process_media.tools import ToolError, ensure_tools, probe_audio_codec, run, which


class TestWhich:
    def test_which_returns_string_when_present(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/" + n if n == "true" else None)
        which.cache_clear()
        assert which("true") == "/usr/bin/true"

    def test_which_returns_none_when_absent(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda _: None)
        which.cache_clear()
        assert which("nope-xyz-not-here") is None


class TestEnsureTools:
    def test_passes_when_all_present(self, monkeypatch):
        which.cache_clear()
        monkeypatch.setattr("shutil.which", lambda n: f"/usr/bin/{n}")
        ensure_tools(needs_ffmpeg=True, needs_exiftool=True)

    def test_raises_when_ffmpeg_missing(self, monkeypatch):
        which.cache_clear()

        def fake(n):
            return None if n in ("ffmpeg", "ffprobe") else f"/usr/bin/{n}"

        monkeypatch.setattr("shutil.which", fake)
        with pytest.raises(RuntimeError, match="ffmpeg"):
            ensure_tools(needs_ffmpeg=True, needs_exiftool=False)

    def test_raises_when_exiftool_missing(self, monkeypatch):
        which.cache_clear()
        monkeypatch.setattr("shutil.which", lambda n: None if n == "exiftool" else f"/usr/bin/{n}")
        with pytest.raises(RuntimeError, match="exiftool"):
            ensure_tools(needs_ffmpeg=False, needs_exiftool=True)

    def test_no_check_when_neither_needed(self, monkeypatch):
        which.cache_clear()
        monkeypatch.setattr("shutil.which", lambda _: None)
        ensure_tools(needs_ffmpeg=False, needs_exiftool=False)


class TestRun:
    def test_success_returns_completed_process(self):
        cp = run(["true"])  # true exists in /bin on CI
        assert isinstance(cp, subprocess.CompletedProcess)
        assert cp.returncode == 0

    def test_failure_raises_toolerror(self):
        with pytest.raises(ToolError):
            run(["/bin/sh", "-c", "exit 2"])  # non-zero

    def test_check_false_does_not_raise(self):
        cp = run(["/bin/sh", "-c", "exit 3"], check=False)
        assert cp.returncode != 0


class TestProbeAudioCodec:
    def test_returns_codec_name(self, monkeypatch):
        def fake_run(cmd, **kw):
            assert cmd[0].endswith("ffprobe")
            return subprocess.CompletedProcess(cmd, 0, stdout=b"aac\n", stderr=b"")

        monkeypatch.setattr("subprocess.run", fake_run)
        which.cache_clear()
        monkeypatch.setattr("shutil.which", lambda n: f"/usr/bin/{n}")
        codec = probe_audio_codec(Path("/tmp/x.mp4"))
        assert codec == "aac"

    def test_returns_none_when_no_audio(self, monkeypatch):
        def fake_run(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

        monkeypatch.setattr("subprocess.run", fake_run)
        which.cache_clear()
        monkeypatch.setattr("shutil.which", lambda n: f"/usr/bin/{n}")
        codec = probe_audio_codec(Path("/tmp/x.mp4"))
        assert codec is None
