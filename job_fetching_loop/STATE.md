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

- **Beat #:** 145 — weekday 9am heartbeat: triage; CLEAR FIX found for CI-blindness but **HUMAN GATE** (2 hard blockers)
- **Date:** 2026-09-30
- **Trigger:** schedule (`0 9 * * 1-5` autonomous job, branch `opencode/schedule-d9af64-*`)
- **Status:** **TRIAGE + ONE BLOCKED CLEAR FIX — no PR, no landed code.** 0 new issues (#1/#3/#4/#6 all Aug-era, #3+#4 duplicates, each with an open stale PR). Ran the real gate locally since CI is blind: **job loop 378 passed EXIT 0 on `main`** (up from 306 on Beat 144 — Phase 2 is in), **root+video 273 passed / 1 failed** (env-only `ffprobe` absence, PR #10 already covers it). **Root cause of CI-blindness re-diagnosed and fixed in the working tree:** `autonomous` job declared no `actions` scope → `gh run list`, `actions/runs` AND `gh pr view --json statusCheckRollup` all 403. Commit `a4e6951` (6 lines, one job, `actions: read`) is **NOT pushed and NOT in any branch** — `git push` **rejected again**: *"refusing to allow a GitHub App to create or update workflow `.github/workflows/opencode.yml` without `workflows` permission"* (2nd occurrence, Beat 143 hit the same wall). **`checker` spawn failed a 5th time** (`OpenCode's free tier can only be used from within OpenCode`) → no APPROVED verdict obtainable, so §2 rule 1 forbids a PR even if the push were allowed. Freeze per §7. **Next: human applies the 1-line patch + unblocks the checker runner (task 20 + 14).** `PASS` (triage complete; 0 product code changed)

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
recompressed at 2026-09-25 (beat 138, §9 cap): beats 110–113 merged (111–113 PASS; 110 CHANGES REQUESTED).
recompressed at 2026-09-25 (beat 141, §9 cap): beats 114–115 merged (114 CR; 115 Maker done, verdicts kept).
recompressed at 2026-09-25 (beat 142, §9 cap): beats 121–122 merged (verdicts kept).
recompressed at 2026-09-30 (beat 145, §9 cap): beat 116 folded in — re-reviewed PR #13 rework
3eb382f, 309 green, repros+pins intact, Glassdoor A2 + dead var done; **residual CR** (`_US_RESTRICTED_RE`
hyphen alt + no-comma city group-walk false-dropping Worldwide "Remote-first … offices in
Seattle/Austin" → needs pin-gated group-walk), non-blocking, posted to PR #13; also fixed the
retired `checker` model id in `.opencode/agent/checker.md` + both AGENTS.md lessons.

| Beat | Date | Trigger | Action | Result |
|------|------|---------|--------|--------|
| 145 | 2026-09-30 | schedule — weekday 9am heartbeat | 0 new issues; local gate substitute run (job 378 EXIT 0; root+video 273p/1f env-only); re-diagnosed CI 403 → `actions: read` on `autonomous` job, commit `a4e6951`; push rejected (App token, no `workflows`); `checker` spawn fail #5 | **HUMAN GATE** — CLEAR FIX prepared but unlandable (push scope + no verdict); video-loop 1 failure already covered by PR #10; freeze §7 |
| 143 | 2026-09-25 | user — start phase-3 + bot guard | A3 TDD: `test_localized_residency.py` first (3 RED: DE Wohnsitz/wohnen/Ansässigkeit, FR résidant/résider/Résidence leaked) → minimal pattern set in `_DESCRIPTION_RESTRICTION_PATTERNS` (worldwide + au/sg pass fixtures locked) — PR #20; bot guard `[bot]` on comment jobs → main `7fd4d3c` | **MAKER DONE** — 383 passed EXIT 0; PR #20 → checker; beats 141–142 went to parallel session (PR #16 merged `842223b`) |
| 142 | 2026-09-25 | user — "yh tum kar do" (rework 2/2) | Chronological `open_until` parsed instant comparison; non-dict legacy/composite merge guards; RFC 1035 max 63 DNS label length check; +3 regressions | **MAKER DONE (rework 2/2)** — 378 passed EXIT 0; ready for final re-review |
| 141 | 2026-09-25 | pull_request #16 — current-head review | Reviewed `origin/main...333e8bb`; full job-loop pytest, compileall, diff check, and targeted probes; posted summary review | **CHANGES REQUESTED** — P1 deadline merge, malformed-state crash/history loss, DNS label validation, and dry-run purity; 375 tests pass; rework 2/2 human gate |
| 140 | 2026-09-25 | user — proceed with checker review (model fix 2fed239) | Published `2fed239`→main as `4e5d38f` (issue_comment runs use default branch — fix was PR-branch-only); `/opencode check` re-triggered (`5833222378`); round-1 fixes confirmed passing (375) | **CHANGES REQUESTED ×2 (round 2)** — lexical `open_until` merge, malformed-state merge crash, dry-run mkdir/quarantine writes, WS nit; adversarial in flight → **rework 2/2 next run (§7, last retry)** |
| 139 | 2026-09-25 | user — continue (Beat 138 CR) | `pick_domain_key`: registry source + empty domain list → None (fail-closed, no plain-key fallback); migration → `cfg.default_domain()` hardcoded host (env-independent, runs under broken env); legacy+composite merge (totals sum, consecutive max, later deadline); +4/−1 regressions; P1 repro re-verified | **MAKER DONE (rework 1/2)** — 375 passed EXIT 0; `1095508` pushed → checker re-review; adversarial §6 blocked on task 19 |
| 138 | 2026-09-25 | pull_request #16 — Phase 2 (A2) checker | Isolated repro: all-invalid nonempty `INDEED_DOMAINS` returns `[]`; `pick_domain_key` falls back to plain `indeed`, and Indeed uses hard-coded `pk.indeed.com`. Full 372-test gate passed. | **CHANGES REQUESTED** — P1 fail-open registry fallback; Maker fix + regression required; review 5317951401 |
| 137 | 2026-09-25 | user — proceed to Phase 2 (A2) | Domain registry (`parse_domains`/`source_domains`, 15-cap, env+cloud split, proven defaults); `domain_key` + legacy-key migration + base-aware `prune_unknown` + `pick_domain_key`; `run_source` ckey pre-gate (timeout/error/success keyed, outcomes plain); `_apply_domain` URL bases on both scrapers; `session_file` traversal rejection (PR #15 note); +30 tests | **MAKER DONE — 372 passed EXIT 0; `b092661` on `phase2-multi-domain` → checker gate; Phase 2b (storage_state `load()` wiring) deferred to task18** |
| 136 | 2026-09-25 | user — verify & approve PR #15 | Checker pass on `731f934` (not authored by me): audited both guards, 342-test gate, 4 hand repros (bad `__str__`, circular, unserializable, CAPTCHA+secret scan); APPROVED verdict as review comment (self-approve blocked by GitHub) | **APPROVED** — **PR #15 merged `f1defd6` → Phase 1 LANDED**; Phase 2 next run |
| 134–135 | 2026-09-25 | PR #15 final checker + human gate (§9 compress) | 134: adversarial probes found malformed `__str__` escaping CAPTCHA classification + non-JSON state escaping the OSError save guard → **CHANGES REQUESTED, human gate, rework 2/2**; 135 (user-approved): safe `str(exc)` conversion + `(OSError, TypeError, ValueError)` save guard, +2 regressions | **CHANGES REQUESTED → MAKER DONE** — 342 passed EXIT 0; PR #15 ready to land |
| 133 | 2026-09-25 | user — approved option (a), bound exception | `load()` catches `OverflowError` → corrupt path (unlink+None); `attempt_login` guards same signal; non-finite expiries rejected (`math.isfinite`); +3 regressions (1000-digit expiry, inf/nan, corrupt `do_login`) | **MAKER DONE** — 340 passed EXIT 0; repro None+unlinked; pushed → final verdict pending |
| 132–131 | 2026-09-25 | PR #15 checker syncs (§9 compress) | 132: re-review of `c2321b3` (overflow still raised, still on disk); 131: final review of `169fddb` (repro'd OverflowError escape) | **CHANGES REQUESTED — human gate** both; rework 2/2 exhausted → human approved option (a) |
| 130–129 | 2026-09-25 | PR #15 rework cycle (§9 compress) | 129: re-review of `4aad984` — R1/R2 fixed, found `load()` non-UTF-8 raise + unguarded `save()` (**CR 2/2**); 130 (final rework): `read_bytes`+`except ValueError`, `save()` guarded, +2 regressions, repros hand-verified | **MAKER DONE** 337 → **residual 3 (`OverflowError`) → HUMAN GATE** (§7 bound 2/2, no 3rd rework) |
| 128 | 2026-09-25 | rework of Beat 127 checker CR (PR #15) | R1: `save()` 0644→`tempfile.mkstemp` 0600 + `stat` regression; R2: login/load logs → exception class name/outcome only (module-wide) + `caplog` regression (generic + CAPTCHA branches) | **MAKER DONE (rework 1/2)** — 335 passed EXIT 0; pushed for re-review |
| 127–126 | 2026-09-25 | user/PR #15 Phase 1 open (§9 compress) | 126: approved blueprint, built `src/session.py` (atomic storage_state, A1 cloud refusal, bounded CAPTCHA-fail-closed login) +15 tests; 127: reviewed with 333-test gate + adversarial probes | **MAKER DONE** 333 → **CHANGES REQUESTED** (0644 save, `str(exc)` leak) → Beat 128 rework |
| 125 | 2026-09-25 | user — forwarded summary, Option 1 (merge PR #13 now) | Applied 2 CodeRabbit minors from 10:10 review: wfa guard admits `in world` (`(?:the\s+)?`); polish requirement-context patterns (`Polish required`, `Fluency in Polish required`); +2 asserts; cancelled stalled reviewer; merged | **PASS** — 318 passed + test-gate green on `e9d3ec7`; **PR #13 merged `6e98459`** (verdict waived by human, 4× infra stall); branch deleted |
| 124 | 2026-09-25 | user — roadmap Steps 1–3 + "fix critical subset" | timeout 20→45 (`40664a8`); topology=github, secrets verified, 15 CR comments triaged; CodeRabbit crit ×5 (wfa-country, abbr finditer+isupper, APAC-tz lookbehind, polish context, dry-run ops-alert) +4 tests | **MAKER DONE** — 318 passed; checker blocked 4× (3×20m + 45m run stalled 09:20→kill) → **FREEZE (§7)**, `@Moh-Tayyab` pinged on PR #13 |
| 123–121 | 2026-09-25 | user/checker PR #13 cycle (§9 compress) | 123: markers-after-pins + foreign-hyphen/enumeration/bare-`X only` desc patterns (+2); 122: CR on 121 (US pin fail-open); 121: clause charset, locality tokens, finditer stop (+3) | **MAKER DONE** 314 CI-green + 312 green; **CR then reviewer cancelled 3× → FREEZE (§7)** (task 16) |
| 120–119 | 2026-09-25 | checker sync/user beats (§9 compress) | 120: CR on Beat 119; 119: foreign-aware group-walk + & clause charset, fixed _utc_today monkeypatch leak | **CHECKER CR; MAKER DONE** 311 green |
| 118–117 | 2026-09-24 | checker sync/residual beats (§9 compress) | 118: re-reviewed Beat-117 (short-clause sibling drops residual → bound hit → human gate); 117: pin-gated group-walk + residency pins, +5 tests | **CHECKER CR** (non-blocking, PR #13); **MAKER DONE** 309 green |



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
14. **(SHARED INFRA — STILL OPEN, now 5th occurrence)** `checker` subagent spawn: `.opencode/agent/checker.md` is already on `opencode/mimo-v2.6-flash-free`, but a real spawn on 2026-09-30 failed for the **5th** time (`OpenCode's free tier can only be used from within OpenCode`). It is a **runner-side free-tier restriction, not the model id**, and it blocks EVERY maker→checker cycle in the trainer ⇒ **no PR is permissible anywhere in this repo** until a human fixes it. Tried again with a full diff+test-results handoff (Beat 145) — same error, so it is not a prompt/permissions problem. Needs a runner-side model/creds fix.
20. **(Beat 143/145, SHARED INFRA — HUMAN GATE, CI-BLIND, 3rd heartbeat)** `gh run list --workflow=test-gate.yml` returns `HTTP 403: Resource not accessible by integration`; `actions/runs` and `gh pr view --json statusCheckRollup` fail the same way, while issues/PRs work. **Root cause (confirmed twice, fix prepared):** a job-level `permissions:` block REPLACES GitHub's default token scopes and the `autonomous` job never declared `actions`. **Ready-to-apply patch = commit `a4e6951` (local branch `fix/heartbeat-actions-read`, 6 added lines, `autonomous` job only):**
    ```yaml
        permissions:
          id-token: write
          contents: write
          pull-requests: write
          issues: write
    +      actions: read
    ```
    **It cannot be pushed by this agent — `git push` is rejected: *"refusing to allow a GitHub App to create or update workflow `.github/workflows/opencode.yml` without `workflows` permission"* (Beat 143 and Beat 145, identical).** Human must either (a) hand-apply the 6 lines above, or (b) grant the runner `workflows: write`. **I deliberately did NOT self-grant `workflows: write`** — it would let an autonomous agent rewrite CI to exfiltrate secrets. Note the `adversarial-checker` job has the same missing scope (deliberately left out of the patch: it is a separate, comment-triggered job). Until this lands, heartbeats are structurally blind to CI and must keep using the local gate substitute.
15. **Proposed durable lesson (human approval):** Evaluate explicit Worldwide/APAC markers only after hard residency-pin detection; add mixed-marker and foreign-city/country-only regressions. (Implemented Beat 123; approve for AGENTS.md §11.)
16. ~~**(Beat 124, HUMAN, shared infra)**~~ **MOSTLY RESOLVED Beats 127+129:** autonomous reviewer **completed twice in a row on PR #15** (11:17Z CR with real findings; 11:46Z re-review verifying R1/R2 fixed) — 45-min timeout (Beat 124 fix) + no stall on either attempt; PR #13's 4× failures look transient/first-run. Keep watching (stall signature: 32-min silence + orphan playwright — `gh run view 36116678518 --log`). Still open: CodeRabbit comment-runs spawning `opencode` noise jobs (2× fast-fail 11:33Z on this PR), and `checker` subagent spawn (task 14). Verdict-waiver precedent applies only to PR #13 (human Option 1).
17. **(Next beat, Mon 2026-09-28 — cloud watchdog):** first weekday cron on **merged `main`** (checkout is default ref, so Monday uses Beat 104–125 code) — verify `gh run list --workflow=job-loop-cron.yml`, `.slc/state.json` advanced, Telegram digest landed, then task-9 spot-check (5 jobs, Rule 11 fidelity, live URLs). **Observed schedule latency:** cron is `0 3 * * 1-5` (03:00Z/08:00 PKT intended) but Sep 24/25 runs were created ~08:20–08:42Z (GitHub queue delay → digest ~13:30 PKT); if the delay persists and 08:00 PKT delivery matters, human decision: accept or shift cron earlier.
18. **(Approved blueprint — remaining phases, amendments A2–A6):** Phase 1 PR #15 — Beat 128 rework fixed R1/R2 (0600 via mkstemp, class-name-only logs, 335); Beat 129 re-review confirmed those, found 2 residuals (rework bound 2/2); **Beat 130 (final rework) fixed both** (`load()` `read_bytes`+`except ValueError` → non-UTF-8 = corruption→unlink; `save()` guarded in `attempt_login` → OSError → class-only log → None; +2 regressions; 337 passed). **Beat 131/132 CHANGES REQUESTED — human gate** (oversized cookie expiry made `load()` raise `OverflowError`); human approved bound exception (a); **Beat 133 landed the fix** (`load()` self-heals on OverflowError → None+unlink, `attempt_login` guards the same signal, non-finite expiries rejected; +3 regressions; 340 passed). **Beats 134–136:** 134 final checker CR (bad `__str__` escape + non-JSON state escape) → human gate; 135 human approved fulfillment → both guards +2 regressions (342); **136 Checker APPROVED (342, 4 repros) and PR #15 MERGED `f1defd6` → PHASE 1 LANDED.** **Phase 2 (A2) MAKER DONE in Beat 137** (branch `phase2-multi-domain`, `b092661`, 372 tests): env domain registry (`INDEED_DOMAINS`/`GLASSDOOR_DOMAINS` + `_CLOUD` split, 15-cap, fail-closed hostname validation, proven pre-Phase-2 defaults = no behaviour change), per-domain circuit keys `source:domain` with legacy-key state migration (history carried, idempotent, never clobbers composites), `prune_unknown` base-aware, `pick_domain_key` first-closed-wins, `run_source` ckey pre-gate (timeout/error/success all keyed; outcomes stay plain source), `_apply_domain` URL bases on Indeed+Glassdoor (+ Glassdoor hardcoded job-listing URL fixed), `session_file` traversal rejection. **Checker CR (Beat 138): all-invalid registry falls back to the default host; Maker fix + regression required. PR #16 cycle CLOSED: rounds 1–2 of fixes (Beats 139/142) → PR #16 MERGED `842223b` → PHASE 2 LANDED (parallel session drove beats 141–142). PHASE 2b DEFERRED (this task): wire `session.load()` storage_state into `launch_browser` — sessions are saved but still unused by the scrape path; do before relying on login sessions in cloud.** Also open: optional `.runtime/` 0700 note (checker non-blocking). **Phase 3 (A3) MAKER DONE Beat 143 — PR #20 open, checker pending:** DE/FR localized-residency TDD (RED on `Wohnsitz`/`résidant` leaks → minimal pattern set → 383 green) + worldwide and au/sg pass fixtures. **Phase 4** Docker: base image must be `mcr.microsoft.com/playwright/python:v1.62.0-noble` (match `requirements.txt` pin, NOT v1.49.0); headless/CI-parity only — human CAPTCHA stays bare-metal (A4). **Phase 5** raise `job-loop-cron.yml` `timeout-minutes: 20`→45 (or domain rotation) BEFORE cloud multi-domain (A5); env docs + README (A6: ≤2 phases per run, ≤3 beats/run, STATE row per phase).

19. ~~**(Beat 139→140 — adversarial model block)**~~ **RESOLVED Beat 143:** model fix published to main (`4e5d38f`), adversarial job ran (later cancelled by the merged cycle), **PR #16 MERGED `842223b` (Phase 2 landed)**, and the `[bot]` comment-trigger guard landed as `7fd4d3c` so CodeRabbit/github-actions comments no longer spawn permission-error runs. In-session `checker` subagent spawn still gated (task 14).

## 11. Human Gate Decisions (job loop)

- 2026-09-14 — Telegram token was pasted in chat → Rotated via BotFather `/revoke` on 2026-09-16. Store the new token in Actions secrets; never commit `.env`.
- 2026-09-16 — Cloud production is HTTP/JSON/RSS only. Headed CAPTCHA boards are a local ops cost, not a cloud feature.
- 2026-09-14 — Indeed/Glassdoor CAPTCHAs stay fail-closed.
