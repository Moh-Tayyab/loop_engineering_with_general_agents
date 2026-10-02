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

- **Beat #:** 151 — weekday-9am heartbeat triage (shared-infra CI-blindness fix, prepared)
- **Date:** 2026-10-02
- **Trigger:** schedule — `opencode.yml` `autonomous` job, cron `0 9 * * 1-5`
- **Status:** **ESCALATED (human gate).** Triage: (1) **CI unreadable** — `gh run list
  --workflow=test-gate.yml` and `GET /actions/runs` both HTTP 403, so no failure could be
  triaged this morning; root cause = `opencode.yml` job `autonomous` sets an explicit
  `permissions:` block (unlisted scopes → `none`) with no `actions:` scope, blinding every
  heartbeat since 2026-09-28. Fix prepared (+4 lines, trainer gate 123
  passed; patch-id `406923e6`) but **push is impossible for the loop**: GitHub rejects workflow-file edits from
  this App token (`without workflows permission`). (2) 4 stale open issues (#1/#3/#4/#6) —
  RISKY/AMBIGUOUS, human merge/close call, no code touched (video STATE §10 item 3 holds the
  repro evidence). (3) PR #25 (A3 residual LOWs) is open/MERGEABLE with no grade yet.
  No code changed, no PR opened, no secrets touched.

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
compressed at 2026-10-02 (beat 151, §9 cap): beats 116–136 detail folded here — 116 CHECKER REVIEWED → CHANGES REQUESTED (residual, non-blocking; also fixed retired `checker` model in `.opencode/agent/checker.md`); 117–120 CHECKER CR ×2 (118, 120), MAKER DONE 309→311; 121–123 MAKER DONE 314 CI-green, reviewer cancelled 3× → FREEZE (§7); 124 MAKER DONE 318, checker blocked 4× → FREEZE (§7) + `@Moh-Tayyab` pinged; 125 **PASS** → **PR #13 merged `6e98459`** (verdict waived by human); 126–127 MAKER DONE 333 → CHANGES REQUESTED (0644 save, `str(exc)` leak); 128 MAKER DONE (rework 1/2) 335 (mkstemp 0600 + class-name-only logs); 129–130 MAKER DONE 337 → residual 3 (`OverflowError`) → HUMAN GATE (§7 bound 2/2); 131–132 CHANGES REQUESTED → human gate; 133 MAKER DONE 340 (human-approved bound exception: OverflowError self-heal + `isfinite` expiries); 134–135 CHANGES REQUESTED → MAKER DONE 342 (safe `str(exc)` + guarded `save()`); 136 **APPROVED** → **PR #15 merged `f1defd6` → Phase 1 LANDED**.

| Beat | Date | Trigger | Action | Result |
|------|------|---------|--------|--------|
| 151 | 2026-10-02 | schedule — weekday 9am heartbeat (shared infra) | Triaged CI + issues: Actions API 403 (no `actions:` scope on `opencode.yml` job `autonomous`) → prepared `actions: read` fix (patch-id `406923e6`, trainer gate 123 passed); 4 stale issues re-graded RISKY/AMBIGUOUS; PR #25 still ungraded | **ESCALATED (human)** — push rejected (`without workflows permission`): no loop can edit `.github/workflows/*`; checker spawn blocked (task 14) → no PR |
| 150 | 2026-10-02 | user — proceed with Phase 5 | `job-loop-cron.yml` timeout 20➔45m; `.env.example` multi-domain + session engine variables; `README.md` Docker quickstart | **MAKER DONE (Phase 5)** — 400 passed EXIT 0; CI hardening + docs complete; **all 5 phases landed** |
| 149 | 2026-10-02 | user — "yes" (Phase 4 Containerization) | Dockerfile (`mcr.microsoft.com/playwright/python:v1.62.0-noble`, `USER pwuser`), `docker-compose.yml` (`job-loop` service, `.slc`/`.runtime`/`output` mounts), `.dockerignore`; +3 tests in `test_containerization.py` | **MAKER DONE (Phase 4)** — 400 passed EXIT 0; docker compose config valid; **PR #23 merged `0d4033c`** |
| 148 | 2026-10-02 | user — Option A approved (§7 Human Gate) | Targeted rework M1 (client-HQ scope on basé), M2 (conjunction clause-splits), M3 (nicht zwingend, nicht pflicht, non/pas obligatoire, wohnen möglich), B2 (Berlin/Hamburg/NRW localities in muss/wohnen); +4 regressions (total 19) | **MAKER DONE (Human Option A)** — 397 passed EXIT 0; 24 adversarial repros verified green; **PR #20 merged `e415d52`** |
| 147 | 2026-09-30 | adversarial checker run 36715127038 → §7 escalation | Re-review of rework 2/2 `f1bb3ee`: round-1 fixtures all hold (393 green, gate/encoding/perf/secrets/STATE coherence pass) but **M1 regression** (context-skip broad — 10 company-word fixtures fail-open vs 8a1da19), **M2** conjunction-joined negation (5 fixtures, `und/aber/mais/et` outside clause seps), **M3** 6 missing exempt forms (`nicht zwingend`, `nicht pflicht`, `non/pas obligatoire`, `wohnen ist möglich`) drop worldwide; LOW: 5.3s@704KB exempt path, dead branch | **CHANGES REQUESTED (final) → ESCALATED** — `@Moh-Tayyab` options A/B/C posted (5911584186); frozen, no 3rd rework; beats 145–147 = 3/3 STOP |
| 146 | 2026-09-30 | user — continue (adversarial run 36712129823 CR) | Rework 2/2 FINAL: M1/M2 clause-anchored exemption (seps `[,;:—–()[]]`), newline collapse + sentence-straddle fail-closed (whole-text exempt REMOVED), M3 tail `wohnen\|ansässig\|leben`, M4 suffix `t\|…\|sten` + FR neg forms + kann-wohnen + wohnort-frei + client-HQ skip, NFC; 7 RED-first `test_r2_*` | **MAKER DONE** — 393 passed EXIT 0; `f1bb3ee`; comment 5911302378; §7 LAST rework (next reject → human gate) |
| 145 | 2026-09-30 | user — continue (PR #20 checker M1/M2/M3) | Rework 1/2: M1 7 pins (basé/résident*/résiderez/domiciliation/Wohnort/Aufenthaltserlaubnis), M2 **umlaut root cause** (`müssen`=m-ü) → `(?:u\|ü)(?:ss\|ß)` + country-in-clause + `[^.!?\n]`, M3 per-sentence `_LOCALIZED_RESIDENCY_EXEMPT`; merged origin/main (STATE 143+144+task20); PR body → 378+8=386; re-review comment 5910803656 | **MAKER DONE** — 386 passed EXIT 0; push `8a1da19`; task20 rework 1/2 (1 left §7) |
| 144 | 2026-09-30 | pull_request #20 — A3 localized DE/FR residency (checker, §9 row kept from branch) | Reviewed `7fd4d3c...99150e2`; full job-loop gate, TDD RED repro on base, 14 open-fixture FP sweep, 20 leak/negation probes; no Maker edits (§2 rule 1) | **CHANGES REQUESTED (residual, non-blocking)** — 383 passed EXIT 0; M1 `basé/Wohnort`+FR pins leak, M2 `muss…wohnen` dead for `müssen`/`muß`, M3 no negation guard (`ohne` pin); task 20 |
| 143 | 2026-09-25 | user — start phase-3 + bot guard | A3 TDD: `test_localized_residency.py` first (3 RED: DE Wohnsitz/wohnen/Ansässigkeit, FR résidant/résider/Résidence leaked) → minimal pattern set in `_DESCRIPTION_RESTRICTION_PATTERNS` (worldwide + au/sg pass fixtures locked) — PR #20; bot guard `[bot]` on comment jobs → main `7fd4d3c` | **MAKER DONE** — 383 passed EXIT 0; PR #20 → checker; beats 141–142 went to parallel session (PR #16 merged `842223b`) |
| 142–141 | 2026-09-25 | PR #16 review + rework 2/2 (§9 compress) | 141: CHANGES REQUESTED on `333e8bb` (deadline merge, malformed-state crash, DNS label, dry-run purity; 375 green); 142: rework 2/2 — chronological `open_until`, non-dict merge guards, RFC-1035 63-char label, +3 regressions (**378 green**) | **CHANGES REQUESTED → MAKER DONE (rework 2/2)** → later merged `842223b` |
| 140–139 | 2026-09-25 | PR #16 model-fix sync + rework 1/2 (§9 compress) | 140: model fix `2fed239`→main `4e5d38f` (issue_comment needs default branch), re-trigger `5833222378`, 375 green → **CHANGES REQUESTED ×2 round 2** (lexical `open_until`, merge crash, dry-run writes); 139: `pick_domain_key` fail-closed + env-independent migration + legacy/composite merge, +4/−1 (**375 green**) | **MAKER DONE (rework 1/2) → CHANGES REQUESTED ×2** → rework 2/2 = beat 142 → merged `842223b` |
| 138–137 | 2026-09-25 | Phase 2 (A2) maker + checker (§9 compress) | 137: domain registry (`parse_domains`/`source_domains`, 15-cap, env+cloud split), `domain_key` + migration + `_apply_domain` + `session_file` traversal reject, +30 tests (**372 green**); 138: isolated repro — all-invalid registry fell back to plain `indeed`, hard-coded `pk.indeed.com` | **MAKER DONE → CHANGES REQUESTED** (P1 fail-open registry fallback; review 5317951401) → fixed 139 |



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
18. **(Approved blueprint — remaining phases, amendments A2–A6):** Phase 1 PR #15 — Beat 128 rework fixed R1/R2 (0600 via mkstemp, class-name-only logs, 335); Beat 129 re-review confirmed those, found 2 residuals (rework bound 2/2); **Beat 130 (final rework) fixed both** (`load()` `read_bytes`+`except ValueError` → non-UTF-8 = corruption→unlink; `save()` guarded in `attempt_login` → OSError → class-only log → None; +2 regressions; 337 passed). **Beat 131/132 CHANGES REQUESTED — human gate** (oversized cookie expiry made `load()` raise `OverflowError`); human approved bound exception (a); **Beat 133 landed the fix** (`load()` self-heals on OverflowError → None+unlink, `attempt_login` guards the same signal, non-finite expiries rejected; +3 regressions; 340 passed). **Beats 134–136:** 134 final checker CR (bad `__str__` escape + non-JSON state escape) → human gate; 135 human approved fulfillment → both guards +2 regressions (342); **136 Checker APPROVED (342, 4 repros) and PR #15 MERGED `f1defd6` → PHASE 1 LANDED.** **Phase 2 (A2) MAKER DONE in Beat 137** (branch `phase2-multi-domain`, `b092661`, 372 tests): env domain registry (`INDEED_DOMAINS`/`GLASSDOOR_DOMAINS` + `_CLOUD` split, 15-cap, fail-closed hostname validation, proven pre-Phase-2 defaults = no behaviour change), per-domain circuit keys `source:domain` with legacy-key state migration (history carried, idempotent, never clobbers composites), `prune_unknown` base-aware, `pick_domain_key` first-closed-wins, `run_source` ckey pre-gate (timeout/error/success all keyed; outcomes stay plain source), `_apply_domain` URL bases on Indeed+Glassdoor (+ Glassdoor hardcoded job-listing URL fixed), `session_file` traversal rejection. **Checker CR (Beat 138): all-invalid registry falls back to the default host; Maker fix + regression required. PR #16 cycle CLOSED: rounds 1–2 of fixes (Beats 139/142) → PR #16 MERGED `842223b` → PHASE 2 LANDED (parallel session drove beats 141–142). PHASE 2b DEFERRED (this task): wire `session.load()` storage_state into `launch_browser` — sessions are saved but still unused by the scrape path; do before relying on login sessions in cloud.** Also open: optional `.runtime/` 0700 note (checker non-blocking). **Phase 3 (A3) MAKER DONE Beat 143 — PR #20 open, checker pending:** DE/FR localized-residency TDD (RED on `Wohnsitz`/`résidant` leaks → minimal pattern set → 383 green) + worldwide and au/sg pass fixtures. **Phase 4** Docker: base image must be `mcr.microsoft.com/playwright/python:v1.62.0-noble` (match `requirements.txt` pin, NOT v1.49.0); headless/CI-parity only — human CAPTCHA stays bare-metal (A4). **Phase 5** raise `job-loop-cron.yml` `timeout-minutes: 20`→45 (or domain rotation) BEFORE cloud multi-domain (A5); env docs + README (A6: ≤2 phases per run, ≤3 beats/run, STATE row per phase).

19. ~~**(Beat 139→140 — adversarial model block)**~~ **RESOLVED Beat 143:** model fix published to main (`4e5d38f`), adversarial job ran (later cancelled by the merged cycle), **PR #16 MERGED `842223b` (Phase 2 landed)**, and the `[bot]` comment-trigger guard landed as `7fd4d3c` so CodeRabbit/github-actions comments no longer spawn permission-error runs. In-session `checker` subagent spawn still gated (task 14).
20. **(Beat 147, PR #20 A3 — ESCALATED, awaiting human decision):** frozen after 2 reworks (§7); verdict on `f1bb3ee` = CHANGES REQUESTED (M1 context-skip regression, M2 conjunction scoping, M3 exempt gaps — full lists in comment 5911584186 / run 36715127038). **Do NOT push to `phase3-localized-residency` until @Moh-Tayyab picks option A (targeted 3rd rework — fixtures exist in checker verdict), B (merge as-is, not recommended), or C (revert A3 + follow-up issue).** Then: Phase 4 (Docker `v1.62.0-noble` + compose) → Phase 5 (cron 45m, `.env.example`, README). Still deferred: task 18 (session `load()` wiring), title-path localized pins (LOW).
21. **(Beat 151, shared infra, §7 ESCALATED — HUMAN, blocking all future heartbeats):** add
    `actions: read` to the `permissions:` block of job `autonomous` in `.github/workflows/opencode.yml`.
    Evidence: `gh run list --workflow=test-gate.yml` → `HTTP 403 Resource not accessible by
    integration`; also `gh pr checks 25` → 403 (`statusCheckRollup`), so CI verdicts are invisible
    to every heartbeat since 2026-09-28. Fix is prepared locally (patch-id
    `406923e6`, YAML parses, trainer gate 123 passed) but **`git push` is refused**:
    `refusing to allow a GitHub App to create or update workflow .github/workflows/opencode.yml
    without workflows permission`. Chicken-and-egg: granting `workflows: write` is itself a
    workflow-file edit. Human options: (a) apply the one line from a local clone / PAT;
    (b) one `workflow_dispatch` run with a PAT that has `workflows: write`;
    (c) leave it and accept blind heartbeats. Also unblocks re-verifying PR #25's checks. **Escalation surfaced in PR #26** (docs-only; the
    one-line patch is in the PR body, not the diff — the token cannot push workflow files).
22. **(Beat 151, PR #25 — awaiting a grade):** `fix/localized-lows-title-coverage` (opened
    2026-10-02T07:46Z) closes the two task-20 residual LOWs (title-path localized pins,
    `Wohnsitz` without preposition). State: OPEN, `MERGEABLE/UNSTABLE`, **no review recorded**,
    and its check results are unreadable from this token (task 21). Needs a human-triggered
    `/oc check` (or a runner with `actions: read`) before merge — do not auto-merge.
23. **(Beat 151, stale issues #1/#3/#4/#6 — HUMAN, RISKY/AMBIGUOUS):** re-graded, no code
    touched. Both bugs are still live on `main` (`redact_secrets` leaks all 3 repros; `wrap_text`
    absent) but the candidate fixes already exist as unmerged PRs #5/#7/#8/#9, so a fresh branch
    would duplicate them. The call is merge-vs-close on old loop output → human gate. Evidence
    in video STATE §10 item 3.

## 11. Human Gate Decisions (job loop)

- 2026-09-14 — Telegram token was pasted in chat → Rotated via BotFather `/revoke` on 2026-09-16. Store the new token in Actions secrets; never commit `.env`.
- 2026-09-16 — Cloud production is HTTP/JSON/RSS only. Headed CAPTCHA boards are a local ops cost, not a cloud feature.
- 2026-09-14 — Indeed/Glassdoor CAPTCHAs stay fail-closed.
