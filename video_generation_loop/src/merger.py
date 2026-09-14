"""Clip merging (FFmpeg concat) and final-video evaluation."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import src.config as cfg


def _concat_escape(path: str) -> str:
    """Escape a path for the ffmpeg concat demuxer (single-quote splitting)."""
    return path.replace("'", "'\\''")


def ffmpeg_available() -> bool:
    binary = cfg.ffmpeg_binary()
    if binary == "ffmpeg":  # the pip-fallback wasn't there either
        import shutil

        return shutil.which("ffmpeg") is not None
    return True


def concat_clips(clip_paths: list[Path], output_path: Path) -> Path:
    """Lossless concat of same-codec MP4 clips into one file."""
    if not clip_paths:
        raise ValueError("no clips to merge")
    for p in clip_paths:
        if not p.exists() or p.stat().st_size == 0:
            raise FileNotFoundError(f"clip missing/empty: {p}")
    ffmpeg = cfg.ffmpeg_binary()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    list_file = output_path.with_suffix(".concat.txt")
    list_file.write_text(
        "".join(f"file '{_concat_escape(str(p.resolve()))}'\n" for p in clip_paths),
        encoding="utf-8",
    )
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("ffmpeg merge timed out") from exc
    if proc.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"ffmpeg failed: {proc.stderr[-500:]}")
    return output_path


def probe_duration(path: Path) -> float | None:
    """Return duration in seconds via ffprobe (None if ffprobe unavailable)."""
    ffprobe = cfg.ffprobe_binary()
    if not ffprobe:
        return None
    cmd = [
        ffprobe,
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return None
    if out.returncode != 0:
        return None
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError:
        return None
    dur = float(data.get("format", {}).get("duration", 0) or 0)
    return dur if dur > 0 else None


def probe_media(path: Path) -> dict[str, object] | None:
    """Stream summary via ffprobe: {'has_video', 'has_audio', 'width', 'height',
    'duration_s'}, or None when ffprobe is missing or the file is not readable
    media.

    Used by download-verify (flow_automation) to tell a real clip apart from an
    empty or unreadable download WITHOUT ever re-triggering a paid generation."""
    ffprobe = cfg.ffprobe_binary()
    if not ffprobe:
        return None
    cmd = [
        ffprobe,
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return None
    if out.returncode != 0:
        return None
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError:
        return None
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    dur = float(data.get("format", {}).get("duration", 0) or 0)
    return {
        "has_video": video is not None,
        "has_audio": audio is not None,
        "width": int(video.get("width", 0)) if video else 0,
        "height": int(video.get("height", 0)) if video else 0,
        "duration_s": dur if dur > 0 else None,
    }


ASPECT_9_16 = 9 / 16  # 0.5625
ASPECT_TOLERANCE = 0.03  # ~±5% — admits 720x1280 / 1080x1920; rejects 2:3, 3:4, 1:1, 4:5


def evaluate_final(path: Path, expected_s: int, tolerance_s: int = 5) -> dict[str, object]:
    """Check the final video: exists, non-empty, ~expected duration.

    When ffprobe is available, additionally require a real set of streams:
    video present AND audio present AND a TIGHT 9:16 aspect ratio (9/16 ± 3%).
    Portrait-but-not-916 files (2:3, 3:4, 4:5, 1:1) are rejected for the
    vertical format.

    Missing ffprobe -> pass on size/duration alone (mirror the download-verify
    contract: a valid video is never rejected just because nothing could probe
    it)."""
    info: dict[str, object] = {"path": str(path), "ok": False}
    if not path.exists():
        info["error"] = "file missing"
        return info
    if path.stat().st_size == 0:
        info["error"] = "file empty"
        return info

    ffprobe = cfg.ffprobe_binary()
    if ffprobe:
        probe = probe_media(path)
        if probe is None:
            info["error"] = "unreadable media (ffprobe failed)"
            return info
        if not probe["has_video"]:
            info["error"] = "no video stream"
            return info
        if not probe["has_audio"]:
            info["error"] = "no audio stream"
            return info
        w, h = int(probe["width"]), int(probe["height"])
        info["width"], info["height"] = w, h
        ratio = w / h if h else 0.0
        info["aspect"] = round(ratio, 4)
        if not (ASPECT_9_16 - ASPECT_TOLERANCE <= ratio <= ASPECT_9_16 + ASPECT_TOLERANCE):
            info["error"] = f"aspect {ratio:.3f} not tight 9:16 (w={w}, h={h})"
            return info

    dur = probe_duration(path)
    info["duration"] = dur
    if dur is None and ffprobe:
        info["error"] = "duration unreadable (ffprobe failed)"
        return info
    if dur is not None and not (expected_s - tolerance_s <= dur <= expected_s + tolerance_s):
        info["error"] = f"duration {dur:.1f}s outside {expected_s}±{tolerance_s}"
        return info

    info["ok"] = True
    return info