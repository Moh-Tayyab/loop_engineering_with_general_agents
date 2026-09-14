"""Tests for post-package generation and ffmpeg merge/evaluate (mocked)."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.config as cfg
import src.merger as merger
import src.post_package as postpkg
from src.planner import template_storyboard
from src.state import Topic


@pytest.fixture
def sb():
    t = Topic("c1", "Subagents", "Delegate info-heavy tasks to an isolated agent.", "pending")
    return template_storyboard(4, t)


def test_build_caption_has_cta_and_hashtags(sb):
    for p in postpkg.PLATFORMS:
        cap = postpkg.build_caption(sb, p)
        assert "Follow for 1-minute" in cap
        assert "#" in cap
        assert f"#{p}" in cap or any(h.startswith("#") for h in cap.split())


def test_write_post_package_writes_all_platforms(sb, tmp_path):
    videos = tmp_path / "videos"
    videos.mkdir()
    fake = videos / "final.mp4"
    fake.write_bytes(b"fake-mp4")
    out = tmp_path / "pkg"
    postpkg.write_post_package(sb, fake, out)
    assert (out / "post.json").exists()
    assert len(list(out.glob("caption_*.txt"))) == 4
    assert (out / "final.mp4").read_bytes() == b"fake-mp4"
    data = json.loads((out / "post.json").read_text())
    assert set(data["platforms"].keys()) == set(postpkg.PLATFORMS)
    assert data["video"] == "final.mp4"


def test_write_post_package_skips_missing_video(sb, tmp_path):
    out = tmp_path / "pkg"
    postpkg.write_post_package(sb, out / "final.mp4", out)
    # no crash, package still written, no copied video
    assert (out / "post.json").exists()


# --- merge / evaluate (no real ffmpeg required — symbol-level) ---

def test_concat_clips_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        merger.concat_clips([tmp_path / "nope.mp4"], tmp_path / "out.mp4")


def test_concat_clips_empty_raises():
    with pytest.raises(ValueError):
        merger.concat_clips([], Path("/tmp/out.mp4"))


def test_concat_clips_ffmpeg_failure_propagates(tmp_path, monkeypatch):
    good_clips = []
    for i in range(2):
        p = tmp_path / f"c{i}.mp4"
        p.write_bytes(b"data")
        good_clips.append(p)
    out = tmp_path / "merged.mp4"

    def fake_run(cmd, **kw):
        class Res:
            returncode = 1
            stderr = "boom"
        return Res()

    monkeypatch.setattr(merger.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="ffmpeg failed"):
        merger.concat_clips(good_clips, out)


def test_concat_clips_success(tmp_path, monkeypatch):
    good_clips = []
    for i in range(2):
        p = tmp_path / f"c{i}.mp4"
        p.write_bytes(b"data")
        good_clips.append(p)
    out = tmp_path / "merged.mp4"

    def fake_run(cmd, **kw):
        out.write_bytes(b"merged")
        assert "ffmpeg" in cmd[0]
        assert "-f" in cmd and "concat" in cmd
        class Res:
            returncode = 0
            stderr = ""
        return Res()

    monkeypatch.setattr(merger.subprocess, "run", fake_run)
    result = merger.concat_clips(good_clips, out)
    assert result.read_bytes() == b"merged"


def test_evaluate_final_missing(tmp_path):
    info = merger.evaluate_final(tmp_path / "missing.mp4", expected_s=60)
    assert info["ok"] is False
    assert "error" in info


def test_evaluate_final_empty(tmp_path):
    p = tmp_path / "empty.mp4"
    p.write_bytes(b"")
    info = merger.evaluate_final(p, expected_s=60)
    assert info["ok"] is False
    assert info["error"] == "file empty"


def test_evaluate_final_without_ffprobe_passes_on_size_only(tmp_path, monkeypatch):
    p = tmp_path / "ok.mp4"
    p.write_bytes(b"some bytes")
    monkeypatch.setattr(cfg, "ffprobe_binary", lambda: None)  # ffprobe unavailable
    info = merger.evaluate_final(p, expected_s=60, tolerance_s=5)
    # duration unknown -> not rejected
    assert info["ok"] is True


def test_ffmpeg_available_is_bool():
    assert isinstance(merger.ffmpeg_available(), bool)


# --- probe_media (download-verify data source; mocked, no real ffmpeg needed) ---

_VIDEO_AUDIO_JSON = json.dumps({
    "streams": [
        {"codec_type": "video", "width": 720, "height": 1280},
        {"codec_type": "audio"},
    ],
    "format": {"duration": "6.0"},
})
_AUDIO_ONLY_JSON = json.dumps({
    "streams": [{"codec_type": "audio"}],
    "format": {"duration": "3.0"},
})


def _probe_ok(stdout):
    return SimpleNamespace(returncode=0, stdout=stdout)


def test_probe_media_none_when_ffprobe_missing(tmp_path, monkeypatch):
    f = tmp_path / "x.mp4"
    f.write_bytes(b"bytes")
    monkeypatch.setattr(cfg, "ffprobe_binary", lambda: None)
    assert merger.probe_media(f) is None


def test_probe_media_none_on_ffprobe_failure(tmp_path, monkeypatch):
    f = tmp_path / "x.mp4"
    f.write_bytes(b"bytes")
    monkeypatch.setattr(cfg, "ffprobe_binary", lambda: "/usr/bin/ffprobe")
    monkeypatch.setattr(merger.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout=""))
    assert merger.probe_media(f) is None


def test_probe_media_parses_video_and_audio(tmp_path, monkeypatch):
    f = tmp_path / "x.mp4"
    f.write_bytes(b"bytes")
    monkeypatch.setattr(cfg, "ffprobe_binary", lambda: "/usr/bin/ffprobe")
    monkeypatch.setattr(merger.subprocess, "run", lambda *a, **k: _probe_ok(_VIDEO_AUDIO_JSON))
    info = merger.probe_media(f)
    assert info is not None
    assert info["has_video"] is True
    assert info["has_audio"] is True
    assert (info["width"], info["height"]) == (720, 1280)
    assert info["duration_s"] == 6.0


def test_probe_media_audio_only_has_no_video(tmp_path, monkeypatch):
    f = tmp_path / "x.mp3"
    f.write_bytes(b"bytes")
    monkeypatch.setattr(cfg, "ffprobe_binary", lambda: "/usr/bin/ffprobe")
    monkeypatch.setattr(merger.subprocess, "run", lambda *a, **k: _probe_ok(_AUDIO_ONLY_JSON))
    info = merger.probe_media(f)
    assert info is not None
    assert info["has_video"] is False


def test_probe_media_none_on_garbage_stdout(tmp_path, monkeypatch):
    f = tmp_path / "x.mp4"
    f.write_bytes(b"bytes")
    monkeypatch.setattr(cfg, "ffprobe_binary", lambda: "/usr/bin/ffprobe")
    monkeypatch.setattr(merger.subprocess, "run", lambda *a, **k: _probe_ok("{not json"))
    assert merger.probe_media(f) is None


def test_evaluate_final_unreadable_media_fails_closed(tmp_path, monkeypatch):
    p = tmp_path / "garbage.mp4"
    p.write_bytes(b"this is not a video")

    class Res:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(merger.subprocess, "run", lambda *a, **k: Res())
    monkeypatch.setattr(cfg, "ffprobe_binary", lambda: "/usr/bin/ffprobe")
    info = merger.evaluate_final(p, expected_s=60)
    assert info["ok"] is False
    assert "unreadable" in info.get("error", "")


def test_evaluate_final_rejects_landscape(tmp_path, monkeypatch):
    p = tmp_path / "wide.mp4"
    p.write_bytes(b"real-ish bytes")

    probes = [
        json.dumps({"streams": [
            {"codec_type": "video", "width": 1920, "height": 1080},
            {"codec_type": "audio"},
        ], "format": {"duration": "60.0"}}),
        '{"format": {"duration": "60.0"}}',  # duration probe
    ]

    class FakeRun:
        def __init__(self, outputs):
            self._outs = list(outputs)

        def __call__(self, cmd, **kw):
            return SimpleNamespace(returncode=0, stdout=self._outs.pop(0))

    monkeypatch.setattr(merger.subprocess, "run", FakeRun(probes))
    monkeypatch.setattr(cfg, "ffprobe_binary", lambda: "/usr/bin/ffprobe")
    info = merger.evaluate_final(p, expected_s=60)
    assert info["ok"] is False
    assert "9:16" in info.get("error", "")


def test_evaluate_final_rejects_landscape_under_916(tmp_path, monkeypatch):
    """16:9 landscape is rejected when FLOW_ASPECT=9:16 (default pipeline)."""
    p = tmp_path / "landscape.mp4"
    p.write_bytes(b"bytes")

    probes = [
        json.dumps({"streams": [
            {"codec_type": "video", "width": 1280, "height": 720},
            {"codec_type": "audio"},
        ], "format": {"duration": "60.0"}}),
        '{"format": {"duration": "60.0"}}',
    ]

    class FakeRun:
        def __init__(self, outputs):
            self._outs = list(outputs)

        def __call__(self, cmd, **kw):
            return SimpleNamespace(returncode=0, stdout=self._outs.pop(0))

    monkeypatch.setattr(merger.subprocess, "run", FakeRun(probes))
    monkeypatch.setattr(cfg, "ffprobe_binary", lambda: "/usr/bin/ffprobe")
    info = merger.evaluate_final(p, expected_s=60)
    assert info["ok"] is False
    assert "9:16" in info.get("error", "")


def test_evaluate_final_accepts_169_when_configured(tmp_path, monkeypatch):
    """16:9 landscape PASSES when FLOW_ASPECT=16:9 (user directive Sep 2026)."""
    monkeypatch.setenv("FLOW_ASPECT", "16:9")
    p = tmp_path / "landscape.mp4"
    p.write_bytes(b"bytes")

    probes = [
        json.dumps({"streams": [
            {"codec_type": "video", "width": 1280, "height": 720},
            {"codec_type": "audio"},
        ], "format": {"duration": "60.0"}}),
        '{"format": {"duration": "60.0"}}',
    ]

    class FakeRun:
        def __init__(self, outputs):
            self._outs = list(outputs)

        def __call__(self, cmd, **kw):
            return SimpleNamespace(returncode=0, stdout=self._outs.pop(0))

    monkeypatch.setattr(merger.subprocess, "run", FakeRun(probes))
    monkeypatch.setattr(cfg, "ffprobe_binary", lambda: "/usr/bin/ffprobe")
    info = merger.evaluate_final(p, expected_s=60)
    assert info["ok"] is True


def test_evaluate_final_rejects_no_audio_stream(tmp_path, monkeypatch):
    p = tmp_path / "silent.mp4"
    p.write_bytes(b"bytes")

    probes = [
        json.dumps({"streams": [{"codec_type": "video", "width": 720, "height": 1280}],
                    "format": {"duration": "60.0"}}),
        '{"format": {"duration": "60.0"}}',
    ]

    class FakeRun:
        def __init__(self, outputs):
            self._outs = list(outputs)

        def __call__(self, cmd, **kw):
            return SimpleNamespace(returncode=0, stdout=self._outs.pop(0))

    monkeypatch.setattr(merger.subprocess, "run", FakeRun(probes))
    monkeypatch.setattr(cfg, "ffprobe_binary", lambda: "/usr/bin/ffprobe")
    info = merger.evaluate_final(p, expected_s=60)
    assert info["ok"] is False
    assert "no audio stream" in info.get("error", "")


def test_evaluate_final_rejects_wrong_duration(tmp_path, monkeypatch):
    p = tmp_path / "short.mp4"
    p.write_bytes(b"bytes")

    probes = [
        json.dumps({"streams": [
            {"codec_type": "video", "width": 720, "height": 1280},
            {"codec_type": "audio"},
        ], "format": {"duration": "30.0"}}),
        '{"format": {"duration": "30.0"}}',  # duration probe
    ]

    class FakeRun:
        def __init__(self, outputs):
            self._outs = list(outputs)

        def __call__(self, cmd, **kw):
            return SimpleNamespace(returncode=0, stdout=self._outs.pop(0))

    monkeypatch.setattr(merger.subprocess, "run", FakeRun(probes))
    monkeypatch.setattr(cfg, "ffprobe_binary", lambda: "/usr/bin/ffprobe")
    info = merger.evaluate_final(p, expected_s=60, tolerance_s=5)
    assert info["ok"] is False
    assert "duration" in info.get("error", "")


def test_concat_escape_handles_single_quotes():
    from pathlib import Path

    assert merger._concat_escape("dave's repo/x.mp4") == "dave'\\''s repo/x.mp4"


def test_evaluate_final_ok_vertical(tmp_path, monkeypatch):
    p = tmp_path / "good.mp4"
    p.write_bytes(b"real bytes")

    probes = [
        json.dumps({"streams": [
            {"codec_type": "video", "width": 720, "height": 1280},
            {"codec_type": "audio"},
        ], "format": {"duration": "60.5"}}),
        '{"format": {"duration": "60.5"}}',
    ]

    class FakeRun:
        def __init__(self, outputs):
            self._outs = list(outputs)

        def __call__(self, cmd, **kw):
            return SimpleNamespace(returncode=0, stdout=self._outs.pop(0))

    monkeypatch.setattr(merger.subprocess, "run", FakeRun(probes))
    monkeypatch.setattr(cfg, "ffprobe_binary", lambda: "/usr/bin/ffprobe")
    info = merger.evaluate_final(p, expected_s=60, tolerance_s=5)
    assert info["ok"] is True