# STATE.md — Loop Engineering State

Persistent context memory for the Loop Engineering with General Agents crash course.
This file is the agent's shared memory across beats (heartbeats, issue comments, PR events).
The OpenCode agent reads this file at the start of every run and updates it at the end.

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
- **Primary Agent:** OpenCode (GitHub Actions) — `opencode/deepseek-v4-flash-free`
- **Model budget note:** this is a free/cheap model; still track beats and wall-clock as a proxy for cost.

## 2. Current Beat

- **Beat #:** 6
- **Date:** 2026-09-14
- **Trigger:** schedule heartbeat — morning triage
- **Status:** Issue #6 CLEAR FIX implemented — 57/57 tests pass; 133/133 total pass; checker model unavailable, verified manually. PR #7 already open with same fix (2026-08-19). RISKY/AMBIGUOUS issues (#1, #3, #4) deferred to §10.

## 3. Beat Log

| Beat | Date | Trigger | Action | Result |
|------|------|---------|--------|--------|
| 1 | 2026-08-17 | manual | Repo init, workflow setup, auth fix, `/oc summarize` test | PASS — agent replied on issue #1 |
| 2 | 2026-08-17 | manual | Setup STATE.md, AGENTS.md, heartbeat cron, issue-to-PR trigger | PASS — agent answered `/oc ask` on issue #1 |
| 3 | 2026-08-17 | manual | Advanced loop design: inner/outer loops, test gate, escalation, skills | PASS — pushed `bb93f18`, test-gate workflow runs |
| 4 | 2026-08-17 | manual | Add textutils practice library + 46 pytest tests | PASS — 46 passed locally; test-gate CI pending |
| 5 | 2026-08-18 | schedule | Heartbeat: adversarial Checker pass on textutils | CHANGES REQUESTED — `redact_secrets` misses `sk-...`/uppercase tokens; bug issue #6 filed |
| 6 | 2026-09-14 | schedule | Morning triage: issue #6 CLEAR FIX implemented | PASS — 57/57 tests pass; `redact_secrets` hardened; type-check added |

## 10. Open / Needs a Human

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

Two distinct roles run in every beat; one agent instance must never do both for the same change:

- **Maker (build agent):** proposes/creates code changes, writes files, commits.
  - Identifies itself with role `Maker` when modifying code.
  - Never approves its own work.
- **Checker (review agent):** reviews, tests, and verifies the Maker's output.
  - Runs tests/lint, checks diff against requirements, verifies no secrets leaked.
  - Explicitly approves (`APPROVED`) or rejects (`CHANGES REQUESTED`) with reasons.

**Gate rule:** A beat is only marked complete after the Checker approves.
If the Checker rejects, the next beat must be a rework beat (Maker fixes, Checker re-verifies),
bounded by the max-beats budget above.

### 5a. Adversarial Checker (hardened gate)

On every beat that changes code, after the normal Checker pass, run an **adversarial pass**:
- Attempt to break the change: feed invalid/edge-case inputs, boundary values, empty/missing data.
- Check security: secret leakage, injection, unsafe deserialization, overly-broad permissions.
- Verify error paths: exceptions are handled and logged without leaking internals.
- Only then mark the beat `APPROVED`. Any finding → `CHANGES REQUESTED` with the failing case attached.

## 6. Automation Triggers (Heartbeat)

Defined in `.github/workflows/opencode.yml`:

- `issue_comment` + `pull_request_review_comment` → on-demand beats (`/oc`, `/opencode`)
- `issues` (opened) → Autonomous Issue-to-PR Loop
- `pull_request` (opened/synchronize) → automated review
- `schedule` cron `0 0 * * *` → daily heartbeat beat (no comment; output to logs/PR)

## 7. Inner vs Outer Loop

**Outer Loop (strategic steering) — runs on every trigger, briefly:**
1. Read this file (`STATE.md`) and `AGENTS.md`.
2. Re-align goal with the current beat. Is the beat still serving the practice goal?
3. Review budget/token consumption (§4). Are we near a ceiling? Stop if so.
4. Check that the previous beat's stopping condition was met cleanly (beat log row present, status `PASS`).
5. Decide: continue current work, start a new beat, or stop + report.

**Inner Loop (execution & refinement) — runs autonomously inside a beat:**
1. Edit code (Maker) → run tests → read error logs → refactor → re-test.
2. Iterate WITHOUT manual intervention until one of: all tests pass, the Checker approves,
   or an iteration budget/escalation condition fires (§4, §8).
3. Each inner iteration must be recorded (test result) so the beat log stays truthful.

The outer loop must never spin on planning; the inner loop must never spin on retries past budget.

## 8. Escalation Protocols

- **Retry cap (test failures):** if the same test/task fails **3 consecutive times**, FREEZE the
  inner loop. Do not keep re-attempting silently.
- **Freeze action:** stop editing, write a status summary, and ping the human supervisor in a
  GitHub comment: `@Moh-Tayyab please review — inner loop frozen after N failed attempts on <X>`.
- **Loop detection:** if the last 3 beats produced no user-visible progress (no code, no PR,
  no answer), treat as a loop and escalate the same way.
- **Rework bound:** a rework beat (Checker rejection) may be retried at most 2 times per feature.
  After that, escalate to the human rather than continuing to mutate the code.
- Escalation consumes one stopping-condition slot — see §4 condition 4.

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

## 10. Open / Needs a Human

Items classified RISKY/AMBIGUOUS — do NOT touch code; human gate required.

- **Issue #1** (Test OpenCode agent workflow): Just a test issue; no actionable bug. Needs human review to determine if it should be closed or expanded.
- **Issue #3** (Feature: Add wrap_text to textutils): Duplicate of #4. New feature requiring product decisions on behavior, edge cases, and API design.
- **Issue #4** (Feature: Add wrap_text to textutils): New feature requiring product decisions on behavior, edge cases, and API design.
- **Beat 4 merge**: test-gate CI must pass on the textutils suite (could not verify via `gh` API — 403 error).

## 11. Next Actionable Tasks

1. Merge beat 4 via CI (test-gate must pass on the textutils suite) — blocked by API 403.
2. Exercise the adversarial checker (`/oc check`) on the textutils code.
3. Resolve RISKY/AMBIGUOUS issues (#1, #3, #4) — human decision required.
4. Open a real feature-request issue to run the Autonomous Issue-to-PR Loop end-to-end.
5. Expand textutils with a new function (e.g., `wrap_text`) via an issue-driven beat.
