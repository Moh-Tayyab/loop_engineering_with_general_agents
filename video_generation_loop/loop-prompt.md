# Agentic Loop Contract — Daily AI-Video Production

opencode reads this file at the START of every iteration and performs exactly ONE
loop turn per invocation. The scheduler (`agentic-loop.sh`) only re-triggers opencode;
ALL checking, condition-testing, and deciding happens here in opencode.

## Goal

Produce today's 60-second YouTube Short from the approved presenter-style pipeline,
fully autonomously while the laptop is on, then hand the merged result to the upload
step. Repeat day over day, picking a NEW topic from the course queue each time, until
the queue is exhausted.

## Per-iteration action

One loop turn = one day of production. In order:

1. Read `STATE.md` (repo root) + `video_generation_loop/STATE-local.md` (if present) to
   restore loop context. Read `video_generation_loop/course/topics.json` (the topic queue)
   and `video_generation_loop/.slc/state.json` (durable day/topic state).
2. Decide today's topic: if a day is `in_progress`, resume it; else pick the next pending
   topic via the state logic (first topic not done / in-progress / blocked / retry-exhausted).
   NEVER invent a topic — only topics in `topics.json`.
3. Build the presenter-style storyboard for that topic (6 scenes, 10s each, 9:16, Veo 3.1
   Lite). Mix: presenter scenes (young man from a `references/ref_*.png` image built into a
   Flow **Character**) + pure-visual scenes. Use the user-approved presenter prompt TEMPLATE
   (STATE.md §11). Write to `output/day_XX/storyboard.json`.
4. For each of the 6 scenes, drive real Google Flow via the Playwright automation
   (`python -m src.main` `--day` etc. OR the underlying `flow_automation`): enter workspace,
   fill the scene prompt, set Video + Veo 3.1 Lite + 10s + 9:16, click Create, approve the
   credit dialog, wait for finish, download the resolved MP4 to `output/day_XX/clips/clip_NN.mp4`.
   For presenter scenes, build a Flow **Character** from the reference image first
   (`_ensure_presenter_character`: Add Media -> Upload media -> Characters -> Add from
   Project -> Add to Character -> Done) so Veo uses the young man as a consistent presenter.
5. Merge the 6 clips with ffmpeg → `output/day_XX/final.mp4`. Build the 4-platform post
   package (captions). Update `video_generation_loop/.slc/state.json` (mark clips done,
   then finish_day ok).
6. Trigger the upload (`python -m src.main --upload-today`, idempotent via
   `.runtime/uploaded.json`) so the video is scheduled private + publishAt.
7. Update STATE.md beat log (one tight row, ≤ ~400 chars) + current beat. Mark the topic done.
8. End with exactly one decision token.

## Check / condition to test (each iteration)

- Is the laptop online and the Flow browser profile signed in
  (`video_generation_loop/.runtime/flow-profile` has Google session cookies)? If not
  signed in, one `--login` once-off manual gate is required — signal that and
  `LOOP_FAIL` (or `LOOP_DONE` if the queue is empty) rather than burning credits on a
  logged-out half-broken run.
- Has today's day already been fully produced and uploaded (idempotency via
  `.runtime/uploaded.json` + `state.json`)? Skip if done.
- Queue exhausted? All topics done/blocked → `LOOP_DONE`.
- A day failed 3 consecutive attempts (retry cap) → mark failed, `LOOP_CONTINUE` to the
  next topic (do not spin on the same failing topic).

## Stop condition

All available topics in `topics.json` are done or blocked → reply `LOOP_DONE`. (The
scheduler also force-stops at `MAX_ITERATIONS` as a safety backstop.)

## Failure handling

- Flow generation or download fails: retry the clip up to the retry cap; if a day hits 3
  failed attempts, mark the day failed, log the reason, and move to the next topic
  (`LOOP_CONTINUE`).
- Credit-approval / paid-generation guard: if you are ever unsure the generation is
  against the approved storyboard (wrong topic, model not Veo 3.1 Lite, presenter image
  wrong), STOP and reply `LOOP_FAIL` WITHOUT generating — never burn paid credits on a
  wrong probe.
- Foot-/budget guard from STATE.md §4: max beats, cost, wall-clock. If hit → `LOOP_FAIL`.

## Unattended

- [X] Yes — opencode runs fully autonomous; never stop to ask for approval.
  BUT respect the paid-account guard above: only generate from an approved storyboard,
  Veo 3.1 Lite, and the correct per-scene reference image.

## Constraints

- Work only toward the goal. Never invent new scope.
- Treat every iteration as independent; do not assume prior iterations succeeded.
- Video generation costs real money (paid Google account) — never generate a
  throwaway/probe video; every clip must come from the approved storyboard topic.
- End your reply with exactly one token on its own final line:
  LOOP_CONTINUE, LOOP_DONE, or LOOP_FAIL.
