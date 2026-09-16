---
name: verify-loop-state
description: Check that the loop state is coherent after a beat — STATE.md current-beat matches the beat log, a beat-log row exists with a verdict, budget and escalation sections are intact, and no secrets leaked. Also propose rules-file lessons when a mistake repeats across beats (improvement hook). Use when the loop ends a beat, reports to an issue or PR, or any diff touches STATE.md or AGENTS.md.
allowed-tools: [read, grep, edit]
---

# Verify Loop State

You are the Checker, grading the loop's own bookkeeping. There is no root `STATE.md` and no
root `AGENTS.md` — every loop is fully self-contained. For EACH loop touched by the beat
(`video_generation_loop/`, `job_fetching_loop/`) read that loop's `STATE.md` + `AGENTS.md`
(the `AGENTS.md` carries ALL rules: budget §3, maker-checker §2/§6, escalation §7).
Confirm each rule for every loop spine that changed, then fix mechanical violations. Report
every violation as `file:line`, then fix it.

## Rules

1. **Current beat is truthful.** Each changed loop's `## 2. Current Beat` section lists a
   beat number, a date, a trigger, a status, and a verdict (`PASS` / `FAIL` / `ESCALATED`)
   that match the most recent row in that loop's beat log.
2. **Beat log has the latest row.** Each touched loop has a row in its `STATE.md` for the
   current beat with `Date`, `Trigger`, `Action`, and `Result` filled in. A completed beat
   without a row is a violation (that loop's AGENTS.md §2). Loop beats belong to the owner
   loop's own spine; there is no root STATE.md to log trainer-level beats in, so record
   them in the affected loop's STATE.md.
3. **Budget and escalation sections intact.** The loop `STATE.md` §4 (`Budget & Stopping
   Conditions`) and its §5–8 pointer to that loop's `AGENTS.md` escalation (§7) still exist
   with their ceilings and caps. Never silently delete these when compressing (that loop's
   AGENTS.md §7). Loop spines define their ceilings in their own `AGENTS.md` §3.
4. **Beat log not bloated.** Each loop's `STATE.md` beat log has at most 20 rows; otherwise
   compress per that spine's §9 (keep verdicts, drop detail, never drop budget/escalation)
   and note `compressed at <date>`.
5. **No secrets.** In any `STATE.md`, `AGENTS.md`, and any diff under review, there are no
   secret-looking strings: `sk-` / `sk-proj-`, `ghp_`, `gho_`, `AKIA`, `AIza`, `Bearer <token>`,
   or `api_key = "<value>"`. Referencing `${{ secrets.* }}` in workflows is fine; echoing or
   logging a resolved value is not.
6. **Report the verdict.** Reply with one line `APPROVED` or `CHANGES REQUESTED`, then the
   violations as bullets with `file:line` and the fix applied.
7. **Improvement hook (propose, never apply).** If the same failure pattern appears in ≥3
   consecutive beat-log rows (in any spine), propose adding a one-line durable lesson to that
   loop's `AGENTS.md` §11. Do NOT edit `AGENTS.md` yourself — report the proposed line with
   the evidence for the human gate.

## Fixing

Fix only mechanical violations yourself: add a missing beat-log row when the beat visibly
completed, correct a stale `Current Beat`, and redact accidental secrets by replacing the
value with `<redacted>`. If a violation needs judgment (e.g., a beat is genuinely incomplete,
or the change is a rules-file edit), leave it and say so in the report.

## Gate rule

A beat is only `PASS` after this check returns `APPROVED`. If it returns `CHANGES REQUESTED`,
the next beat must be a rework beat.
