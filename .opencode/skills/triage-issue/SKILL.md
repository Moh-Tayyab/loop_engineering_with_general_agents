---
name: triage-issue
description: Classify a CI failure or GitHub issue as CLEAR FIX or RISKY/AMBIGUOUS and, for clear fixes, draft a minimal fix plan. Use when the weekday heartbeat picks up a failed CI run or an open issue.
allowed-tools: [read, grep, edit, bash]
---

# Triage Issue

You are the triage desk of the morning loop. For each CI failure or open issue,
decide: is this a CLEAR FIX the loop can ship, or RISKY/AMBIGUOUS for a human?

## Steps

1. **Read the item.** For a CI failure: `gh run view <run-id> --log-failed` to
   get the failing test/log. For an issue: read the body and any linked code.
2. **Find the owning spine.** Route by scope — a failure in `video_generation_loop/` owns
   that loop; `job_fetching_loop/` owns the job loop; a trainer-infra failure (workflows,
   `.opencode/` skills, subagents) touches whichever loop the change lands in. There are no
   root rules files: every loop is fully self-contained (`STATE.md` + `AGENTS.md`). Read the
   owning loop's `STATE.md` + `AGENTS.md` before touching anything.
3. **Understand the code.** Read the relevant files around the failure or
   feature. Reproduce locally if the failure is deterministic (that loop's
   `pytest`, per its AGENTS.md §4).
4. **Classify** with one verdict:

   - `CLEAR FIX` — well-scoped, minimal, low-risk (a broken assertion, a
     missing edge case, a typo). The change is unambiguous and covered by the
     existing test suite.
   - `RISKY/AMBIGUOUS` — touches core paths, changes an output format, needs a
     product decision, missing requirements, or the fix is not obviously
     correct. These go to the human gate.

5. **For CLEAR FIX, draft the plan** (do NOT implement yet — the Maker does):
   - Files to change, with line references.
   - The exact minimal change.
   - The tests that prove it (run inside the owning loop).
   - The `checker` subagent handoff: after implementing, grade with `@checker`
     (read-only) and open a PR only on APPROVED.

6. **For RISKY/AMBIGUOUS**, write the item under the owning loop's `STATE.md` §10
   (Open / needs a human) with: the failure evidence, what is blocking, and the
   question a human needs to answer. Do NOT touch code.

## Gate rule

A clear-fix plan is only shippable after the checker subagent approves the
implemented change. Anything risky stays in §10 until a human picks it up.
Rules-file lessons are proposed through `verify-loop-state`, never applied here —
Do NOT edit `AGENTS.md` yourself; that is a human-gate change.
