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

- **Beat #:** 32 — weekday 9am heartbeat: triage only, no video-loop code (CI 403-blind; `checker` spawn frozen 5th time)
- **Date:** 2026-09-30
- **Trigger:** schedule (`0 9 * * 1-5` autonomous job)
- **Status:** **TRIAGE ONLY — 0 video-loop code changed, no PR.** Ran this loop's own gate locally (CI is 403-blind): `pip install -r video_generation_loop/requirements.txt` + `pip install -e .` + `pytest` (seconds), then `python -m pytest -q video_generation_loop/tests tests` → **273 passed, 1 failed**. Same single env-only failure as Beat 31 — `video_generation_loop/tests/test_flow_automation.py::test_clip_is_real_video_rejects_empty_and_audio_only`: this runner has no `ffmpeg`/`ffprobe`, so `flow_automation._clip_is_real_video` takes its documented pass-on-size fallback and the audio-only `.mp4` fixture reads as a real clip. `test-gate.yml` apt-installs ffmpeg, so CI is unaffected. **The hermeticity fix already exists as open PR #10** — not duplicated, and no PR is permissible anyway (`checker` spawn failed a 5th time). The job loop recorded the shared-infra root cause + prepared `actions: read` patch under its §10 task 20; the same missing scope affects this loop's CI gate, so it is owned by the job loop (task 7 here stays cross-reference only). `PASS` (nothing committed)

## 3. Beat Log

| Beat | Date | Trigger | Action | Result |
|------|------|---------|--------|--------|
| 32 | 2026-09-30 | schedule — weekday 9am heartbeat | Local gate substitute (CI 403-blind): `python -m pytest -q video_generation_loop/tests tests` → 273 passed, 1 failed; failure is env-only (no ffprobe → pass-on-size fallback) and already covered by open PR #10; `checker` spawn fail #5 ⇒ no PR | **PASS** — no video-loop code changed; 1 pre-existing env-only failure, fix already on PR #10 |
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
3. Decide stale PRs: #5 (wrap_text), #7 (redact fix), #8 (issue #6 fix) — merge or close.
4. **rclone Drive sync** (laptop-off design): GitHub cron pulls clips/uploads/syncs back
   with the laptop off — still pending.
5. `_approve_credits` live verification on the credit dialog (part of G5).
6. Beat 6-12 follow-ups (verify-loop-state graduation) remain available.
7. **(2026-09-24, shared infra — owned by job loop Beat 116):** retired `checker` model
   `opencode/mimo-v2.5-free` was fixed to `opencode/mimo-v2.6-flash-free` in
   `.opencode/agent/checker.md`; this loop's `AGENTS.md` §11 lesson line was updated to
   match (consistency only, no video-loop behavior change). Verify the Checker spawn works
   next session before this loop's next maker–checker cycle.
8. **(2026-09-30, shared infra — HUMAN GATE, this loop's CI gate is blind too):** the
   `autonomous` job in `.github/workflows/opencode.yml` has no `actions` scope, so
   `gh run list --workflow=test-gate.yml` 403s and this loop's gate cannot be observed from a
   heartbeat. Patch prepared (commit `a4e6951`, `actions: read`) but un-pushable — the App
   token may not edit `.github/workflows/**`. Owned + documented by **job loop §10 task 20**;
   not tracked here beyond this cross-reference. Until it lands, run this loop's gate locally:
   `pip install -r video_generation_loop/requirements.txt && pip install -e . && python -m pytest -q video_generation_loop/tests`
   (~5 s). Expect `test_clip_is_real_video_rejects_empty_and_audio_only` to FAIL on any runner
   without ffmpeg — that is the runner, not the code (PR #10 pins the ffprobe seam).

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