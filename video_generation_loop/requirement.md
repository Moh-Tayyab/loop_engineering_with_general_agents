# requirement.md — Daily AI-Video Generation Loop (content automation)

## Goal

An autonomous, daily "content factory" loop that produces ONE ready-to-post
1-minute (60s) short-form AI video per day for Facebook, Instagram, TikTok and
YouTube Shorts. The loop itself:

1. Picks today's topic automatically from the **Agentic Coding Crash Course**
   (15 concepts, `https://agentfactory.panaversity.org/docs/agentic-coding-crash-course`).
   Never repeats a completed topic; keeps the list in a state file.
2. Uses an LLM (Gemini via the pro account / an OpenAI-compatible endpoint) to
   turn that topic into a 6-scene storyboard (6 x 10s clips) with:
   - a hook line (first-3s), Urdu/English mixed,
   - a scene-by-scene voiceover script,
   - one Google Flow video-generation prompt per scene (9:16 vertical, HD),
   - caption + hashtags per platform.
3. Drives **Google Flow (web app)** with **Playwright browser automation** using
   the user's saved Google login (session persisted in a user-data dir):
   prompts one Flow generation per scene, downloads the resulting clip MP4.
4. Merges the 6 clips into one final MP4 (~60s) with a checkpoint evaluator
   (duration/aspect checks) and a retry guardrail.
5. Writes a per-day "post package" (final video + per-platform caption/desc +
   hashtags + thumbnail note) into `output/`. Auto-upload to the four social
   platforms is explicitly OUT of scope for v1 (manual upload, batch ready).

The loop is resumable and crash-safe: state is written atomically; a partial
day can be resumed without regenerating already-done clips.

## User Journeys

1. **Daily run (fully autonomous):** User runs `python -m src.main` (or a cron).
   The loop reads state → picks next topic → generates storyboard →
   generates 6 clips via Google Flow → merges → writes post package →
   updates state. User's only job: review `output/day_N/` and post.
2. **Dry-run / rehearsal (no browser, no API):** `--dry-run` renders the same
   storyboard + post package from a template planner. Used for tests, CI, and
   previewing tomorrow's video without spending a Flow generation.
3. **Resume after interruption:** If a day fails mid-way (browser closed, API
   hiccup), the next run detects the in-progress day and resumes from the
   missing clips only. Clips on disk are reused, not regenerated.
4. **Manual assist:** If Google Flow's DOM changes and automation cannot find
   the generate/download controls, the loop prints the exact prompt and waits
   for the human to paste it into Flow and save the clip file, then continues.

## Features

- Topic queue: 15 crash-course concepts; auto-advance; explicit `--topic` override.
- Storyboard generator: 6 scenes, hook, VO script, Flow prompt, caption, tags.
- Google Flow automation (Playwright, Chromium, persistent Google session).
- Clip downloads to `output/day_N/clips/clip_01..06.mp4`.
- Merging via FFmpeg concat → `output/day_N/final.mp4`.
- Evaluator: verifies final video exists, ~60s (±5s), aspect 9:16; retry limited.
- Post package per platform: TikTok, Instagram Reels, Facebook, YouTube Shorts.
- State machine (JSON, atomic writes, resume-safe).
- Deterministic template planner for `--dry-run` and tests.
- `docs/USAGE.md`, `.env.example`, `course/topics.json` (editable).
- SLC spec tree (`slc`-generated) + STATE-like run log (`.slc/run/run.log`).

## Tech Stack

- Python 3.12 (scripts, pipeline orchestration).
- Playwright (Python) + system Chromium for Google Flow automation.
- FFmpeg (system binary) for lossless clip concat.
- Gemini API via OpenAI-compatible endpoint (`https://generativelanguage.googleapis.com/v1beta/openai/`)
  for storyboard generation; `GEMINI_API_KEY` from `.env`.
- Google Flow web app (user's Google AI / Flow pro account) — the video engine.
- JSON for state (`.slc/state.json`) and topics (`course/topics.json`).
- pytest for the test suite (CI-friendly, `--dry-run` needs no credentials).

## Design

- Vertical 9:16 (1080x1920), ~60s total, 6 scenes x 10s, 24fps, no burn-in text
  (captions added on-platform), Urdu/English mixed voiceover + hooks.
- Visual identity per video: tech/terminal/AI-agent aesthetic, consistent
  character/style anchor phrase injected at the START of every Flow prompt so
  the 6 clips feel consistent (per Gemini's tip on character consistency).
- Prompt format for Flow: scene description + camera + mood + aspect anchor.

## Non-Goals

- Auto-posting to TikTok/Instagram/Facebook/YouTube (v1 = manual post, batched).
- Long-form (YouTube main feed) videos, livestreams, or multi-day schedules.
- Any video-editing beyond concat (no burned captions, transitions, BG music).
- Monetization/analytics harvesting. Not a substitute for audience building.
- Support for YouTube/FB accounts without a Google login in the profile dir.

## Constraints

- Never send real credentials/keys into prompts. `.env` + `.slc/` are gitignored;
  secret-scan the requirement/storyboard text before sending (SLC-style).
- Never reuse/duplicate a completed topic (state is the single source of truth).
- Never exceed 3 consecutive failures on the same clip → stop that day, log and
  escalate to a human (`@Moh-Tayyab`) instead of spinning.
- Never silently overwrite an existing completed `output/day_N/`.
- One model for the whole project; do not mix Gemini/Claude for storyboards.
- Chrome profile dir must hold a signed-in Google session for Flow; automation
  must degrade to manual-assist rather than trying to log in automatically.