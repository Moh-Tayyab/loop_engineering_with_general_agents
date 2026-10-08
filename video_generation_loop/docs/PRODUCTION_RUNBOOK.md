# Production Runbook — Video Generation Loop

Goal: end one supervised-then-unattended production pipeline that turns a topic
into a scheduled private YouTube short, fail-closed, with money-safety.

## Status gates (in order)

| Gate | Command / action | Pass = |
|---|---|---|
| 1. Unit suite | `cd video_generation_loop && .venv/bin/python -m pytest -q` | 202 passed |
| 2. Repo suite + CI | `python -m pytest -q` (root) + push → `.github/workflows/test-gate.yml` | 325 passed on GitHub |
| 3. Planner parity | `FLOW_PLANNER=template .venv/bin/python -m src.main --dry-run` | storyboard + post pkg printed |
| 4. **G5 supervised live** | below | legacy: 6 clips + merge; extend mode: 1 scene grown to target + single download |

## Pre-flight (every real run)

```bash
cd video_generation_loop
.venv/bin/python -m src.main --list-topics        # queue sane; concept X pending
.venv/bin/python -m src.main --dry-run            # template storyboard + captions
```

- `.env`: `FLOW_PLANNER=template` (default; NEVER `gemini-web` for unattended).
- Browser profile signed in: `python -m src.main --login` once if the profile is
  signed out (`.runtime/flow-profile/`). Never auto-login.
- YouTube token fresh: `python -m src.main --youtube-auth` if the token is >5
  days old (Google testing-mode refresh tokens expire ~7 days).

## G5 supervised live run (the acceptance test)

Interactive terminal, `FLOW_HEADLESS=0`, fresh day (concept-03):

```bash
FLOW_HEADLESS=0 .venv/bin/python -m src.main
```

Watch the browser at each clip and confirm, on the REAL Flow DOM:
- character attach (presenter scenes use `ref_0N.png`);
- **credit dialog** appears for the first generation → `_approve_credits` clicks it
  (if NO dialog ever appears, the run aborts fail-closed — see
  `FLOW_CREDITS_PREAPPROVED` in USAGE §6; do NOT set it unless you know why);
- generation finishes (Stop control disappears + result present);
- download lands in `output/day_*/clips/` and is verified as a real video;
- ffmpeg merge passes so `final.mp4` exists with audio + 9:16;
- post package written (4 caption files + `post.json`).

Extend mode (`FLOW_EXTEND_MODE=1`) — same gates, different middle steps:

- segment 1 generates in the main editor, then the run opens the scene editor
  (`/edit/…`) instead of downloading;
- each extend: `Add clip` → `Extend (Veo 3.1 - Lite)` → continuation prompt →
  `Start generation` → credit gate (free-credit accept, or paid dialog →
  `FLOW_APPROVE_CREDITS=1` for supervised runs) → duration timecode grows by 8s;
- `output/day_*/extend_progress.json` updates after every paid step (crash →
  `--resume` re-enters the same scene, never regenerates a paid segment);
- ONE download at the end (`Download media` in the scene editor) → `final.mp4`,
  duration must land on the clip multiple ≥ `FLOW_TARGET_DURATION_S`, gated
  ±5s around that multiple (60 → 64s, pass window 59..69s).

Then schedule:
```bash
.venv/bin/python -m src.main --upload-today
```

Accept if: 6/6 clips, `final.mp4` non-empty with audio, upload tombstone reads
`done` with a real `video_id`, and YouTube shows a PRIVATE scheduled video.

If any step degrades to MANUAL ASSIST: paste the prompt into Flow, generate,
save the file to the printed path; the run continues. Unattended (headless/non-
TTY) runs log it to `manual_todo.txt` (repo root) and STOP fail-fast instead.

## Cutover to nightly unattended

1. G5 approved (gate 4).
2. `crontab -e`: `0 13 * * * cd <repo>/video_generation_loop && .venv/bin/python -m src.main >> .runtime/run.log 2>&1`
3. Watch the first 3 mornings: review `run.log`, `manual_todo.txt`,
   `.runtime/uploaded.json`, and confirm publishAt fires on YouTube.
4. Until rclone Drive sync exists: to run while the laptop is OFF, keep the
   laptop on at 18:00 PKT, or run the pipeline on a VPS/runner instead.

## Rollback / recovery

| Symptom | Action |
|---|---|
| Day aborted mid-clips | `python -m src.main --resume` (auto-resumed anyway; existing clips reused via clip ledger) |
| Clip burned budget (3×) | day escalates + never re-picks; human reviews then `--topic` force |
| Upload left PENDING | video MAY be live; reconcile on YouTube first (`uploaded.json`), never blindly retry |
| State corrupt / newer schema | quarantined automatically (`state.corrupt-*`); stop, restore, understand why |
| Flow UI changed → manual assist | update `flow_automation.py` selectors, re-approve with checker, bump test counts |

## Secrets & hygiene

- Gitignored and NEVER pushed: `.env`, `.runtime/` (tokens, profile, client
  secret, uploaded.json), `.slc/`, `output/`, `.playwright-mcp/`, and
  `manual_todo.txt` (repo root — `cfg.manual_todo_path()`).
- GitHub Actions CI has its own token injection policy (`YOUTUBE_TOKEN_FILE`).
- Reference images (`references/`) and `course/topics.json` ARE committed — they
  are the deterministic inputs a resume must reproduce.