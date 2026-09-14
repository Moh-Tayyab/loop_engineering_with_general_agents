# Video Generation Loop — Usage

Autonomous daily 1-minute short-form video pipeline. `Agentic Coding Crash
Course` (15 concepts) → storyboard → Google Flow clips → merge → post package
for TikTok / Instagram Reels / Facebook / YouTube Shorts.

## 1. The SLC spec-first step

> Note: `requirement.md` at the project root is the SLC input. Full docs:
> `https://slc.wewiselabs.com/docs`

1. You are already connected to an LLM of your choice. We use **Gemini**
   (`https://slc.wewiselabs.com/docs#connect`).
2. Run the guided flow in this folder:

   ```bash
   npx @wewiselabs/slc
   ```

   It finds `requirement.md`, scrutinizes the idea, then generates a validated
   `spec/` tree. Create the DB/hosting steps can be skipped (this project is
   local-first).
3. Hand-off line it prints tells your coding agent where to start. Our pipelined
   code already lives in `src/`; regenerate/validate with:

   ```bash
   npx @wewiselabs/slc doctor
   ```

## 2. Install

```bash
# system deps (ffmpeg required for merging)
sudo apt install -y ffmpeg

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Google Flow automation needs a real Chromium for Playwright:
.venv/bin/python -m playwright install chromium

cp .env.example .env   # no API key needed — template planner is the default
```

`imageio-ffmpeg` is included as a pip fallback if system ffmpeg is missing.

## 3. Give the agent access to your Google PRO account (once)

The pipeline does **not** use your password or API keys to reach Google. Access
is granted through **your own sign-in**, kept in a persistent browser profile:

```bash
.venv/bin/python -m src.main --login
```

A headed browser opens Google Flow. **You** sign in with the Google account that
holds your PRO plan (password + 2FA stay on your screen). Close the window; the
signed-in session is stored at `.runtime/flow-profile/` and every later run
reuses it. The agent never sees, asks for, or stores your credentials.

Security rules (treat the profile like a password file):

- Never type your password / 2FA code into a prompt, code, or file.
- `.runtime/`, `.env`, `.slc/` are gitignored — nothing account-related goes to
  git.
- Keep `.runtime/flow-profile/` on your own machine; don't copy it to a shared
  server/CI runner. If you ever automate on a remote box, sign in there once
  yourself (or use a separate, least-privilege Google account).
- To revoke access: sign out of Flow in that profile (or delete
  `.runtime/flow-profile/`) and re-run `--login` when you want it back.

## 4. Daily run

```bash
# preview today's storyboard + captions (no API, no browser, no credits)
.venv/bin/python -m src.main --dry-run

# the real thing: storyboard script + Google Flow clips (your PRO session) + merge
.venv/bin/python -m src.main

# force a specific topic / resume an interrupted day
.venv/bin/python -m src.main --topic "MCP"
.venv/bin/python -m src.main --resume

# inspect the queue
.venv/bin/python -m src.main --list-topics

# (optional) watch the browser while it works
FLOW_HEADLESS=0 .venv/bin/python -m src.main
```

> **Storyboard planners:** default is the offline **template** planner — a
> deterministic 6-scene script built from `course/topics.json`, no API, no key,
> no cost. AI options (opt-in):
> - `FLOW_PLANNER=gemini` + `GEMINI_API_KEY` — Gemini API (OpenAI-compatible);
>   `--strict` makes failures fatal instead of falling back to template.
> - `FLOW_PLANNER=gemini-web` (or `--gemini-web`) — browser on gemini.google.com
>   using the signed-in profile (no API key).
>
> **Planner parity guard:** whatever an LLM planner produces, its hook, scene
> prompts, voiceovers and captions are run through the same secret/prompt-
> injection screen before they can reach paid Flow prompts or the YouTube SEO
> doc. Unscreened output either fails (`--strict`) or degrades to the
> deterministic template — never a paid generation with unscreened content.

Outputs land in `output/day_NN/`:
- `storyboard.json` — the 6-scene plan (template or Gemini)
- `clips/clip_01..06.mp4` — raw Flow downloads (reused on resume)
- `final.mp4` — merged ~60s video
- `caption_{tiktok,instagram_reels,facebook,youtube_shorts}.txt` — ready captions
- `post.json` — machine-readable package manifest

## 5. YouTube: OAuth + scheduled upload (Data API v3)

The GitHub Actions cipher posts today's video as a **PRIVATE scheduled upload** —
YouTube auto-publishes it at `publishAt` (no browser needed on the runner).

**One-time setup (you, once):**

1. Google Cloud Console → new project → enable **YouTube Data API v3**.
2. OAuth consent screen → External → add your email as a **test user**.
3. Credentials → **OAuth client ID** → *Desktop app* → download JSON →
   save as `.runtime/client_secret.json` (gitignored).
4. Consent + save a refresh token:

   ```bash
   .venv/bin/python -m src.main --youtube-auth
   ```

   A browser opens; sign into the channel's Google account and **Allow**.
   The refresh token is stored at `.runtime/youtube_token.json` (env
   `YOUTUBE_TOKEN_FILE` overrides it — used to point CI at an injected
   secrets file). Scope is only `youtube.upload`.

**Daily upload** (what the cron runs):

```bash
.venv/bin/python -m src.main --upload-today
```

- Uploads the newest `output/day_*/final.mp4`, sanitize SEO (title ≤70 chars,
  tags, category Education), schedule private with `publishAt` from
  `YOUTUBE_PUBLISH_TIME` (default 18:00) in `YOUTUBE_PUBLISH_TZ`
  (default Asia/Karachi). A thumbnail (`thumbnail.png/jpg`) in the day folder
  is auto-attached.
- Idempotent: already-uploaded days are skipped via `.runtime/uploaded.json`.
  The tombstone is 3-state: `pending` (network call was made, no confirmation
  yet) / `done` / `failed`. A `pending` day left by a crash mid-upload refuses
  to re-post on the next run — run `--upload-today` once more after the backend
  responds, or manually delete the row from `.runtime/uploaded.json` if you
  verified no clip was actually posted. Only *pre-commit* failures (nothing
  reached YouTube) are retried automatically.
- Google may expire testing-mode refresh tokens after ~7 days; re-run
  `--youtube-auth` to re-consent.

## 6. Google Flow + Playwright (browser automation)

- The launcher uses **real system Chrome** (`channel="chrome"`) when available —
  Playwright's bundled Chromium gets blocked by Google with "browser or app may
  not be secure". Bundled Chromium is only a fallback when no system Chrome is
  installed.
- Chromium/Chrome opens with the persistent profile at `.runtime/flow-profile/`.
  Use `--login` (§3) to sign into your Google account there once; every run
  reuses that session.
- Never auto-login — if the profile is signed out you see a hint, not a crash.
- Flow's DOM changes over time. `src/flow_automation.py` uses defensive
  selector hints and **degrades to MANUAL ASSIST** when it can't find a control:
  it prints the exact prompt and waits for you to paste + save the clip. The
  run continues from there — nothing is thrown away.
- **Fail-fast (unattended runs):** that manual-assist wait is only for an
  *interactive* terminal. With `FLOW_AUTO_FAILFAST=1` (or headless, or a
  non-TTY stdin like cron), a blocking step FAILS loudly instead — the day
  stops at its first blocker, the step is queued in `manual_todo.txt`, and
  nothing is burned past it.
- `FLOW_HEADLESS=0` shows the browser while it works (helpful for diagnosis).
- If there is no system Chrome, point `FLOW_PROFILE_DIR` at your real Chrome
  profile or install `chromium`/`google-chrome` so Playwright can use the
  `chrome` channel.

## 7. Scheduling

Add to cron (daily 18:00 PKT = 13:00 UTC):

```cron
0 13 * * * cd /path/to/video_generation_loop && .venv/bin/python -m src.main >> .runtime/run.log 2>&1
```

**First supervised live run (G5 runbook):** don't rawdog it to cron.
1. Fresh topic (`course/topics.json` → new row, e.g. `concept-03`), template
   planner, `FLOW_HEADLESS=0`, interactive terminal.
2. `.venv/bin/python -m src.main` — watch the browser; if Flow's DOM shifted
   you'll get the exact manual-assist prompt. Paste + save it.
3. Verify the clip: `output/day_*/final.mp4` exists, `Videos` page shows it.
4. Archive: pause or delete the cron (there is no `--done` flag — the day
   auto-marks `done` in `done_topic_ids` when its clips finish; use `--fresh`
   or `--day N` only to force a restart).
5. Confirm the YouTube scheduled upload posted on time (tombstone in
   `.runtime/uploaded.json` reads `done`).

## 8. Guardrails (from requirement.md Constraint)

- Per-clip retry ledger: max 3 attempts per clip, tracked durably in
  `.slc/state.json` (`clip_attempts`). A clip that burns its budget is
  escalated, never re-generated.
- Completed topics are never repeated (`done_topic_ids` in `.slc/state.json`).
- A topic that burned its retry budget is never auto-re-picked (durable block).
- **Reference preflight:** before the first browser opens, every presenter
  scene's reference image is verified — a missing/failed reference stops the
  day before it spends credits.
- **Planner output guard:** LLM-generated storyboards are screened for secret/
  injection-looking text before they reach paid prompts or the SEO doc
  (see §4). Template storyboards are trusted.
- `.slc/`, `.env`, `.runtime/`, `output/` are gitignored — no secrets in git.
- Don't point a stealth/free model at private client work; this pipeline's
  prompts/scripts are fine but keep real keys out of the requirement.
- A storyboard/state file whose `schema_version` is newer or corrupt is never
  guessed at — it's quarantined (`state.corrupt-*`) and the run stops rather
  than overwrite evidence.

## 9. Tests

```bash
.venv/bin/python -m pytest
```

**140 tests** in this repo (`src/planner.py`, `src/gemini_web.py`, `src/state.py`,
`src/youtube_upload.py`, `src/main.py --dry-run` preflight capture, Flow automation
capture, YouTube upload error contract incl. post-commit-failure recovery),
all runnable without network/keys (template planner + mocked ffmpeg + mocked
YouTube client). The CI test gate runs the same suite.