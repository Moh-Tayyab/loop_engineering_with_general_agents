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

- **Beat #:** 144 — weekday 9am heartbeat: triage only, no code (CI blind + checker spawn frozen)
- **Date:** 2026-09-29
- **Trigger:** schedule (`0 9 * * 1-5` autonomous job)
- **Status:** **TRIAGE ONLY — no code, no PR.** Built a local CI substitute (CI is 403-blind): installed both loops' requirements + `pip install -e .` + pytest, then ran the exact two `test-gate.yml` commands → **job loop 306 tests EXIT 0; root+video 273 passed, 1 failed** (`test_clip_is_real_video_rejects_empty_and_audio_only` — env-only: ffprobe absent on this runner, CI apt-installs ffmpeg; the fix for that hermeticity gap is already open as PR #10). No new issues (4 stale: #1/#3/#4/#6, all Aug). Both human-gate blockers re-confirmed unchanged: Actions API 403 (no `actions: read`) and `checker` spawn failure — **4th occurrence**. Issue #6 verified **REAL on main** (repro below). `PASS` (nothing committed)

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
recompressed at 2026-09-25 (beat 138, §9 cap): beats 110–113 merged (111–113 PASS; 110 CHANGES REQUESTED).
recompressed at 2026-09-25 (beat 141, §9 cap): beats 114–115 merged (114 CR; 115 Maker done, verdicts kept).
recompressed at 2026-09-25 (beat 142, §9 cap): beats 121–122 merged (verdicts kept).

| Beat | Date | Trigger | Action | Result |
|------|------|---------|--------|--------|
| 144 | 2026-09-29 | schedule — weekday 9am heartbeat | Triage: 0 new issues (4 stale Aug #1/#3/#4/#6); Actions still 403; built local CI substitute (deps + `pip install -e .` + the 2 test-gate commands): job 306 EXIT 0, root+video 273p/1 env-only fail. Issue #6 leak repro'd on main; video ffprobe gap = open PR #10. `checker` spawn failed 4th time | **PASS (triage only, no code, no PR)** — §2 rule 1 blocks PRs; human gate tasks 14/20 |
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
| 123 | 2026-09-25 | user — continue (Beat 122 CR findings) | MEDIUM-A markers-after-pins in `_is_us_restricted`; MEDIUM-B sole-foreign-hyphen / foreign-enumeration / bare-`X only` desc patterns; +2 tests (daily+digest) | **MAKER DONE** — 314 passed, CI green on `960b80e`; **Checker blocked: reviewer cancelled 3× at `timeout-minutes: 20` → FREEZE (§7), no verdict**; run 3/3 → stop (§10 task 16) |
| 122–121 | 2026-09-25 | checker sync/user beats (§9 compress) | 122: CR on Beat 121 (US pin fail-open); 121: `,` clause charset, `_NON_US_LOCALITY_TOKENS`, finditer tempered stop, +3 tests | **CHECKER CR; MAKER DONE** 312 green |
| 120–117 | 2026-09-24/25 | checker sync beats (§9 compress) | 120: CR on 119; 119: foreign-aware group-walk + `&` clause charset, `_utc_today` monkeypatch leak fixed; 118: re-reviewed 117 (short-clause sibling residual → bound hit → human gate); 117: pin-gated group-walk + residency pins, +5 tests | **CHECKER CR** (120, 118 — non-blocking, PR #13); **MAKER DONE** 309 → 311 green |
| 116 | 2026-09-24 | pull_request sync (Beat 115 rework pushed) | Re-reviewed PR #13 rework 3eb382f: 309 tests green; repros fixed + pins intact; MEDIUM#2 (HEAD-after-dedup, 1.5s timeout, close) correct; Glassdoor A2 + dead var done. **Residual CHANGES REQUESTED**: `_US_RESTRICTED_RE` hyphen alt + city group-walk still false-drops Worldwide "Remote-first team with offices in Seattle..." / "Remote-first hubs in Austin..." (no comma) — needs pin-gated group-walk. Fixed retired `checker` model in `.opencode/agent/checker.md` (mimo-v2.5-free→v2.6-flash-free) + both AGENTS.md lessons | **CHECKER REVIEWED** — CHANGES REQUESTED (residual, non-blocking); posted to PR #13 |



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
14. **(Beat 116–118 + 144, SHARED INFRA — STILL OPEN, NOW THE TOP BLOCKER)** `checker` subagent spawn: Beat 116 updated `.opencode/agent/checker.md` to `opencode/mimo-v2.6-flash-free`, but a real spawn still fails in the Actions runner — **re-tested 2026-09-29 (Beat 144): 4th consecutive failure**, verbatim `Subagent failed (task_id: …): OpenCode's free tier can only be used from within OpenCode`. It is **not** a model-id problem (`opencode.yml:167` is already on the working `mimo-v2.6-flash-free`, `2fed239`) and **not** a permissions problem — it is a runner-side OpenCode free-tier restriction on nested spawns, so it blocks *every* maker→checker cycle in the trainer and therefore every PR (§2 rule 1 + the triage gate rule). **Human: run the `checker` subagent from inside a local opencode session, or point `.opencode/agent/checker.md` at a model the runner's free tier allows.** Until then, heartbeats can only triage in-main and leave everything to §10.
15. **Proposed durable lesson (human approval):** Evaluate explicit Worldwide/APAC markers only after hard residency-pin detection; add mixed-marker and foreign-city/country-only regressions. (Implemented Beat 123; approve for AGENTS.md §11.)
16. ~~**(Beat 124, HUMAN, shared infra)**~~ **MOSTLY RESOLVED Beats 127+129:** autonomous reviewer **completed twice in a row on PR #15** (11:17Z CR with real findings; 11:46Z re-review verifying R1/R2 fixed) — 45-min timeout (Beat 124 fix) + no stall on either attempt; PR #13's 4× failures look transient/first-run. Keep watching (stall signature: 32-min silence + orphan playwright — `gh run view 36116678518 --log`). Still open: CodeRabbit comment-runs spawning `opencode` noise jobs (2× fast-fail 11:33Z on this PR), and `checker` subagent spawn (task 14). Verdict-waiver precedent applies only to PR #13 (human Option 1).
17. **(Mon 2026-09-28 cloud watchdog — STILL UNVERIFIED, blocked on task 20)** first weekday cron on **merged `main`** (checkout is default ref) — verify `gh run list --workflow=job-loop-cron.yml`, `.slc/state.json` advanced, Telegram digest landed, then task-9 spot-check (5 jobs, Rule 11 fidelity, live URLs). **Beat 144 could not run this check: it needs the same Actions read access as task 20.** The cron *test suite* is confirmed green locally (306 EXIT 0, task 21), but delivery is unconfirmed. **Observed schedule latency:** cron is `0 3 * * 1-5` (03:00Z/08:00 PKT intended) but Sep 24/25 runs were created ~08:20–08:42Z and the Sep 28 heartbeat itself fired ~8.5h late; if the delay persists and 08:00 PKT delivery matters, human decision: accept or shift cron earlier.
18. **(Approved blueprint — remaining phases, amendments A2–A6):** Phase 1 PR #15 — Beat 128 rework fixed R1/R2 (0600 via mkstemp, class-name-only logs, 335); Beat 129 re-review confirmed those, found 2 residuals (rework bound 2/2); **Beat 130 (final rework) fixed both** (`load()` `read_bytes`+`except ValueError` → non-UTF-8 = corruption→unlink; `save()` guarded in `attempt_login` → OSError → class-only log → None; +2 regressions; 337 passed). **Beat 131/132 CHANGES REQUESTED — human gate** (oversized cookie expiry made `load()` raise `OverflowError`); human approved bound exception (a); **Beat 133 landed the fix** (`load()` self-heals on OverflowError → None+unlink, `attempt_login` guards the same signal, non-finite expiries rejected; +3 regressions; 340 passed). **Beats 134–136:** 134 final checker CR (bad `__str__` escape + non-JSON state escape) → human gate; 135 human approved fulfillment → both guards +2 regressions (342); **136 Checker APPROVED (342, 4 repros) and PR #15 MERGED `f1defd6` → PHASE 1 LANDED.** **Phase 2 (A2) MAKER DONE in Beat 137** (branch `phase2-multi-domain`, `b092661`, 372 tests): env domain registry (`INDEED_DOMAINS`/`GLASSDOOR_DOMAINS` + `_CLOUD` split, 15-cap, fail-closed hostname validation, proven pre-Phase-2 defaults = no behaviour change), per-domain circuit keys `source:domain` with legacy-key state migration (history carried, idempotent, never clobbers composites), `prune_unknown` base-aware, `pick_domain_key` first-closed-wins, `run_source` ckey pre-gate (timeout/error/success all keyed; outcomes stay plain source), `_apply_domain` URL bases on Indeed+Glassdoor (+ Glassdoor hardcoded job-listing URL fixed), `session_file` traversal rejection. **Checker CR (Beat 138): all-invalid registry falls back to the default host; Maker fix + regression required. PHASE 2b DEFERRED (this task): wire `session.load()` storage_state into `launch_browser` — sessions are saved but still unused by the scrape path; do before relying on login sessions in cloud.** Also open: optional `.runtime/` 0700 note (checker non-blocking). **Phase 3** Rule-11 localized-residency fixtures FIRST (TDD — German/French examples will FAIL today: no `Wohnsitz`/`résidant` patterns), then add DE/FR minimal pattern set + au/sg worldwide-pass fixtures (A3). **Phase 4** Docker: base image must be `mcr.microsoft.com/playwright/python:v1.62.0-noble` (match `requirements.txt` pin, NOT v1.49.0); headless/CI-parity only — human CAPTCHA stays bare-metal (A4). **Phase 5** raise `job-loop-cron.yml` `timeout-minutes: 20`→45 (or domain rotation) BEFORE cloud multi-domain (A5); env docs + README (A6: ≤2 phases per run, ≤3 beats/run, STATE row per phase).

19. **(Beat 139→140 — resolved model, pending verdict):** `opencode.yml:167` model fixed by human (`2fed239`) and **published to main as `4e5d38f`** (issue_comment runs read the default branch — the fix was PR-branch-only until then); `/opencode check` re-triggered on PR #16 and the adversarial job now runs (past the 24s `Model not found` death). **MOOT:** PR #16 merged `842223b` (2026-09-25) → Phase 2 landed. In-session `checker` subagent spawn still gated (task 14).
20. **(Beat 143 + 144, HUMAN, SHARED INFRA — 2nd confirmation, BLOCKING ALL CI TRIAGE)** The heartbeat's mandated step 2 is structurally blind: `gh run list`, `actions/runs`, and check-runs all return `HTTP 403: Resource not accessible by integration`, while `gh issue/pr list` work. Cause: job-level `permissions:` replaces the default scopes and the `autonomous` job in `.github/workflows/opencode.yml` never declared `actions`. Verified minimal + read-only (that job already holds `contents: write`); the fix exists **only on the unmerged beat-143 branch** (`d488c01`) and could not be pushed from the runner — a GitHub App token may not edit `.github/workflows/**` without the `workflows` scope. **Human must do one of:** (a) hand-apply `actions: read` to the `autonomous` job, or (b) grant the runner `workflows: write`. Beat 143 deliberately did **not** self-grant (b): it would let an autonomous agent rewrite CI to exfiltrate secrets. **Interim workaround now in place (Beat 144):** run the two `test-gate.yml` commands locally — see task 21.
21. **(Beat 144, RESOLVED — no longer a blocker) Local CI substitute.** A heartbeat CAN verify the gate without CI read access: `pip install -r video_generation_loop/requirements.txt -r job_fetching_loop/requirements.txt && pip install -e . && pip install pytest` (all three finish in **seconds** on the runner — Beat 143/its PR #18 wrongly assumed the install would blow the 15-min wall-clock budget), then run `python -m pytest -q --ignore=job_fetching_loop` at the root and `python -m pytest -q` in `job_fetching_loop/`. **Result 2026-09-29: job loop 306 tests EXIT 0; root+video 273 passed, 1 failed** (`video_generation_loop/tests/test_flow_automation.py::test_clip_is_real_video_rejects_empty_and_audio_only`). Note: the job loop's `pyproject.toml` sets `addopts = "-q"`, so a second `-q` suppresses the summary line — trust `EXIT=0` + dot count, not a missing summary. Use this as the standard stand-in while task 20 is open.
22. **(Beat 144, HUMAN — issue #6 verified REAL on main, fix already exists unmerged)** `src/textutils/__init__.py:73` is `\b(sk|pk|ghp|gho|ghu|ghs|github_pat|AKIA)[A-Za-z0-9_]{16,}\b` (no `IGNORECASE`, no `-` in the class). Repro on `main` @ `842223b`: `redact_secrets("sk-proj-9f8e7d6c5b4a3c2d1e0f")` → **UNCHANGED (leaks)**; `redact_secrets("GHP_abcdefghijklmnopqrstuvwxyz1234567890")` → **UNCHANGED (leaks)**; `ghp_…` and `AKIA…` are correctly redacted. Fixes already sit in **two** open, unmerged PRs — #7 and #9 (`fix(…redact_secrets + int type-checks)`) — both stuck behind a human merge decision; a third PR was deliberately NOT opened (PR sprawl + no `checker` verdict). `wrap_text` (issues #3/#4) is likewise still absent from `main` (fix in open PR #5). **Human: merge #5/#7 or #9, then close #3/#4/#6 — or say "land it" and the loop will open one clean PR once the checker spawn works.**
23. **(Beat 144, PROPOSED DURABLE LESSON — human approval for AGENTS.md §11)** "When CI is unreadable, reproduce the gate locally before declaring the loop blocked: install the loop's `requirements.txt` + `pip install -e .` and run the same commands `test-gate.yml` runs. Runner installs take seconds, not minutes — do not skip the gate on a budget guess." (Cost of not learning this: two consecutive heartbeats reported 'no verification possible' when both suites were in fact runnable.)

## 11. Human Gate Decisions (job loop)

- 2026-09-14 — Telegram token was pasted in chat → Rotated via BotFather `/revoke` on 2026-09-16. Store the new token in Actions secrets; never commit `.env`.
- 2026-09-16 — Cloud production is HTTP/JSON/RSS only. Headed CAPTCHA boards are a local ops cost, not a cloud feature.
- 2026-09-14 — Indeed/Glassdoor CAPTCHAs stay fail-closed.
