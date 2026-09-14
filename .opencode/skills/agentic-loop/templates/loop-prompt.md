# Agentic Loop Contract

opencode reads this file at the START of every iteration and performs exactly ONE
loop turn per invocation. Fill in every section before running.

## Goal

What the loop must eventually achieve.

## Per-iteration action

What opencode should do on every iteration.

## Check / condition to test (each iteration)

What opencode must verify before and/or after acting. The condition is tested by
opencode, never by the shell script.

## Stop condition

The condition that ends the loop. When true, end your reply with exactly one final
line containing the token LOOP_DONE.

## Failure handling

What opencode should do if an iteration errors. If the loop cannot continue, end
your reply with exactly one final line containing the token LOOP_FAIL.

## Unattended

- [ ] Yes — opencode runs fully autonomous; never stop to ask for approval.
- [ ] No — opencode may stop and ask for input.

## Constraints

- Work only toward the goal. Never invent new scope.
- Treat every iteration as independent; do not assume prior iterations succeeded.
- End your reply with exactly one token on its own final line:
  LOOP_CONTINUE, LOOP_DONE, or LOOP_FAIL.