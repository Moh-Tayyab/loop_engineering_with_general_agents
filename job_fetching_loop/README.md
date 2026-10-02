# Job Fetching Loop — AI/ML Remote Jobs

Daily scraper for AI/ML worldwide-remote jobs: HTTP/JSON/RSS boards plus
optional headed Playwright sources, dedup, atomic store, Telegram (and
optional WhatsApp / LinkedIn / Google Sheet).

## Production topology (pick one primary)

| Runner | When | Sources | State |
|--------|------|---------|--------|
| **GitHub Actions** (`job-loop-cron.yml`) | Weekdays 08:00 PKT (`0 3 * * 1-5` UTC) | Cloud-safe HTTP/JSON/RSS only (no CAPTCHA browsers) | `.slc/` restored via Actions cache |
| **This machine** (`run_loop.sh` cron) | Only if `JOB_LOOP_PRIMARY=local` | Full set including Indeed/Glassdoor headed | local `.slc/` |

Set `JOB_LOOP_PRIMARY=github` in `.env` (recommended) so laptop cron **does
not** double-send Telegram while Actions is the writer. Set `local` if you
are not using the Actions schedule.

Cloud skips Playwright/CAPTCHA sources (`indeed`, `glassdoor`, `justremote`,
`remote_rocketship`, `apac_remote`, `pakistan_remote`) unless
`CLOUD_ALLOW_BROWSER=1`. LinkedIn **guest** search still runs on cloud.

## Quick Start

### Local Python Environment
```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium   # local headed sources only

cp .env.example .env   # Telegram bot token, chat id, JOB_LOOP_PRIMARY
.venv/bin/python -m src.main --list-sources
.venv/bin/python -m src.main --dry-run
```

### Docker & Docker Compose (Phase 4)
The container environment uses `mcr.microsoft.com/playwright/python:v1.62.0-noble` with a non-root `pwuser`:
```bash
# Build the container image
docker compose build

# Rehearsal run (dry-run mode without mutations or notifications)
docker compose run --rm job-loop --dry-run

# Run scheduled fetch
docker compose run --rm job-loop
```

## Schedule

| Day       | Window       | Action                                      |
|-----------|--------------|---------------------------------------------|
| Monday    | 3 days       | All-source backfill + weekly digest         |
| Tue–Thu   | 24 hours     | Incremental scrape                          |
| Friday    | 7 days       | LinkedIn hiring-feed / guest only           |
| Sat–Sun   | —            | Idle                                        |

GitHub Actions secrets required for cloud: `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`, optional `GOOGLE_SHEET_WEBHOOK_URL`.

## CLI

```bash
python -m src.main                       # auto schedule
python -m src.main --source linkedin     # test one source
python -m src.main --dry-run             # rehearsal (no writes/notifications)
python -m src.main --window weekly       # force weekly digest
python -m src.main --digest              # regenerate digest
python -m src.main --stats               # circuit breaker status
python -m src.main --reset-circuit       # clear all breakers
python -m src.main --linkedin-login      # LinkedIn session gate (local)
python -m src.main --serve               # daemon (local only; not for cloud)
```

## Output

```
output/jobs_YYYY-MM-DD.json      # structured job data
output/jobs_YYYY-MM-DD.csv       # BD spreadsheet
output/digest_YYYY-Www.json/.md  # weekly digest
.slc/                            # seen hashes, circuits, notify keys (gitignored)
```

## Constraints

- Never store credentials in git; use `.env` (gitignored) or Actions secrets.
- `--dry-run` writes nothing to `.slc/` or `output/`.
- FileLock + `run_loop.sh` flock stop overlapping **local** runs. Cloud uses
  workflow `concurrency`. Local and cloud do **not** share a lock — use
  `JOB_LOOP_PRIMARY`.
- Unscored CV matches are exported as `unscored`, never a fake percentage.
- Rotate the Telegram token if it was ever pasted into chat.

## Tests

```bash
.venv/bin/python -m pytest tests/ -q
```
