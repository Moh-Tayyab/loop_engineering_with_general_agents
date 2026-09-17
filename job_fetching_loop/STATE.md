# STATE.md — Job Fetching Loop (project spine)

> This is the **project spine** for `job_fetching_loop/` — the back of that diary.
> Read `job_fetching_loop/AGENTS.md` (rules) then this file (progress); update THIS file
> last when a beat touches the job loop. There is no root STATE.md or root AGENTS.md —
> this spine pair is fully self-contained (rules + budget live in this loop's `AGENTS.md`).
> (Nested-spine split decided 2026-09-14, beat 28; root files removed beat 30, 2026-09-15.)

## 1. Project Identity

- **Project:** `job_fetching_loop/` — autonomous AI/ML remote-job scraper loop.
- **Scope:** HTTP/JSON/RSS boards (LinkedIn guest, Working Nomads, Remotive, Himalayas,
  RemoteOK, WeWorkRemotely, Jobicy, Wellfound, NoDesk) plus local-only Playwright
  sources (Indeed, Glassdoor, JustRemote, Remote Rocketship, APAC, Pakistan Remote).
  Five scaffolds remain default-OFF. Cloud cron skips browser-bound sources.
- **Stack:** Python 3.12, Playwright (local headed + persistent profiles), requests, pytest.
- **Live end-to-end since:** Beat 26 (2026-09-14) — real Telegram delivery.
- **Runners:** GitHub Actions `job-loop-cron.yml` (weekday 09:00 PKT = `0 4 * * 1-5` UTC,
  `.slc/` cache) and local `run_loop.sh` via crontab (weekday **08:00 PKT**, `0 8 * * 1-5`).
  Which one is primary follows `JOB_LOOP_PRIMARY`; `both` = both fire (duplicate Telegram risk).
- **CI gate:** `.github/workflows/test-gate.yml` runs pytest in
  `working-directory: job_fetching_loop`.

## 2. Current Beat

- **Beat #:** 64 — CI Alignment, Dead Code Purge, Google Sheets Retry/DLQ & Worker Thread Join
- **Date:** 2026-09-17
- **Trigger:** user request — fix LOW audit items (CI drift, dead code/dev deps, Sheets retry/DLQ, daemon thread join)
- **Status:** Resolved all LOW audit findings: aligned `actions/checkout@v6` across all workflows; separated `pytest` out of `requirements.txt` into `requirements-dev.txt`; purged dead code (`_KNOWN_COMPANIES` and `_parse_company` in `apac_remote.py` & `pakistan_remote.py`); added 3-attempt exponential backoff and `DeadLetterQueue` recording to `sync_to_google_sheet`; added grace `worker.join(0.5)` on scraper timeouts in `src/main.py`; 265 tests passing. `PASS`

## 3. Beat Log

compressed at 2026-09-17: beats 26–50 all PASS (prod-readiness, spine split, schedule, heartbeat, lock watchdog, weekly retry, volume scaling, scaffolds purge).

| Beat | Date | Trigger | Action | Result |
|------|------|---------|--------|--------|
| 64 | 2026-09-17 | user request (low audit items) | **CI Checkout v6, Dead Code Purge, Sheets Retry/DLQ & Worker Join:** Aligned workflows to `actions/checkout@v6`; separated dev deps into `requirements-dev.txt`; deleted dead code in scrapers; added retries & DLQ recording to `sync_to_google_sheet`; added timeout worker join grace in `src/main.py`; 265 tests green | PASS — 265 tests, exit 0 |
| 63 | 2026-09-17 | user request (salary, 24h datetime, cron hour) | **Salary Comma Parser, 24h Datetime & Cron Hour:** Stripped commas in `parse_salary`; compared ISO datetimes in `_run_source_impl`; added `SCRAPE_RUN_HOUR` to `next_fetch_start`; added regression tests; 263 tests green | PASS — 263 tests, exit 0 |
| 62 | 2026-09-17 | user request (exact dedup mismatch) | **Canonical URL Exact-Dedup Alignment:** Canonicalized URLs in `job_id`; updated `dedup_job` to use `normalized.id` and pass `normalized` in `_run_source_impl`; added regression test; 259 tests green | PASS — 259 tests, exit 0 |
| 61 | 2026-09-17 | user request (feed gate & timeout dedup) | **Feed Gate Unblock & Timeout Dedup Safety:** Dropped undocumented `LINKEDIN_FEED_PASS`; deferred dedup `accept_and_record` to caller thread on confirmed success (no burning jobs on timeout, no cross-thread seen race); 258 tests green | PASS — 258 tests, exit 0 |
| 60 | 2026-09-17 | user request (prod audit gaps) | **Full Production Audit Remediation:** Single-writer standby aligned (`JOB_LOOP_PRIMARY=github`); LinkedIn guest outage honesty; Google Sheets decoupled from lock; single-threaded circuit & DLQ ops; DLQ CLI tools; localhost health server; 255 tests green | PASS — 255 tests, exit 0 |
| 59 | 2026-09-17 | user request (source & regex filter) | **Source Exclusion & US Regex Hardening:** Confirmed zero reliance/inclusion of AI-Jobs, Upwork, Toptal; updated `_is_us_restricted` and `_US_RESTRICTED_RE` to strictly drop `Remote - US/USA/United States` variants; 249 tests green | PASS — 249 tests, exit 0 |
| 58 | 2026-09-17 | user request (prod gaps) | **Outage Honesty, Timeout Double-Count Shield & Topology Alignment:** Propagated HTTP/network failures across all curated & HTTP scrapers (no swallowed outage errors); added `cancel_event` to prevent daemon threads from double-counting circuit breaker failures on timeout; aligned `JOB_LOOP_PRIMARY=local` across configs; added regression tests; 249 tests green | PASS — 249 tests, exit 0 |
| 57 | 2026-09-16 | user request (universal 24h) | **Universal 24h Cutoff:** Removed 10-day relaxation for curated boards in `src/main.py`; enforced strict `cutoff_date = posted_after.date()` for every platform; added regression test; 243 tests green | PASS — 243 tests, exit 0 |
| 56 | 2026-09-16 | manual (audit debt & 24h filter) | **EPIPE Shield, 24h Filter, defusedxml & Concurrency Tests:** Enforced exact 24h query on Indeed (`fromage=1`) & Glassdoor (`fromAge=1`); shielded Node EPIPE crashes in browser teardown & fail-isolated `run_source`; migrated RSS to `defusedxml`; updated UAs to Chrome 133; added cross-process FileLock test; 242 tests green | PASS — 242 tests, exit 0 |
| 55 | 2026-09-16 | manual (prod audit) | **Prod Audit Remediation:** Handled browser process cleanup on timeout/daemon cycle; added 3-attempt Telegram retries; added /healthz endpoint & graceful SIGTERM in --serve; untracked PDF & updated .gitignore; cleaned .env.example; 240 tests green | PASS — 240 tests, exit 0 |
| 54 | 2026-09-16 | manual (onsite/expired purge) | **On-site & Expired Purge:** Removed fake `(Remote)` in linkedin.py; hardened `is_worldwide_remote` to reject hybrid/onsite in Pakistan/regions; added deep `jobPosting` verification for expired/closed/onsite drops; 234 tests pass | PASS — 234 tests, exit 0 |
| 53 | 2026-09-16 | manual (unattended & 24h filter) | **LinkedIn 24h filter & unattended loop fix:** Added `import os` to `linkedin.py` (fixed `NameError`); shielded Node/Playwright `EPIPE` crash in background; locked `sortBy=DD&f_TPR=r86400`; synced 32 verified 24h jobs to Google Sheet; 234 tests pass | PASS — 234 tests, exit 0 |
| 52 | 2026-09-16 | manual (volume scaling) | **High-volume platform expansion:** Added `ArbeitnowScraper` (250+ JSON API) & `PythonOrgScraper` (PSF RSS); multi-tag RemoteOK & Jobicy data-science; expanded tech context in matcher; 17 live sources; 234 tests green | PASS — 234 tests, exit 0 |
| 51 | 2026-09-16 | manual (prod hardening) | **Per-source timeout guard:** `run_source()` daemon worker capped `SOURCE_TIMEOUT_S=150`; timeout → circuit failure + verdict + DLQ (real runs) + loop continues. LinkedIn guest pass 45s monotonic, browser pass 90s `asyncio.wait_for`. Live: linkedin 135s/4 jobs (was >180s hang), indeed capped 150s. Scaffolds 4/5 still blocked | PASS — 228 tests, exit 0; checker APPROVED |

## 4. Budget & Stopping Conditions

Same ceilings as the trainer (shared loop budgets) — see THIS loop's `AGENTS.md` §3.
Project-specific note: max beats per run is shared across the trainer — a job-loop beat
still consumes the shared budget counter.

## 5–8. Maker–Checker, Inner/Outer, Automation, Escalation

All defined in THIS loop's `AGENTS.md` (§2 non-negotiables, §5 inner/outer, §6 hardened
maker–checker, §7 escalation). Single source of truth — do not restate here.

## 9. State Compression

Cap this project's beat log at 20 rows; compress into a one-line "Legacy beats" summary when
exceeded. Keep verdicts; never drop budget (§4) or escalation (THIS loop's `AGENTS.md` §7).

## 10. Next Actionable Tasks (job loop)

1. ~~**Rotate the Telegram token** (pasted into chat 2026-09-14) via BotFather `/revoke`~~ (Done 2026-09-16). **Next:** Update `.env` and GitHub secrets `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` with the newly generated token.
2. Confirm repo secrets exist for the cloud cron (`GOOGLE_SHEET_WEBHOOK_URL` optional). Push so weekday Actions can run.
3. Local crontab is standby while `JOB_LOOP_PRIMARY=github`. Set `JOB_LOOP_PRIMARY=local` only if Actions is off.
4. Indeed/Glassdoor remain local-headed only; cloud never waits on CAPTCHA.
5. Scaffolds cleanly retired: feedcoyote, jobboardsearch, flexjobs, dynamitejobs, and virtual_vocations purged. Production operates on 15 live, verified sources.

## 11. Human Gate Decisions (job loop)

- 2026-09-14 — Telegram token was pasted in chat → Rotated via BotFather `/revoke` on 2026-09-16. Store the new token in Actions secrets; never commit `.env`.
- 2026-09-16 — Cloud production is HTTP/JSON/RSS only. Headed CAPTCHA boards are a local ops cost, not a cloud feature.
- 2026-09-14 — Indeed/Glassdoor CAPTCHAs stay fail-closed.
