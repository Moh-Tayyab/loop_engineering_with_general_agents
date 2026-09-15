# Job Fetching Loop — AI/ML Remote Jobs

Autonomous daily scraper for AI/ML remote jobs across 7 sources, with
intelligent dedup (URL hash + fuzzy title/company), circuit-breaker
resilience, and Telegram/WhatsApp notifications.

## Quick Start

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium

cp .env.example .env   # edit credentials (Telegram bot, etc.)
.venv/bin/python -m src.main --list-sources
.venv/bin/python -m src.main --window daily   # run one pass
```

## Schedule (automatic)

| Day       | Window       | Action                                   |
|-----------|--------------|------------------------------------------|
| Monday    | 3 days       | Backfill weekend backlog                 |
| Tue–Thu   | 24 hours     | Daily incremental scrape                 |
| Friday    | 7 days       | Scrape + weekly digest + notify          |
| Sat–Sun   | —            | Idle                                     |

## CLI

```bash
python -m src.main                       # auto schedule
python -m src.main --source linkedin     # test one source
python -m src.main --dry-run             # rehearsal (no writes/notifications)
python -m src.main --window weekly       # force weekly digest
python -m src.main --digest              # regenerate digest
python -m src.main --stats               # circuit breaker status
python -m src.main --reset-circuit       # clear all breakers
python -m src.main --linkedin-login      # LinkedIn session gate
```

## Output

```
output/jobs_YYYY-MM-DD.json      # structured job data
output/digest_YYYY-Www.json/.md  # Friday digest
```

## Architecture

```
Schedule → Source Router (7 scrapers) → Pipeline:
           Fetch (Playwright stealth / plain HTTP where available) → Dedup
           (hash + fuzzy + TTL expiry) → Normalize → Store (atomic JSON)
           → Notify (Telegram/WhatsApp, per-channel dedup)
Resilience: per-source circuit breaker + retry + dead-letter queue
           + inter-process FileLock (cron race safety)
```

Sources: Remote Rocketship, Working Nomads, LinkedIn, Indeed, Glassdoor,
APAC Remote, Pakistan Remote. Enable/disable via `SOURCE_*` env flags.
Working Nomads and (when HTTP is enough) other JSON APIs are fetched via
plain `requests`; the browser is only launched when HTML crawling is required.

## Anti-bot Sources (Indeed / Glassdoor)

These two are the primary targets but serve Cloudflare/hCaptcha challenges to
headless browsers. The loop treats them as **human-in-the-loop**:

1. They run **headed** (a real Chrome window opens) with a **persistent profile**:
   `.runtime/indeed-profile/` and `.runtime/glassdoor-profile/`.
2. On each run the scraper **warms up** on the homepage first (human-like scroll
   + delays) before hitting search URLs.
3. When a CAPTCHA appears the window **stays open** and prints
   `⚠ CAPTCHA detected — solve it in the open browser window`. Solve it once
   (the challenge typically clears on a single click).
4. The solved session is saved to the profile, so **later runs reuse it** — a
   one-time cost per source per IP/cleared state.
5. If not solved within `CAPTCHA_SOLVE_TIMEOUT` (default 300s) the source
   escalates and the run moves on.

Interactive debugging via Playwright MCP (`.opencode/opencode.json`):
`browser_navigate` / `browser_snapshot` / `browser_click` against the same
system-Chrome profiles, so selectors can be confirmed visually on a live page
before the loop re-runs.

## Constraints

- Never store credentials in code/git; use `.env` (gitignored).
- Rate limiting enforced between requests (1-3s, randomized).
- Max 3 consecutive failures per source → circuit opens 1h.
- Seen-hash dedup expires after `DEDUP_WINDOW_DAYS` (default 30) so old jobs
  can be re-discovered.
- A `LOCK_TIMEOUT_S` FileLock (default 5s) guards `state.json` against two
  overlapping cron runs; the loser exits cleanly instead of corrupting state.
- LinkedIn require a manual login gate (`--linkedin-login`); Indeed/Glassdoor
  use the headed human-in-the-loop CAPTCHA flow above.
- `--dry-run` is side-effect free: no state, output, or notifications.

## Tests

```bash
.venv/bin/python -m pytest tests/
```