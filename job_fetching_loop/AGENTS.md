# AGENTS.md — Job Fetching Loop (project rules)

> Project rules for `job_fetching_loop/`. Auto-loaded when running inside this dir.
> THIS file is self-contained: the full rules for this loop (shared loop-trainer rules AND
> project-specific rules) live here. THIS loop's spine is `job_fetching_loop/STATE.md`.
> There is no root `STATE.md` or root `AGENTS.md` — every loop is its own spine pair.
> On every run: read THIS `STATE.md` → this file. Update THIS `STATE.md` last.

## 0. Spine Self-Containment

This loop is an independent project. It owns exactly one spine pair: `STATE.md` (progress,
read first) + `AGENTS.md` (rules, this file, read every run). There are no root rules files —
budget, maker-checker, escalation, lessons, and skills pointers are defined HERE, not one
level up. A task inside this loop touches only this loop's spine.

## 1. Project Context

- **What:** Autonomous AI/ML remote-job scraper: 7 sources → dedup → normalize →
  atomic store → Telegram/WhatsApp. Runs by cron schedule (daily/weekly windows).
- **Layout:** `src/` (DAG: main orchestrator, config, state, circuit_breaker, dedup,
  digest, browser, notifier, models, scrapers/), `tests/` (284 tests), `jobs output/`,
  `.slc/` runtime state, `.env` (gitignored — secrets!), `.env.example` (template).
- **Runtime state lives in `.slc/`** (state.json, seen.json, dead_letter.json) —
  never commit it.

## 2. Non-Negotiable Rules

1. **Maker–Checker split:** The agent acts as Maker OR Checker in a single run, never both for the same change.
   - Maker: makes the change, then reports to Checker role.
   - Checker: reviews/verifies Maker output, runs tests, approves (`APPROVED`) or rejects (`CHANGES REQUESTED`).
2. **Never approve your own work.** Self-approval is forbidden; verification must be an explicit second pass.
3. **Budget & stopping conditions:** Enforced from §3 below. If max beats/cost/time is hit, stop and report —
   never keep spinning.
4. **No secrets:** Never commit or log tokens/keys. Never echo `${{ secrets.* }}` values.
   The Telegram token lives only in `.env`; `--list-sources`/`--stats`/logs must never echo
   it; `.env.example` uses placeholders.
5. **Beats are atomic:** One task per beat. Update the beat log with the outcome.
6. **`--dry-run` is sacred:** no state writes, no output files, no notifications.
   A dry-run that mutates `.slc/` or `output/` is a bug, not a feature.
7. **State lock is required for any state.json write.** All scrapes run under
   `state.locked(timeout_s=LOCK_TIMEOUT_S)`. Never write `.slc/*.json` by hand from a beat.
8. **Per-channel notification dedup keys:** `daily:telegram`, `daily:whatsapp`,
   `weekly:telegram`, `weekly:whatsapp` — always UTC date strings. Never reuse the
   local-date bug (Beat 27 finding).
9. **Notifications are delivered OUTSIDE the state lock** via `_guarded_deliver`
   (check→send→re-lock-and-mark). Never hold the lock during a network send.
10. **Fail-closed on scrapers:** network/CAPTCHA failures → `record_failure` → circuit
    opens after threshold; never retry past `CIRCUIT_BREAKER_THRESHOLD`. seen-hash store
    TTL-evicts after `DEDUP_WINDOW_DAYS`.

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
Project-specific note: a job-loop beat consumes the shared budget counter; a job loop scrape
also spends wall-clock on live network sources.

## 4. Recurring Instruction

Unless the comment/task says otherwise, default to: read context → make minimal change → verify (Maker then
Checker pass) → update THIS `STATE.md` → report concisely as a comment. Keep changes within
`job_fetching_loop/` unless the task explicitly crosses projects.

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
   (`.github/workflows/test-gate.yml` runs `pytest` in an isolated
   `working-directory: job_fetching_loop` step) before a PR is mergeable.
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

Custom skills live in the shared `.opencode/skills/`. If a skill is referenced in a task, load
and follow it. Relevant: `python-test-runner` (pytest/CI gate), `agentic-loop` (autonomous
recurring loops — thin scheduler + opencode brain via decision tokens),
`verify-loop-state` (codified Checker: STATE.md/beat-log coherence + secret hygiene after every
beat), `triage-issue` (morning-loop triage: CLEAR FIX vs RISKY/AMBIGUOUS + fix plan).

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
  404s in this env; the checker runs on `opencode/mimo-v2.5-free`.
- **A read-only checker must deny `edit` AND `bash` entirely.** A bash allowlist of "read-only" command
  patterns is bypassable (`pytest; rm -rf x`, `git diff > out.txt`); pass the diff and test results to it.
- **Keep the nesting guard.** `subagent_depth: 1` + global `permission.task: deny`; grant `task` explicitly
  only where a spawn is required (build and maker→checker).
- **Write STATE.md beat-log rows tight (≤ ~400 chars, this file §9).** Bloated rows get
  auto-compressed by `verify-loop-state`; write them lean the first time.
- **One spine per loop, no root files.** Fully self-contained loop rules: each loop owns one
  `STATE.md` + one `AGENTS.md`; the root keeps only automation and shared skills.
- Clock/eval: `normalize_raw` must normalize (title/company through `normalize_text`);
  the old test asserting `title_normalized == title` was asserting the bug (updated Beat 27).
- `mark_notified` prunes `v < today`; keep user-date strings out — always UTC.
- Two concurrent crons → one wins the FileLock, the loser logs `[lock]` and exits 0.
  That's correct behavior, not an error.
- **On-site/Hybrid guard:** `is_worldwide_remote` must strictly reject physical city postings in Pakistan/foreign hubs unless an explicit remote/wfh marker is present; never fake `(Remote)` in scrapers. Drop LinkedIn redirects (`expired_jd_redirect`) as expired.