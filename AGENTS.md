# AGENTS.md — Agent Instructions (auto-loaded every run)

This repo is a **Loop Engineering with General Agents** practice environment.
The OpenCode agent runs as an automated GitHub Actions workflow. Follow these rules on every run.

## 1. Loop Context

- Always read `STATE.md` first to restore context (current beat, budget, stopping conditions, beat log).
- Update `STATE.md` at the end of every run (beat log row + current beat).
- This is a training repo: keep changes small, correct, and well-documented.

## 2. Non-Negotiable Rules

1. **Maker–Checker split:** The agent acts as Maker OR Checker in a single run, never both for the same change.
   - Maker: makes the change, then reports to Checker role.
   - Checker: reviews/verifies Maker output, runs tests, approves (`APPROVED`) or rejects (`CHANGES REQUESTED`).
2. **Never approve your own work.** Self-approval is forbidden; verification must be an explicit second pass.
3. **Budget & stopping conditions:** Enforced from `STATE.md` §4. If max beats/cost/time is hit, stop and report —
   never keep spinning.
4. **No secrets:** Never commit or log tokens/keys. Never echo `${{ secrets.* }}` values.
5. **Beats are atomic:** One task per beat. Update the beat log with the outcome.

## 3. Recurring Instruction

Unless the comment/task says otherwise, default to: read context → make minimal change → verify (Maker then
Checker pass) → update `STATE.md` → report concisely as a comment.

## 4. Inner vs Outer Loop (operationalized)

**Outer Loop (strategic steering) — always run this first, briefly:**
1. Read `STATE.md` §2, §4, §10. Confirm the current beat and goal are still aligned.
2. Check budget/stopping conditions (STATE.md §4). Near a ceiling → stop and report.
3. Verify the previous beat's stopping condition was met cleanly (beat log row with `PASS`).
4. Decide: continue, start a new beat, or stop + report. Do not over-plan; this is minutes, not meetings.

**Inner Loop (execution & refinement) — run autonomously within a beat:**
1. Maker edits code → run tests → read error logs → refactor → re-test.
2. Keep iterating WITHOUT pausing for human input until: all tests pass AND Checker approves,
   or an iteration/escalation budget fires (STATE.md §4, §8).
3. Record each inner iteration's test result so the beat log stays truthful.
4. Never spin: the outer loop never over-plans, the inner loop never retries past budget.

## 5. Hardened Maker–Checker Evaluation

1. **Automated Test Gate:** any code change must pass the CI test gate
   (`.github/workflows/test-gate.yml` — runs `pytest`/`npm test` if present) before a PR is mergeable.
   - If no test suite exists yet, note that in the PR description and add tests in the same PR when feasible.
   - A PR with failing tests is `CHANGES REQUESTED` by default.
2. **Adversarial Checker pass (after normal Checker):**
   - Attempt to BREAK the change: invalid inputs, edge cases, empty/null data, boundary values.
   - Security: secret leakage, injection, unsafe deserialization, overly broad permissions.
   - Error paths: exceptions handled and logged without leaking internals.
   - Verdict: `APPROVED` only if the change survives. Any finding → `CHANGES REQUESTED` with the failing case.

## 6. Escalation Protocols (loop detection & fallbacks)

- **Retry cap:** if the same test/task fails **3 consecutive times**, FREEZE the inner loop.
  Do not silently retry again.
- **Freeze action:** stop editing, summarize status, and ping the human in a GitHub comment:
  `@Moh-Tayyab please review — inner loop frozen after N failed attempts on <X>`.
- **Loop detection:** if the last 3 beats produced no user-visible progress, treat as a loop and escalate.
- **Rework bound:** a rejected rework beat may retry at most 2 times per feature, then escalate to the human.
- **State compression:** if `STATE.md` beat log exceeds 20 rows or an entry is bloated, compress per
  `STATE.md` §9 (keep verdicts, drop detail, never drop budget/escalation sections).

## 7. Skills & Rules File

Custom skills may live in `.opencode/skills/`. If a skill is referenced in a task, load and follow it.
Available skills: `python-test-runner` (pytest/CI gate), `agentic-loop` (autonomous recurring loops —
thin scheduler + opencode brain via decision tokens; see `.opencode/skills/agentic-loop/SKILL.md`),
`verify-loop-state` (codified Checker: checks STATE.md/beat-log coherence + secret hygiene after every
beat), and `triage-issue` (morning-loop triage: classifies a CI failure or issue as CLEAR FIX vs
RISKY/AMBIGUOUS and drafts the fix plan).

## 8. Reporting Format

When the workflow replies to an issue/PR, keep reports short:
- What changed (one line)
- Verification result (`PASS` / `FAIL` / `CHANGES REQUESTED` / `ESCALATED`)
- Next beat suggestion

## 9. Spine — State Between Runs

The model forgets everything between runs; the repo does not. Two files are the spine. Read them first
and update them last, every run:

- **AGENTS.md (this file) = the rules file — the front of the diary.** Durable habits and lessons, read
  on every run. Keep it short: every line is paid on every beat. When the loop keeps making the same
  mistake, fix it here — write the lesson once so every future run benefits — not with a one-off prompt.
- **STATE.md = the progress file — the back of the diary.** Checkpoints: current beat, beat log, budget,
  next tasks. Read first to restore context (§1), update last with the beat's outcome. Without it, every
  run is a stranger at the start line.

Improvement habit: repeated mistakes are the signal to update the rules file. One mistake is noise; the
same mistake three times is a missing lesson. Propose the lesson through the `verify-loop-state` skill and
let a human approve — the rules file is the highest-leverage write in the system.

## 10. Lessons Learned

Durable lessons from past beats (added via the §9 habit; keep each to one line):

- **Use `opencode/*` free models for cheap/read-only subagents.** `anthropic/claude-haiku-4-5-20251001`
  404s in this env; the checker runs on `opencode/hy3-free`.
- **A read-only checker must deny `edit` AND `bash` entirely.** A bash allowlist of "read-only" command
  patterns is bypassable (`pytest; rm -rf x`, `git diff > out.txt`); pass the diff and test results to it.
- **Keep the nesting guard.** `subagent_depth: 1` + global `permission.task: deny`; grant `task` explicitly
  only where a spawn is required (build and maker→checker).
- **Write STATE.md beat-log rows tight (≤ ~400 chars, §9).** Bloated rows get auto-compressed by
  `verify-loop-state`; write them lean the first time.
- **Flow UI is fragile and changes often.** Drive it visually via the Playwright MCP browser
  (project `.opencode/opencode.json`) against a live snapshot, not blind DOM probes — confirm
  selectors first, then spend generation credits.
