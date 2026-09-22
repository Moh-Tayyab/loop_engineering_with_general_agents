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
- **Runners:** GitHub Actions `job-loop-cron.yml` (weekday 08:00 PKT = `0 3 * * 1-5` UTC,
  `.slc/` cache) and local `run_loop.sh` via crontab (weekday **08:00 PKT**, `0 8 * * 1-5`).
  Which one is primary follows `JOB_LOOP_PRIMARY`; `both` = both fire (duplicate Telegram risk).
- **CI gate:** `.github/workflows/test-gate.yml` runs pytest in
  `working-directory: job_fetching_loop`.

## 2. Current Beat

- **Beat #:** 77 — morning triage: job suite red on main (`date-bomb` fixtures), fix verified in PR #11
- **Date:** 2026-09-22
- **Trigger:** weekday 9am heartbeat (morning triage)
- **Status:** Triage (no code): reproduced 2 fails on `main` — `test_smart_working_and_trellions_onsite_jobs_dropped`, `test_run_source_drops_us_only_and_restricted_jobs` (fixtures hardcoded `09-17/09-16`; `run_source` cuts at `now−2d` = 09-20, so fixtures aged out). CLEAR FIX already shipped as open PR #11 (verified 2/2 on branch) but blocked: its test-gate run is `action_required` — a human must approve the workflow run + merge. Beat 76 pending inside PR #11. `PASS`

## 3. Beat Log

compressed at 2026-09-22: beats 51–69 all PASS (per-source timeouts, volume expansion, onsite/expired purge, EPIPE shield, 24h cutoff, source exclusions, prod-audit remediation, salary/dedup hardening, weekly-digest cache, DLQ replay).
compressed at 2026-09-17: beats 26–50 all PASS (prod-readiness, spine split, schedule, heartbeat, lock watchdog, weekly retry, volume scaling, scaffolds purge).

| Beat | Date | Trigger | Action | Result |
|------|------|---------|--------|--------|
| 77 | 2026-09-22 | weekday 9am heartbeat | **Morning triage (no code):** reproduced job suite red on `main` — 2 date-bomb fails (`test_smart_working_and_trellions_onsite_jobs_dropped`, `test_run_source_drops_us_only_and_restricted_jobs`): fixtures hardcoded 09-17/09-16 vs `now−2d` cutoff. Fix verified in open PR #11 (2/2 pass on branch); PR's test-gate run `action_required` — human approval + merge needed | PASS — triage only; no code |
| 75 | 2026-09-17 | user report (location mismatch frustration) | **Description & Scraper-level Remote Hardening:** `WellfoundScraper` keeps on-site locations when `remote: False`; `ArbeitnowScraper` preserves real German/EU city locations; `is_description_restricted` filters US auth, hybrid, clearance, and tight timezones; +3 tests | PASS — 297 tests, exit 0 |
| 74 | 2026-09-17 | user report (US-only/foreign jobs in sheet) | **Strict Pakistan Remote Verification & Domestic Purge:** `is_title_restricted` catches US-only/hub titles; `_is_us_restricted` and `is_foreign_country_restricted` filter non-APAC foreign remote; `PythonOrgScraper` parses real location line instead of faking Worldwide; +4 regression tests | PASS — 294 tests, exit 0 |
| 73 | 2026-09-17 | user report (on-site jobs in output) | **Strict Remote Gate & Pakistan Onsite Elimination:** `is_remotely_workable` rejects `location_type != LOCATION_REMOTE`; `is_worldwide_remote` rejects physical Pakistan cities & bare country without explicit remote markers; LinkedIn drops non-remote title/loc; +3 regression tests | PASS — 290 tests, exit 0 |
| 72 | 2026-09-17 | user request (in-depth audit fix) | **Deep Salary Scale & Indicator Hardening:** added bidirectional range suffix propagation (`$150K-200`) and annual context scaling (`$150 - $200 / yr` -> 150k-200k, `/hr` preserved); +2 regression tests | PASS — 287 tests, exit 0 |
| 71 | 2026-09-17 | user request (fix audit findings) | **Salary Scale Fix & Scraper Hardening:** propagated multiplier suffix to range min when omitted in `parse_salary` (`$150-200K` -> 150k); added `wait_until="domcontentloaded"` to `remote_rocketship`; diagnosed GitHub Actions schedule default-branch requirement; +1 regression test | PASS — 285 tests, exit 0 |
| 70 | 2026-09-17 | user request (clarify cloud sources) | **Clarify `--list-sources` for browser scrapers:** in `src/main.py:658`, report `disabled (browser-bound; skipped on cloud runner)` instead of confusing `(set SOURCE_XYZ=1)` for browser sources on cloud; +1 regression test | PASS — 284 tests, exit 0 |
| 69 | 2026-09-17 + legacy 51–69 | (see compressed line above) | **Legacy beats 51–69 compressed per §9:** 228→283 green, all PASS — per-source timeout guard (150s), volume expansion (Arbeitnow/PythonOrg), onsite/expired purge, EPIPE shield + 24h filter, universal 24h cutoff, US/foreign restrict, prod-audit remediation, salary/dedup hardening, output/ cache + DLQ replay, cloud cron 08:00 PKT | compressed — see summary line |

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
6. ~~**(Beat 65, HIGH)** Persist `output/` in `job-loop-cron.yml` cache (or build Monday weekly digest from durable state) — cloud primary otherwise mails a near-empty digest.~~ Done Beat 66: `output/` in cache+artifact, seen-store fallback in `collect_weekly_jobs`.
7. ~~**(Beat 65, MED)** Add a Sheets DLQ replay path (`--replay-dlq google_sheets`) so webhook-outage rows aren't lost; then `--clear-dlq` the stale legacy rows.~~ Done Beat 66: replay added (dry-run safe), 12 legacy rows cleared.
8. **Beat 77 finding — merge PR #11** (`fix(job-loop-fixtures)`): job suite is RED on `main` (date-bomb fixtures, verified 09-22); its test-gate run is `action_required` (workflow run needs a human to Approve it in the Actions UI, then merge). The fix is small and verified (297 green claimed; 2/2 targeted re-checked 09-22).

## 11. Human Gate Decisions (job loop)

- 2026-09-14 — Telegram token was pasted in chat → Rotated via BotFather `/revoke` on 2026-09-16. Store the new token in Actions secrets; never commit `.env`.
- 2026-09-16 — Cloud production is HTTP/JSON/RSS only. Headed CAPTCHA boards are a local ops cost, not a cloud feature.
- 2026-09-14 — Indeed/Glassdoor CAPTCHAs stay fail-closed.
