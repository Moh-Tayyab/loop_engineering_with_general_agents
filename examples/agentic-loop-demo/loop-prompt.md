# Agentic Loop Contract — file-builder demo

opencode reads this at the START of every iteration and performs exactly ONE turn.

## Goal

Create the files `demo-state/1.txt`, `demo-state/2.txt`, `demo-state/3.txt`, in that
order. Each file's content is its own number: `1.txt` contains `1`, `2.txt` contains
`2`, `3.txt` contains `3`.

## Per-iteration action

Inspect the `demo-state/` directory. Create the lowest-numbered file that does not yet
exist. Create at most one file per iteration.

## Check / condition to test (each iteration)

List the files in `demo-state/`. Which of `1.txt`, `2.txt`, `3.txt` exist? Which are
missing?

## Stop condition

When `demo-state/3.txt` exists, the goal is complete. End your reply with exactly one
final line containing the token LOOP_DONE.

## Failure handling

If you cannot create a file (permission or error), end your reply with exactly one
final line containing the token LOOP_FAIL.

## Unattended

- [x] Yes — opencode runs fully autonomous; never stop to ask for approval.

## Constraints

- Work only toward the goal. Never invent new scope.
- Treat every iteration as independent; do not assume prior iterations succeeded.
- Create at most one file per iteration.
- If the goal is not yet met, end your reply with LOOP_CONTINUE.
- End your reply with exactly one token on its own final line:
  LOOP_CONTINUE, LOOP_DONE, or LOOP_FAIL.