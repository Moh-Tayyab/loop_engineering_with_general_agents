# Daily AI-Video Generation Loop

Daily 1-minute (6×10s) short-form AI video from the
[Agentic Coding Crash Course](https://agentfactory.panaversity.org/docs/agentic-coding-crash-course),
generated in **Google Flow** via Playwright automation, merged with FFmpeg, and
packaged for TikTok, Instagram Reels, Facebook and YouTube Shorts — Urdu/English
mixed for a Pakistani audience.

Built spec-first with **SLC** (`requirement.md` → `slc` → `spec/`).

```
course/topics.json  →  storyboard (template; Gemini optional)
     →  Google Flow clips (Playwright, your signed-in PRO account)
     →  ffmpeg merge  →  post package (final.mp4 + 4 captions)
```

## Quick start

```bash
# 1. SLC spec tree (you run this in your terminal, connected to your LLM)
npx @wewiselabs/slc

# 2. install
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
cp .env.example .env            # no API key needed (template planner default)

# 3. give the agent access to YOUR Google account (once, PRO plan gate):
.venv/bin/python -m src.main --login    # sign in to Flow in the window that opens

# 4. preview (no browser, no credits) then run
.venv/bin/python -m src.main --dry-run
.venv/bin/python -m src.main
```

Full instructions: [`docs/USAGE.md`](docs/USAGE.md). Outputs → `output/day_NN/`.

## Structure

- `requirement.md` — SLC input (goal, journeys, features, constraints)
- `course/topics.json` — the 15 crash-course concepts (editable queue)
- `src/` — state, planner (template default, Gemini optional), Flow automation,
  merge/evaluate, post package, orchestrator
- `tests/` — 49 pytest cases (no network/keys needed)
- `.slc/state.json` — resume-safe run state (gitignored)