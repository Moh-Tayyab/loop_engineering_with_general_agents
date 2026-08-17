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
- **Primary Agent:** OpenCode (GitHub Actions) — `opencode/deepseek-v4-flash-free`

## 2. Current Beat

- **Beat #:** 2
- **Date:** 2026-08-17
- **Trigger:** manual setup verification (issue #1)
- **Status:** Setup verified — outer loop design in progress

## 3. Beat Log

| Beat | Date | Trigger | Action | Result |
|------|------|---------|--------|--------|
| 1 | 2026-08-17 | manual | Repo init, workflow setup, auth fix, `/oc summarize` test | PASS — agent replied on issue #1 |
| 2 | 2026-08-17 | manual | Setup STATE.md, AGENTS.md, heartbeat cron, issue-to-PR trigger | In progress |

## 4. Budget & Stopping Conditions

**Hard ceiling (budget):**
- Max beats per run: **3** (a run that exceeds this must stop and report, never spin)
- Max cost per run: **$0.50 equivalent** (watch model spend; stop and report if exceeded)
- Max wall-clock per run: **15 minutes**

**Stopping conditions (loop exits immediately when ANY is true):**
1. Task goal reached and verified by the Checker.
2. Max beats / cost / time budget exceeded.
3. Irrecoverable error (build, test, or auth failure that cannot be fixed in-loop).
4. Requested action requires human decision or credentials not in secrets.
5. User or owner explicitly says stop.

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

## 6. Automation Triggers (Heartbeat)

Defined in `.github/workflows/opencode.yml`:

- `issue_comment` + `pull_request_review_comment` → on-demand beats (`/oc`, `/opencode`)
- `issues` (opened) → Autonomous Issue-to-PR Loop
- `pull_request` (opened/synchronize) → automated review
- `schedule` cron `0 0 * * *` → daily heartbeat beat (no comment; output to logs/PR)

## 7. Next Actionable Tasks

1. Complete outer loop design: Maker–Checker split enforced via AGENTS.md.
2. Test Autonomous Issue-to-PR Loop end-to-end (issue → branch → code → tests → PR).
3. Add a real practice project (small app) to loop on.
4. Review this STATE.md after beat 3 and tidy the format.
