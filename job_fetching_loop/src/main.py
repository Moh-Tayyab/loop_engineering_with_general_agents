"""Job Fetching Loop — CLI orchestrator.

Usage:
    python -m src.main                         # run per day-of-week schedule
    python -m src.main --source linkedin       # test a single source
    python -m src.main --source indeed --dry-run  # mock run, no notifications
    python -m src.main --window daily          # override schedule
    python -m src.main --window weekly         # force weekly digest
    python -m src.main --digest                # force digest generation
    python -m src.main --stats                 # print circuit-breaker stats
    python -m src.main --reset-circuit         # reset all circuit breakers
    python -m src.main --linkedin-login        # manual LinkedIn login gate
"""
from __future__ import annotations

import argparse
import asyncio
import http.server
import json
import re
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import src.config as cfg
from src.log import get_logger, setup_logging
from src.models import (
    LOCATION_REMOTE,
    NormalizedJob,
    RawJob,
    ai_keyword_matches,
    classify_job_type,
    classify_location,
    is_expired_job,
    is_worldwide_remote,
    job_id,
    normalize_text,
    parse_posted_date,
    parse_salary,
    utc_now,
)
from src.schedule import compute_fetch_window, check_last_run_freshness, next_fetch_start
from src.circuit_breaker import CircuitManager, pick_all_domain_keys
from src.state import DeadLetterQueue, LockTimeoutError, LoopState, SeenStore, atomic_write_text, lock_holder, lock_path_for
from src.dedup import accept_and_record, dedup_job
from src.digest import collect_weekly_jobs, generate_digest, write_digest, week_key
from src.notifier import build_notifiers, send_ops_alert
from src.scrapers import load_all_scrapers, all_scrapers, enabled_scrapers, get_scraper

log = get_logger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AI/ML Job Fetching Loop")
    p.add_argument("--dry-run", action="store_true", help="no notifications, log output only")
    p.add_argument("--source", type=str, default=None, help="test a single source by name")
    p.add_argument("--window", choices=["daily", "weekly", "backfill", "idle", "auto"], default="auto",
                   help="override schedule logic")
    p.add_argument("--digest", action="store_true", help="force weekly digest generation")
    p.add_argument("--stats", action="store_true", help="print per-source circuit breaker stats")
    p.add_argument("--dlq", action="store_true", help="inspect unresolved dead-letter queue items")
    p.add_argument("--clear-dlq", action="store_true", help="clear dead-letter queue items")
    p.add_argument("--replay-dlq", nargs="?", const="google_sheets", default=None, metavar="SOURCE",
                   help="replay dead-lettered batches for a source (default: google_sheets); respects --dry-run")
    p.add_argument("--reset-circuit", action="store_true", help="reset all circuit breakers")
    p.add_argument("--linkedin-login", action="store_true", help="open LinkedIn login gate")
    p.add_argument("--solve", type=str, default=None, metavar="SOURCE",
                   help="open headed browser for a source (indeed, glassdoor, linkedin) to solve CAPTCHA and persist session")
    p.add_argument("--list-sources", action="store_true", help="print registered sources and exit")
    p.add_argument("--keywords", type=str, default=None, help="override SCRAPE_KEYWORDS (comma-sep)")
    p.add_argument("--serve", action="store_true",
                   help="run as a self-scheduling daemon (no cron needed)")
    p.add_argument("--health-port", type=int, default=None,
                   help="port for HTTP health check endpoint (/healthz) in --serve mode")
    return p.parse_args(argv)


# ── LinkedIn login gate ──────────────────────────────────────────────────────

async def linkedin_login() -> int:
    from src.browser import launch_browser

    log.info("opening LinkedIn in headed browser; sign in manually, then close it")
    async with launch_browser("linkedin", headless=False, persistent=True) as context:
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://www.linkedin.com/login")
        log.info("Waiting for sign-in in the browser window (will auto-detect once logged in)...")
        try:
            for _ in range(600):
                await asyncio.sleep(2)
                try:
                    if "feed" in page.url or "/in/" in page.url:
                        log.info("Login detected via navigation to: %s", page.url)
                        await asyncio.sleep(3)
                        break
                    cookies = await context.cookies()
                    if any(c.get("name") == "li_at" for c in cookies):
                        log.info("Login detected via li_at session cookie!")
                        await asyncio.sleep(3)
                        break
                except Exception:
                    pass
        except KeyboardInterrupt:
            log.info("Received interrupt — proceeding to save session marker")
        await page.close()
    # Deterministic session gate: is_available() consults this marker, not a
    # "profile dir has any file" heuristic (Chromium creates hundreds of files
    # before a human has even logged in).
    marker = cfg.RUNTIME_DIR / ".linkedin-session"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(utc_now().isoformat(), encoding="utf-8")
    log.info("session saved (marker %s). You can now run: python -m src.main", marker)
    return 0


async def solve_source(source_name: str) -> int:
    source_name = source_name.lower().strip()
    if source_name == "linkedin":
        return await linkedin_login()

    url_map = {
        "indeed": "https://pk.indeed.com/",
        "glassdoor": "https://www.glassdoor.com/",
    }
    target_url = url_map.get(source_name)
    if not target_url:
        print(f"Unknown source '{source_name}'. Supported for --solve: indeed, glassdoor, linkedin")
        return 1

    from src.browser import await_captcha_solve, has_captcha, human_delay, human_scroll, launch_browser
    log.info("Opening headed browser for %s (%s) to solve CAPTCHA and persist session...", source_name, target_url)
    async with launch_browser(source_name, headless=False, persistent=True) as context:
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            await page.bring_to_front()
        except Exception:
            pass
        log.info("[%s] Navigating to %s ...", source_name, target_url)
        try:
            await page.goto(target_url, timeout=45_000, wait_until="domcontentloaded")
        except Exception as exc:
            log.warning("[%s] Initial navigation note: %s", source_name, exc)

        try:
            await page.bring_to_front()
        except Exception:
            pass

        # Check for captcha or allow manual interaction
        if await has_captcha(page):
            log.info("[%s] CAPTCHA detected — please solve the checkbox in the opened browser window.", source_name)
            solved = await await_captcha_solve(page, source_name, target_url, timeout=300.0)
            if not solved:
                log.error("[%s] CAPTCHA was not solved within 300s.", source_name)
                return 1
        else:
            log.info("[%s] No blocking CAPTCHA detected initially. Lingering to ensure session cookies are set...", source_name)
            await human_delay(min_s=2.0, max_s=4.0)
            await human_scroll(page)

        # Save storage state
        try:
            from src.session import save as save_session
            storage = await context.storage_state()
            save_session(source_name, storage)
            log.info("[%s] Saved session state to .runtime/%s-session.json", source_name, source_name)
        except Exception as exc:
            log.warning("[%s] Could not save storage_state: %s", source_name, exc)

        log.info("[%s] Session solve complete and persistent context saved! You can now run the scraper.", source_name)
        await asyncio.sleep(2.0)
    return 0


# ── Normalization & Qualification Gates (Beat 182 GateChain) ─────────────────
from src.gate_chain import (
    GateChain,
    GateResult,
    is_remotely_workable,
    normalize_raw,
    record_reject as _record_reject,
)



# ── Save jobs to file ────────────────────────────────────────────────────────

def save_jobs(jobs: list[NormalizedJob], output_dir: Path) -> Path:
    """Write jobs_YYYY-MM-DD.json atomically and return the path.

    Merges with any existing file for the day so two beats both land in it.
    Atomic temp-file + os.replace means a crash never leaves a torn file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    today = utc_now().date().isoformat()
    path = output_dir / f"jobs_{today}.json"
    existing: list[dict] = []
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            existing = raw if isinstance(raw, list) else raw.get("jobs", [])
        except (json.JSONDecodeError, OSError):
            log.warning("existing jobs file unreadable; starting fresh: %s", path)
            existing = []
    seen = {j["id"] for j in existing if "id" in j}
    for j in jobs:
        if j.id not in seen:
            existing.append(j.to_dict())
            seen.add(j.id)
    atomic_write_text(path, json.dumps(existing, indent=2, ensure_ascii=False))
    log.info("saved %d jobs -> %s", len(existing), path)

    # Auto-export BD Spreadsheet (CSV) - local atomic file write
    try:
        from src.sheets import export_jobs_to_csv
        export_jobs_to_csv(jobs, output_dir)
    except Exception as exc:
        log.warning("[sheets] CSV export failed: %s", exc)

    return path


# ── Source execution ─────────────────────────────────────────────────────────

def run_source(
    source_name: str,
    keywords: list[str],
    posted_after: datetime,
    seen: SeenStore,
    circuit: CircuitManager,
    max_jobs: int,
    dry_run: bool = False,
    outcomes: dict[str, str] | None = None,
    timeout_s: float | None = None,
) -> list[NormalizedJob]:
    """Run one source, normalizing + deduping, returning new jobs — bounded.

    `timeout_s`: every source runs in its own daemon worker with this hard
    wall-clock cap (default `cfg.source_timeout_s()`, 150s). A hung Playwright
    source (CAPTCHA stall, EPIPE, stuck SPA) can no longer stall the whole
    loop: on timeout the source is failed (circuit breaker + verdict + dead
    letter on a real run) and the orchestration continues with the rest.

    `dry_run`: rehearsal semantics — mutations stay in memory (the in-process
    `seen` set keeps cross-source dedup working) but NOTHING is written to
    `.slc/` (rule 6: a dry-run that writes state is a bug, not a feature).

    `outcomes`: optional tally of this source's verdict for the run report
    ('ok' | 'failed' | 'open' | 'login' | 'timeout'), used by the outer run to
    detect a total-outage day for the exit code.

    Beat 170 fan-out: registry sources (Indeed/Glassdoor) run EVERY closed
    domain key sequentially inside the one worker (same timeout/cancel/max_jobs
    budget) — `INDEED_DOMAINS` is a rotation no longer, each surface adds jobs
    and cross-domain dupes collapse via canonical `jk=` ids. Per-domain success
    and failure record under that domain's own key, so one CAPTCHA-burned host
    never takes the rest down (Rule 10).
    """
    if timeout_s is None:
        timeout_s = cfg.source_timeout_s(source_name)

    # Phase 2 (A2) + Beat 170: resolve ALL runnable per-domain circuit keys
    # BEFORE the worker starts. Empty → skip exactly like the old gate.
    ckeys = pick_all_domain_keys(circuit, source_name)
    if not ckeys:
        log.info("[%s] circuit OPEN — skipping", source_name)
        if outcomes is not None:
            outcomes[source_name] = "open"
        return []

    box: dict[str, object] = {}
    cancel_event = threading.Event()
    rejects: list[dict] = []
    # Pre-seed: a timeout striking before the worker thread even starts still
    # charges the first domain (old unconditional semantics) instead of
    # recording nothing on a real stall.
    box["current"] = ckeys[0]

    def _work() -> None:
        results: list[tuple[str, str, list, BaseException | None]] = []
        shared_ids: set[str] = set()
        shared_recent: list[dict] = []
        for ck in ckeys:
            if cancel_event.is_set():
                break
            domain = ck.split(":", 1)[1] if ":" in ck else None
            box["current"] = ck
            try:
                done = sum(len(r[2]) for r in results)
                remaining = max_jobs - done
                if remaining <= 0:
                    break
                verdict, jobs = _run_source_impl(source_name, keywords, posted_after,
                                                seen, circuit, remaining, cancel_event=cancel_event,
                                                rejects=rejects, circuit_key=ck, domain=domain,
                                                batch_ids=shared_ids, batch_recent=shared_recent)
                results.append((ck, verdict, jobs, None))
                if verdict == "ok":
                    box.setdefault("done_ok", []).append(ck)
            except Exception as exc:  # noqa: BLE001 - one burned domain (CAPTCHA/timeout) must not take the rest down: record below, fan out on
                results.append((ck, "failed", [], exc))
                continue
            except BaseException as exc:  # noqa: BLE001 - KeyboardInterrupt/SystemExit: abort the whole source like the old path
                results.append((ck, "failed", [], exc))
                break
        box["results"] = results

    def _record_domain_failure(ck: str, err: str) -> None:
        circuit.record_failure(ck, dry_run=dry_run)
        log.warning(
            "[%s] failure recorded — if CAPTCHA/timeout persists past threshold, "
            "circuit opens; recover with local headed run or --reset-circuit",
            _ckey_label(ck, source_name),
        )
        if not dry_run:
            dlq = DeadLetterQueue()
            dlq.push({
                "source": source_name,
                "domain": ck,
                "error": err,
                "timestamp": utc_now().isoformat(),
            })
            dlq.save()

    worker = threading.Thread(target=_work, name=f"source-{source_name}", daemon=True)
    worker.start()
    worker.join(timeout_s)
    if worker.is_alive():
        cancel_event.set()
        log.error("[%s] timed out after %.0fs — recording failure, continuing loop",
                  source_name, timeout_s)
        try:
            from src.browser import kill_child_browser_processes
            cleaned = kill_child_browser_processes()
            if cleaned:
                log.info("[%s] cleaned up %d orphaned browser process(es)", source_name, cleaned)
        except Exception as exc:
            log.warning("[%s] error cleaning up browser processes: %s", source_name, exc)
        worker.join(0.5)
        # Timeout struck mid-fan-out: only the in-flight domain earns the
        # failure — never a domain never attempted (that would open innocent
        # circuits), and never one already completed-ok (microsecond gap race:
        # its results were lost with the worker, but its breaker stays clean).
        # A domain that errored during the grace join still earns the timeout
        # failure (old unconditional semantics: exactly one count per stall).
        current = box.get("current")
        done_ok = set(box.get("done_ok", []))
        if isinstance(current, str) and current not in done_ok:
            _record_domain_failure(current, f"TimeoutError: exceeded {timeout_s:.0f}s")
        if outcomes is not None:
            outcomes[source_name] = "timeout"
        return []

    results = box.get("results", [])
    all_jobs: list = []
    last_verdict = "ok"
    any_ok = False
    for ck, verdict, jobs, err in results:
        if err is not None:
            log.error("[%s] scraper failed: %s — recording failure, continuing loop",
                      _ckey_label(ck, source_name), err)
            try:
                from src.browser import kill_child_browser_processes
                kill_child_browser_processes()
            except Exception:
                pass
            _record_domain_failure(ck, f"{type(err).__name__}: {err}")
            last_verdict = "failed"
            continue
        last_verdict = verdict
        if verdict != "ok":
            continue  # "cancelled"/"open"/"login": neither success nor failure
        any_ok = True
        circuit.record_success(ck)
        all_jobs.extend(jobs)
    if outcomes is not None:
        if any_ok:
            outcomes[source_name] = "ok"
        elif not results:
            # Worker finished with zero completed domains (instant cancel before
            # the first fetch, or max_jobs<=0): never report a hollow "ok" —
            # the old single-key path surfaced impl's "cancelled" here.
            outcomes[source_name] = "cancelled" if cancel_event.is_set() else "ok"
        else:
            outcomes[source_name] = last_verdict

    # C5: persist filter-reject audit rows (real runs only — dry-run stays pure)
    if not dry_run and rejects:
        _flush_rejects(rejects)

    if any_ok:
        log.info("[%s] found %d new jobs", source_name, len(all_jobs))
        for j in all_jobs:
            accept_and_record(j, seen)
    return all_jobs


def _ckey_label(ckey: str, source_name: str) -> str:
    """Log label for a circuit key: `source:domain`, or plain source."""
    return ckey if ":" in ckey else source_name



def _flush_rejects(rejects: list[dict]) -> None:
    """Append reject rows to output/rejected.jsonl (never on dry-run — callers gate)."""
    if not rejects:
        return
    try:
        path = cfg.OUTPUT_DIR / "rejected.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(r, ensure_ascii=False) for r in rejects]
        with path.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        log.info("[rejects] appended %d row(s) -> %s", len(rejects), path)
    except Exception as exc:
        log.warning("[rejects] failed to write rejected.jsonl: %s", exc)


def _run_source_impl(
    source_name: str,
    keywords: list[str],
    posted_after: datetime,
    seen: SeenStore,
    circuit: CircuitManager,
    max_jobs: int,
    cancel_event: threading.Event | None = None,
    rejects: list[dict] | None = None,
    circuit_key: str | None = None,
    domain: str | None = None,
    batch_ids: set[str] | None = None,
    batch_recent: list[dict] | None = None,
) -> tuple[str, list[NormalizedJob]]:
    """Unbounded implementation of run_source (the worker-thread body).

    Pure execution: never mutates circuit, outcomes, DeadLetterQueue, or SeenStore
    directly, eliminating concurrent mutation and TOCTOU races between worker and main thread.
    Dedup state mutations are deferred to caller on confirmed success.

    Beat 170 fan-out: `batch_ids`/`batch_recent` may be SHARED across sequential
    per-domain calls so a job seen on pk.indeed.com dedups on www.indeed.com
    within the same run (canonical `jk=` id + fuzzy layer both consult them).
    Defaults to fresh sets (single-source behaviour unchanged).
    """
    key = circuit_key or source_name
    if not circuit.is_available(key):
        log.info("[%s] circuit OPEN — skipping", source_name)
        return "open", []

    log.info("[%s] fetching (after=%s)", source_name, posted_after.date())
    scraper = get_scraper(source_name)
    if domain:
        scraper.active_domain = domain  # Phase 2: registry-backed URL base
    if scraper.login_required() and not scraper.is_available():
        log.warning("[%s] login required but no session — skipping (run --linkedin-login)", source_name)
        return "login", []

    new_jobs: list[NormalizedJob] = []
    if batch_ids is None:
        batch_ids = set()
    if batch_recent is None:
        batch_recent = []
    count = 0
    chain = GateChain(
        posted_after=posted_after,
        seen=seen,
        keywords=cfg.scan_keywords(),
        scrape_remote_only=cfg.scrape_remote_only(),
        batch_ids=batch_ids,
        batch_recent=batch_recent,
        rejects=rejects,
    )
    for raw in scraper.fetch(keywords, posted_after):
        if cancel_event is not None and cancel_event.is_set():
            return "cancelled", []
        if count >= max_jobs:
            break
        res = chain.evaluate(raw, source=source_name)
        if res.accepted and res.job is not None:
            new_jobs.append(res.job)
            count += 1

    if cancel_event is not None and cancel_event.is_set():
        return "cancelled", []

    return "ok", new_jobs


# ── Notifications ────────────────────────────────────────────────────────────

def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _guarded_deliver(state: LoopState, notifiers: list, prefix: str, deliver) -> set[str]:
    """Send a notification to each channel without holding the state lock during
    the slow network call.

    Two-phase: (1) check-already-sent under a short lock, (2) send unlocked,
    (3) re-lock and mark only if nobody else marked while we sent. This keeps
    the lock free for scrapers during seconds of HTTP IO while still preventing
    duplicate sends across processes.

    Returns the set of `kind` values confirmed delivered this call (including
    kinds already marked for today — callers use this for weekly retry)."""
    today_str = _today_utc()
    done: set[str] = set()
    for n in notifiers:
        key = f"{prefix}:{n.kind}"
        with state.locked(timeout_s=cfg.lock_timeout_s()):
            state.reload()
            if state.notified_today(key, today_str):
                done.add(n.kind)
                continue
        try:
            ok = deliver(n)
        except Exception as exc:  # noqa: BLE001 - a flaky channel must not kill the run
            log.error("[notify] %s failed: %s", key, exc)
            ok = False
        if not ok:
            continue
        done.add(n.kind)
        with state.locked(timeout_s=cfg.lock_timeout_s()):
            state.reload()
            if not state.notified_today(key, today_str):
                state.mark_notified(key, today_str)
                state.save()
    return done


# ── Scrape pass (runs under the state lock) ─────────────────────────────────

def _compute_window(args: argparse.Namespace):
    from src.schedule import FetchWindow, FREQ_IDLE

    if args.window == "idle":
        return FetchWindow(reason=FREQ_IDLE, window_start=utc_now(), window_end=utc_now(),
                           generate_digest=False, window_label="manual idle", day_of_week=6)
    if args.window != "auto":
        now = utc_now()
        if args.window == "daily":
            start = now - timedelta(hours=24)
        elif args.window == "weekly":
            start = now - timedelta(days=7)
        elif args.window == "backfill":
            start = now - timedelta(days=3)
        else:
            start = now
        return FetchWindow(reason=args.window, window_start=start, window_end=now,
                           generate_digest=(args.window == "weekly"),
                           window_label=f"manual {args.window}", day_of_week=now.weekday())
    return compute_fetch_window()


def _run_scrape_pass(state: LoopState, circuit: CircuitManager, args: argparse.Namespace,
                     window) -> tuple[list[NormalizedJob], tuple[dict, list[NormalizedJob]] | None, dict[str, str]]:
    """Run scrape → save → digest (local I/O only) under the state lock.

    Returns (new_jobs, digest_plan, outcomes) where digest_plan is
    (digest, top_jobs) if a digest was written, else None, and outcomes maps
    each scheduled source to 'ok'/'failed'/'open'/'login' (for the run's
    outage exit-code decision). Notifications are NOT sent here — network
    IO must not hold the lock, so the caller delivers them after release.
    """
    if args.source:
        sources_to_run = [args.source]
    else:
        sources_to_run = list(window.sources) if window.sources else enabled_scrapers()

    log.info("[sources] %d sources: %s", len(sources_to_run), ", ".join(sources_to_run))

    seen = SeenStore()
    keywords = [k.strip() for k in args.keywords.split(",")] if args.keywords else cfg.all_scan_keywords()
    max_jobs = cfg.max_jobs_per_source()
    all_new_jobs: list[NormalizedJob] = []
    outcomes: dict[str, str] = {}

    for source_name in sources_to_run:
        new = run_source(source_name, keywords, window.window_start, seen, circuit, max_jobs,
                         dry_run=args.dry_run, outcomes=outcomes)
        all_new_jobs.extend(new)
        # seen.save() only on a real run: a --dry-run must never write .slc/
        # (rule 6) or it burns hashes into the dedup store and the next real
        # run silently skips those jobs.
        if not args.dry_run:
            seen.save()

    # ── save ──
    if all_new_jobs and not args.dry_run:
        save_jobs(all_new_jobs, cfg.OUTPUT_DIR)

    # ── state update (skipped for --dry-run: pure rehearsal, no side effects) ──
    if not args.dry_run:
        state.ensure_week(week_key())
        state.add_jobs_this_week(len(all_new_jobs))
        state.mark_run()
        state.save()
    else:
        log.info("[dry-run] state/output writes skipped (rehearsal only)")

    # ── weekly digest (local file writes stay under the lock) ──
    digest_plan: tuple[dict, list[NormalizedJob]] | None = None
    if (window.generate_digest or args.digest) and not args.dry_run:
        wk = week_key()
        if state.digest_generated_for() != wk or args.digest:
            log.info("generating weekly digest...")
            week_jobs = collect_weekly_jobs()
            digest = generate_digest(week_jobs)
            json_path, md_path = write_digest(digest)
            log.info("[digest] %s", json_path)
            log.info("[digest] %s", md_path)
            state.mark_digest(wk)
            state.save()
            top = [NormalizedJob.from_dict(j) for j in digest["top_jobs"][:10]]
            digest_plan = (digest, top)
    elif args.digest and args.dry_run:
        log.info("[dry-run] digest generation skipped (rehearsal only)")

    return all_new_jobs, digest_plan, outcomes


# ── Main loop ────────────────────────────────────────────────────────────────

class HealthCheckHandler(http.server.BaseHTTPRequestHandler):
    """Minimal HTTP handler serving /healthz and / for liveness probes in --serve mode."""
    daemon_state: dict[str, Any] = {}

    def do_GET(self) -> None:
        if self.path in ("/healthz", "/health"):
            body = json.dumps(self.daemon_state, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/":
            body = b"Job Fetching Loop Daemon OK\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        pass


def start_health_server(port: int, state_ref: dict[str, Any]) -> tuple[Any, threading.Thread | None]:
    from http.server import ThreadingHTTPServer

    HealthCheckHandler.daemon_state = state_ref
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), HealthCheckHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True, name="health-server")
        thread.start()
        log.info("[serve] health check server listening on http://127.0.0.1:%d/healthz", port)
        return server, thread
    except Exception as exc:
        log.warning("[serve] could not bind health server on port %d: %s", port, exc)
        return None, None


def serve_loop(health_port: int | None = None, shutdown_event: threading.Event | None = None) -> int:
    """Self-scheduling daemon: run without cron.

    Includes /healthz HTTP liveness endpoint, graceful SIGTERM/SIGINT signal
    handling, responsive sleeping (interruptible shutdown), and browser process
    cleanup after each pass.
    """
    import signal
    from src.browser import kill_child_browser_processes

    port = health_port if health_port is not None else cfg.health_port()
    if shutdown_event is None:
        shutdown_event = threading.Event()

    def _sig_handler(signum: int, _frame: Any) -> None:
        try:
            sig_name = signal.Signals(signum).name
        except Exception:
            sig_name = str(signum)
        log.info("[serve] received %s — initiating graceful shutdown", sig_name)
        shutdown_event.set()

    if threading.current_thread() is threading.main_thread():
        try:
            signal.signal(signal.SIGTERM, _sig_handler)
            signal.signal(signal.SIGINT, _sig_handler)
        except (ValueError, AttributeError):
            pass

    daemon_state: dict[str, Any] = {
        "status": "starting",
        "started_at": utc_now().isoformat(),
        "passes_completed": 0,
        "last_pass_rc": None,
        "last_pass_finished_at": None,
        "next_fetch_window": None,
    }
    server, _ = start_health_server(port, daemon_state)

    log.info("[serve] starting self-scheduled loop (no cron needed)")
    try:
        while not shutdown_event.is_set():
            daemon_state["status"] = "running"
            rc = main([])
            daemon_state["last_pass_rc"] = rc
            daemon_state["last_pass_finished_at"] = utc_now().isoformat()
            daemon_state["passes_completed"] += 1
            log.info("[serve] pass finished rc=%d", rc)

            kill_child_browser_processes()

            nxt = next_fetch_start()
            daemon_state["next_fetch_window"] = nxt.isoformat()
            daemon_state["status"] = "idle"
            wait_s = max(0.0, (nxt - datetime.now(timezone.utc)).total_seconds())
            log.info("[serve] next fetch window %s (in %.1fh)", nxt.isoformat(), wait_s / 3600)

            if shutdown_event.wait(timeout=wait_s):
                break
    except KeyboardInterrupt:
        log.info("[serve] keyboard interrupt caught")
    finally:
        daemon_state["status"] = "stopping"
        if server:
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass
        kill_child_browser_processes()
        log.info("[serve] daemon stopped cleanly")
    return 0


def _warn_stale_env_override(dotenv_path=None) -> bool:
    """Beat 173 (pending since Beat 162): a shell-exported TELEGRAM_BOT_TOKEN
    silently masks `.env` because dotenv never overrides existing env vars —
    the exact trap that produced a phantom 401 while the file token was
    already valid. Logs a loud WARNING naming the winner (never values).
    Returns True when a stale shell export shadows the file."""
    import os
    from pathlib import Path

    path = Path(dotenv_path) if dotenv_path is not None else cfg.ROOT / ".env"
    file_val = ""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                file_val = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    except OSError:
        return False
    env_val = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if file_val and env_val and file_val != env_val:
        log.warning(
            "[config] shell-exported TELEGRAM_BOT_TOKEN shadows .env — "
            "the SHELL value wins (stale exports cause phantom 401s); "
            "run `unset TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID` to use the file"
        )
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    cfg.load_env()
    _warn_stale_env_override()
    setup_logging()
    cfg.ensure_dirs()
    load_all_scrapers()

    if args.serve:
        return serve_loop(health_port=args.health_port)

    # ── utility commands ──
    if args.linkedin_login:
        return asyncio.run(linkedin_login())

    if args.solve:
        return asyncio.run(solve_source(args.solve))

    if args.list_sources:
        print("registered sources:")
        for name, cls in all_scrapers().items():
            enabled = cfg.source_enabled(name)
            if enabled:
                status = "enabled"
            elif not cfg.allow_browser_scrapers() and name in cfg.BROWSER_BOUND_SOURCES:
                status = "disabled (browser-bound; skipped on cloud runner)"
            else:
                status = f"disabled (set SOURCE_{name.upper()}=1)"
            print(f"  {name:25} {status}")
        return 0

    state = LoopState()
    circuit = CircuitManager(state)
    # Drop circuits for sources purged from the registry (deleted scrapers).
    stale = circuit.prune_unknown(frozenset(all_scrapers()))
    if stale:
        log.info("[circuit] pruned stale source(s): %s", ", ".join(sorted(stale)))

    if args.dlq:
        dlq = DeadLetterQueue()
        if not dlq.items:
            print("dead-letter queue is empty")
        else:
            print(f"dead-letter queue ({len(dlq.items)} items):")
            for it in dlq.items:
                print(f"  [{it.get('timestamp')}] {it.get('source')}: {it.get('error')}")
        return 0

    if args.clear_dlq:
        dlq = DeadLetterQueue()
        count = len(dlq.items)
        dlq.clear()
        print(f"[dlq] cleared {count} item(s)")
        return 0

    if args.replay_dlq:
        if args.replay_dlq != "google_sheets":
            print(f"[replay-dlq] unsupported source '{args.replay_dlq}' (only 'google_sheets' currently)")
            return 1
        from src.sheets import replay_sheets_dlq
        replayed = replay_sheets_dlq(dry_run=args.dry_run)
        verb = "would have replayed" if args.dry_run else "replayed"
        print(f"[replay-dlq] {verb} {replayed} google_sheets batch(es)")
        return 0

    if args.stats:
        for s in circuit.summary():
            print(f"  {s['source']:25} {s['status']}  fails={s['consecutive_fails']}  ok={s['total_ok']}  err={s['total_fail']}")
        dlq_count = len(DeadLetterQueue().items)
        print(f"  dead_letter_queue         items={dlq_count}")
        return 0

    if args.reset_circuit:
        with state.locked(timeout_s=cfg.lock_timeout_s()):
            circuit.reset_all()
            state.save()
        print("[reset] all circuit breakers reset")
        return 0

    if not args.dry_run and not cfg.job_loop_should_run():
        log.info(
            "[config] scrape skipped (JOB_LOOP_ENABLED/JOB_LOOP_PRIMARY) — "
            "this host is not the primary runner"
        )
        return 0

    # ── compute fetch window ──
    window = _compute_window(args)

    log.info("=" * 60)
    log.info("JOB FETCHING LOOP — %s", window.window_label)
    log.info("Window: %s -> %s", window.window_start.date(), window.window_end.date())
    log.info("=" * 60)

    if window.is_idle():
        log.info("[schedule] today is idle — nothing to do")
        return 0

    freshness = check_last_run_freshness(state.last_run(), window)
    log.info(freshness)

    # ── scrape under the state lock (leadership election) ──
    # Two concurrent crons: the winner scrapes, the loser waits LOCK_TIMEOUT_S
    # then exits cleanly. This prevents double-scraping and lost writes to
    # state.json / seen.json / output.
    # A --dry-run is pure rehearsal: it writes nothing, so it takes NO lock —
    # not even the empty advisory lock file — and never contends with a real
    # cron that happens to be mid-run (rule 6).
    if args.dry_run:
        new_jobs, digest_plan, outcomes = _run_scrape_pass(state, circuit, args, window)
    else:
        try:
            with state.locked(timeout_s=cfg.lock_timeout_s()):
                new_jobs, digest_plan, outcomes = _run_scrape_pass(state, circuit, args, window)
                state.save()
        except LockTimeoutError:
            # Lock-starved: benign overlap vs stale (hung) holder? The holder
            # sidecar (pid + acquired_at) tells the difference. A hung browser
            # squatting the lock must NOT look like a clean skip — exit 1 so
            # monitoring/cron catches the DOWN day (P2 watchdog).
            holder = lock_holder(lock_path_for(state.path))
            stale = False
            if holder:
                try:
                    acquired = datetime.fromisoformat(str(holder.get("acquired_at")))
                    age = (datetime.now(timezone.utc) - acquired).total_seconds()
                    pid = holder.get("pid")
                    if age > cfg.lock_stale_s():
                        stale = True
                        log.error("[lock] held by pid=%s for %.0fs — stale (hung?) — exiting 1 so monitoring alerts",
                                  pid, age)
                    else:
                        log.warning("[lock] another run in progress (pid=%s, %.0fs) — skipping this invocation", pid, age)
                except (TypeError, ValueError):
                    log.warning("[lock] another run in progress (unreadable holder) — skipping this invocation")
            else:
                log.warning("[lock] another run is in progress — skipping this invocation")
            return 1 if stale else 0

    # ── Google Sheets webhook sync (runs OUTSIDE lock, best-effort) ──
    if new_jobs and not args.dry_run:
        try:
            from src.sheets import sync_to_google_sheet
            sync_to_google_sheet(new_jobs)
        except Exception as exc:
            log.warning("[sheets] Google Sheets sync failed: %s", exc)

    # ── notifications run AFTER the lock is released ──
    # Telegram/WhatsApp sends take seconds of network IO; holding the state
    # lock during them would block other cron runs. `_guarded_deliver` uses a
    # short re-lock only to check + record, never during the actual send.
    #
    # A healthy quiet day (a general multi-source run that found 0 new jobs)
    # still sends a daily heartbeat so silence is never ambiguous — "no message"
    # from the loop MUST mean the loop is down, not "nothing was new today".
    # Total-outage days skip the heartbeat (exit 1 alerts downstream instead).
    outage = (not args.dry_run and not args.source and not new_jobs
              and outcomes and all(v != "ok" for v in outcomes.values()))
    if not args.dry_run and not outage and (new_jobs or not args.source):
        stats = {
            "total_this_week": state.jobs_this_week(),
            "sources": {s: sum(1 for j in new_jobs if j.source == s)
                        for s in set(j.source for j in new_jobs)},
        }
        notifiers = build_notifiers()
        _guarded_deliver(state, notifiers, "daily", lambda n: n.send_daily(new_jobs, stats))
    elif args.dry_run:
        log.info("[dry-run] would notify %d jobs", len(new_jobs))

    # ── weekly digest delivery — retried until every channel confirms ──
    # Generation (`mark_digest`) and DELIVERY are decoupled. The digest files
    # are written once per week, but a channel that failed (LinkedIn API hiccup,
    # Telegram timeout) stays pending in `weekly_delivered_kinds` and is retried
    # on whichever later run raises a healthy pass — never silently dropped just
    # because the files already exist. `_guarded_deliver` still de-dups within a
    # day, so a healthy run never re-sends to a channel that already confirmed.
    wk = week_key()
    if state.digest_generated_for() == wk and not args.dry_run and not args.source:
        notifiers = build_notifiers()
        today = _today_utc()
        already = state.weekly_delivered_kinds(wk)
        # A channel that sent today (daily dedup key set) counts as delivered.
        already |= {n.kind for n in notifiers
                    if n.kind not in already and state.notified_today(f"weekly:{n.kind}", today)}
        pending = [n for n in notifiers if n.kind not in already]
        if pending:
            week_jobs = collect_weekly_jobs()
            digest = generate_digest(week_jobs)
            top = [NormalizedJob.from_dict(j) for j in digest["top_jobs"][:10]]
            delivered = _guarded_deliver(state, pending, "weekly",
                                         lambda n: n.send_weekly_digest(digest, top))
            already |= delivered
            log.info("[digest] weekly delivery: confirmed=%s pending=%s",
                     sorted(already), sorted(n.kind for n in pending if n.kind not in already))
        if already:
            with state.locked(timeout_s=cfg.lock_timeout_s()):
                state.reload()
                state.mark_weekly_delivered(wk, already)
                state.save()
    if not args.dry_run and new_jobs and not digest_plan:
        log.info("[done] %d new jobs discovered", len(new_jobs))
    elif not args.dry_run and not new_jobs:
        log.info("[done] no new jobs found")

    # ── summary (re-read; the lock may have changed circuits) ──
    log.info("Circuit breaker status:")
    for s in circuit.summary():
        log.info("  %-25s %s  fails=%s  ok=%s", s["source"], s["status"],
                 s["consecutive_fails"], s["total_ok"])

    # ── outage signal for monitoring ──
    # A real (non-rehearsal), general (non-single-source) run that fetched NOTHING
    # and had every scheduled source skip-or-fail would otherwise exit 0 — an
    # all-sources-down day looks identical to a good day to cron/alerting. Exit 1
    # only on a TOTAL outage (`OK` on at least one source == healthy quiet day).
    if outage:
        log.error("[outage] every scheduled source failed this run — %s",
                  ", ".join(f"{k}={v}" for k, v in sorted(outcomes.items())))
        log.error("[outage] returning exit code 1 so monitoring/downstream can alert")
        if not cfg.is_cloud_runner():
            send_ops_alert(
                "total source outage — every scheduled source failed. "
                "Check loop.log / GitHub Actions."
            )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())