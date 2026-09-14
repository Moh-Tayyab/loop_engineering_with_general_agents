"""Per-platform post package writer (caption, description, hashtags, meta)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from src.planner import Storyboard

PLATFORMS = {
    # platform -> (hashtag set)
    "tiktok": {
        "aivit", "aigrowth", "agentic", "aicoding",
        "pakistani", "urdu", "techtok", "opencode", "coding",
    },
    "instagram_reels": {
        "reels", "aikit", "aitools", "agentic", "aicoding",
        "kaamkarotricks", "pakistan", "urducoding",
    },
    "facebook": {
        "facebook", "ailearning", "agentic", "ai", "pakistan",
    },
    "youtube_shorts": {
        "shorts", "ai", "agentic", "opencode", "coding",
        "learnai", "urdutech",
    },
}

MIXED_CTA = (
    "Follow for 1-minute AI/agent skills daily — har roz ek naya concept. "
    "Comment 'AGENT' for the free roadmap."
)


def _hashtags(platform: str) -> str:
    tags = PLATFORMS.get(platform, set())
    return " ".join(f"#{t}" for t in sorted(tags, key=str.lower))


def build_caption(storyboard: Storyboard, platform: str) -> str:
    """Full postable caption: caption line + CTA + hashtags."""
    caption = storyboard.captions.get(platform) or _default_caption(storyboard)
    return f"{caption}\n\n{MIXED_CTA}\n\n{_hashtags(platform)}"


def _default_caption(storyboard: Storyboard) -> str:
    return f"{storyboard.topic.title} — 1 minute. #AI #AgenticCoding"


def write_post_package(
    storyboard: Storyboard,
    video_path: Path,
    out_dir: Path,
    *,
    platform_names: list[str] | None = None,
) -> Path:
    """Write per-platform caption files + post.json + a copy of the video."""
    out_dir.mkdir(parents=True, exist_ok=True)
    platforms = platform_names or list(PLATFORMS)
    post: dict[str, object] = {
        "day": storyboard.day,
        "topic": storyboard.topic.title,
        "video": "final.mp4",
        "platforms": {},
    }
    for p in platforms:
        caption = build_caption(storyboard, p)
        (out_dir / f"caption_{p}.txt").write_text(caption, encoding="utf-8")
        post["platforms"][p] = {"caption_file": f"caption_{p}.txt", "caption": caption}

    if video_path.exists() and (out_dir / "final.mp4").exists() is False:
        shutil.copy2(video_path, out_dir / "final.mp4")

    (out_dir / "post.json").write_text(
        json.dumps(post, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return out_dir / "post.json"