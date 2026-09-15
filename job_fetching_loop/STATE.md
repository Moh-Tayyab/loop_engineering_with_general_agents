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

- **Beat #:** 35 — Team bug fixes: location parsing, expired jobs, scraper quality
- **Date:** 2026-09-15
- **Trigger:** manual — team feedback: location bug ("Remote, Oregon" treated as remote), expired jobs not filtered, Indeed/Glassdoor returning low-quality results
- **Status:** Done — `classify_location` rewritten (city names "Remote, OR" + city-restricted "Remote in Brooklyn, NY" no longer match as remote); `is_worldwide_remote` added for strict location filter; `is_expired_job` detects closed/expired/filled titles+descriptions; `is_remotely_workable` updated to use location text when available; Indeed scraper now extracts posted_date + description (3 selector fallbacks); Glassdoor scraper company extraction fixed (7 selector fallbacks) + description + date added; 36 model tests + full suite green. `PASS`

## 3. Beat Log

| Beat | Date | Trigger | Action | Result |
|------|------|---------|--------|--------|
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