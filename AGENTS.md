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

## 4. Skills & Rules File

Custom skills may live in `.opencode/skills/`. If a skill is referenced in a task, load and follow it.

## 5. Reporting Format

When the workflow replies to an issue/PR, keep reports short:
- What changed (one line)
- Verification result (`PASS` / `FAIL` / `CHANGES REQUESTED`)
- Next beat suggestion
