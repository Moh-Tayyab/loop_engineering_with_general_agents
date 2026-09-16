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


def _raw(title="Machine Learning Engineer", location="Remote", posted_date=None):
    from datetime import datetime, timezone
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

    state_mod._utc_today = lambda: datetime(2026, 9, 15, tzinfo=timezone.utc).date()
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