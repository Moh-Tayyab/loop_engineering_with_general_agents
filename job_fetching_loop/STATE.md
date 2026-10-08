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

- **Beat #:** 184 — Candidate #3: BoardScraper engine promotion (Maker)
- **Date:** 2026-10-08
- **Trigger:** user — act as senior engineer now run candidate #3
- **Status:** **MAKER DONE.** Implemented Candidate #3 `BoardScraper` abstract engine in `src/scrapers/base.py` promoting browser lifecycle, persistent context, CAPTCHA handling, drift detection, and multi-page pagination. Refactored `indeed.py` and `glassdoor.py` to inherit `BoardScraper`, eliminating >150 lines of boilerplate duplication. Added `tests/test_board_scraper.py`. All 513 tests pass green (100%).

## 3. Beat Log

compressed at 2026-10-08 (beat 164, §9 cap 20): orphan 153 row folded into 153–152 (verdict kept: MAKER DONE 413).

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
recompressed at 2026-09-25 (beat 125, §9 cap): beats 107–109 merged (verdicts kept).
recompressed at 2026-09-25 (beat 128, §9 cap): beats 111–113 merged (verdicts kept).
recompressed at 2026-09-25 (beat 129, §9 cap): beats 101–103 merged (verdicts kept:
accuracy scrape + remote-badge cards, native-Chrome stealth + Bezier Turnstile live 5/5
Indeed + 5/5 Glassdoor, digest-validity gate; all PASS 268 tests).
recompressed at 2026-09-25 (beat 131, §9 cap): beats 104–106 merged (verdicts kept).
recompressed at 2026-09-25 (beat 132, §9 cap): prior 109–107 row folded into the Beat 125 summary (verdicts kept).
recompressed at 2026-09-25 (beat 133, §9 cap): beats 117–118 merged (verdicts kept).
recompressed at 2026-09-25 (beat 134, §9 cap): beat 110 folded into 113–110 summary (verdict kept).
recompressed at 2026-09-25 (beat 135, §9 cap): beats 119–120 merged (verdicts kept).
recompressed at 2026-09-25 (beat 136, §9 cap): beats 131–132 merged (verdicts kept).
recompressed at 2026-09-25 (beat 137, §9 cap): beats 134–135 merged (verdicts kept).
recompressed at 2026-09-25 (beat 139, §9 cap): beats 126–127 merged (verdicts kept).
recompressed at 2026-09-25 (beat 140, §9 cap): beats 129–130 merged (verdicts kept).
recompressed at 2026-09-25 (beat 143, §9 cap): beats 121–123 merged (verdicts kept).
recompressed at 2026-09-30 (beat 144, §9 cap): beats 117–120 merged (verdicts kept).
recompressed at 2026-09-30 (beat 145, §9 cap): beats 141–142 merged (verdicts kept).
recompressed at 2026-09-30 (beat 146, §9 cap): beats 137–138 merged (verdicts kept).
recompressed at 2026-09-30 (beat 147, §9 cap): beats 139–140 merged (verdicts kept).
recompressed at 2026-10-02 (beat 148, §9 cap): beats 121–125 merged (verdicts kept).
recompressed at 2026-10-02 (beat 149, §9 cap): beats 126–130 merged (verdicts kept).
recompressed at 2026-10-02 (beat 150, §9 cap): beats 131–135 merged (verdicts kept).
recompressed at 2026-10-02 (beat 151, §9 cap): PR #15 rows 126–135 + PR #13 rows 117–123 merged into 3 rows (verdicts kept); log back at the 20-row cap.
recompressed at 2026-10-06 (beat 152, §9 cap): beat 116 folded into legacy beats summary (verdict kept: CHECKER REVIEWED 309 green).

| Beat | Date | Trigger | Action | Result |
|------|------|---------|--------|--------|
| 184 | 2026-10-08 | user — run candidate #3 (maker) | Candidate #3 BoardScraper: base.py shared browser/CAPTCHA/page engine; indeed + glassdoor refactored; +4 tests | **MAKER DONE** — 513 passed (100% green) |
| 183–182 | 2026-10-08 | Candidate #2 GateChain + review | 182: GateChain extracted 9 gates, main decoupled +9 tests; 183: Checker review APPROVED 509 live green | **APPROVED** — GateChain live |
| 181 | 2026-10-08 | user — proceed better approach (maker) | Guest timeout headroom fixed under source timeout; pagination early break < 10 cards; expanded remote descriptors; live dry-run PASS | **MAKER DONE** — 493 passed, breaker closed |
| 180–179 | 2026-10-08 | user — location enforcement (§9 compress) | 179: PK onsite/hybrid hard block (9/9 markers drop) +2; 180: mismatch battery 4/4 drop, guest verdict extracted +5 | **MAKER DONE ×2** — 495 → 500 passed |
| 178 | 2026-10-08 | user — linkedin audit response (maker) | 6/8 audit calls correct; (c) declined (Melior proves strictness); pre-filter + hub-first order live-verified; +4 tests | **MAKER DONE** — 493 passed |
| 177 | 2026-10-08 | user — proceed best approach (maker) | `src/location_law.py`: 1 evaluator, 18 flags, stage projections; 3 gates delegate, strictness preserved; +8 tests incl. matrix | **MAKER DONE** — 489 passed, zero behavior change |
| 176 | 2026-10-08 | user — architecture review skill (report) | 5 deepening candidates (LocationLaw, GateChain, BoardScraper, LinkedIn split, DomainRegistry) + top pick; no code, no GLOSSARY/ADR in repo | **DONE** — report open; grilling awaits pick |
| 175 | 2026-10-08 | user — token update in env/secrets (maker) | Token getMe 200 (@muhmmad_assistant_bot); live message delivered; shell clean (no stale env); circuits CLOSED (0 fails); DLQ 0 | **MAKER DONE** — token active & verified |
| 174 | 2026-10-08 | user — pending sweep 2 (maker+checker) | DLQ: 21 stale outage records (0 replayable) backed up + cleared → 0; re-pass 173 APPROVED (481 post-change, cron YAML valid, no secrets) | **APPROVED** — shell/cloud/single-writer stay human |
| 173 | 2026-10-08 | user — pending sweep (maker+checker) | Adversarial 170–172: fixed hollow-ok, timeout gap race, per-call batch dupes + stale-shell guard; +2 tests | **MAKER DONE** — 481 passed; DLQ 21 + shell/cloud-sync stay human |
| 172–171 | 2026-10-08 | user — worldwide max jobs (§9 compress) | 171: deep pages 3→5, board cap 900s, cron 60min, roles data-only; 172: LinkedIn board `_board_url` guest-parity + live volume audit (~50 cards/kw, gates correct) | **MAKER DONE ×2** — 477 → 479 passed |
| 170 | 2026-10-08 | user — indeed multi-domains max jobs (maker) | Default fan-out pk+www+ae+sa+sg; run_source tries ALL closed keys (shared budget, per-key verdicts, shared in-batch dedup); pick_all added; +5 tests | **MAKER DONE** — 474 passed; live multi-domain run pending (fresh CAPTCHA per host) |
| 169 | 2026-10-08 | user — now run next (checker re-pass 167, in-main) | Delta re-pass: data-test hooks lead (diff-verified), bare Apply gone, `:text-is` OK on playwright 1.63, 469 gate post-change green, no secrets/state writes; residual 'Remote' decoy risk inherent + backstop holds | **APPROVED** — no rework; MINOR #1 closed; NOTE: parallel session wrote its own 168 concurrently — single-writer call needed |
| 168–163 | 2026-10-08 | user — CAPTCHA saga (§9 compress) | 163 (PARTIAL): Indeed still walled (6 clicks fail), Glassdoor one auto-solve + cookie save; 168 (parallel): Singleton cleaner + bring_to_front + `--solve` CLI + page recovery +3 tests | **PARTIAL → MAKER DONE** — 469; Glassdoor active, Indeed auto-solved (per 168) |
| 167–166 | 2026-10-08 | user — review cycle 164/165 (§9 compress) | 166: in-main adversarial pass APPROVED with 3 MINORs (spawn failed, task 14); 167: MINOR#1 fixed (data-test first, exact text-is Apply) +2 tests | **APPROVED → MAKER DONE** — 469 passed |
| 165–164 | 2026-10-08 | user — board filters + full-JD (§9 compress) | 164: Glassdoor UI (last-day + remote-only + Apply) + every-card full JD; 165: Indeed parity (fromage/Remote/DSQF7 + auto-apply UI) + every-card full JD; Easy Apply removed both | **MAKER DONE ×2** — 459 → 467 passed |
| 162–160 | 2026-10-07/08 | user — token saga (§9 compress) | 160/161: dead token + Indeed wall → BLOCKED; 162: file token valid (shell stale), 2-job resend delivered `daily:telegram` 10-08 | **BLOCKED ×2 → MAKER DONE** — delivery PASS |
| 159–156 | 2026-10-07 | user — Oct-7 pilot day (§9 compress) | 159: token 401 + any-profile JD gate + SF-DROP/PK-KEEP; 158: keyword union + JD4000 +4 tests; 157: hireability gates +10 (SF-leak closed); 156: PILOT_MODE live, 2 survivors, Telegram 401 → BLOCKED auth | **MAKER DONE ×3 + BLOCKED(auth)** — 448 → 454 |
| 155–152 | 2026-10-06/07 | user — hardening + pilot base (§9 compress) | 153: stealth hardening; 152: Phase 2b + residency pins +7 tests; 155: per-profile scoring +10; 154: profiles engine +15 | **MAKER DONE ×4** — 413 → 438 passed |
| 151–145 | 2026-09-30/10-02 | PR #20 + closed infra (§9 compress) | PR #20 escalation→Option A→merge `e415d52` (reworks 1/2+2/2); PR #25 LOWs APPROVED; Phases 4+5 (`0d4033c`) | **ESCALATED → APPROVED + MAKER DONE ×4** |
recompressed at 2026-10-08 (beat 182, §9 cap 20): beats 117–144 merged (verdicts kept: PRs #13/#15/#16/#20/#25 cycles, phases 1–5, 383–413 green).



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
12. **(Beat 112–113, HUMAN)** Open gaps: (a) ~~PR `job-fetching-loop→main`~~ **DONE Beat 125 — PR #13 merged `6e98459`**; (b) restore-or-drop parked external WIP `/tmp/opencode/b11*_wip*`; (c) Indeed/Glassdoor CAPTCHA once; (d) weekly human spot-check (task 9); (e) ~~confirm Actions schedule~~ resolved Beat 124: `JOB_LOOP_PRIMARY=github` (cloud primary, cron 08:00 PKT weekdays).
13. ~~**(Beat 122, HUMAN, PR #13)**~~ **Fixed Beat 123 (user-authorized):** (A) target-marker exception moved below all hard US pins in `_is_us_restricted` — marker'd text with a real pin now restricts (daily+digest); (B) `is_description_restricted` gained sole-foreign-hyphen, foreign-only-enumeration, and bare `X only` patterns. 314 tests green; awaiting Checker re-review on PR #13.
14. **(Beat 116–118, SHARED INFRA — STILL OPEN)** `checker` subagent spawn: Beat 116 updated `.opencode/agent/checker.md` to `opencode/mimo-v2.6-flash-free`, but a real spawn on 2026-09-24 still fails in the Actions runner ("OpenCode's free tier can only be used from within OpenCode"). Beat 118 Checker pass ran in-main. Needs a runner-side model/creds fix before the next maker→checker cycle.
15. **Proposed durable lesson (human approval):** Evaluate explicit Worldwide/APAC markers only after hard residency-pin detection; add mixed-marker and foreign-city/country-only regressions. (Implemented Beat 123; approve for AGENTS.md §11.)
16. ~~**(Beat 124, HUMAN, shared infra)**~~ **MOSTLY RESOLVED Beats 127+129:** autonomous reviewer **completed twice in a row on PR #15** (11:17Z CR with real findings; 11:46Z re-review verifying R1/R2 fixed) — 45-min timeout (Beat 124 fix) + no stall on either attempt; PR #13's 4× failures look transient/first-run. Keep watching (stall signature: 32-min silence + orphan playwright — `gh run view 36116678518 --log`). Still open: CodeRabbit comment-runs spawning `opencode` noise jobs (2× fast-fail 11:33Z on this PR), and `checker` subagent spawn (task 14). Verdict-waiver precedent applies only to PR #13 (human Option 1).
17. **(Next beat, Mon 2026-09-28 — cloud watchdog):** first weekday cron on **merged `main`** (checkout is default ref, so Monday uses Beat 104–125 code) — verify `gh run list --workflow=job-loop-cron.yml`, `.slc/state.json` advanced, Telegram digest landed, then task-9 spot-check (5 jobs, Rule 11 fidelity, live URLs). **Observed schedule latency:** cron is `0 3 * * 1-5` (03:00Z/08:00 PKT intended) but Sep 24/25 runs were created ~08:20–08:42Z (GitHub queue delay → digest ~13:30 PKT); if the delay persists and 08:00 PKT delivery matters, human decision: accept or shift cron earlier.
18. ~~**(Approved blueprint — remaining phases, amendments A2–A6):**~~ **ALL PHASES LANDED:** Phase 1 (`f1defd6`), Phase 2 (`842223b`), Phase 3 (`e415d52`), Phase 4 (`0d4033c`), Phase 5 (`d2684c9`), and **Phase 2b completed Beat 152** (`session.load()` storage_state wired into `launch_browser` context creation + persistent cookie seeding + `.runtime/` 0700 mode).
19. ~~**(Beat 139→140 — adversarial model block)**~~ **RESOLVED Beat 143:** model fix published to main (`4e5d38f`), adversarial job ran (later cancelled by the merged cycle), **PR #16 MERGED `842223b` (Phase 2 landed)**, and the `[bot]` comment-trigger guard landed as `7fd4d3c` so CodeRabbit/github-actions comments no longer spawn permission-error runs. In-session `checker` subagent spawn still gated (task 14).
20. ~~**(Beat 147, PR #20 A3 — ESCALATED, awaiting human decision):**~~ **RESOLVED Beats 148 & 151:** Option A approved, PR #20 merged (`e415d52`), and PR #25 merged (`778ee5c`).
21. ~~**(Beat 151, PR #25 follow-ups — open, non-blocking):**~~ **RESOLVED Beat 152:** (a) title-path EN pins `must reside in` / `residence in` and description-path `Residence in Germany required` covered; (b) German post-verb locality `müssen wohnen in` and French European `Résidence en Europe` covered; (c) bare `Wohnsitz <locality>` guarded by requirement-phrasing check so questionnaire and Standort frames stay open; (d) negative title fixtures locked (LOW1). 413 tests green.
22. **(Beat 154, PILOT — next)** Wire per-profile scoring into `main.py` `normalize_raw` (scrape once, match twice; keep single `cv_match_score` gate for now vs per-profile filter — human call), combined 2-section Telegram digest, `--dry-run` purity verify, test message to owner before house delivery. Awais expectation set: 1–3 leads/week = success (niche market).
23. **(Beat 155, PILOT GO-LIVE — human)** Set `PILOT_MODE=1` + house `TELEGRAM_CHAT_ID` in `.env` (never commit), run Day-1 live weekday 08:00 PKT, confirm digest lands in house chat. Week-1: track leads/day per profile + reject reasons; Day 4–5 first relevance feedback → blacklist/tier update. Kill/continue gate end Week-2.
24. ~~**(Beat 156, BLOCKED — human token fix)**~~ **RESOLVED Beat 175:** Telegram bot token updated in local `.env` and GitHub secrets; `getMe` HTTP 200 (`@muhmmad_assistant_bot`), test notification delivered successfully (`MESSAGE_DELIVERED: True`).

## 11. Human Gate Decisions (job loop)

- 2026-09-14 — Telegram token was pasted in chat → Rotated via BotFather `/revoke` on 2026-09-16. Store the new token in Actions secrets; never commit `.env`.
- 2026-09-16 — Cloud production is HTTP/JSON/RSS only. Headed CAPTCHA boards are a local ops cost, not a cloud feature.
- 2026-09-14 — Indeed/Glassdoor CAPTCHAs stay fail-closed.
