# STATE.md — Loop Engineering State

Persistent context memory for the Loop Engineering with General Agents crash course.
This file is the agent's shared memory across beats (heartbeats, issue comments, PR events).
The OpenCode agent reads this file at the start of every run and updates it at the end.

> This file is the loop's progress file — the course's `progress.md`. Read first, update last (AGENTS.md §9).

## 1. Loop Identity

- **Repo:** `Moh-Tayyab/loop_engineering_with_general_agents`
- **Practice Goal:** Master the Outer Loop (Big Loop) architecture:
  1. Verification Gate & Loop Design Core
  2. Maker–Checker Split
  3. Heartbeat / Automation
  4. Autonomous Issue-to-PR Loop
  5. Inner vs Outer Loop operationalization
  6. Hardened Maker–Checker evaluation (test gate + adversarial checker)
  7. Escalation protocols (loop detection, retry caps, state compression)
  8. Custom domain skills
- **Primary Agent:** OpenCode (GitHub Actions) — `opencode/ling-3.0-flash-fin-free`
  (2026-09-14: `deepseek-v4-flash-free` removed, `hy3-free` retired, `gemini-3-flash`
  requires billing → this free model is the validated one. Lessons in AGENTS.md §10.)
- **Model budget note:** track beats and wall-clock as a proxy for cost.

## 2. Current Beat

- **Beat #:** 25
- **Date:** 2026-09-14
- **Trigger:** manual — production-readiness hardening (user: "make it ready for production")
- **Status:** Beat 25 complete. Money-gate fail-closed: `_approve_credits` now REQUIRES the day's first explicit credit approval (raises `FlowAutomationError` if no dialog; later clips lenient; `FLOW_CREDITS_PREAPPROVED=1` documented opt-out) + 4 new tests. CI: test-gate now triggers on push to main + installs ffmpeg — **first-ever GREEN run over the loop code (266 passed on GitHub)**. Loop-engine automation fixed: root cause was model lifecycle (`gemini-3-flash` → CreditsError "No payment method" on wrk_01KRGJ...C0H; `hy3-free` retired) → switched to `opencode/ling-3.0-flash-fin-free`; workflow_dispatch smoke ran morning-triage agent to **SUCCESS** (it re-opened issue→PR loop; PR #8 for issue #6 is open, unmerged, for human review). Machine `.env` → `FLOW_PLANNER=template`. Added `docs/PRODUCTION_RUNBOOK.md` (gates, preflight, G5 acceptance, cutover, rollback). Repaired spine: beats 13-24 rows were lost from a stale commit — restored below. **Remaining human gates before unsupervised autonomy:** G5 supervised live run + YouTube re-consent (token 2026-08-31, testing-mode ~7d expiry). `PASS`

## 3. Beat Log

| Beat | Date | Trigger | Action | Result |
|------|------|---------|--------|--------|
| 1-12 | 2026-08-17→21 | legacy course beats | 1 repo+workflow init · 2 STATE/AGENTS/heartbeat · 3 loop design · 4 textutils lib · 5 agentic-loop skill · 6 textutils.diff · 7 maker-checker subagents · 8 verify skill · 9 spine §9/§10/§11 · 10 heartbeat+triage skill · 11 §27 spine audit · 12 workspace cleanup | all PASS (compressed at 2026-09-13, §9) |
| 13 | 2026-08-30 | manual | Built `video_generation_loop/` (SLC spec → daily 60s shorts via Google Flow automation): template+Gemini planners w/ secret screening, durable state (atomic save, corrupt quarantine, budget-blocked topics), Playwright Flow clipper, fail-closed ffmpeg evaluator, 4-platform post package, 14→39 tests | PASS — 39 pytest green, dry-run smoke OK; 2 adversarial checker passes (model `opencode/hy3-free` 404; ran via `general`; `.opencode/agent/checker.md` switched to `ling-3.0-flash-fin-free`); final APPROVED |
| 14 | 2026-08-30 | manual | Pivot: storyboard TEMPLATE-only default (Gemini only on `FLOW_PLANNER=gemini`+key; gate enforced in `storyboard_for`, no implicit env-key), added `--login` MANUAL LOGIN GATE (once-off headed Flow sign-in, Google-SSO cookie detection, session reused; creds never in code/files/git); docs/.env/README updated; config + session-cookie tests | PASS — 49 tests, dry-run OK; 2 adversarial checker passes (planner-gate bypass HIGH caught + fixed, sign-in substring scan → cookie signal), final APPROVED; env: system ffmpeg+ffprobe installed, Playwright chromium downloaded (49→49, real merge+evaluate smoke PASS; no-ffprobe test now mocks absence) |
| 15 | 2026-08-31 | manual | YouTube beat: new `youtube_upload.py` (OAuth refresh token, SEO doc, resumable PRIVATE scheduled upload+publishAt, thumbnail), `--youtube-auth`/`--upload-today`/`--auth-console` flags, `config.youtube_publish_at` (+`env_or`), google libs deps, 11 tests | PASS — 60 tests, compile OK, secret scan clean; 2 adversarial checker passes (req spec `>=0.1>=0.5` broken, idempotency marker missing, raw tracebacks on upload errors, unvalidated HH:MM/tz — all fixed), final APPROVED |
| 16 | 2026-08-31 | manual | Google login blocked ("browser/app may not be secure") → root cause bundled-Chromium automation detection; launcher now prefers real system Chrome (`channel="chrome"`, `--disable-blink-features=AutomationControlled`, bundled fallback), removed dead helper; user did `--youtube-auth` (test-user approved, refresh token saved, gitignored); FIRST REAL UPLOAD — synthetic day_03 → videoId pT7ziFDM_yc, publishAt 13:00Z, idempotent skip on re-run; USAGE.md §5/§6/§9 | PASS — 60 tests; checker APPROVED. OPEN: Flow UI auto-click degrades to MANUAL ASSIST (DOM changed) — selector research pending |
| 17 | 2026-08-31 | manual | Playwright MCP configured **project-level** (`.opencode/opencode.json`, system Chrome + signed-in flow-profile; removed from global config). Visually inspected a REAL generated video (project b7cb/editor edit/b3e38…): editor top-bar `download Download` saves resolved MP4 directly (no 3-dots/resolution). Downloaded + validated clip_01.mp4 (H.264 720x1280 9:16, AAC, 10s, 3MB; prompt == storyboard scene 1), saved to output/day_02/clips/. Refactored `_download_clip`: path1 direct accessible-name Download, path2 tile 3-dots fallback. Human-gated AGENTS.md §10 lesson approved+added (Flow UI fragility → drive via Playwright MCP) | PASS — 60 tests; checker APPROVED. Flow gen+download end-to-end PROVEN via direct editor Download |
| 18 | 2026-08-31 | manual | **Agentic loop enabled** (cron `0 9 * * *`) + `loop-prompt.md` + **presenter-style planner** (5 presenter scenes + 1 terminal visual). Fixed 3 blockers: ref image Character wiring (`_ensure_presenter_character`), state reset for presenter, Character feature integration. | PASS — 64 tests. |
| 19 | 2026-08-31 | manual | **Videos 1-3 Completed by User.** Synced `topics.json` (concept-01 done, concept-02 pending) + `.slc/state.json` (current_day=3, done_topic_ids=[concept-01]). Next run primed for **Day 04 = Concept 02: Plan mode**. All 190 tests pass. | PASS — 190 tests pass. Ready for autonomous Day 04 production. |
| 20 | 2026-09-13 | manual | **Hardening run A / Beat 1 — concurrency & state integrity:** reentrant POSIX `FileLock` (fcntl.flock + in-process registry), `LoopState.locked()`/`reload()`, `_run_real` day-boundary lock, `uploaded.json` marker lock, `config.env_float` for clean bad-value fail; 5 locking tests; 2 checker passes APPROVED (general subagent fallback; checker.md model still 404s). | PASS — 198 repo tests; dry-run OK. |
| 21 | 2026-09-13 | manual | **Hardening run A / Beat 2 — money-path:** credit approval scoped to modal overlays (never page-wide), dedicated-hints-first order, clip-scoped `_credits_approved` guard; pure `_is_generation_finished` (only real results signal done, no editor-chrome false-done); download-verify `_clip_is_real_video` (pass-on-size if no ffprobe; fail-closed if unreadable) + `merger.probe_media`; `_ensure_real_video` 2× re-download, never re-generate. Checker: 2 findings fixed (ffprobe-absent double-charge; dialog-only too strict) → APPROVED. 217 repo tests. | PASS — runs clear; 217 tests. |
| 22 | 2026-09-13 | manual | **Hardening run A / Beat 3 — unattended lifecycle + final eval:** fail-fast seam (`FLOW_AUTO_FAILFAST`/headless/non-TTY → fail, never block) + `manual_todo.txt` append log; `evaluate_final` requires video+audio streams and tight 9:16 (0.5625±0.03) when ffprobe present (pass-on-size contract kept). Checker APPROVED (empirical concat: video-only later clips still concat-with-audio; only truly-audio-less final is rejected). 226 repo tests. | PASS — Run A (Beats 1-3) complete; 226 tests. |
| 23 | 2026-09-13 | manual | **Hardening run B / Beat 4 — upload + durability:** `uploaded.json` 3-state tombstone (`pending→done|failed`); pre-commit-only→`failed`, every post-commit-capable failure→`PostCommitError`→`pending` (double-post logically impossible); per-clip durable `clip_attempts` ledger (crash-resume never re-burns a capped clip); state `schema_version` guard + quarantine on garbage; reference-image day preflight; latent `_upload_one` NameError fixed. 4 adversarial rounds (B1/F1/F2/no-id) → APPROVED. 250 repo tests. | PASS — Run B Beat 4 done; 250 tests. |
| 24 | 2026-09-13 | manual | **Hardening run B / Beat 5 — planner parity + deps/env/docs:** shared `screen_storyboard` output gate wired into BOTH LLM planners (API + gemini-web, new `strict`; unscreened output / timeout / parse fail / unsafe topic → strict raises, lenient → template; success log after gate); requirements.txt exact-pinned; `.env.example` rewritten (`FLOW_PLANNER=template`, `FLOW_AUTO_FAILFAST=1`, dead vars removed); USAGE.md (fail-fast, tombstone, parity, tests, G5 runbook, real flags). Checker round 1: 5 findings — all fixed; round 2 APPROVED. 262 repo tests. | PASS — Run B Beat 5 done; dry-run OK. |
| 25 | 2026-09-14 | manual | **Production-readiness hardening:** money-gate fail-closed (`_approve_credits` requires first explicit credit approval; `FLOW_CREDITS_PREAPPROVED=1` opt-out) + 4 tests; test-gate triggers on push + ffmpeg → first CI green over loop (266 passed); autonomous-loop model fixed (`opencode/ling-3.0-flash-fin-free`) + dispatch smoke SUCCESS (opened PR #8, left for human); machine `.env` → template; PRODUCTION_RUNBOOK.md added; spine beats 13-24 restored. | PASS — 266 local, 266 CI. Humans: G5 live + YouTube re-consent next. |

## 4. Budget & Stopping Conditions

**Hard ceiling (budget):**
- Max beats per run: **3** (a run that exceeds this must stop and report, never spin)
- Max cost per run: **$0.50 equivalent** (watch model spend; stop and report if exceeded)
- Max wall-clock per run: **15 minutes**
- Max inner-loop iterations per beat: **5** (edit→test→refactor spins beyond this must escalate, see §8)

**Stopping conditions (loop exits immediately when ANY is true):**
1. Task goal reached and verified by the Checker.
2. Max beats / cost / time / iteration budget exceeded.
3. Irrecoverable error (build, test, or auth failure that cannot be fixed in-loop).
4. Escalation trigger fired (see §8 — retry cap reached, human pinged).
5. Requested action requires human decision or credentials not in secrets.
6. User or owner explicitly says stop.

On every stop, the agent must append a row to the Beat Log above and update "Current Beat".

## 5. Maker–Checker Split

Rules live in AGENTS.md §2 and §5 (single source of truth). Not restated here —
this file only records which verdict each beat got (see §3).

## 6. Automation Triggers (Heartbeat)

Defined in `.github/workflows/opencode.yml`:
- `issue_comment` + `pull_request_review_comment` → on-demand beats (`/oc`, `/opencode`)
- `issues` (opened) → Autonomous Issue-to-PR Loop
- `pull_request` (opened/synchronize) → automated review
- `schedule` cron `0 9 * * 1-5` → weekday 9am (UTC) morning triage beat: read spine → scan CI failures + open issues → triage each (skill) → fix/checker/PR or leave for human → update spine

## 7. Inner vs Outer Loop

Rules live in AGENTS.md §4 (single source of truth). Not restated here.

## 8. Escalation Protocols

Rules live in AGENTS.md §6 (retry cap, freeze action, loop detection, rework bound — single source
of truth). Not restated here. A fired escalation consumes stopping-condition slot §4-4.

## 9. State Compression

Prevent `STATE.md` from overflowing the context window on long multi-beat loops:
- **Beat log cap:** keep only the **last 20 rows**. When a row is dropped, fold its `Result` into a
  one-line "Legacy beats" summary at the top of the table.
- **Per-beat entry:** never exceed ~4 lines each (trigger, action, result).
- **When to compress:** run compression at the start of any run where the beat log exceeds 20 rows,
  or when a single beat entry grows past ~400 chars.
- **Compression rule:** drop detail, keep the verdict (PASS/FAIL/ESCALATED) and one-line action.
  Never delete the "Current Beat", budget (§4), or escalation (§8) sections.
- After compressing, note `compressed at <date>` in the beat log header.

## 10. Next Actionable Tasks

1. **G5 supervised live run (the last gate):** `FLOW_PLANNER=template FLOW_HEADLESS=0 .venv/bin/python -m src.main` on a fresh day (concept-03); accept 6/6 real clips → merge → post package → `--upload-today` (tombstone `done` + video_id). Use `docs/PRODUCTION_RUNBOOK.md`.
2. **YouTube re-consent:** `.venv/bin/python -m src.main --youtube-auth` (token from 2026-08-31 is past Google testing-mode ~7d expiry).
3. Decide stale PRs: #5 (wrap_text), #7 (redact fix), #8 (issue #6 fix from morning triage) — merge or close after review.
4. **rclone Drive sync** (laptop-off design): GitHub cron pulls clips/uploads/syncs back with the laptop off — still pending.
5. `_approve_credits` live verification on the credit dialog (part of G5) — BEAT 2 selectors exercise on real PRO DOM.
6. Beat 6-12 follow-ups (verify-loop-state graduation) remain available.

## 11. Human Gate Decisions

Decisions the human gate made, so future runs do not re-litigate or forget them:

- 2026-08-19 — keep the progress file named `STATE.md`; add the one-line "progress.md" note instead of renaming it.
- 2026-08-19 — heartbeat = weekdays 09:00 UTC; per item: triage skill → checker subagent → PR only on APPROVED; risky items stay in §10 for the human.
- 2026-08-19 — rules-file (AGENTS.md) changes need a human; propose via `verify-loop-state`, never edit directly.
- 2026-08-19 — cheap/read-only subagents run on `opencode/*` free models (`anthropic/claude-haiku-4-5-20251001` 404s in this env).
- 2026-08-31 — **PAID Google account.** Every video generation costs real money; never run an accidental/scrap/watchdog generation. Generate ONLY from the approved storyboard topic — never topic-derive a video.
- 2026-08-31 — **Video style = presenter + narration.** Videos feature the presenter (young man) from user-provided reference images; prompt format: educational explainer + presenter + clean studio bg + blue tech accents + "Narrate / Lip-sync exactly: '<Urdu text>'". Do NOT generate generic terminal-only clips.
- 2026-08-31 — **Reference images** live in `video_generation_loop/references/` (drop-in: `ref_01.jpg`, `ref_02.jpg`...). Use them in generated videos — "kabhi koi image, kabhi koi" — with a perfect background each time. **Conditional use:** use the reference image for the on-screen presenter ONLY when the scene/script needs the young-man presenter on screen; when a scene is purely visual/animated narration, do NOT force the presenter into it.
- 2026-08-31 — **Flow presenter mechanism = Characters (MCP-verified, live PRO account).** A raw `input[type=file]` upload only drops the image into the project LIBRARY; it does NOT give Veo a consistent presenter. The verified pipeline is: `Add Media -> Upload media` (hidden file input) -> image in library, then `Characters` nav (`/characters`) -> `Add from Project` -> pick the image -> `Add to Character` -> `Done` -> a reusable Character (portrait = the reference image). Implemented as `flow_automation._ensure_presenter_character` (fail-closed: raises before generating if the Character can't be built — paid-account guard). Throwaway test project + Character from ref_01 were created during live verification and then DELETED (paid account left clean).
- 2026-08-31 — **Presenter prompt TEMPLATE (user-approved)** — the working format for any scene with the young-man presenter: `Educational explainer video featuring the young man from the reference image as the on-screen presenter/narrator. Clean modern dark-themed studio setting with soft blue neon accents and subtle tech elements in the background. The presenter looks directly into the camera with confident, professional, and engaging body language, speaking naturally with realistic lip-sync. Animated clean text overlays highlighting key takeaways.` then `Narrate / Lip-Sync exactly (in clear Urdu/Hindi): > '<Urdu/Hindi narration>'.`
- 2026-09-14 — **Unattended runs must default to the template planner.** `FLOW_PLANNER=gemini-web` hangs at the planner stage with no human; production `.env` = `template`.
- 2026-09-14 — **Autonomous model = `opencode/ling-3.0-flash-fin-free`.** `opencode/deepseek-v4-flash-free` removed, `opencode/hy3-free` retired, `opencode/gemini-3-flash` needs billing (CreditsError on workspace wrk_01KRG...C0H). Pinned in all three opencode.yml jobs + checker.md.