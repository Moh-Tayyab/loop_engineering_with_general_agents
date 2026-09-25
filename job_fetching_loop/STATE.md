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

- **Beat #:** 124 — Roadmap Steps 1–3 (CI unblock / topology / secrets) + CodeRabbit critical subset
- **Date:** 2026-09-25
- **Trigger:** user — pasted production roadmap; "fix critical subset now"
- **Status:** **MAKER DONE; CHECKER BLOCKED (infra) — FREEZE (§7, 4 consecutive no-verdict attempts) + human pinged on PR #13.** Done: `opencode.yml` autonomous timeout 20→45 min (`40664a8`, pushed — past the old 20-min kill point); topology answered = GitHub Actions cloud primary (`.env` `JOB_LOOP_PRIMARY=github`, cloud cron 08:00 PKT active); secrets verified (names only); all 15 CodeRabbit comments triaged. Fixed 5 critical items (models.py + circuit_breaker.py + main.py): country-scoped `work from anywhere in <geo>` no longer grants worldwide eligibility; abbr pins now `finditer` on original text + uppercase-only captures (fixes "located in **or** near Lahore"/Karachi false-drop AND masked `must be based in TX`); `Asia Pacific/APAC time` lookbehinds (was dropping in-scope APAC); `\bpolish\b` narrowed to language contexts (was matching "UI polish"); dry-run circuit-open sends **no** ops alert (§2 rule 6). +4 regression tests. **318 passed** EXIT 0; `diff --check` clean. **Checker: run 36116678518 ran full 45 min then cancelled — last activity 09:20:43 (reading `setup/*.service`), then 32-min silent stall (orphan `opencode` + `npm exec @playwright` alive at kill). 4th consecutive attempt with no verdict → §7 FREEZE; `@Moh-Tayyab` pinged on PR #13 with merge/re-trigger/stall-investigation options.**

## 3. Beat Log

compressed at 2026-09-17: beats 26–62 all PASS (prod-readiness, spine split, schedule, heartbeat, lock watchdog, weekly retry, volume scaling, scaffolds purge, outage honesty, DLQ replay, salary/cron hardening, strict 24h cutoff, EPIPE shield, feed gate, timeout safety, canonical URL dedup).

compressed at 2026-09-17 (beat 104, §9 cap 20): beats 63–89 all PASS except 82 FAIL
(env incomplete) — salary/24h/cron, checkout-v6, prod audits, gap remediation, cloud cron
08:00 PKT, list-sources clarity, past-24h fail-closed, title/description leak closure,
3-platform exclusive purge, 7 AI keywords, exp-level filter removal, APAC/ME regional sets
(beats 85–89), Pakistan remote integrity (90).

compressed at 2026-09-24 (beat 109, §9 cap 20): beats 90–96 all PASS — Pakistan remote
integrity, live pipeline, AI matcher, anti-bot Turnstile, 3-platform verify, pk.indeed,
systemd Persistent catch-up (Telegram ISP-blocked that day).

compressed at 2026-09-24 (beat 116, §9 cap 20): beats 97–100b — rule-11 guardrails
(window/Location/feed/link-health), digest empty-body fail-closed, India/JP/KR/Bangalore
blocklist tighten, profile-URL + onsite-before-remote + recruiter-title rejects, digest
20/20. recompressed at 2026-09-25 (beat 121, §9 cap): beats 101–103 merged (verdicts kept).
recompressed at 2026-09-25 (beat 123, §9 cap): beats 104–106 merged (verdicts kept).

| Beat | Date | Trigger | Action | Result |
|------|------|---------|--------|--------|
| 124 | 2026-09-25 | user — roadmap Steps 1–3 + "fix critical subset" | timeout 20→45 (`40664a8`); topology=github, secrets verified, 15 CR comments triaged; CodeRabbit crit ×5 (wfa-country, abbr finditer+isupper, APAC-tz lookbehind, polish context, dry-run ops-alert) +4 tests | **MAKER DONE** — 318 passed; checker blocked 4× (3×20m + 45m run stalled 09:20→kill) → **FREEZE (§7)**, `@Moh-Tayyab` pinged on PR #13 |
| 123 | 2026-09-25 | user — continue (Beat 122 CR findings) | MEDIUM-A markers-after-pins in `_is_us_restricted`; MEDIUM-B sole-foreign-hyphen / foreign-enumeration / bare-`X only` desc patterns; +2 tests (daily+digest) | **MAKER DONE** — 314 passed, CI green on `960b80e`; **Checker blocked: reviewer cancelled 3× at `timeout-minutes: 20` → FREEZE (§7), no verdict**; run 3/3 → stop (§10 task 16) |
| 122 | 2026-09-25 | pull_request sync (`5caa5e4`) | Re-reviewed Beat 121; 312 tests, syntax, diff, and secret checks clean; reproduced marker-override US-pin fail-open and foreign geography-only description leaks in daily+digest | **FAIL — CHANGES REQUESTED (comment)** — two MEDIUM findings posted; no production code changed; human gate |
| 121 | 2026-09-25 | user — continue (Beat 120 CR findings) | MEDIUM-1a `,` in clause charset; MEDIUM-1b `_NON_US_LOCALITY_TOKENS` = FOREIGN\|APAC\|ME; MEDIUM-2 `finditer` + tempered group stop; +3 tests; `diff --check` cleanups | **MAKER DONE** — 312 passed, repros open/pins restrict, secrets clean; push for re-review |
| 120 | 2026-09-25 | pull_request sync (`629b951`) | Re-reviewed Beat 119; ran 311 tests + syntax/secret checks; reproduced comma/APAC-ME false drops and first-match masking of a later US pin | **CHECKER REVIEWED** — CHANGES REQUESTED; posted to PR #13 |
| 119 | 2026-09-25 | user — fix (a) then (b), past §7 bound | (a) foreign-locality-aware group-walk + `&` clause charset; (b) tradeoff-pinning tests; fixed `_utc_today` monkeypatch leak in test_main (UTC-roll suite break) | **MAKER DONE** — 311 passed, repros open/pins restrict, secrets clean; push for re-review |
| 118 | 2026-09-24 | pull_request sync (Beat 117 rework d5c1b23 pushed) | Re-reviewed: 309 green; Beat-116 repros + realistic prose kept open; precision intact. **Residual**: >4-word gate leaves short-clause siblings dropping Worldwide ("Remote - Austin and Berlin", "Remote (New York, London)", "Remote - Texas and Germany"...). 2nd rework → rework bound hit → human gate. `checker` subagent spawn fails again (this pass is the Checker) | **CHECKER REVIEWED** — CHANGES REQUESTED (non-blocking); posted to PR #13 |
| 117 | 2026-09-24 | Checker residual CR on Beat 115 | Pin-gated group-walk (≤4-word qualifiers) + full-text state/abbr residency pins; 5 new repro/pin asserts | **MAKER DONE** — 309 passed, matrix/parity fails=0; push for re-review |
| 116 | 2026-09-24 | pull_request sync (Beat 115 rework pushed) | Re-reviewed PR #13 rework 3eb382f: 309 tests green; repros fixed + pins intact; MEDIUM#2 (HEAD-after-dedup, 1.5s timeout, close) correct; Glassdoor A2 + dead var done. **Residual CHANGES REQUESTED**: `_US_RESTRICTED_RE` hyphen alt + city group-walk still false-drops Worldwide "Remote-first team with offices in Seattle..." / "Remote-first hubs in Austin..." (no comma) — needs pin-gated group-walk. Fixed retired `checker` model in `.opencode/agent/checker.md` (mimo-v2.5-free→v2.6-flash-free) + both AGENTS.md lessons | **CHECKER REVIEWED** — CHANGES REQUESTED (residual, non-blocking); posted to PR #13 |
| 115 | 2026-09-24 | user — run next beat / PR#13 rework | Fixed MEDIUM #1 residency-pin-only city restrict; MEDIUM #2 HEAD-after-dedup + 1.5s timeout + response close; Glassdoor A2; dead var; 4 regression tests | **MAKER DONE** — suite EXIT 0, matrix/parity fails=0; awaiting Checker |
| 114 | 2026-09-24 | PR #13 review (job→main) | Reviewed Beats 104–112 diff; 305 tests green; posted CHANGES REQUESTED(comment): desc-level `_is_us_restricted` drops Worldwide roles naming a US office; per-job `check_link_health` HEAD budget risk; LOW nits (service path hardcode, catch-up stamp, has_captcha card-clean, dead vars, Glassdoor location fabrication, stale STATE "uncommitted" text) | **DONE** — review sent; findings to human gate |
| 113 | 2026-09-24 | user — option c (stop) | Run stop after Beat 112; listed 5 open human-owned gaps | **STOPPED** — 2/3 beats; no further work |
| 112 | 2026-09-24 | user — 100% production ready | Commit+push Beat 111 F1–F4 (4 files) to origin; video gitignore hygiene (`loop.log`, `.agents/`, `skills-lock.json`) | **PASS** — HEAD=origin, 305 tests, secrets clean |
| 111 | 2026-09-24 | user — continue / fix accuracy gaps | Fixed Beat 110 F1–F3 + **F4 drop Hybrid Cloud carve-out** + F1 residuals (`not only` / `the only thing` / `non-US persons only`); 305 tests, matrix 34/34, parity 34/34 | **PASS** — Checker R4 `APPROVED`; not committed |
| 110 | 2026-09-24 | user — residual leak hunt | R4 fixes + `_usa_token_polarity_open` in `_is_us_restricted`; 305 tests green | **CHANGES REQUESTED** — same-clause open-neg suppresses hard pin; recruiter inverse (`Technical Recruiter - Engineering`) opens; underscore country/`Software_Engineer_Recruiting_Solutions` inconsistent. Frozen, uncommitted |
| 109 | 2026-09-24 | backlog #2 push | Pushed `job-fetching-loop` 02955e9→68de118 (Beats 104–108) so cloud cron runs fixed filters | PASS — remote synced, secrets clean |
| 108 | 2026-09-24 | audit Sep 23–24 output | **B3 tighten + foreign metros:** bare worldwide marketing no longer overrides Germany/Chile/Rio; `_has_strong_worldwide_eligibility`; daily/digest parity; purge 3 BairesDev FPs from output | PASS — 300 tests, exit 0 |
| 107 | 2026-09-22 | user — yes next beat | **Commit Beat 105–106** accuracy-gap remediation + LinkedIn dry-run smoke + worktree drift | PASS — 298 tests, exit 0; run 3/3 ceiling → stop |
| 106–104 | 2026-09-22 | backlog/user beats (§9 compress) | 106: LinkedIn dry-run smoke → 71 jobs, B4 drops visible, Indeed CAPTCHA. 105: A1–C5 accuracy remediation (fail-closed location, filter parity, hybrid/Israel/B3, circuit alert) + `test_accuracy_gaps.py`. 104: test isolation, 38-file drift commit, DLQ replay→0 | **PASS** — 274–298 tests; Beat 105 Checker APPROVED |
| 103–101 | 2026-09-21 | user/audio beats (§9 compress) | 103: Monday 3-day live accuracy scrape + remote-badge cards (100% Rule 11). 102: native Chrome stealth + Bezier Turnstile → live 5/5 Indeed + 5/5 Glassdoor. 101: `is_valid_digest_job` gate, purged 93 invalid seen, digest W39 12/12 | **PASS** — 268 tests each |

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
2. ~~Confirm repo secrets exist for the cloud cron (`GOOGLE_SHEET_WEBHOOK_URL` optional). Push so weekday Actions can run.~~ — Pushed Beat 109 (2026-09-24); cloud HEAD = `68de118`.
3. Local systemd timer is standby while `JOB_LOOP_PRIMARY=github`. Set `JOB_LOOP_PRIMARY=local` only if Actions is off.
4. Indeed/Glassdoor remain local-headed only; cloud never waits on CAPTCHA. Circuit breakers may open daily on CAPTCHA timeouts (Rule 10 — expected).
5. Exclusive 3-platform production (Beat 79): linkedin, indeed, glassdoor only.
6. ~~**(Beat 65, HIGH)** Persist `output/` in cron cache~~ Done Beat 66.
7. ~~**(Beat 65, MED)** Sheets DLQ replay + clear~~ Done Beat 66 / re-run Beat 104 (DLQ now 0).
8. ~~Restore LinkedIn feed **description body capture** (Beat 100b)~~ — A9 now fail-closes missing JD bodies in guest path (Beat 105); authenticated feed body capture still worth a live Friday check.
9. **Human spot-check (weekly):** open `output/jobs_*.json` + latest Telegram digest; sample 5 jobs — confirm Rule 11 (APAC/ME remote, Global, or Worldwide contractor only), live URLs, and description_snippet length ≤ 2000. Log pass/fail in beat log.
10. ~~**Live smoke after Beat 105**~~ LinkedIn guest dry-run PASS (Beat 106). **Still open:** Indeed/Glassdoor headed run needs human CAPTCHA solve once (Turnstile blocks unattended dry-run).
11. ~~**(Beat 110, ESCALATED)**~~ Done Beat 111 (PASS); **committed+pushed Beat 112.** External WIP still parked in `/tmp/opencode/b11*_wip*` (Dockerfile, docker-compose, .github workflows, config/linkedin drift) — decide restore vs drop.
12. **(Beat 112–113, HUMAN)** Open gaps: (a) PR `job-fetching-loop→main` so test-gate runs on GitHub; (b) restore-or-drop parked external WIP `/tmp/opencode/b11*_wip*`; (c) Indeed/Glassdoor CAPTCHA once; (d) weekly human spot-check (task 9); (e) confirm Actions schedule intentionally off (`JOB_LOOP_PRIMARY=local`). STATE Beat 113 row uncommitted.
13. ~~**(Beat 122, HUMAN, PR #13)**~~ **Fixed Beat 123 (user-authorized):** (A) target-marker exception moved below all hard US pins in `_is_us_restricted` — marker'd text with a real pin now restricts (daily+digest); (B) `is_description_restricted` gained sole-foreign-hyphen, foreign-only-enumeration, and bare `X only` patterns. 314 tests green; awaiting Checker re-review on PR #13.
14. **(Beat 116–118, SHARED INFRA — STILL OPEN)** `checker` subagent spawn: Beat 116 updated `.opencode/agent/checker.md` to `opencode/mimo-v2.6-flash-free`, but a real spawn on 2026-09-24 still fails in the Actions runner ("OpenCode's free tier can only be used from within OpenCode"). Beat 118 Checker pass ran in-main. Needs a runner-side model/creds fix before the next maker→checker cycle.
15. **Proposed durable lesson (human approval):** Evaluate explicit Worldwide/APAC markers only after hard residency-pin detection; add mixed-marker and foreign-city/country-only regressions. (Implemented Beat 123; approve for AGENTS.md §11.)
16. **(Beat 124, HUMAN, shared infra — STILL OPEN)** Autonomous reviewer has now failed **4× with no verdict**: 3× cancelled at 20 min (fixed Beat 124 → `timeout-minutes: 45`, `40664a8`), then run 36116678518 ran the full 45 min — last log activity 09:20:43 (reading `setup/*.service`), then a **32-min silent stall** (orphan `opencode` + `npm exec @playwright` still alive at kill) → cancelled. Human options: (a) re-trigger `gh workflow run opencode.yml` / push to retry once (stall may be transient model-API hang), (b) merge PR #13 on test-gate green + CodeRabbit review without an autonomous verdict, (c) dig into the stall (logs: `gh run view 36116678518 --log`), (d) stop CodeRabbit review-comments from spawning `opencode` comment-runs ("Comments must mention /opencode" noise — 6 runs). §7 freeze active until a human picks one.

## 11. Human Gate Decisions (job loop)

- 2026-09-14 — Telegram token was pasted in chat → Rotated via BotFather `/revoke` on 2026-09-16. Store the new token in Actions secrets; never commit `.env`.
- 2026-09-16 — Cloud production is HTTP/JSON/RSS only. Headed CAPTCHA boards are a local ops cost, not a cloud feature.
- 2026-09-14 — Indeed/Glassdoor CAPTCHAs stay fail-closed.
