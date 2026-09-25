"""Integration tests for the orchestration layer: run_source pipeline,
notification dedup, atomic save, the scrape pass wiring, and the sacred
--dry-run no-mutation rule."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from src.circuit_breaker import CircuitManager
from src.main import _guarded_deliver, run_source, save_jobs
from src.models import NormalizedJob, RawJob
from src.state import LoopState, SeenStore


class FakeScraper:
    """Minimal scraper double: no browser, just returns canned RawJobs."""

    name = "fake"

    def __init__(self, jobs):
        self._jobs = jobs

    def fetch(self, keywords, posted_after):
        yield from self._jobs

    def is_available(self):
        return True

    def login_required(self):
        return False


class FakeNotifier:
    """Records deliveries instead of hitting an API."""

    def __init__(self, kind="fake"):
        self.kind = kind
        self.dailies = 0
        self.weeklies = 0

    def send_daily(self, jobs, stats):
        self.dailies += 1
        return True

    def send_weekly_digest(self, stats, top_jobs):
        self.weeklies += 1
        return True


def _raw(title="Machine Learning Engineer", location="Remote", posted_date=None, _no_date=False):
    from datetime import datetime, timezone
    if _no_date:
        posted_date = None
    elif posted_date is None:
        posted_date = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return RawJob(
        source="fake",
        title=title,
        company="Acme",
        url=f"https://fake.example/{title.replace(' ', '-')}",
        location=location,
        posted_date=posted_date,
        description="We build LLM systems in Python.",
        fetched_at=datetime.now(timezone.utc),
    )


def test_run_source_pipeline(tmp_slc, monkeypatch):
    """A qualifying remote AI job is normalized, deduped, recorded, and the
    circuit breaker records a success."""
    monkeypatch.setenv("SCRAPE_KEYWORDS", "AI,LLM,Machine Learning")
    monkeypatch.setenv("SCRAPE_REMOTE_ONLY", "1")
    import src.main as main

    fake = FakeScraper([_raw()])
    monkeypatch.setattr(main, "get_scraper", lambda name: fake)

    seen = SeenStore()
    state = LoopState()
    circuit = CircuitManager(state.state)
    posted_after = datetime.now(timezone.utc) - timedelta(days=1)

    jobs = run_source("fake", ["AI", "LLM", "Machine Learning", "FDE"], posted_after, seen, circuit, 100)

    assert len(jobs) == 1
    j = jobs[0]
    assert j.title_normalized == "machine learning engineer"
    assert j.location_type == "remote"
    # recorded in dedup store
    assert seen.has_exact(j.id)
    # circuit breaker counts the success
    assert circuit._get("fake").total_successes == 1


def test_run_source_drops_onsite_when_remote_only(tmp_slc, monkeypatch):
    monkeypatch.setenv("SCRAPE_KEYWORDS", "AI,LLM")
    monkeypatch.setenv("SCRAPE_REMOTE_ONLY", "1")
    import src.main as main

    fake = FakeScraper([
        _raw(title="Machine Learning Engineer", location="New York, NY"),
        _raw(title="Machine Learning Engineer", location=""),
    ])
    monkeypatch.setattr(main, "get_scraper", lambda name: fake)

    seen = SeenStore()
    state = LoopState()
    circuit = CircuitManager(state.state)

    jobs = run_source("fake", ["AI", "LLM"], datetime.now(timezone.utc), seen, circuit, 100)
    assert jobs == []


def test_run_source_skips_jobs_outside_window(tmp_slc, monkeypatch):
    monkeypatch.setenv("SCRAPE_KEYWORDS", "AI,LLM")
    import src.main as main

    posted_after = datetime(2026, 9, 15, 9, 0, tzinfo=timezone.utc)
    fake = FakeScraper([
        # Outside window (older than posted_after) -> must be dropped
        _raw(title="AI Engineer", location="Worldwide", posted_date="2026-09-10"),
        # Inside window -> must be kept
        _raw(title="LLM Engineer", location="Worldwide", posted_date="2026-09-15"),
    ])
    monkeypatch.setattr(main, "get_scraper", lambda name: fake)

    seen = SeenStore()
    state = LoopState()
    circuit = CircuitManager(state.state)

    jobs = run_source("fake", ["AI", "LLM"], posted_after, seen, circuit, 100)
    assert len(jobs) == 1
    assert jobs[0].title == "LLM Engineer"


def test_run_source_strict_24h_window_on_curated_boards(tmp_slc, monkeypatch):
    """Confirm curated boards now enforce strict 24-hour cutoff (no 10-day relaxation)."""
    monkeypatch.setenv("SCRAPE_KEYWORDS", "AI,LLM")
    import src.main as main

    posted_after = datetime(2026, 9, 15, 9, 0, tzinfo=timezone.utc)
    fake = FakeScraper([
        _raw(title="AI Engineer", location="Worldwide", posted_date="2026-09-12"),
        _raw(title="Staff AI Engineer", location="Worldwide", posted_date="2026-09-15"),
    ])
    monkeypatch.setattr(main, "get_scraper", lambda name: fake)

    seen = SeenStore()
    state = LoopState()
    circuit = CircuitManager(state.state)

    jobs = run_source("himalayas", ["AI", "LLM"], posted_after, seen, circuit, 100)
    assert len(jobs) == 1
    assert jobs[0].title == "Staff AI Engineer"


def test_run_source_drops_jobs_without_parseable_date(tmp_slc, monkeypatch):
    """Strict past-24h policy: a job with no parseable posted date cannot be
    verified inside the window and must be dropped (fail-closed)."""
    monkeypatch.setenv("SCRAPE_KEYWORDS", "AI,LLM")
    import src.main as main

    posted_after = datetime.now(timezone.utc) - timedelta(hours=24)
    fake = FakeScraper([
        # No date at all -> must be dropped
        _raw(title="Undated AI Engineer", location="Worldwide", _no_date=True),
        # Garbage date -> must be dropped
        _raw(title="ASAP AI Engineer", location="Worldwide", posted_date="asap"),
        # Fresh timestamp inside window -> must be kept
        _raw(title="Fresh AI Engineer", location="Worldwide", posted_date=(datetime.now(timezone.utc) - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")),
    ])
    monkeypatch.setattr(main, "get_scraper", lambda name: fake)

    seen = SeenStore()
    state = LoopState()
    circuit = CircuitManager(state.state)

    jobs = run_source("fake", ["AI", "LLM"], posted_after, seen, circuit, 100)
    assert [j.title for j in jobs] == ["Fresh AI Engineer"]


def test_run_source_failure_opens_circuit(tmp_slc, monkeypatch):
    monkeypatch.setenv("CIRCUIT_BREAKER_THRESHOLD", "1")
    import src.main as main

    class Broken:
        name = "broken"
        def fetch(self, keywords, posted_after):
            raise RuntimeError("source exploded")
        def is_available(self):
            return True
        def login_required(self):
            return False

    monkeypatch.setattr(main, "get_scraper", lambda name: Broken())

    seen = SeenStore()
    state = LoopState()
    circuit = CircuitManager(state.state)
    jobs = run_source("broken", ["AI"], datetime.now(timezone.utc), seen, circuit, 100)

    assert jobs == []
    assert circuit._get("broken").total_fails == 1
    assert not circuit.is_available("broken")


def test_run_source_failure_writes_dead_letter_unless_dry_run(tmp_slc, monkeypatch):
    """A failed source records to the dead-letter queue ONLY on a real run.
    Rule 6: --dry-run must not write .slc/ at all."""
    import src.main as main
    from src.state import DeadLetterQueue

    class Broken:
        name = "broken"
        def fetch(self, keywords, posted_after):
            raise RuntimeError("source exploded")
        def is_available(self):
            return True
        def login_required(self):
            return False

    monkeypatch.setattr(main, "get_scraper", lambda name: Broken())

    # Real run → DLQ gets the failure.
    seen = SeenStore()
    circuit = CircuitManager(LoopState().state)
    jobs = run_source("broken", ["AI"], datetime.now(timezone.utc), seen, circuit, 100)
    assert jobs == []
    assert len(DeadLetterQueue().items) == 1
    assert circuit._get("broken").total_fails == 1

    # Dry-run → circuit records in memory, but .slc stays untouched.
    seen2 = SeenStore()
    circuit2 = CircuitManager(LoopState().state)
    jobs = run_source("broken", ["AI"], datetime.now(timezone.utc), seen2, circuit2, 100,
                      dry_run=True, outcomes={})
    assert jobs == []
    assert circuit2._get("broken").total_fails == 1
    assert len(DeadLetterQueue().items) == 1  # unchanged — no new DLQ entry

    # outcomes verdict captured for the run report
    outcomes = {}
    run_source("broken", ["AI"], datetime.now(timezone.utc), SeenStore(),
               CircuitManager(LoopState().state), 100, dry_run=True, outcomes=outcomes)
    assert outcomes == {"broken": "failed"}


def test_run_source_times_out_records_failure(tmp_slc, monkeypatch):
    """A hung source must be failed by the orchestrator timeout, not allowed to
    stall the loop forever. On timeout: circuit failure recorded, empty result,
    verdict 'timeout'."""
    import threading

    import src.main as main
    monkeypatch.setenv("CIRCUIT_BREAKER_THRESHOLD", "1")

    class Hang:
        name = "hang"
        def fetch(self, keywords, posted_after):
            threading.Event().wait()  # never returns — simulated dead source
        def is_available(self):
            return True
        def login_required(self):
            return False

    monkeypatch.setattr(main, "get_scraper", lambda name: Hang())

    seen = SeenStore()
    state = LoopState()
    circuit = CircuitManager(state.state)
    outcomes = {}
    jobs = run_source("hang", ["AI"], datetime.now(timezone.utc), seen, circuit, 100,
                      dry_run=True, outcomes=outcomes, timeout_s=0.05)

    assert jobs == []
    assert outcomes == {"hang": "timeout"}
    assert circuit._get("hang").total_fails == 1
    assert not circuit.is_available("hang")


def test_run_source_timeout_does_not_write_dlq_on_dry_run(tmp_slc, monkeypatch):
    """Rule 6: even a timed-out dry-run must not touch `.slc/` — the dead-letter
    push happens only on a real run."""
    import threading

    import src.main as main
    from src.state import DeadLetterQueue

    class Hang:
        name = "hang"
        def fetch(self, keywords, posted_after):
            threading.Event().wait()
        def is_available(self):
            return True
        def login_required(self):
            return False

    monkeypatch.setattr(main, "get_scraper", lambda name: Hang())

    before = len(DeadLetterQueue().items)
    run_source("hang", ["AI"], datetime.now(timezone.utc), SeenStore(),
               CircuitManager(LoopState().state), 100, dry_run=True, timeout_s=0.05)
    assert len(DeadLetterQueue().items) == before

    # Real run → the timeout lands in the dead-letter queue.
    run_source("hang", ["AI"], datetime.now(timezone.utc), SeenStore(),
               CircuitManager(LoopState().state), 100, timeout_s=0.05)
    assert len(DeadLetterQueue().items) == before + 1


def test_guarded_deliver_sends_all_channels_and_dedupes(tmp_slc):
    """The production notify path: sends happen OUTSIDE the state lock; the
    lock is only held for the check + the mark. Channels must be delivered
    independently and a same-day re-run must not double-send."""
    state = LoopState()
    tg = FakeNotifier(kind="telegram")
    wa = FakeNotifier(kind="whatsapp")

    _guarded_deliver(state, [tg, wa], "daily", lambda n: n.send_daily([], {}))

    assert tg.dailies == 1
    assert wa.dailies == 1
    # recorded in state so a later run skips
    marked = state.state["notifications_sent_today"]
    assert marked.get("daily:telegram") is not None
    assert marked.get("daily:whatsapp") is not None

    _guarded_deliver(state, [tg, wa], "daily", lambda n: n.send_daily([], {}))
    assert tg.dailies == 1
    assert wa.dailies == 1


def test_guarded_deliver_skips_failed_channels(tmp_slc):
    state = LoopState()

    class Flaky:
        kind = "flaky"
        attempts = 0

    def deliver(n):
        n.attempts += 1
        return False  # always fails

    flaky = Flaky()
    _guarded_deliver(state, [flaky], "daily", deliver)
    # failure must not be marked as sent → retried next run
    assert flaky.attempts == 1
    assert "daily:flaky" not in state.state["notifications_sent_today"]

    _guarded_deliver(state, [flaky], "daily", deliver)
    assert flaky.attempts == 2


def test_guarded_deliver_raising_channel_does_not_crash_or_mark(tmp_slc):
    """A notifier that raises (network blip) must not kill the run, must not be
    marked sent (so it retries), and must not block the next channel."""
    state = LoopState()

    class Booming:
        kind = "booming"

    class Calm:
        kind = "calm"
        dailies = 0

    def boom(n):
        raise ConnectionError("telegram down")

    def calm(n):
        n.dailies += 1
        return True

    b, c = Booming(), Calm()
    _guarded_deliver(state, [b, c], "daily", lambda n: boom(n) if n.kind == "booming" else calm(n))

    assert c.dailies == 1
    assert "daily:booming" not in state.state["notifications_sent_today"]
    assert "daily:calm" in state.state["notifications_sent_today"]


def test_circuit_manager_survives_state_reload(tmp_slc):
    """CircuitManager keeps a live handle on LoopState, so a reload (which swaps
    the internal dict) must not strand circuit updates in a dead dict."""
    state = LoopState()
    circuit = CircuitManager(state)
    circuit.record_failure("fake")
    state.save()

    state.reload()  # e.g. _guarded_deliver does this under the lock
    circuit.record_success("fake")

    assert state.state["sources"]["fake"]["total_successes"] == 1
    assert state.state["sources"]["fake"]["total_fails"] == 1


def test_save_jobs_atomic_merge(tmp_path):
    now = datetime.now(timezone.utc)
    mk = lambda i: NormalizedJob(
        id=f"id-{i}", title=f"Job {i}", title_normalized=f"job {i}",
        company="Acme", company_normalized="acme", url=f"https://x/{i}",
        source="fake", location="Remote", location_type="remote",
        salary_min=None, salary_max=None, salary_currency=None,
        job_type="unknown", posted_date=None, fetched_at=now,
        tags=[], description_snippet="",
    )
    p1 = save_jobs([mk(1), mk(2)], tmp_path)
    p2 = save_jobs([mk(2), mk(3)], tmp_path)  # same day, overlap id-2
    data = json.loads(p2.read_text(encoding="utf-8"))
    ids = {d["id"] for d in data}
    assert ids == {"id-1", "id-2", "id-3"}
    assert p1 == p2


def test_main_dry_run_never_writes_slc_or_output(tmp_slc, monkeypatch):
    """Rule 6, end-to-end: `python -m src.main --source fake --dry-run` must
    leave .slc/ AND output/ byte-for-byte untouched. The regression that
    motivated this: seen.save() and the dead-letter queue ran during dry-run,
    burning job hashes so a later real run silently skipped them."""
    import src.main as main
    import src.config as cfg

    monkeypatch.setenv("SCRAPE_KEYWORDS", "AI,ML")
    monkeypatch.setenv("SCRAPE_REMOTE_ONLY", "1")
    fake = FakeScraper([_raw(), _raw(title="ML Researcher")])
    monkeypatch.setattr(main, "get_scraper", lambda name: fake)

    out_dir = tmp_slc / "output"
    cfg.OUTPUT_DIR = out_dir
    cfg.RUNTIME_DIR = tmp_slc / ".runtime"

    def _snapshot():
        files = {}
        for p in cfg.SLC_DIR.iterdir():
            files[p.name] = p.read_text(encoding="utf-8") if p.suffix == ".json" else ""
        out = sorted(f.name for f in out_dir.iterdir()) if out_dir.exists() else []
        return files, out

    before = _snapshot()
    rc = main.main(["--source", "fake", "--dry-run"])
    after = _snapshot()

    assert rc == 0
    assert after == before, "dry-run mutated .slc/ or output/"

def test_main_exit_code_one_on_total_outage(tmp_slc, monkeypatch):
    """A real run where every scheduled source fails must exit 1 (monitoring
    signal); an all-sources-down day must not look identical to a good day.
    A total outage must ALSO suppress the daily heartbeat — exit 1 is the
    single alert, a 'no new jobs' Telegram would be noise on a DOWN day."""
    import src.main as main
    import src.config as cfg

    class Broken:
        name = "broken"
        def fetch(self, keywords, posted_after):
            raise RuntimeError("source exploded")
        def is_available(self):
            return True
        def login_required(self):
            return False

    delivered: list[str] = []

    class SpyNotifier:
        kind = "spy"
        def send_daily(self, jobs, stats):
            delivered.append("daily")
            return True
        def send_weekly_digest(self, stats, top_jobs):
            delivered.append("weekly")
            return True

    monkeypatch.setattr(main, "enabled_scrapers", lambda: ["broken"])
    monkeypatch.setattr(main, "get_scraper", lambda name: Broken())
    monkeypatch.setattr(main, "build_notifiers", lambda: [SpyNotifier()])
    cfg.OUTPUT_DIR = tmp_slc / "output"
    cfg.RUNTIME_DIR = tmp_slc / ".runtime"

    rc = main.main(["--window", "daily"])
    assert rc == 1
    assert delivered == [], "total outage must skip the daily heartbeat"


def test_outage_alert_cloud_runner_suppresses_send_ops_alert(tmp_slc, monkeypatch):
    """In cloud (JOB_LOOP_CLOUD=1), Python send_ops_alert is suppressed because
    GitHub Actions workflow has an `if: failure()` step that handles the Telegram ping.
    Double-alerting on the same exit-1 must not happen."""
    import src.main as main
    import src.config as cfg

    class Broken:
        name = "broken"
        def fetch(self, keywords, posted_after):
            raise RuntimeError("source exploded")
        def is_available(self):
            return True
        def login_required(self):
            return False

    alerts: list[str] = []
    monkeypatch.setattr(main, "enabled_scrapers", lambda: ["broken"])
    monkeypatch.setattr(main, "get_scraper", lambda name: Broken())
    monkeypatch.setattr(main, "build_notifiers", lambda: [])
    monkeypatch.setattr(main, "send_ops_alert", lambda msg: alerts.append(msg))
    monkeypatch.setenv("JOB_LOOP_PRIMARY", "github")
    monkeypatch.setenv("JOB_LOOP_CLOUD", "1")
    cfg.OUTPUT_DIR = tmp_slc / "output"
    cfg.RUNTIME_DIR = tmp_slc / ".runtime"

    rc = main.main(["--window", "daily"])
    assert rc == 1
    assert alerts == [], "cloud runner must suppress send_ops_alert to avoid duplex alert"


def test_outage_alert_local_runner_sends_ops_alert(tmp_slc, monkeypatch):
    """On local runner (JOB_LOOP_CLOUD unset), Python send_ops_alert fires on total outage."""
    import src.main as main
    import src.config as cfg

    class Broken:
        name = "broken"
        def fetch(self, keywords, posted_after):
            raise RuntimeError("source exploded")
        def is_available(self):
            return True
        def login_required(self):
            return False

    alerts: list[str] = []
    monkeypatch.setattr(main, "enabled_scrapers", lambda: ["broken"])
    monkeypatch.setattr(main, "get_scraper", lambda name: Broken())
    monkeypatch.setattr(main, "build_notifiers", lambda: [])
    monkeypatch.setattr(main, "send_ops_alert", lambda msg: alerts.append(msg))
    monkeypatch.delenv("JOB_LOOP_CLOUD", raising=False)
    cfg.OUTPUT_DIR = tmp_slc / "output"
    cfg.RUNTIME_DIR = tmp_slc / ".runtime"

    rc = main.main(["--window", "daily"])
    assert rc == 1
    assert len(alerts) == 1
    assert "total source outage" in alerts[0]


def test_main_exit_code_zero_when_a_source_succeeds_empty(tmp_slc, monkeypatch):
    """Exit 0 on a healthy quiet day (a source ran OK but found nothing) —
    the outage signal must not fire on silence alone. And a healthy 0-new-job
    day must still send the DAILY HEARTBEAT, so 'no message' is never
    ambiguous (0 jobs ≠ loop down)."""
    import src.main as main
    import src.config as cfg

    class Quiet:
        name = "quiet"
        def fetch(self, keywords, posted_after):
            return iter(())  # healthy, empty
        def is_available(self):
            return True
        def login_required(self):
            return False

    delivered: list[tuple] = []

    class SpyNotifier:
        kind = "spy"
        def send_daily(self, jobs, stats):
            delivered.append((jobs, stats))
            return True
        def send_weekly_digest(self, stats, top_jobs):
            delivered.append(("weekly", stats))
            return True

    monkeypatch.setattr(main, "enabled_scrapers", lambda: ["quiet"])
    monkeypatch.setattr(main, "get_scraper", lambda name: Quiet())
    monkeypatch.setattr(main, "build_notifiers", lambda: [SpyNotifier()])
    cfg.OUTPUT_DIR = tmp_slc / "output"
    cfg.RUNTIME_DIR = tmp_slc / ".runtime"

    rc = main.main(["--window", "daily"])
    assert rc == 0
    assert delivered, "healthy 0-new-job day must still send the daily heartbeat"
    jobs, stats = delivered[0]
    assert jobs == []


def test_seen_store_ttl_uses_utc(tmp_slc, monkeypatch):
    """Dedup TTL keys must be UTC (Beat 27 lesson) — a local `date.today()`
    in a UTC+ timezone returns a different day than `fetched_at`."""
    import src.state as state_mod

    # MUST go through monkeypatch: a bare assignment leaks the pinned date to
    # every later test in the suite (broke test_state_hygiene after UTC roll).
    monkeypatch.setattr(
        state_mod, "_utc_today",
        lambda: datetime(2026, 9, 15, tzinfo=timezone.utc).date(),
    )
    store = SeenStore()
    store.mark_exact("h1")
    assert store.seen_until["h1"] == "2026-09-15"


def test_run_scrape_pass_honors_window_sources(tmp_slc, monkeypatch):
    """The scrape pass must run ONLY the sources the window lists (Friday =
    ['linkedin']). A source outside the window must never be fetched, even if
    enabled_scrapers() would include it."""
    from datetime import datetime, timezone

    import src.main as main
    import src.config as cfg
    from src.schedule import FREQ_WEEKLY, FetchWindow

    called: list[str] = []
    fake = FakeScraper([_raw()])
    monkeypatch.setattr(main, "get_scraper",
                        lambda name: (called.append(name) or fake))
    # If the filter is ignored, these would all run too:
    monkeypatch.setattr(main, "enabled_scrapers",
                        lambda: ["all", "sources", "normally", "run"])

    w = FetchWindow(reason=FREQ_WEEKLY, window_start=datetime.now(timezone.utc),
                    window_end=datetime.now(timezone.utc), generate_digest=False,
                    window_label="test", day_of_week=4, sources=["linkedin"])
    monkeypatch.setattr(main, "compute_fetch_window", lambda: w)

    cfg.OUTPUT_DIR = tmp_slc / "output"
    cfg.RUNTIME_DIR = tmp_slc / ".runtime"

    rc = main.main(["--dry-run"])
    assert rc == 0
    assert called == ["linkedin"]


def test_health_check_server_endpoints():
    import urllib.request
    import urllib.error
    import src.main as main

    state = {"status": "running", "passes_completed": 3}
    server, thread = main.start_health_server(0, state)
    assert server is not None
    port = server.server_address[1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert data["status"] == "running"
            assert data["passes_completed"] == 3

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
            assert resp.status == 200
            assert b"OK" in resp.read()

        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/invalid", timeout=5)
        except urllib.error.HTTPError as err:
            assert err.code == 404
    finally:
        server.shutdown()
        server.server_close()


def test_serve_loop_graceful_shutdown(monkeypatch):
    import threading
    import src.main as main

    shutdown_ev = threading.Event()
    passes = []

    def mock_main(args):
        passes.append(args)
        shutdown_ev.set()
        return 0

    monkeypatch.setattr(main, "main", mock_main)
    rc = main.serve_loop(health_port=0, shutdown_event=shutdown_ev)
    assert rc == 0
    assert len(passes) == 1


# ── Timeout single-counting & outage honesty regression tests ────────────────

def test_run_source_timeout_single_circuit_count(tmp_path, monkeypatch):
    import time
    from unittest.mock import MagicMock
    from src.main import run_source
    from src.circuit_breaker import CircuitManager
    from src.dedup import SeenStore
    from src.state import DeadLetterQueue
    from src.scrapers import _REGISTRY, BaseScraper

    class SlowScraper(BaseScraper):
        name = "slow_test"
        def is_available(self):
            return True
        def fetch(self, kw, posted_after):
            time.sleep(0.15)
            raise RuntimeError("delayed crash after timeout")

    monkeypatch.setitem(_REGISTRY, "slow_test", SlowScraper)
    monkeypatch.setattr("src.config.DEAD_LETTER_PATH", tmp_path / "dlq.json")

    circuit = CircuitManager({})
    seen = SeenStore(path=tmp_path / "seen.json")
    outcomes = {}

    jobs = run_source(
        "slow_test",
        keywords=["AI"],
        posted_after=datetime.now(timezone.utc),
        seen=seen,
        circuit=circuit,
        max_jobs=10,
        dry_run=False,
        outcomes=outcomes,
        timeout_s=0.05,
    )

    assert jobs == []
    assert outcomes["slow_test"] == "timeout"
    assert circuit._get("slow_test").consecutive_fails == 1

    # Wait for the abandoned daemon worker to execute its delayed crash
    time.sleep(0.25)

    # Must STILL be 1 (never double-counted by the timed-out thread)
    assert circuit._get("slow_test").consecutive_fails == 1
    assert outcomes["slow_test"] == "timeout"

    dlq = DeadLetterQueue()
    assert len(dlq.items) == 1
    assert "TimeoutError" in dlq.items[0]["error"]


def test_run_source_scraper_failure_records_failed_outcome(tmp_path, monkeypatch):
    import requests
    from src.main import run_source
    from src.circuit_breaker import CircuitManager
    from src.dedup import SeenStore
    from src.state import DeadLetterQueue
    from src.scrapers import _REGISTRY, BaseScraper

    class BrokenScraper(BaseScraper):
        name = "broken_test"
        def is_available(self):
            return True
        def fetch(self, kw, posted_after):
            raise requests.ConnectionError("upstream board offline")

    monkeypatch.setitem(_REGISTRY, "broken_test", BrokenScraper)
    monkeypatch.setattr("src.config.DEAD_LETTER_PATH", tmp_path / "dlq.json")

    circuit = CircuitManager({})
    seen = SeenStore(path=tmp_path / "seen.json")
    outcomes = {}

    jobs = run_source(
        "broken_test",
        keywords=["AI"],
        posted_after=datetime.now(timezone.utc),
        seen=seen,
        circuit=circuit,
        max_jobs=10,
        dry_run=False,
        outcomes=outcomes,
        timeout_s=10.0,
    )

    assert jobs == []
    assert outcomes["broken_test"] == "failed"
    assert circuit._get("broken_test").consecutive_fails == 1
    dlq = DeadLetterQueue()
    assert len(dlq.items) == 1
    assert "upstream board offline" in dlq.items[0]["error"]


def test_main_dlq_flags(tmp_path, monkeypatch, capsys):
    from src.main import main
    from src.state import DeadLetterQueue

    dlq_file = tmp_path / "dlq.json"
    monkeypatch.setattr("src.config.DEAD_LETTER_PATH", dlq_file)

    # Empty DLQ display
    ret = main(["--dlq"])
    assert ret == 0
    assert "dead-letter queue is empty" in capsys.readouterr().out

    # Push an item
    dlq = DeadLetterQueue()
    dlq.push({"source": "unit_test", "error": "dummy error", "timestamp": "2026-09-17T12:00:00Z"})
    dlq.save()

    # Non-empty DLQ display
    ret = main(["--dlq"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "dead-letter queue (1 items):" in out
    assert "unit_test: dummy error" in out

    # Clear DLQ
    ret = main(["--clear-dlq"])
    assert ret == 0
    assert "[dlq] cleared 1 item(s)" in capsys.readouterr().out
    assert len(DeadLetterQueue().items) == 0


def test_main_stats_shows_dlq_count(tmp_path, monkeypatch, capsys):
    from src.main import main
    from src.state import DeadLetterQueue

    dlq_file = tmp_path / "dlq.json"
    monkeypatch.setattr("src.config.DEAD_LETTER_PATH", dlq_file)

    dlq = DeadLetterQueue()
    dlq.push({"source": "stats_test", "error": "err", "timestamp": "2026-09-17T12:00:00Z"})
    dlq.save()

    ret = main(["--stats"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "dead_letter_queue" in out
    assert "items=1" in out


def test_start_health_server_binds_localhost(monkeypatch):
    import socket
    from src.main import start_health_server

    # Find an open port on localhost
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    server, thread = start_health_server(port, {"status": "ok"})
    try:
        assert server.server_address[0] == "127.0.0.1"
        assert server.server_address[1] == port
    finally:
        server.shutdown()
        server.server_close()


def test_run_source_timeout_does_not_burn_jobs_in_seen(tmp_path, monkeypatch):
    """When a scraper times out after yielding a job, the jobs must NOT be burned

    in SeenStore. A subsequent run must still be able to discover and accept them.
    """
    import threading
    from src.main import run_source
    from src.circuit_breaker import CircuitManager
    from src.dedup import SeenStore, job_id
    from src.models import RawJob
    from src.scrapers import _REGISTRY, BaseScraper

    block_event = threading.Event()

    test_raw = RawJob(
        source="timeout_dedup_test",
        title="AI Engineer",
        company="TechCorp",
        url="https://example.com/ai-1",
        location="Worldwide Remote",
        posted_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        description="Build LLM systems with Python",
        tags=["AI"],
        fetched_at=datetime.now(timezone.utc),
    )

    class SlowScraper(BaseScraper):
        name = "timeout_dedup_test"
        def is_available(self):
            return True
        def fetch(self, kw, posted_after):
            yield test_raw
            block_event.wait(timeout=1.0)

    monkeypatch.setitem(_REGISTRY, "timeout_dedup_test", SlowScraper)

    seen = SeenStore(path=tmp_path / "seen.json")
    circuit = CircuitManager({})
    outcomes = {}

    # Run with small timeout so it aborts while blocked
    jobs = run_source(
        "timeout_dedup_test",
        keywords=["AI"],
        posted_after=datetime.now(timezone.utc) - timedelta(days=1),
        seen=seen,
        circuit=circuit,
        max_jobs=10,
        dry_run=False,
        outcomes=outcomes,
        timeout_s=0.05,
    )

    block_event.set()  # unblock worker thread

    assert jobs == []
    assert outcomes["timeout_dedup_test"] == "timeout"

    jid = job_id(test_raw.url, test_raw.title, test_raw.company)
    # The job must NOT be marked in seen!
    assert not seen.has_exact(jid)
    assert len(seen.recent_jobs()) == 0

    # On a normal run that does not timeout, the job must be successfully collected
    class FastScraper(BaseScraper):
        name = "timeout_dedup_test"
        def is_available(self):
            return True
        def fetch(self, kw, posted_after):
            yield test_raw

    monkeypatch.setitem(_REGISTRY, "timeout_dedup_test", FastScraper)
    circuit._get("timeout_dedup_test").record_success()

    jobs2 = run_source(
        "timeout_dedup_test",
        keywords=["AI"],
        posted_after=datetime.now(timezone.utc) - timedelta(days=1),
        seen=seen,
        circuit=circuit,
        max_jobs=10,
        dry_run=False,
        outcomes=outcomes,
        timeout_s=5.0,
    )

    assert len(jobs2) == 1
    assert seen.has_exact(jid)


def test_run_source_strict_24h_datetime_comparison(tmp_path, monkeypatch):
    """When a job has an ISO datetime, run_source must compare full datetime

    rather than only calendar date (preventing jobs >24h old from slipping in).
    """
    from src.main import run_source
    from src.circuit_breaker import CircuitManager
    from src.dedup import SeenStore
    from src.models import RawJob
    from src.scrapers import _REGISTRY, BaseScraper

    now = datetime.now(timezone.utc)
    posted_after = now - timedelta(hours=24)

    # Job from 30 hours ago (e.g. earlier yesterday)
    old_raw = RawJob(
        source="dt_test",
        title="Senior AI Engineer",
        company="OldCorp",
        url="https://example.com/old-1",
        location="Worldwide Remote",
        posted_date=(now - timedelta(hours=30)).isoformat(),
        description="Python LLM",
        tags=["AI"],
        fetched_at=now,
    )

    # Job from 10 hours ago (within 24h)
    fresh_raw = RawJob(
        source="dt_test",
        title="Senior AI Engineer",
        company="FreshCorp",
        url="https://example.com/fresh-1",
        location="Worldwide Remote",
        posted_date=(now - timedelta(hours=10)).isoformat(),
        description="Python LLM",
        tags=["AI"],
        fetched_at=now,
    )

    class DtScraper(BaseScraper):
        name = "dt_test"
        def is_available(self):
            return True
        def fetch(self, kw, dt):
            yield old_raw
            yield fresh_raw

    monkeypatch.setitem(_REGISTRY, "dt_test", DtScraper)

    seen = SeenStore(path=tmp_path / "seen.json")
    circuit = CircuitManager({})

    jobs = run_source(
        "dt_test",
        keywords=["AI"],
        posted_after=posted_after,
        seen=seen,
        circuit=circuit,
        max_jobs=10,
        dry_run=False,
    )

    # old_raw (30h ago) must be skipped, fresh_raw (10h ago) must be collected
    assert len(jobs) == 1
    assert jobs[0].company == "FreshCorp"


def test_list_sources_cloud_indicates_browser_bound(capsys, monkeypatch):
    import src.main as main
    monkeypatch.setenv("JOB_LOOP_CLOUD", "1")
    monkeypatch.delenv("CLOUD_ALLOW_BROWSER", raising=False)
    rc = main.main(["--list-sources"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "registered sources:" in out
    assert "disabled (browser-bound; skipped on cloud runner)" in out
    assert "linkedin" in out
    assert "indeed" in out
    assert "glassdoor" in out
    assert "enabled" in out


def test_smart_working_and_trellions_onsite_jobs_dropped(monkeypatch, tmp_path):
    """Ensure Smart Working and Trellions Pakistan on-site postings are dropped under SCRAPE_REMOTE_ONLY=1."""
    import src.main as main
    from src.models import RawJob, utc_now
    from src.scrapers import _REGISTRY, BaseScraper
    from src.state import SeenStore
    from src.circuit_breaker import CircuitManager

    yesterday = (utc_now() - timedelta(days=1)).strftime("%Y-%m-%d")

    j1 = RawJob(
        source="linkedin",
        title="Senior Data Engineer (Contract, Full-Time) [HR208] (PK)",
        company="Smart Working",
        url="https://pk.linkedin.com/jobs/view/senior-data-engineer-contract-full-time-hr208-pk-at-smart-working-4467172677",
        location="Islamabad, Islāmābād, Pakistan",
        description="Join one of the highest-rated workplaces and thrive in a truly remote-first world.",
        posted_date=yesterday,
        fetched_at=utc_now(),
    )
    j2 = RawJob(
        source="linkedin",
        title="Senior Software Engineer",
        company="Trellions",
        url="https://pk.linkedin.com/jobs/view/senior-software-engineer-at-trellions-4467121181",
        location="Pakistan",
        description="We are looking for experienced software engineers to join our team and work remotely.",
        posted_date=yesterday,
        fetched_at=utc_now(),
    )
    j3 = RawJob(
        source="linkedin",
        title="Senior AI Engineer",
        company="Acme Corp",
        url="https://pk.linkedin.com/jobs/view/acme-remote-12345",
        location="Pakistan (Remote)",
        description="100% remote work from home position.",
        posted_date=yesterday,
        fetched_at=utc_now(),
    )

    class TestScraper(BaseScraper):
        name = "test_drop_onsite"
        def is_available(self):
            return True
        def fetch(self, keywords, posted_after):
            return iter([j1, j2, j3])

    monkeypatch.setitem(_REGISTRY, "test_drop_onsite", TestScraper)
    monkeypatch.setenv("SCRAPE_REMOTE_ONLY", "1")

    seen = SeenStore(path=tmp_path / "seen.json")
    circuit = CircuitManager({})

    jobs = main.run_source(
        "test_drop_onsite",
        keywords=["AI"],
        posted_after=utc_now() - timedelta(days=2),
        seen=seen,
        circuit=circuit,
        max_jobs=10,
        dry_run=False,
    )

    # Only j3 (Pakistan (Remote)) must be kept
    assert len(jobs) == 1
    assert jobs[0].company == "Acme Corp"
    assert jobs[0].location_type == "remote"
    assert jobs[0].location == "Pakistan (Remote)"


def test_run_source_drops_us_only_and_restricted_jobs(tmp_path, monkeypatch):
    """Ensure US-only, domestic-restricted, physical city-hub, and foreign-restricted jobs are dropped."""
    import src.main as main
    from src.models import RawJob, utc_now
    from src.scrapers import _REGISTRY, BaseScraper
    from src.state import SeenStore
    from src.circuit_breaker import CircuitManager

    yesterday = (utc_now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # US-only in title with Worldwide location
    j_sixfeet = RawJob(
        source="python_org",
        title="Senior Python/DevOps Engineer (100% Remote - USA Only)",
        company="Six Feet Up",
        url="https://www.python.org/jobs/8113/",
        location="Worldwide",
        description="Must reside in the USA.",
        posted_date=yesterday,
        fetched_at=utc_now(),
    )
    # US domestic remote in location
    j_raven = RawJob(
        source="python_org",
        title="Software Engineer",
        company="Raven Technologies Group LLC",
        url="https://www.python.org/jobs/8132/",
        location="Remote, United States of America",
        description="Looking for remote US engineer.",
        posted_date=yesterday,
        fetched_at=utc_now(),
    )
    # Foreign country restricted (Poland/Ukraine)
    j_eleks = RawJob(
        source="python_org",
        title="Python developer",
        company="Eleks",
        url="https://www.python.org/jobs/8129/",
        location="Poland, Lviv, Ivano-Frankivsk, Ternopil, Uzhhorod, Chernivtsi or Kyiv, Ukraine/Poland",
        description="Python developer in Poland or Ukraine.",
        posted_date=yesterday,
        fetched_at=utc_now(),
    )
    # Hub-restricted in title
    j_amigo = RawJob(
        source="wellfound",
        title="Staff Software Engineer - Backend/Infra [NYC or SF]",
        company="Amigo AI",
        url="https://wellfound.com/jobs/4523599-staff-software-engineer-backend-infra-nyc-or-sf",
        location="Remote",
        description="Join our team in NYC or SF.",
        posted_date=yesterday,
        fetched_at=utc_now(),
    )
    # Onsite in title
    j_offduty = RawJob(
        source="python_org",
        title="Backend Software Engineer (FastAPI) -Onsite in Katy, Texas",
        company="Off Duty Management",
        url="https://www.python.org/jobs/8123/",
        location="Worldwide",
        description="Onsite position.",
        posted_date=yesterday,
        fetched_at=utc_now(),
    )
    # Legitimate worldwide remote (Sticker Mule)
    j_stickermule = RawJob(
        source="weworkremotely",
        title="AI agent engineer",
        company="Sticker Mule",
        url="https://weworkremotely.com/remote-jobs/sticker-mule-ai-agent-engineer",
        location="Anywhere in the World",
        description="We are 100% remote and hire worldwide.",
        posted_date=yesterday,
        fetched_at=utc_now(),
    )
    # Legitimate worldwide remote (Evaboot)
    j_evaboot = RawJob(
        source="python_org",
        title="Agentic Python Engineer",
        company="Evaboot",
        url="https://www.python.org/jobs/8133/",
        location="Worldwide",
        description="Build agentic AI workflows with Python and FastAPI.",
        posted_date=yesterday,
        fetched_at=utc_now(),
    )

    class TestScraper(BaseScraper):
        name = "test_drop_us_only"
        def is_available(self):
            return True
        def fetch(self, keywords, posted_after):
            return iter([j_sixfeet, j_raven, j_eleks, j_amigo, j_offduty, j_stickermule, j_evaboot])

    monkeypatch.setitem(_REGISTRY, "test_drop_us_only", TestScraper)
    monkeypatch.setenv("SCRAPE_REMOTE_ONLY", "1")

    seen = SeenStore(path=tmp_path / "seen.json")
    circuit = CircuitManager({})

    jobs = main.run_source(
        "test_drop_us_only",
        keywords=["AI"],
        posted_after=utc_now() - timedelta(days=2),
        seen=seen,
        circuit=circuit,
        max_jobs=10,
        dry_run=False,
    )

    # Only Sticker Mule and Evaboot must pass
    assert len(jobs) == 2
    companies = {j.company for j in jobs}
    assert companies == {"Sticker Mule", "Evaboot"}