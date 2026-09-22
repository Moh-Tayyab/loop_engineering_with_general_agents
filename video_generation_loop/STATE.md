# STATE.md — Video Generation Loop (project spine)

> This is the **project spine** for `video_generation_loop/` — the back of that diary.
> Read `video_generation_loop/AGENTS.md` (rules) then this file (progress); update THIS file
> last when a beat touches the video loop. There is no root STATE.md or root AGENTS.md —
> this spine pair is fully self-contained (rules + budget live in this loop's `AGENTS.md`).
> (Nested-spine split decided 2026-09-14, beat 28; root files removed beat 30, 2026-09-15.)

## 1. Project Identity

- **Project:** `video_generation_loop/` — daily 60-second shorts via Google Flow automation.
- **Scope:** template/Gemini planners → storyboard → Flow Clip generation (PAID Google
  account) → ffmpeg merge/eval → 4-platform post package → YouTube private scheduled upload.
- **Stack:** Python 3.12, Playwright Flow, ffmpeg/ffprobe, Google APIs, pytest.
- **First real upload:** 2026-08-31 (videoId pT7ziFDM_yc, day_03 synthetic).
- **CI gate:** `.github/workflows/test-gate.yml` runs this loop's tests
  (installs its requirements; `python -m pytest -q video_generation_loop/tests`).

## 2. Current Beat

- **Beat #:** 32 — morning triage: root+video 1 red on `main` (ffprobe-seam test), fix verified in PR #10
- **Date:** 2026-09-22
- **Trigger:** weekday 9am heartbeat (morning triage)
- **Status:** Triage (no code): reproduced 1 red on `main` — `test_clip_is_real_video_rejects_empty_and_audio_only` fails on any host without ffprobe (env-dependent; CI installs ffmpeg so green). CLEAR FIX already shipped as open PR #10 (verified 5/5 clip tests on branch) but blocked: its test-gate run is `action_required` — a human must approve the workflow run + merge. Stale issues #1/#3/#4/#6 all already have fixes in open PRs #5/#9 (human merge gate, §10 item 3). Beat 31 pending inside PR #10. `PASS`

## 3. Beat Log

| Beat | Date | Trigger | Action | Result |
|------|------|---------|--------|--------|
| 32 | 2026-09-22 | weekday 9am heartbeat | **Morning triage (no code):** reproduced root+video 1 red on `main` — `_clip_is_real_video` ffprobe-seam (`test_clip_is_real_video_rejects_empty_and_audio_only` fails w/o ffprobe; env-dependent). Fix verified in open PR #10 (5/5 clip tests on branch); its test-gate run `action_required` — human approval + merge needed | PASS — triage only; no code |
| 30 | 2026-09-15 | manual | **Root AGENTS.md removed:** root `AGENTS.md` deleted by user request; THIS loop's `AGENTS.md` now carries the full rules (§0 self-containment, §2 non-negotiables, §3 budget, §5 inner/outer, §7 escalation, §11 lessons); consumers updated (opencode.yml, maker.md, skills, other loop) | PASS — 151 tests; checker APPROVED |
| 29 | 2026-09-15 | manual | **Root STATE.md removed:** root `STATE.md` deleted by user request; budget/maker-checker/escalation moved to root `AGENTS.md` (§3/§5/§7); THIS STATE.md self-contained; consumers updated (opencode.yml, maker.md, loop-prompt.md, verify/triage skills) | PASS — 151 tests; checker APPROVED |
| 28 | 2026-09-14 | manual | **Project split (dual spine):** created THIS `STATE.md` + `AGENTS.md` (identity, beats 13-25, §10/§11); loop-prompt.md now points here | PASS — 151 tests; leak scan clean; checker APPROVED |
| 13 | 2026-08-30 | manual | Built loop (SLC spec → daily shorts via Flow): template+Gemini planners w/ secret screening, durable state, Flow clipper, ffmpeg evaluator, 4-platform post package, 14→39 tests | PASS — checker APPROVED |
| 14 | 2026-08-30 | manual | Storyboard TEMPLATE-only default + `--login` MANUAL LOGIN GATE, config/env/README tests | PASS — 49 tests, 2 checker passes |
| 15 | 2026-08-31 | manual | YouTube upload (OAuth, SEO, private scheduled, thumbnail, idempotent), 11 tests | PASS — 60 tests |
| 16 | 2026-08-31 | manual | Google login blocked → prefer system Chrome; FIRST REAL UPLOAD (day_03 → videoId pT7ziFDM_yc) | PASS — 60 tests |
| 17 | 2026-08-31 | manual | Playwright MCP project-level; visually validated a real generated video; `_download_clip` direct-Download path | PASS — 60 tests |
| 18 | 2026-08-31 | manual | Agentic loop enabled (cron) + presenter-style planner + 3 blockers fixed | PASS — 64 tests |
| 19 | 2026-08-31 | manual | Videos 1-3 completed by user; state synced; primed for Day 04 Concept 02 | PASS — 190 tests |
| 20 | 2026-09-13 | manual | **Hardening A1 — concurrency & state:** reentrant FileLock, `LoopState.locked()/reload()`, day-boundary lock, uploaded.json marker lock, env_float | PASS — 198 tests |
| 21 | 2026-09-13 | manual | **Hardening A2 — money-path:** credit approval scoped to modals, pure `_is_generation_finished`, download-verify `_clip_is_real_video`, `_ensure_real_video` 2× re-download | PASS — 217 tests, checker findings fixed |
| 22 | 2026-09-13 | manual | **Hardening A3 — unattended lifecycle:** fail-fast seam, `manual_todo.txt` log, `evaluate_final` stream+9:16 gate | PASS — 226 tests |
| 23 | 2026-09-13 | manual | **Hardening B4 — upload durability:** uploaded.json tombstone (pending→done|failed), PostCommitError, clip_attempts ledger, schema_version guard, NameError fix | PASS — 250 tests |
| 24 | 2026-09-13 | manual | **Hardening B5 — planner parity + docs:** screen_storyboard gate in both planners, exact-pins, .env.example rewrite, USAGE.md | PASS — 262 tests |
| 25 | 2026-09-14 | manual | **Production-readiness:** money-gate fail-closed + 4 tests; test-gate triggers on push → first CI green (266 passed); autonomous model fixed; machine .env → template; PRODUCTION_RUNBOOK.md | PASS — 266 local, 266 CI |

## 4. Budget & Stopping Conditions

Same ceilings as the trainer (shared loop budgets) — see THIS loop's `AGENTS.md` §3.
Project-specific note: video beats cost REAL MONEY (PAID Google account); never run an
accidental watch/generation. Budget counter is shared with the job loop.

## 5–8. Maker–Checker, Inner/Outer, Automation, Escalation

All defined in THIS loop's `AGENTS.md` (§2 non-negotiables, §5 inner/outer, §6 hardened
maker–checker, §7 escalation). Single source of truth — do not restate here.

## 9. State Compression

Cap this project's beat log at 20 rows; compress into a one-line "Legacy beats" summary when
exceeded. Keep verdicts; never drop budget (§4) or escalation (THIS loop's `AGENTS.md` §7).

## 10. Next Actionable Tasks (video loop)

1. **G5 supervised live run (the last gate):** `FLOW_PLANNER=template FLOW_HEADLESS=0
   .venv/bin/python -m src.main` on a fresh day (concept-03); accept 6/6 real clips →
   merge → post package → `--upload-today` (tombstone `done` + video_id).
   Use `docs/PRODUCTION_RUNBOOK.md`.
2. **YouTube re-consent:** `.venv/bin/python -m src.main --youtube-auth` (token from
   2026-08-31 past Google testing-mode ~7d expiry).
3. Decide stale PRs: #5 (wrap_text), #7 (redact fix), #8 (issue #6 fix), **#9 (issue #6 fix, supersedes #7/#8), #10 (hermetic clip tests)** — merge or close. All OPEN with fixes complete; the two `action_required` test-gate runs (#10/#11) need a human to Approve the workflow run in the Actions UI.
4. **rclone Drive sync** (laptop-off design): GitHub cron pulls clips/uploads/syncs back
   with the laptop off — still pending.
5. `_approve_credits` live verification on the credit dialog (part of G5).
6. Beat 6-12 follow-ups (verify-loop-state graduation) remain available.

## 11. Human Gate Decisions (video loop)

- 2026-08-31 — **PAID Google account.** Every video generation costs real money; never
  generate from a non-approved storyboard topic; never topic-derive a video.
- 2026-08-31 — **Video style = presenter + narration.** Presenter (young man) from
  reference images; explainer + presenter + clean studio bg + blue accents +
  "Narrate / Lip-sync exactly: '<Urdu text>'".
- 2026-08-31 — **Reference images** live in `references/`: use the presenter image ONLY
  when the scene needs the on-screen presenter; purely visual scenes must NOT force it.
- 2026-08-31 — **Flow presenter = Characters (MCP-verified).** Raw file upload ≠ presenter;
  must go through `Characters → Add from Project`. Implemented fail-closed in
  `_ensure_presenter_character` (paid-account guard).
- 2026-08-31 — **Presenter prompt TEMPLATE** (user-approved) — the exact wording for
  presenter scenes is pinned in the human-gate record (§11 below, legacy beats 14–18).
- 2026-09-14 — **Unattended runs must default to the template planner.** `FLOW_PLANNER=gemini-web`
  hangs at planner stage with no human; production `.env` = `template`.