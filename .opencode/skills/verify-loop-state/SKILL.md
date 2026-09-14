---
name: verify-loop-state
description: Check that the loop state is coherent after a beat — STATE.md current-beat matches the beat log, a beat-log row exists with a verdict, budget and escalation sections are intact, and no secrets leaked. Also propose rules-file lessons when a mistake repeats across beats (improvement hook). Use when the loop ends a beat, reports to an issue or PR, or any diff touches STATE.md or AGENTS.md.
allowed-tools: [read, grep, edit]
---

# Verify Loop State

You are the Checker, grading the loop's own bookkeeping. Read `STATE.md` and `AGENTS.md`
in the repo root, then confirm each rule. Report every violation as `file:line`, then fix it.

## Rules

1. **Current beat is truthful.** The `## 2. Current Beat` section lists a beat number,
   a date, a trigger, a status, and a verdict (`PASS` / `FAIL` / `ESCALATED`) that match
   the most recent row in the beat log.
2. **Beat log has the latest row.** There is a row for the current beat with `Date`,
   `Trigger`, `Action`, and `Result` filled in. A completed beat without a row is a
   violation (AGENTS.md §1).
3. **Budget and escalation sections intact.** The `Budget & Stopping Conditions` (§4) and
   `Escalation Protocols` (§8) sections still exist with their ceilings and caps. Never
   silently delete these when compressing (AGENTS.md §6).
4. **Beat log not bloated.** The beat log has at most 20 rows; otherwise compress per
   `STATE.md` §9 (keep verdicts, drop detail, never drop §4/§8) and note `compressed at <date>`.
5. **No secrets.** In `STATE.md`, `AGENTS.md`, and any diff under review, there are no
   secret-looking strings: `sk-` / `sk-proj-`, `ghp_`, `gho_`, `AKIA`, `AIza`, `Bearer <token>`,
   or `api_key = "<value>"`. Referencing `${{ secrets.* }}` in workflows is fine; echoing or
   logging a resolved value is not.
6. **Report the verdict.** Reply with one line `APPROVED` or `CHANGES REQUESTED`, then the
   violations as bullets with `file:line` and the fix applied.
7. **Improvement hook (propose, never apply).** If the same failure pattern appears in ≥3 consecutive
   beat-log rows (the same finding, test failure, or check result), propose adding a one-line durable
   lesson to `AGENTS.md` §10. Do NOT edit `AGENTS.md` yourself — report the proposed line with the
   evidence (which beats showed it) for the human gate. The rules file is the highest-leverage write
   in the system; changes to it need a person.

## Fixing

Fix only mechanical violations yourself: add a missing beat-log row when the beat visibly
completed, correct a stale `Current Beat`, and redact accidental secrets by replacing the
value with `<redacted>`. If a violation needs judgment (e.g., a beat is genuinely incomplete,
or the change is a rules-file edit), leave it and say so in the report.

## Gate rule

A beat is only `PASS` after this check returns `APPROVED`. If it returns `CHANGES REQUESTED`,
the next beat must be a rework beat.
