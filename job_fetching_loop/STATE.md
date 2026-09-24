# STATE.md — Job Fetching Loop (project spine)

> This is the **project spine** for `job_fetching_loop/` — the back of that diary.
> Read `job_fetching_loop/AGENTS.md` (rules) then this file (progress); update THIS file
> last when a beat touches the job loop. There is no root STATE.md or root AGENTS.md —
> this spine pair is fully self-contained (rules + budget live in this loop's `AGENTS.md`).
> (Nested-spine split decided 2026-09-14, beat 28; root files removed beat 30, 2026-09-15.)

## 1. Project Identity

- **Project:** `job_fetching_loop/` — autonomous AI/ML remote-job scraper loop.
- **Scope:** Exclusive 3-platform focus (Beat 79): LinkedIn guest/feed, Indeed (`pk.indeed.com`),
  Glassdoor. Indeed/Glassdoor are local headed Playwright only; cloud cron skips them.
  Non-target scrapers purged (Beat 79).
- **Stack:** Python 3.12, Playwright (local headed + persistent profiles), requests, pytest.
- **Live end-to-end since:** Beat 26 (2026-09-14) — real Telegram delivery.
- **Runners:** GitHub Actions `job-loop-cron.yml` (weekday 08:00 PKT = `0 3 * * 1-5` UTC,
  `.slc/` cache) and local systemd timer `job-fetching-loop.timer` (Beat 96; Persistent=true
  catch-up). Which one is primary follows `JOB_LOOP_PRIMARY`; `both` = both fire (duplicate risk).
- **CI gate:** `.github/workflows/test-gate.yml` runs pytest in
  `working-directory: job_fetching_loop`.

## 2. Current Beat

- **Beat #:** 108 — BairesDev foreign-location FP (B3 too loose) + metro foreign list
- **Date:** 2026-09-24
- **Trigger:** senior-engineer new run — accuracy audit of Sep 23–24 production output
- **Status:** Found 3 FPs (Germany/Chile/Greater Rio BairesDev) passing daily via bare `"worldwide"` marketing in B3; Rio also slipped digest (`\bbrazil\b` miss). Fixed: `_has_strong_worldwide_eligibility` (eligibility phrases only), metro foreign cities, daily+digest foreign/strong-worldwide parity. Purged 3 jobs from `output/jobs_2026-09-2{3,4}.{json,csv}`. Suite **300 pass** | PASS — 300 tests, exit 0

## 3. Beat Log

compressed at 2026-09-17: beats 26–62 all PASS (prod-readiness, spine split, schedule, heartbeat, lock watchdog, weekly retry, volume scaling, scaffolds purge, outage honesty, DLQ replay, salary/cron hardening, strict 24h cutoff, EPIPE shield, feed gate, timeout safety, canonical URL dedup).

compressed at 2026-09-22 (beat 104, §9 cap 20): beats 63–89 all PASS except 82 FAIL
(env incomplete) — salary/24h/cron, checkout-v6, prod audits, gap remediation, cloud cron
08:00 PKT, list-sources clarity, past-24h fail-closed, title/description leak closure,
3-platform exclusive purge, 7 AI keywords, exp-level filter removal, APAC/ME regional sets
(beats 85–89), Pakistan remote integrity (90).

| Beat | Date | Trigger | Action | Result |
|------|------|---------|--------|--------|
| 108 | 2026-09-24 | audit Sep 23–24 output | **B3 tighten + foreign metros:** bare worldwide marketing no longer overrides Germany/Chile/Rio; `_has_strong_worldwide_eligibility`; daily/digest parity; purge 3 BairesDev FPs from output | PASS — 300 tests, exit 0 |
| 107 | 2026-09-22 | user — yes next beat | **Commit Beat 105–106** accuracy-gap remediation + LinkedIn dry-run smoke + worktree drift (workflow keywords, test isolation, snippet-cap) | PASS — 298 tests, exit 0; run 3/3 ceiling → stop |
| 106 | 2026-09-22 | backlog #10 smoke | Live `--dry-run` after Beat 105: LinkedIn guest 45s budget → 71 jobs, 2 detail_drops (B4), purity clean; Indeed → CAPTCHA (human) | PASS (LinkedIn only; Indeed/Glassdoor pending human CAPTCHA) |
| 105 | 2026-09-22 | user — fix all accuracy gaps small pieces | **A1–C5 remediation:** fail-closed location (A1/A2/A9), US cities+title/desc/lang/TZ+daily-weekly parity (A3–A8), hiring markers+no fake dates+full-desc digest (A10–A12), hybrid precision+Israel market+B3 worldwide override (B1–B3), detail-drop visibility (B4), parse_drift+pagination (B5–B6), circuit ops alert+.env sync+score-sorted top5+rejected.jsonl (C1–C5). New `tests/test_accuracy_gaps.py` | PASS — 298 tests, Checker APPROVED |
| 104 | 2026-09-22 | user — prod-ready audit → fix test fail + commit drift + DLQ | **Audit Remediation:** (1) `tests/test_log.py` autouse fixture resets `log_mod._configured` (was leaking → `assert 10 == 30`); (2) Committed 38 worktree files (3-platform purge, Rule 11, beats 76–103) + `setup/` systemd units; gitignored junk; (3) `--replay-dlq` recovered 2 sheets batches live; `--clear-dlq` removed 33 noise → 0; (4) secret scan 0 hits | PASS — 274 tests, exit 0 |
| 103 | 2026-09-21 | user audio — fetch today's jobs live, test accuracy % | **Live Monday 3-Day Scrape:** Indeed/Glassdoor remote-badge detection from card snippets; 2 fresh Indeed AI roles + 1 LinkedIn; `jobs_2026-09-21` JSON/CSV + Sheet; 100% Rule 11 accuracy | PASS — 268 tests, exit 0 |
| 102 | 2026-09-21 | user audio — act human, kill bot detection | **Anti-Bot Alignment:** removed fake JS shims; native Chrome 152 + `AutomationControlled` off; Bezier mouse for Turnstile; live 5/5 Indeed + 5/5 Glassdoor, 0 blocks | PASS — 268 tests, exit 0 |
| 101 | 2026-09-21 | user — digest hallucinations + Monday 3-day backfill | **Digest Quality Gate:** `is_valid_digest_job` (Rule 11, no `/in/`, no Israel, CV≥70); purged 93 invalid seen; Friday-feed only, Mon = jobs sections 3d back; digest W39 12/12 verified | PASS — 268 tests, exit 0 |
| 100 | 2026-09-18 | user — strict 4-phase guardrails + link health | **4-Phase Hardening:** window fail-closed; location whitelist/blacklist; feed `/in/` rejection; `check_link_health` drops 404s | PASS — 266 tests, exit 0 |
| 100b | 2026-09-18 | user — digest leaked 3 live foreign on-site/hybrid jobs | **RECERTIFICATION:** empty feed bodies blinded location law; `_feed_post_to_raw` fail-closed on empty body/`/in/`; digest 20→17 in-scope; restore body capture next | PASS — 265 tests, digest 17/17 |
| 99 | 2026-09-18 | user — `India (Remote)` flagged | **India domestic remote eliminated:** off `_APAC_REGIONS`, on foreign blocklist (worldwide/contract only); purged output | PASS — 262 tests, exit 0 |
| 98 | 2026-09-18 | user — profile URLs + on-site/hybrid leaks | **Profile/Onsite leak elimination:** reject `linkedin.com/in/`; on-site before remote tokens; recruiter titles negative-matched; purged 19 flawed jobs | PASS — 262 tests, exit 0 |
| 97 | 2026-09-18 | user — digest Bangalore on-site + Japan/Korea remote | **Feed DOM rework + developed-APAC hard-block** before `_APAC_REGIONS` carve-out; digest re-gated; stale foreign pruned | PASS — digest 20/20 in-scope |
| 96 | 2026-09-18 | user — missed 08:00 (system off) | **systemd timer** `Persistent=true` catch-up proven; `.last_cron_run` boot catch-up; Telegram ISP-blocked (jobs via files+sheet) | PASS — 251 tests; Telegram blocked (ISP) |
| 95 | 2026-09-17 | user — `pk.indeed` | **pk.indeed.com endpoint** replaces www.indeed.com | PASS — 251 tests, exit 0 |
| 94 | 2026-09-17 | user audio — verify 3-platform pipeline | Browser 300s timeout; CAPTCHA solver on DISPLAY=:0; unattended fail-closed per Rule 10 | PASS — 251 tests, exit 0 |
| 93 | 2026-09-17 | user audio — human cursor/scroll + city parse | Stealth init script; Bezier mouse/hover/click/scroll; right-pane description; `parse_location_hierarchy` | PASS — 251 tests, exit 0 |
| 92 | 2026-09-17 | user audio — why I/G failed, few LinkedIn jobs | Matcher AI roles expansion; `warm_up` → `await_captcha_solve`; 2 live AI jobs scraped | PASS — 251 tests, exit 0 |
| 91 | 2026-09-17 | user — run live pipeline today | Exempt hybrid-RAG; `Location: Remote, Pakistan`; 1 live 97% AI role saved | PASS — 251 tests, exit 0 |
| 90 | 2026-09-17 | user — unworkable foreign/hybrid jobs | **Pakistan remote integrity:** language restrict (JLPT/DE/HE); zero hybrid; Israel blocked; foreign cities need global/contractor; purged 4 | PASS — 251 tests, exit 0 |

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

0. ~~**(Beat 96, BLOCKING)** Telegram ISP block~~ — Beat 104 state shows `daily:telegram: 2026-09-22` marked sent; re-verify with manual `send_daily` if unsure.
1. ~~**Rotate the Telegram token** (pasted into chat 2026-09-14) via BotFather `/replay`~~ (Done 2026-09-16). Ensure `.env` + GitHub secrets `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` hold the new token.
2. Confirm repo secrets exist for the cloud cron (`GOOGLE_SHEET_WEBHOOK_URL` optional). Push so weekday Actions can run.
3. Local systemd timer is standby while `JOB_LOOP_PRIMARY=github`. Set `JOB_LOOP_PRIMARY=local` only if Actions is off.
4. Indeed/Glassdoor remain local-headed only; cloud never waits on CAPTCHA. Circuit breakers may open daily on CAPTCHA timeouts (Rule 10 — expected).
5. Exclusive 3-platform production (Beat 79): linkedin, indeed, glassdoor only.
6. ~~**(Beat 65, HIGH)** Persist `output/` in cron cache~~ Done Beat 66.
7. ~~**(Beat 65, MED)** Sheets DLQ replay + clear~~ Done Beat 66 / re-run Beat 104 (DLQ now 0).
8. ~~Restore LinkedIn feed **description body capture** (Beat 100b)~~ — A9 now fail-closes missing JD bodies in guest path (Beat 105); authenticated feed body capture still worth a live Friday check.
9. **Human spot-check (weekly):** open `output/jobs_*.json` + latest Telegram digest; sample 5 jobs — confirm Rule 11 (APAC/ME remote, Global, or Worldwide contractor only), live URLs, and description_snippet length ≤ 2000. Log pass/fail in beat log.
10. ~~**Live smoke after Beat 105**~~ LinkedIn guest dry-run PASS (Beat 106). **Still open:** Indeed/Glassdoor headed run needs human CAPTCHA solve once (Turnstile blocks unattended dry-run).

## 11. Human Gate Decisions (job loop)

- 2026-09-14 — Telegram token was pasted in chat → Rotated via BotFather `/revoke` on 2026-09-16. Store the new token in Actions secrets; never commit `.env`.
- 2026-09-16 — Cloud production is HTTP/JSON/RSS only. Headed CAPTCHA boards are a local ops cost, not a cloud feature.
- 2026-09-14 — Indeed/Glassdoor CAPTCHAs stay fail-closed.
