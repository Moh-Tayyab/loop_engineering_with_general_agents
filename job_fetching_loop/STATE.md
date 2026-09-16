# STATE.md — Job Fetching Loop (project spine)

> This is the **project spine** for `job_fetching_loop/` — the back of that diary.
> Read `job_fetching_loop/AGENTS.md` (rules) then this file (progress); update THIS file
> last when a beat touches the job loop. There is no root STATE.md or root AGENTS.md —
> this spine pair is fully self-contained (rules + budget live in this loop's `AGENTS.md`).
> (Nested-spine split decided 2026-09-14, beat 28; root files removed beat 30, 2026-09-15.)

## 1. Project Identity

- **Project:** `job_fetching_loop/` — autonomous AI/ML remote-job scraper loop.
- **Scope:** 13 live sources (Remote Rocketship, Working Nomads, LinkedIn, Indeed, Glassdoor,
  APAC Remote, Pakistan Remote, Remotive, Himalayas, Wellfound, JustRemote) +
  6 scaffolded curated boards (feedcoyote, jobboardsearch, flexjobs, dynamitejobs,
  virtual_vocations, nodesk) → dedup → normalize → atomic store → Telegram/WhatsApp/LinkedIn.
- **Stack:** Python 3.12, Playwright (stealth + persistent profiles), requests, pytest.
- **Live end-to-end since:** Beat 26 (2026-09-14) — real Telegram delivery.
- **CI gate:** `.github/workflows/test-gate.yml` installs this loop's requirements and runs
  its suite in an isolated `working-directory: job_fetching_loop` step
  (`python -m pytest -q`), separate from the trainer/video run.

## 2. Current Beat

- **Beat #:** 44 — P2 LinkedIn public guest unblock & hybrid collector
- **Date:** 2026-09-16
- **Trigger:** manual — P2 implementation (LinkedIn unblock & guest fallback)
- **Status:** Done. Added LinkedIn public guest endpoint fallback (`https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings`) in `src/scrapers/linkedin.py`; returns clean canonical job view URLs without requiring manual session; preserved authenticated Playwright session for hiring feed status updates; live dry-run fetched 2 new worldwide AI jobs on LinkedIn; 204 tests green (exit 0); checker APPROVED. `PASS`

## 3. Beat Log

| Beat | Date | Trigger | Action | Result |
|------|------|---------|--------|--------|
| 44 | 2026-09-16 | manual (P2 implementation) | **P2 LinkedIn public guest unblock & hybrid collector:** Added public guest remote endpoint fallback (`jobs-guest/jobs/api/seeMoreJobPostings`) returning verified canonical job postings without requiring login; preserved authenticated Playwright session for hiring feed posts; live dry-run fetched 2 new worldwide AI jobs on LinkedIn; 204 tests green | PASS — 204 tests, exit 0; checker APPROVED |
| 43 | 2026-09-16 | manual (P1 implementation) | **P1 Autonomous Cron setup + RemoteOK worldwide source expansion:** Created executable `run_loop.sh` wrapper with virtualenv activation and timestamped logging; installed crontab entry (`0 9 * * 1-5 .../run_loop.sh`) running weekday mornings at 09:00 PKT; implemented live-verified `RemoteokScraper` in `curated_boards.py` via public JSON API (`https://remoteok.com/api?tag={kw}`); RemoteOK dry-run fetched 18 new authentic worldwide AI jobs; 4 new unit tests; 204 tests green | PASS — 204 tests, exit 0; checker APPROVED |
| 42 | 2026-09-16 | manual (P0 implementation) | **P0 Working Nomads Global/APAC unblock + Indeed URL canonicalization:** Enhanced `is_worldwide_remote` & `classify_location` to support "Global", "APAC", "Asia Pacific", and multi-region strings; rejected country-restricted "Anywhere in <Country>" while allowing "Anywhere in the world"; canonicalized Indeed URLs from ephemeral `/rc/clk?jk=...` to permanent canonical `https://www.indeed.com/viewjob?jk={jk}` in `scrapers/indeed.py` and `main.py:normalize_raw()`; Working Nomads yield jumped from 0 to 8 authentic worldwide AI jobs; 3 new unit tests; 200 tests green | PASS — 200 tests, exit 0; checker APPROVED |
| 41 | 2026-09-16 | manual (filter hardening) | **Eliminate US-domestic remote false positives + "Remote, Oregon" disambiguation:** Fixed `models.py` syntax corruption; whole-word token matching for US state abbreviations in `_is_us_restricted` (preventing "pakistan" false matches); disambiguated physical hamlet "Remote, Oregon" (Coos County, OR, ZIP 97458, "Remote, OR", "Remote OR"); added source-aware filtering in `is_worldwide_remote` & `is_remotely_workable` — US domestic boards (Indeed, Glassdoor) bare "Remote" (e.g. GoodLeap) rejected for Pakistan workers unless explicit worldwide/anywhere indicators exist in location or description; remote-native boards (Remotive, Himalayas, Wellfound, JustRemote) preserved; 5 new regression tests; 197 tests green | PASS — 197 tests, exit 0; checker APPROVED |
| 36 | 2026-09-15 | manual (Run 1, Beat A) | **Git backstop commit:** `job_fetching_loop/` added to repo (44 files; .env/.slc/output/.runtime/.venv/WhatsApp image excluded; secret scan clean); commit `6622ebb feat(jobs): initial job_fetching_loop` — recovery backstop before code changes | PASS |
| 49 | 2026-09-16 | manual | **Google Sheets & BD Spreadsheet Integration:** Built `src/sheets.py` generating BD-formatted CSV (`output/jobs_YYYY-MM-DD.csv`) with 13 columns (Job ID, Posted Date, Company, Title, Apply URL, Source, Location, Salary, Job Type, Tags, BD Status, BD Notes); added live sync to `GOOGLE_SHEET_WEBHOOK_URL`; wired Telegram `send_document` to auto-upload the spreadsheet directly to chat; 4 new tests; 213 tests green | PASS — 213 tests, exit 0 |
| 48 | 2026-09-16 | manual | **Schedule & Time-Filter Gate Hardening:** Verified & enforced schedule logic: Monday = 3-day backfill (Fri/Sat/Sun weekend catch-up); Tue/Wed/Thu = 24h incremental window; Friday = LinkedIn-only hiring-feed scrape with `#hiring` & `"we are hiring"` phrases; orchestrator level gate added in `main.py:run_source` dropping any job older than `posted_after`; unit test added; 209 tests green | PASS — 209 tests, exit 0 |
| 47 | 2026-09-16 | manual | **BD Volume Scaling & Jobicy Integration:** Added `JobicyScraper` (`jobicy`) via official v2 public JSON API (geo=anywhere & engineering); dry-run verified 20 fresh jobs in 1s; expanded AI keywords in `src/config.py` (+Generative AI, GenAI, Deep Learning, MLOps, AI Agent, PyTorch); raised default `MAX_JOBS_PER_SOURCE` from 100 to 250 (3,500 jobs max run capacity across 14 platforms); 208 tests green | PASS — 208 tests, exit 0 |
| 46 | 2026-09-16 | manual | **WeWorkRemotely global RSS feeds integration:** Added `WeWorkRemotelyScraper` (`weworkremotely`) pulling from 4 high-yield remote engineering RSS feeds (119+ worldwide jobs); XML parsed with region validation ("Anywhere in the World" passed, "USA Only" dropped); dry-run verified 2 fresh AI jobs in 3s; unit test added; 206 tests green | PASS — 206 tests, exit 0 |
| 45 | 2026-09-16 | manual | **LinkedIn Precision Engineering & Location Filtering:** LinkedIn guest search now queries both `location=Worldwide&f_WT=2` and `location=Pakistan&f_WT=2`; location strings normalized with `(Remote)`; `is_worldwide_remote` tested live on real 34-job LinkedIn feed — rejects 100% of US/Canada/India city-restricted domestic remote roles while passing 14 authentic Pakistan-workable remote AI jobs (Devsinc, Systems Ltd, Convo, Albi, CureMD); `headless=cfg.scrape_headless()` wired | PASS — 204 tests green, live verify 14/14 valid |
| 44 | 2026-09-16 | manual | **LinkedIn guest endpoint fallback:** `login_required=False` degradation; public guest endpoint `seeMoreJobPostings` added for unauthenticated runs; preserved Playwright feed pass if session exists | PASS — 204 tests green |
| 43 | 2026-09-16 | manual | **RemoteOK integration & crontab runner:** `RemoteokScraper` public JSON API live (18 jobs); `run_loop.sh` runner installed; system crontab 09:00 PKT wired | PASS — 204 tests green |
| 42 | 2026-09-16 | manual | **Global/APAC remote expansions & Indeed URL canonicalization:** Working Nomads regional unblocking (`Global`, `APAC`, `Asia Pacific`); Indeed clean canonical URLs | PASS — 204 tests green |
| 41 | 2026-09-16 | manual | **Domestic remote & Remote, OR filter hardening:** Strict Coos County/Oregon rejection; domestic board gate rejects US bare remote (GoodLeap bug fixed) | PASS — 204 tests green |
| 37 | 2026-09-15 | manual (Run 1, Beat B) | **H1 posted_date fix:** `parse_posted_date()` in `src/models.py` (ISO dates, ISO datetimes truncated to date, "Today"/"Yesterday" with "posted " prefix, relative regex for "Posted 3 days ago"/"30+ days ago"/"6d"/"6 hours ago"); wired into `normalize_raw()` replacing `posted_date=None`; digest `top_jobs` sort now `(posted_date or fetched_at.date(), fetched_at)` so posts sort by actual post date not just fetch time; 7 new tests (4 model, 3 normalize); adversarial checker APPROVED | PASS — 183 tests, exit 0 |
| 38 | 2026-09-15 | manual (Run 1, Beat G) | **P1 daily heartbeat:** healthy 0-new-job multi-source run now sends daily Telegram (silence == loop DOWN, never "nothing was new"); total-outage skips heartbeat + exits 1 (single alert, no noise); single-source `--source X` debug runs never heartbeat on 0 jobs; spy notifiers in 2 existing tests to keep them hermetic; adversarial checker APPROVED | PASS — 183 tests, exit 0 |
| 39 | 2026-09-15 | manual (Run 2, Beat E) | **Self-scheduling serve loop (no cron) + P2 stale-lock watchdog:** `serve_loop()` + `--serve` flag in `src/main.py` — one pass immediately, then sleeps to next weekday 09:00 fetch window (Sat/Sun idle-skipped; no cron required, cron optional accelerator); `next_fetch_start()` in `src/schedule.py` (tz-aware, weekday-aware, 4 tests). **P2 stale-lock watchdog was DEAD CODE (real bug, fixed cross-file):** main read `lock_holder(state.path)` → `state.json.holder`, but `FileLock` writes its holder sidecar at `lock_path_for(state.path).holder` = `state.json.lock.holder` (state.py:104-105 `_holder_path()`); watchdog read a sidecar that is NEVER written → hung browser squatting the flock looked like a clean skip (DOWN day silent). Now `lock_holder(lock_path_for(state.path))` + `lock_path_for` imported in main.py:42; matches the sidecar FileLock actually writes — a hung holder exits 1, monitoring catches the DOWN day. 192 tests green (exit 0) + adversarial checker APPROVED | PASS — 192 tests, exit 0; checker APPROVED |
| 40 | 2026-09-15 | manual (Run 2, Beat D) | **Weekly digest delivery retry:** weekly block tracks confirmed `kind`s via `weekly.delivered_kinds(wk)` + `mark_weekly_delivered(wk, kinds)` on `LoopState` (sidecar-safe, UTC, pruned); `_guarded_deliver` now returns `set[str]` of confirmed kinds; a channel that fails (Telegram/WhatsApp hiccup) stays pending in the weekly set and is re-sent on the next run's weekly block — never silently dropped because files already exist; already-confirmed kinds skipped; network send outside the flock; `--dry-run`/`--source X` skip weekly retry; 2 new tests | PASS — 192 tests, exit 0; checker APPROVED |
| 33 | 2026-09-15 | manual (spec) | **Spec v2 schedule+boards:** Friday = LinkedIn hiring-feed ONLY (extra `#hiring`/`"we are hiring"` scenes, 7d window, no digest); weekly digest + all-source sweep on Mon 3-day backfill; `window.sources` wired through orchestrator (manual overrides unaffected); Remotive+Himalayas live JSON boards (remote-strict: country lists dropped); 8 curated boards scaffolded default-OFF (can't mask outage); `.env.example` updated | PASS — 149 tests; checker APPROVED |
| 34 | 2026-09-15 | manual | **Wire 2 curated boards:** Wellfound + JustRemote implemented + live-verified (real jobs returned) and flipped default-ON; Wellfound: requests __NEXT_DATA__ apollo parse + real href map; JustRemote: Playwright homepage render + structural card extraction; config removed both from DEFAULT_DISABLED_SOURCES; Checker found nested tag list bug + apollo null-safety gap → fixed + regression tests → re-APPROVED. 6 remaining scaffolds default-OFF with documented per-board blockers | PASS — 160+ tests, exit 0; checker APPROVED |
| 35 | 2026-09-15 | manual (team feedback) | **Team bug fixes:** `classify_location` rewritten — city names "Remote, OR" / "Remote in Brooklyn, NY" no longer match as remote; `is_worldwide_remote` + `is_expired_job` added; `is_remotely_workable` uses location text; Indeed scraper now extracts posted_date + description; Glassdoor scraper company extraction fixed (7 selector fallbacks) + description + date; 36 model tests + full suite green | PASS — 160+ tests, exit 0 |
| 32 | 2026-09-15 | manual | **LinkedIn post + hiring-feeds:** schedule locked (Mon=3d Sat/Sun caught-up, Fri=7d+digest; regression test); `LinkedInNotifier` posts Fri digest to ugcPosts (200/201/202, redirect-refusing, token-safe, fail-closed, weekly-only); LinkedIn source + content-search FEED posts (people's "we're hiring" updates; guarded, remote heuristic, window filter); `.env` placeholders | PASS — 100 tests, compile OK; checker APPROVED (2-finding rework) |
| 31 | 2026-09-15 | manual | **Prod-readiness pass 2:** dry-run writes nothing to `.slc/`/`output/` (seen+DLQ+state+lock all gated, rule 6); dead notify_daily/weekly removed; SeenStore/digest/notifier fully UTC; atomic digest writes; exit-code 1 on total outage; LinkedIn `.linkedin-session` gate; 5 new tests, hygiene/digest tests → UTC | PASS — 78 tests, compile OK; adversarial checker APPROVED |
| 30 | 2026-09-15 | manual | **Root AGENTS.md removed:** root `AGENTS.md` deleted by user request; THIS loop's `AGENTS.md` now carries the full rules (§0 self-containment, §2 non-negotiables, §3 budget, §5 inner/outer, §7 escalation, §11 lessons); consumers updated (opencode.yml, maker.md, skills, other loop) | PASS — 75 tests; checker APPROVED |
| 29 | 2026-09-15 | manual | **Root STATE.md removed:** root `STATE.md` deleted by user request; budget/maker-checker/escalation moved to root `AGENTS.md` (§3/§5/§7); THIS STATE.md self-contained | PASS — 75 tests; checker APPROVED |
| 28 | 2026-09-14 | manual | **Project split (dual spine):** created THIS `STATE.md` + `AGENTS.md` (identity, beats 26-27, §10/§11); test-gate.yml isolates job loop; models pinned | PASS — 75 tests; leak scan clean; checker APPROVED |
| 26 | 2026-09-14 | manual | **Live delivery:** real Telegram daily notification (1056 chars); notifier missing-chat_id warning; tz-aware now() in indeed/glassdoor/linkedin; apac/pakistan repointed to remotearmy.io Asia+Pakistan; 7-source dry-run verified | PASS — 47 tests, compile OK. Open: CAPTCHAs, linkedin login, token rotate |
| 27 | 2026-09-14 | manual | **Production-readiness (senior-SWE):** 10 fixes + 2 hardened checker rounds — FileLock wired + LockTimeoutError skip; SeenStore TTL eviction + legacy compat; per-channel notifier dedup (kind); normalize_raw title_normalized; atomic save merge; ensure_week reset; single BaseScraper; pure is_open/clear_if_due; structured logging (src/log.py); Working Nomads requests-first. Checker round: UTC-only dedup, `_guarded_deliver` notify outside lock, CircuitManager container-ref; 15 new integration tests | PASS — 75 tests green, compile OK; smokes: lock blocks 2nd proc, 7-source dry-run exit 0, nomads API 45 jobs. Open: token rotate, CAPTCHA, linkedin-login, uncommitted |

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

1. **Rotate the Telegram token** (pasted into chat 2026-09-14) via BotFather `/revoke`, update `job_fetching_loop/.env`.
2. **First git commit** — `job_fetching_loop/` is still untracked; stage code+tests+README
   (never `.env`, `.runtime/`, `.slc/`, `.venv/`).
3. `--linkedin-login` once-off session so the LinkedIn source can run.
4. Indeed/Glassdoor: keep fail-closed on Cloudflare CAPTCHA or accept reduced coverage
   (decision for human gate).
5. Verify live run posts to a channel `-1004334348677` (TutorClaw) if the bot gets admin.
6. **Wire remaining 6 curated boards progressively** (next beat): feedcoyote (needs public board route discovery), jobboardsearch (1.1MB meta-search), flexjobs (paywalled/auth), dynamitejobs (job hrefs not in render), virtual_vocations (403), nodesk (no /jobs/ hrefs). Each needs live-verified surface before flipping SOURCE_*=1.

## 11. Human Gate Decisions (job loop)

- 2026-09-14 — Real Telegram token + chat id live in `job_fetching_loop/.env` (gitignored).
  The token was pasted in chat → **MUST rotate** via BotFather `/revoke` before treating
  the bot as trusted. Human action, not a code fix.
- 2026-09-14 — Indeed/Glassdoor CAPTCHAs are handled fail-closed; solving them headed each
  IP-change is accepted as ongoing ops cost unless the human opts for reduced coverage.