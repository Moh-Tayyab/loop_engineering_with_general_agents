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

- **Beat #:** 36 — morning heartbeat triage → issue #6 fix shipped (PR #31)
- **Date:** 2026-10-08
- **Trigger:** schedule — weekday morning triage (both loops' spines read)
- **Status:** **PR #31 OPEN, checker APPROVED (round 2).** Issues #6 CLEAR FIX:
  old PRs #5/#7/#8/#9 were all closed-unmerged and their branches deleted, so
  the leak still reproduced on `main`; re-implemented on
  `fix/redact-secrets-openai-uppercase` — pattern 1 = prefix + `[A-Za-z0-9_-]*`
  + dash-free `[A-Za-z0-9_]{16,}` tail + `IGNORECASE` (catches dashed
  OpenAI-style keys, uppercase/mixed-case prefixes — issue #6's three repros —
  never kebab prose), non-int `max_len`/`max_chars` → `ValueError`. Checker r1
  CHANGES (kebab FP `skill-set-builder-extra-long`) → rework → r2 **APPROVED**
  (via read-only `general` — `checker` spawn still fails, task 14). Tests: 60
  textutils / 350 root gate green. Issue #4 (wrap_text) still OPEN — branch
  deleted, needs a fresh beat. Beat 35 left WAITING ON HUMAN (Google sign-in /
  day-9 resume) — unchanged.

## 3. Beat Log

compressed at 2026-10-08 (beat 36, §9 cap 20): beats 20–25 folded into one legacy row (verdicts kept: PASS ×6 hardening + production-readiness).

| Beat | Date | Trigger | Action | Result |
|------|------|---------|--------|--------|
| 36 | 2026-10-08 | schedule — morning triage | **Issue #6 redact fix (CLEAR FIX):** old PRs #5/#7/#8/#9 closed-unmerged, branches gone, leak still on `main`; re-implemented: pattern = prefix + `[A-Za-z0-9_-]*` + dash-free `{16,}` tail + IGNORECASE, non-int → ValueError, +14 tests; checker r1 CHANGES (kebab FP) → rework → r2 APPROVED (via `general`; `checker` spawn still fails, task 14) | **APPROVED → PR #31 open** — 60 textutils / 350 root green; #4 wrap_text still open (branch deleted), #3 dup, #1 stale |
| 35 | 2026-10-07 | manual — day-9 resume checkpoint | **WAITING ON HUMAN:** Google session revoked server-side (cookies intact, signed-out everywhere); login-gate v4 hardened in beat 34 (checker r5 APPROVED, 213 green). Handoff: user headed `--login`, then clear `extend_progress.json` `pending_extend` (seg-3 render never started) and resume day 9 (1 attempt left, segs 3-8) | **WAITING ON HUMAN** — no code; day 8 failed (`clip_attempts[final.mp4]=3`), day 9 in_progress (attempts=2, 16s) |
| 34 | 2026-10-07 | manual | **Login-gate server-side hardening (final):** gate v1 (cookies) + v2 (myaccount probe) both false-verified a REVOKED session live. v3/v4: probe now navigates RAW `https://flow.google.com/` (signed-out ⇒ server-302 to /about at domcontentloaded, no client race — measured), 16×500ms watch loop backstops slow client hops, startswith-aligned, TWO-consecutive streak, probe-fails hint, exact-host netloc. Tests: `_HopProbePage` pins the watch loop (deletable-proof), probe-destination test, 7 gate tests | **APPROVED** — checker round 5 (adversarial: urlparse bypasses, races, hop pin); 213 loop / 213 CI gate |
| 33 | 2026-10-07 | manual | **Day-8/9 live runs + session-revocation diagnosis:** run10 setsid — day 8 escalated correctly (extend seg-2 never committed, 3/3 attempts, `@Moh-Tayyab` fired). run11 — day 9 seg1 done + seg2 extended 8→16s, seg-3 Start never started (90s gate + 2 pending waits); day 9 kept `attempts=2`/1 budget. Diags: cookies fully intact (SID/SECURE/2PSIDTS exp 2027) yet myaccount/gemini/flow ALL server-side signed-out → session revoked everywhere. Flow facts: project-listing shows poster thumb (`img[alt='Generated video thumbnail']`), not `<video>`; edit_url/project_url → /about; extend wait deadlocked → `pending_extend=True` must be cleared (with evidence) pre-resume | **ESCALATED** — no valid Google session; generation impossible until fresh human sign-in (headed `--login` gate); day 9 in_progress preserves one attempt |
| 32 | 2026-10-06 | manual | **Extend LIVE run (no-ref):** user: "final video generate kro" + "ref images use nhi karni" → storyboard refs stripped (5 scenes), MCP chrome killed (profile free), `FLOW_APPROVE_CREDITS=1 ... --resume` launched; segment-1 generate clicked (free-credit accepted) → 900s timeout → manual assist; resume pending-guard refused re-pay (correct), editor unreachable ×2 → budget 3/3 | **ESCALATED** — day 7 failed, `clip_attempts[final.mp4]=3` durable gate, esc_relay pinged, loop FROZEN; manual_todo 16:57 |
| 31 | 2026-10-06 | manual | **Extend mode (single download):** user chose Recommended — use Flow's Extend to build one ~60s scene, download ONCE. Added env-gated `FLOW_EXTEND_MODE`/`FLOW_TARGET_DURATION_S`, pure seams (timecode parse, `extend_plan`, atomic `extend_progress.json` resume, `expected_final_s`), scene-editor UI (`_enter/_fill/_start/_exit_extend`, duration gate), `_resume_extend` reconcile, force money-gate per segment, `_generate_extend_chain` retry ledger; docs/env wired; `manual_todo.txt` untracked; legacy path untouched | PASS — 202 tests; 4 checker rounds (10+6+5 findings) → APPROVED; 0 credits spent |
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
| 25–20 | 2026-09-13/15 | manual | **Legacy hardening series (§9 compress):** A1 concurrency/state locks, A2 money-path gates, A3 unattended lifecycle/eval gate, B4 upload tombstones+clip_attempts, B5 planner parity+docs, production-readiness (fail-closed money gate, runbook, first CI green) | **PASS ×6** — 198 → 266 tests, checker-approved |

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

1. **Extend-mode supervised live run (NEW, beat 31):** release the Flow profile
   lock (Playwright MCP chrome holds `.runtime/flow-profile`), then
   `.venv/bin/python -m src.main --resume` (day 7, `.env` already has
   `FLOW_EXTEND_MODE=1`) — expect 8 generations ≈ 40-96 min, ONE `final.mp4`
   (64s ±5 gate), progress file updates after every paid step; user checks the
   final output. Money gate: no paid dialog expected (free credits) — if one
   appears the run hard-stops (supervised opt-in = `FLOW_APPROVE_CREDITS=1`).
2. **G5 supervised live run (the last legacy gate):** same command with
   `FLOW_EXTEND_MODE=0` if the legacy 6-clip path must be re-accepted;
   otherwise covered by task 1. Use `docs/PRODUCTION_RUNBOOK.md`.
3. **YouTube re-consent:** `.venv/bin/python -m src.main --youtube-auth` (token from
   2026-08-31 past Google testing-mode ~7d expiry).
4. ~~Decide stale PRs #5/#7/#8~~ **Resolved beat 36:** #5/#7/#8/#9 were all
   closed-unmerged with branches deleted; the redact leak was re-fixed in
   **PR #31** (checker APPROVED) — human: review/merge #31 (closes #6).
   **Issue #4 (wrap_text) still open:** branch `opencode/heartbeat-20261007-wraptext`
   deleted from origin — re-implement next beat (spec + 26-test precedent in the
   issue thread), then checker → PR. #3 is an exact duplicate of #4 (close when
   one lands); #1 is a stale test issue (close when convenient).
5. **rclone Drive sync** (laptop-off design): GitHub cron pulls clips/uploads/syncs back
   with the laptop off — still pending.
6. `_approve_credits` live verification on the credit dialog (part of G5 / extend chain).
7. Beat 6-12 follow-ups (verify-loop-state graduation) remain available.
8. **(2026-09-24, shared infra — owned by job loop Beat 116):** retired `checker` model
   `opencode/mimo-v2.5-free` was fixed to `opencode/mimo-v2.6-flash-free` in
   `.opencode/agent/checker.md`; this loop's `AGENTS.md` §11 lesson line was updated to
   match (consistency only, no video-loop behavior change). NOTE: `checker` subagent
   spawn hit "free tier only within OpenCode" this beat — checker ran as read-only
   `general` instead; verify `checker` agent next session.

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