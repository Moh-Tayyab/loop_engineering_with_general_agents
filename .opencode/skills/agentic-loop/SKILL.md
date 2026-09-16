---
name: agentic-loop
description: Create and run agentic loops for opencode — recurring autonomous tasks where opencode is the loop brain. Use when the user wants an autonomous recurring loop started on demand or by cron, where every check, condition test, and decision happens inside opencode (never in shell scripts). Keywords: agentic loop, watch loop, scheduled task, cron, unattended loop, interval loop, condition-based loop, recurring agent, autonomous agent loop.
---

# Agentic Loop

Build agentic loops: recurring autonomous tasks where **opencode is the loop brain**. A thin bash script
only schedules and re-triggers opencode; all checking, condition testing, acting, and deciding happens
inside opencode.

> Upstream: `abdullahsheikh01/opencode-agentic-loop-skill`. This copy is adapted and hardened for this
> repo: it adds a max-iteration budget guard, strict decision-token parsing, server-startup/failure
> handling, exit-code checks, and auth guidance. The core contract protocol (`LOOP_CONTINUE` /
> `LOOP_DONE` / `LOOP_FAIL`) is unchanged.

## What an agentic loop IS vs ISN'T

- **IS**: `opencode serve` starts on its own port, then a scheduler invokes `opencode run --attach <url>`
  once per iteration with a loop contract. opencode reads the contract, checks the condition, acts toward
  the goal, and replies with a decision token.
- **ISN'T**: a bash/Node/Python loop with hardcoded conditions, thresholds, or business logic. The shell
  script must stay a dumb scheduler. **We are making agentic loops, not code loops.**

## When to use

- A task must run on a cadence and decide for itself when it's done (polling, watching, incremental
  progress, recurring maintenance).
- The check, the goal, and the stop condition are easier to express in prose than in code.
- You want the loop's brain to be opencode (the same model/context), not hand-written logic.

Avoid for: anything a deterministic timer/cron already solves, or anything needing hard guarantees
(transactions, exact cadence). An LLM loop turn is best-effort — always pair it with a budget guard.

## Step 1 — Ask when the loop starts

Use the `question` tool. Ask:

1. **When does the loop start?** By a starting command now, or at a specific time (cron)?
2. If immediate: foreground or background (`nohup`)?
3. **Iteration cadence**: seconds/minutes/hours between turns (default `INTERVAL=300`).
4. **Max iterations**: how many turns before the driver force-stops (default `MAX_ITERATIONS=100`).
5. **Unattended?** Fully autonomous (no interactive approval) or may it ask?

## Step 2 — Capture the loop contract

Fill in `templates/loop-prompt.md` (in this skill dir) with:

- **Goal** — what the loop must eventually achieve.
- **Per-iteration action** — what opencode does each turn.
- **Check / condition** — tested each iteration by opencode.
- **Stop condition** — when true, reply `LOOP_DONE`.
- **Failure handling** — when an iteration can't continue, reply `LOOP_FAIL`.
- **Unattended** — yes/no.

Write the finished contract to the project root as `loop-prompt.md` (or your own name) and point the
driver at it.

## Step 3 — Write the loop

Create two files in the project directory:

1. **`loop-prompt.md`** — the loop contract (see Step 2).
2. **`agentic-loop.sh`** — scheduler driver. Copy `templates/driver.sh`, set `PORT`, `INTERVAL`,
   `MAX_ITERATIONS`, `LOOP_PROMPT`. The script must ONLY: start `opencode serve --port $PORT`, wait for
   readiness, then every `INTERVAL` seconds run `opencode run --attach $SERVER_URL --dir $PROJECT_DIR`
   with the iteration prompt below. **No business logic in the script.**

Iteration prompt:

```
You are driving an agentic loop. Read the loop contract at <loop-prompt.md>.
Perform ONE loop turn: run the check, act toward the goal, and evaluate the stop
condition. End your reply with exactly one decision token on its own final line:
LOOP_CONTINUE, LOOP_DONE, or LOOP_FAIL.
```

Driver token handling (see `templates/driver.sh` for exact logic):

- `LOOP_DONE` → stop, exit 0.
- `LOOP_FAIL` → stop, exit 1.
- `LOOP_CONTINUE` or no token → sleep `INTERVAL`, next iteration.
- `MAX_ITERATIONS` reached with no `LOOP_DONE` → stop, exit 1 (never spin forever).

## Step 4 — Schedule the start

- **Immediate**: `bash agentic-loop.sh` (foreground) or
  `nohup bash agentic-loop.sh > loop.log 2>&1 &` (background).
- **Cron**: one crontab line whose single command is the driver:
  ```
  M H * * * cd /path/to/project && /bin/bash agentic-loop.sh >> loop.log 2>&1
  ```
  Confirm with `crontab -l`; edit with `crontab -e`.

## Step 5 — Run and verify

- Confirm the server log shows `opencode server listening on http://127.0.0.1:<PORT>`.
- Confirm iteration 1 ran and returned a clean decision token.
- Point the user at `loop.log`.

## Security (non-negotiable for unattended loops)

- **Localhost only**: keep `--hostname 127.0.0.1` (the default). NEVER expose the server on a routable
  interface without a password — an unauthenticated opencode server is arbitrary code execution.
- **Auth**: if you must bind beyond localhost, set `OPENCODE_SERVER_PASSWORD` (or pass
  `--username/--password` to `opencode run --attach`) so the server is not unsecured.
- **Auto-approve is a big hammer**: prefer scoped `permission` rules in `opencode.json` over blanket
  `permission: allow` or `--auto`. For unattended runs, scope to the project dir and the specific
  commands the loop legitimately needs.
- **Secrets**: never put tokens/keys in the loop contract or iteration prompt. `loop.log` records model
  output verbatim — redact anything sensitive before sharing.

## Budget guard

`MAX_ITERATIONS` (default 100) is the driver-level backstop against an unsatisfiable stop condition.
Pair it with the budget in the owning loop's `STATE.md` §4 / that loop's `AGENTS.md` §3: the
contract's stop condition is the *goal* exit; `MAX_ITERATIONS` is the *safety* exit. A loop that
hits `MAX_ITERATIONS` should be treated as a loop-detection event (that loop's AGENTS.md §7) and
escalated, not silently re-run.

## Constraints checklist — verify before finishing

- [ ] Agentic loop, not code loop: all checks/conditions/decisions live in opencode prompts.
- [ ] `opencode serve --port $PORT --hostname 127.0.0.1` starts on its own port.
- [ ] Every check and condition test is performed by opencode via `opencode run --attach`.
- [ ] Driver has `MAX_ITERATIONS` set and the token parser handles a missing token safely.
- [ ] Unattended loops have scoped permissions + auth, and the contract says "never stop to ask".
- [ ] Cron scheduling invokes the driver as a single command.