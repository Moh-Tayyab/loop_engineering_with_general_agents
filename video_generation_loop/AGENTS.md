# AGENTS.md — Video Generation Loop (project rules)

> Project rules for `video_generation_loop/`. Auto-loaded when running inside this dir.
> THIS file is self-contained: the full rules for this loop (shared loop-trainer rules AND
> project-specific rules) live here. THIS loop's spine is `video_generation_loop/STATE.md`.
> There is no root `STATE.md` or root `AGENTS.md` — every loop is its own spine pair.
> On every run: read THIS `STATE.md` → this file. Update THIS `STATE.md` last.

## 0. Spine Self-Containment

This loop is an independent project. It owns exactly one spine pair: `STATE.md` (progress,
read first) + `AGENTS.md` (rules, this file, read every run). There are no root rules files —
budget, maker-checker, escalation, lessons, and skills pointers are defined HERE, not one
level up. A task inside this loop touches only this loop's spine.

## 1. Project Context

- **What:** Daily 60-second encode-paced shorts: template/Gemini planners → storyboard →
  paid Google Flow generation → ffmpeg merge+eval → 4-platform post package → YouTube
  private scheduled upload.
- **Layout:** `src/` (main, config, state, flow_automation, gemini_web, planner_templates,
  video_upload, flow_clipper, merger, evaluator, poster), `tests/` (151 tests),
  `references/` (presenter images), `docs/PRODUCTION_RUNBOOK.md`, `.slc/` runtime state.
- **Runtime state lives in `.slc/`** (state.json, uploaded.json, clip_attempts) — never commit.

## 2. Non-Negotiable Rules

1. **Maker–Checker split:** The agent acts as Maker OR Checker in a single run, never both for the same change.
   - Maker: makes the change, then reports to Checker role.
   - Checker: reviews/verifies Maker output, runs tests, approves (`APPROVED`) or rejects (`CHANGES REQUESTED`).
2. **Never approve your own work.** Self-approval is forbidden; verification must be an explicit second pass.
3. **Budget & stopping conditions:** Enforced from §3 below. If max beats/cost/time is hit, stop and report —
   never keep spinning.
4. **No secrets:** Never commit or log tokens/keys. Never echo `${{ secrets.* }}` values.
   `.env` is gitignored; YouTube/Google tokens stay out of code and git.
5. **Beats are atomic:** One task per beat. Update the beat log with the outcome.
6. **Paid-account money guard:** generation is FAIL-CLOSED. `_approve_credits` requires an
   explicit first credit approval (or `FLOW_CREDITS_PREAPPROVED=1` opt-out). Never run an
   accidental/scrap/watchdog generation. Generate ONLY from the approved storyboard topic.
7. **Storyboard gate:** both planners go through `screen_storyboard`; unscreened output,
   timeout, parse fail, or unsafe topic → `strict` raises, `lenient` → template. Success
   is logged after the gate only.
8. **`--dry-run` / template-first:** production `.env` = `FLOW_PLANNER=template` and
   `FLOW_AUTO_FAILFAST=1`. Unattended runs must never hang on a planner or a modal.
9. **State lock + tombstones:** every `_run_real` step is under `state.locked()`;
   uploads use the `uploaded.json` tombstone (`pending→done|failed`). `PostCommitError`
   leaves `pending` so recover runs never double-post.
10. **Manual login gates:** `--login`/`--youtube-auth` are ONCE-OFF headed sign-ins. Never
    auto-drive a password flow. Presenter must go through Flow Characters
    (`_ensure_presenter_character`), never a raw file upload.

## 3. Budget & Stopping Conditions

**Hard ceiling (budget):**
- Max beats per run: **3** (a run that exceeds this must stop and report, never spin)
- Max cost per run: **$0.50 equivalent** (watch model spend; stop and report if exceeded)
- Max wall-clock per run: **15 minutes**
- Max inner-loop iterations per beat: **5** (edit→test→refactor spins beyond this must escalate, see §7)

**Stopping conditions (every run exits immediately when ANY is true):**
1. Task goal reached and verified by the Checker.
2. Max beats / cost / time / iteration budget exceeded.
3. Irrecoverable error (build, test, or auth failure that cannot be fixed in-loop).
4. Escalation trigger fired (see §7 — retry cap reached, human pinged).
5. Requested action requires human decision or credentials not in secrets.
6. User or owner explicitly says stop.

On every stop, append a row to THIS `STATE.md` beat log and update its "Current Beat".
Project-specific note: video beats cost REAL MONEY (PAID Google account); never run an
accidental watch/generation. Budget counter is shared with the job loop.

## 4. Recurring Instruction

Unless the comment/task says otherwise, default to: read context → make minimal change → verify (Maker then
Checker pass) → update THIS `STATE.md` → report concisely as a comment. Keep changes within
`video_generation_loop/` unless the task explicitly crosses projects.

## 5. Inner vs Outer Loop (operationalized)

**Outer Loop (strategic steering) — always run this first, briefly:**
1. Read THIS `STATE.md` §2, §4, §10. Confirm the current beat and goal are still aligned.
2. Check budget/stopping conditions (this file §3). Near a ceiling → stop and report.
3. Verify the previous beat's stopping condition was met cleanly (beat log row with `PASS`).
4. Decide: continue, start a new beat, or stop + report. Do not over-plan; this is minutes, not meetings.

**Inner Loop (execution & refinement) — run autonomously within a beat:**
1. Maker edits code → run tests → read error logs → refactor → re-test.
2. Keep iterating WITHOUT pausing for human input until: all tests pass AND Checker approves,
   or an iteration/escalation budget fires (this file §3, §7).
3. Record each inner iteration's test result so the beat log stays truthful.
4. Never spin: the outer loop never over-plans, the inner loop never retries past budget.

## 6. Hardened Maker–Checker Evaluation

1. **Automated Test Gate:** any code change must pass the CI test gate
   (`.github/workflows/test-gate.yml` — installs this loop's requirements and runs
   `python -m pytest -q video_generation_loop/tests`) before a PR is mergeable.
   A PR with failing tests is `CHANGES REQUESTED` by default.
2. **Adversarial Checker pass (after normal Checker):**
   - Attempt to BREAK the change: invalid inputs, edge cases, empty/null data, boundary values.
   - Security: secret leakage, injection, unsafe deserialization, overly broad permissions.
   - Error paths: exceptions handled and logged without leaking internals.
   - Verdict: `APPROVED` only if the change survives. Any finding → `CHANGES REQUESTED` with the failing case.

## 7. Escalation Protocols (loop detection & fallbacks)

- **Retry cap:** if the same test/task fails **3 consecutive times**, FREEZE the inner loop.
  Do not silently retry again.
- **Freeze action:** stop editing, summarize status, and ping the human in a GitHub comment:
  `@Moh-Tayyab please review — inner loop frozen after N failed attempts on <X>`.
- **Loop detection:** if the last 3 beats produced no user-visible progress, treat as a loop and escalate.
- **Rework bound:** a rejected rework beat may retry at most 2 times per feature, then escalate to the human.
- **State compression:** if THIS `STATE.md` beat log exceeds 20 rows or an entry is bloated,
  compress per this spine's §9 (keep verdicts, drop detail, never drop budget/escalation).

## 8. Skills & Rules File

Custom skills may live in the shared `.opencode/skills/`. If a skill is referenced in a task, load and follow it.
Relevant: `python-test-runner` (pytest/CI gate), `agentic-loop` (autonomous recurring loops —
thin scheduler + opencode brain via decision tokens; see `.opencode/skills/agentic-loop/SKILL.md`),
`verify-loop-state` (codified Checker: checks STATE.md/beat-log coherence + secret hygiene after every
beat), and `triage-issue` (morning-loop triage: classifies a CI failure or issue as CLEAR FIX vs
RISKY/AMBIGUOUS and drafts the fix plan).

## 9. Reporting Format

When the workflow replies to an issue/PR, keep reports short:
- What changed (one line)
- Verification result (`PASS` / `FAIL` / `CHANGES REQUESTED` / `ESCALATED`)
- Next beat suggestion

## 10. Spine — State Between Runs

The model forgets everything between runs; the repo does not. This loop has a spine pair:
**AGENTS.md (rules, this file — the front of the diary)* and **STATE.md (progress — the back
of the diary)**. Read first to restore context, update last with the beat's outcome, every run.

- **AGENTS.md = the rules file.** Durable habits and lessons, read on every run. Keep it short:
  every line is paid on every beat. When this loop keeps making the same mistake, fix it here —
  write the lesson once so every future run benefits — not with a one-off prompt.
- **STATE.md = the progress file.** Checkpoints: current beat, beat log, budget, next tasks.
  Read first to restore context, update last with the beat's outcome. Without it, every run is
  a stranger at the start line.

Improvement habit: repeated mistakes are the signal to update the rules file. One mistake is noise; the
same mistake three times is a missing lesson. Propose the lesson through the `verify-loop-state` skill and
let a human approve — the rules file is the highest-leverage write in the system.

## 11. Lessons Learned

Durable lessons from past beats (added via the §10 habit; keep each to one line):

- **Use `opencode/*` free models for cheap/read-only subagents.** `anthropic/claude-haiku-4-5-20251001`
  404s in this env; the checker runs on `opencode/mimo-v2.6-flash-free` (updated from `mimo-v2.5-free` 2026-09-24, that model id retired).
- **A read-only checker must deny `edit` AND `bash` entirely.** A bash allowlist of "read-only" command
  patterns is bypassable (`pytest; rm -rf x`, `git diff > out.txt`); pass the diff and test results to it.
- **Keep the nesting guard.** `subagent_depth: 1` + global `permission.task: deny`; grant `task` explicitly
  only where a spawn is required (build and maker→checker).
- **Write STATE.md beat-log rows tight (≤ ~400 chars, this file §9).** Bloated rows get
  auto-compressed by `verify-loop-state`; write them lean the first time.
- **One spine per loop, no root files.** Fully self-contained loop rules: each loop owns one
  `STATE.md` + one `AGENTS.md`; the root keeps only automation and shared skills.
- Flow UI is fragile and changes often — drive it visually via the Playwright MCP browser
  against a live snapshot; confirm selectors before spending generation credits.
- `evaluate_final` requires video+audio streams and ~9:16 (0.5625±0.03) when ffprobe is
  present; pass-on-size is a fallback, not the contract.
- A `clip_attempts` ledger + 2× re-download (`_ensure_real_video`) prevents crash loops
  from re-burning a capped clip; never re-generate a clip that was already downloaded.
- Unattended = template planner only; gemini-web hangs without a human at the planner gate.