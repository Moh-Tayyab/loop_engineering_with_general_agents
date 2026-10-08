"""Phase 2 (A2): domain registry, per-domain circuits, migration, sanitization."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
import os

import pytest

import src.config as cfg
from src.circuit_breaker import CircuitManager, domain_key, pick_domain_key
from src.scrapers.glassdoor import GlassdoorScraper
from src.scrapers.indeed import IndeedScraper
from src import session

_DOMAIN_VARS = (
    "INDEED_DOMAINS",
    "INDEED_DOMAINS_CLOUD",
    "GLASSDOOR_DOMAINS",
    "GLASSDOOR_DOMAINS_CLOUD",
    "JOB_LOOP_CLOUD",
)


@contextmanager
def monkeypatch_context(env: dict[str, str]):
    """Set env vars for the block, restoring on exit (migration tests)."""
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@pytest.fixture(autouse=True)
def _clean_domain_env(monkeypatch):
    for var in _DOMAIN_VARS:
        monkeypatch.delenv(var, raising=False)


# ── registry parsing ─────────────────────────────────────────────────────────

def test_parse_domains_valid_dedup_order():
    assert cfg.parse_domains("B.com, a.com ,b.com") == ["b.com", "a.com"]


def test_parse_domains_caps_at_fifteen():
    raw = ",".join(f"d{i}.example" for i in range(20))
    out = cfg.parse_domains(raw)
    assert len(out) == cfg.MAX_DOMAINS_PER_SOURCE == 15
    assert out[-1] == "d14.example"


def test_parse_domains_drops_invalid_tokens():
    raw = "https://evil.com, has space.com, .., a..b.com, /etc/passwd, 192.168.1.1, ok.example"
    assert cfg.parse_domains(raw) == ["ok.example"]


def test_parse_domains_rejects_scheme_and_path_like_hostnames():
    assert cfg.parse_domains("pk.indeed.com/jobs") == []
    assert cfg.parse_domains("-bad.example") == []
    assert cfg.parse_domains("bad-.example") == []


# ── source_domains: defaults, env override, cloud/local split ───────────────

def test_source_domains_defaults_are_fan_out_lists():
    """Beat 170 (owner: maximum jobs): unset env → multi-domain fan-out for
    Indeed (proven host FIRST so `_apply_domain` keeps its base), single for
    Glassdoor (owner scoped multi-domain to Indeed)."""
    assert cfg.source_domains("indeed") == [
        "pk.indeed.com", "www.indeed.com", "ae.indeed.com",
        "sa.indeed.com", "sg.indeed.com",
    ]
    assert cfg.source_domains("glassdoor") == ["www.glassdoor.com"]


def test_source_domains_non_registry_sources_empty():
    assert cfg.source_domains("linkedin") == []
    assert cfg.source_domains("") == []


def test_source_domains_env_override_local(monkeypatch):
    monkeypatch.setenv("INDEED_DOMAINS", "a.example, b.example")
    assert cfg.source_domains("indeed") == ["a.example", "b.example"]


def test_source_domains_cloud_split_prefers_cloud_var(monkeypatch):
    monkeypatch.setenv("INDEED_DOMAINS", "local.example")
    monkeypatch.setenv("INDEED_DOMAINS_CLOUD", "cloud.example, other.example")
    # local run: _CLOUD must be ignored
    assert cfg.source_domains("indeed") == ["local.example"]
    # cloud runner: _CLOUD wins
    monkeypatch.setenv("JOB_LOOP_CLOUD", "1")
    assert cfg.source_domains("indeed") == ["cloud.example", "other.example"]


def test_source_domains_cloud_falls_back_to_shared_var(monkeypatch):
    monkeypatch.setenv("GLASSDOOR_DOMAINS", "shared.example")
    monkeypatch.setenv("JOB_LOOP_CLOUD", "1")
    assert cfg.source_domains("glassdoor") == ["shared.example"]


# ── per-domain circuit keys + state-shape migration ─────────────────────────

def test_domain_key_shapes():
    assert domain_key("indeed", "pk.indeed.com") == "indeed:pk.indeed.com"
    assert domain_key("linkedin", None) == "linkedin"


def test_legacy_source_key_migrates_to_default_domain():
    state = {"sources": {"indeed": {"consecutive_fails": 3, "total_fails": 3}}}
    mgr = CircuitManager(state)
    assert "indeed:pk.indeed.com" in state["sources"]
    assert "indeed" not in state["sources"]
    c = mgr._get("indeed:pk.indeed.com")
    assert c.consecutive_fails == 3  # history carried over
    # idempotent on a second construction
    CircuitManager(state)
    assert list(state["sources"]) == ["indeed:pk.indeed.com"]


def test_migration_leaves_non_registry_sources_alone():
    state = {"sources": {"linkedin": {"consecutive_fails": 2}}}
    CircuitManager(state)
    assert "linkedin" in state["sources"]
    assert not any(":" in k for k in state["sources"])


def test_migration_merges_when_legacy_and_composite_coexist():
    """Coexistence: keep BOTH histories (totals summed, consecutive = max,
    open_until = later deadline) and drop the legacy key — CodeRabbit #3."""
    later = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    state = {"sources": {
        "indeed": {"consecutive_fails": 5, "total_fails": 7, "total_successes": 2},
        "indeed:pk.indeed.com": {"consecutive_fails": 1, "total_fails": 3,
                                 "total_successes": 4, "open_until": later},
    }}
    CircuitManager(state)
    merged = state["sources"]["indeed:pk.indeed.com"]
    assert merged["consecutive_fails"] == 5
    assert merged["total_fails"] == 10
    assert merged["total_successes"] == 6
    assert merged["open_until"] == later
    assert "indeed" not in state["sources"]


def test_migration_targets_default_host_not_env_override():
    """Legacy history belongs to the pre-Phase-2 host — a custom env override
    set at upgrade time must not re-home it (CodeRabbit #1)."""
    state = {"sources": {"indeed": {"consecutive_fails": 3}}}
    with monkeypatch_context({"INDEED_DOMAINS": "custom.example"}):
        CircuitManager(state)
    assert list(state["sources"]) == ["indeed:pk.indeed.com"]
    assert state["sources"]["indeed:pk.indeed.com"]["consecutive_fails"] == 3


def test_migration_runs_even_with_all_invalid_env():
    """Broken registry config must not silently skip migration (defect found
    in Beat 138 checker repro)."""
    state = {"sources": {"indeed": {"consecutive_fails": 4}}}
    with monkeypatch_context({"INDEED_DOMAINS": "https://bad, no space"}):
        CircuitManager(state)
    assert list(state["sources"]) == ["indeed:pk.indeed.com"]


def test_prune_unknown_keeps_composite_keys_for_known_sources():
    state = {"sources": {
        "indeed:pk.indeed.com": {"consecutive_fails": 1},
        "oldsource:old.example": {"consecutive_fails": 9},
    }}
    mgr = CircuitManager(state)
    removed = mgr.prune_unknown(frozenset({"indeed", "linkedin"}))
    assert removed == ["oldsource:old.example"]
    assert "indeed:pk.indeed.com" in state["sources"]


# ── pick_domain_key: per-domain availability ────────────────────────────────

def test_pick_domain_key_skips_open_circuits(monkeypatch):
    monkeypatch.setenv("INDEED_DOMAINS", "one.example, two.example")
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    state = {"sources": {
        "indeed:one.example": {"consecutive_fails": 5, "open_until": future},
        "indeed:two.example": {"consecutive_fails": 0},
    }}
    mgr = CircuitManager(state)
    assert pick_domain_key(mgr, "indeed") == "indeed:two.example"


def test_pick_domain_key_none_when_all_domain_circuits_open(monkeypatch):
    monkeypatch.setenv("INDEED_DOMAINS", "one.example")
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    state = {"sources": {"indeed:one.example": {"consecutive_fails": 5, "open_until": future}}}
    mgr = CircuitManager(state)
    assert pick_domain_key(mgr, "indeed") is None


def test_pick_domain_key_fail_closed_on_all_invalid_registry(monkeypatch):
    """All-invalid non-empty registry → None (skip), never the plain key:
    the plain-key fallback would scrape the hard-coded default host while
    recording under the wrong circuit (checker P1, Beat 138)."""
    monkeypatch.setenv("INDEED_DOMAINS", "https://evil.example, bad host")
    mgr = CircuitManager({"sources": {}})
    assert cfg.source_domains("indeed") == []
    assert pick_domain_key(mgr, "indeed") is None
    # glassdoor too
    monkeypatch.setenv("GLASSDOOR_DOMAINS", ".., /etc/passwd")
    assert pick_domain_key(mgr, "glassdoor") is None


def test_pick_domain_key_plain_source_for_non_registry(monkeypatch):
    mgr = CircuitManager({"sources": {}})
    assert pick_domain_key(mgr, "linkedin") == "linkedin"
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    open_mgr = CircuitManager({"sources": {"linkedin": {"consecutive_fails": 9, "open_until": future}}})
    assert pick_domain_key(open_mgr, "linkedin") is None


def test_per_domain_failures_do_not_block_other_domains(monkeypatch):
    """One domain's failures must not open the source's other domain."""
    monkeypatch.setenv("INDEED_DOMAINS", "bad.example, good.example")
    state: dict = {"sources": {}}
    mgr = CircuitManager(state)
    for _ in range(5):
        mgr.record_failure("indeed:bad.example", dry_run=True)
    assert pick_domain_key(mgr, "indeed") == "indeed:good.example"


# ── session source sanitization (PR #15 checker note) ───────────────────────

@pytest.mark.parametrize("bad", ["../evil", "a/b", "a\\b", "..", "", "./x"])
def test_session_file_rejects_traversal_sources(bad, tmp_path):
    with pytest.raises(ValueError):
        session.session_file(bad, base_dir=tmp_path)


def test_session_file_accepts_normal_sources(tmp_path):
    assert session.session_file("indeed", base_dir=tmp_path) == tmp_path / "indeed-session.json"


def test_save_and_load_reject_traversal_source(tmp_path):
    with pytest.raises(ValueError):
        session.save("../x", {"cookies": []}, base_dir=tmp_path)
    with pytest.raises(ValueError):
        session.load("../x", base_dir=tmp_path)


# ── scraper URL bases follow the registry ───────────────────────────────────

def test_indeed_apply_domain_uses_active_domain():
    s = IndeedScraper()
    s.active_domain = "sg.indeed.com"
    s._apply_domain()
    assert s._BASE == "https://sg.indeed.com"
    assert s._HOME == "https://sg.indeed.com/"
    assert s._SEARCH.startswith("https://sg.indeed.com/jobs?")


def test_indeed_apply_domain_defaults_to_registry_first(monkeypatch):
    monkeypatch.setenv("INDEED_DOMAINS", "first.example, second.example")
    s = IndeedScraper()
    s._apply_domain()
    assert s._BASE == "https://first.example"


def test_glassdoor_apply_domain_from_registry(monkeypatch):
    monkeypatch.setenv("GLASSDOOR_DOMAINS", "au.glassdoor.com")
    s = GlassdoorScraper()
    s._apply_domain()
    assert s._BASE == "https://au.glassdoor.com"
    assert s._SEARCH.startswith("https://au.glassdoor.com/Job/jobs.htm?")


def test_scraper_defaults_unchanged_without_registry():
    assert IndeedScraper()._BASE == "https://pk.indeed.com"
    assert GlassdoorScraper()._BASE == "https://www.glassdoor.com"


def test_parse_domains_rejects_label_longer_than_63_chars():
    long_label = "a" * 64 + ".example"
    assert cfg.parse_domains(long_label) == []


def test_migration_merges_open_until_chronologically_across_timezones():
    # 11:00-02:00 is 13:00 UTC, which is later than 12:00+00:00 UTC
    dt_legacy = "2026-10-01T11:00:00-02:00"
    dt_comp = "2026-10-01T12:00:00+00:00"
    state = {"sources": {
        "indeed": {"open_until": dt_legacy},
        "indeed:pk.indeed.com": {"open_until": dt_comp},
    }}
    CircuitManager(state)
    assert state["sources"]["indeed:pk.indeed.com"]["open_until"] == dt_legacy


def test_migration_handles_malformed_legacy_and_composite_records():
    # None or non-dict records must not crash CircuitManager
    state = {"sources": {
        "indeed": None,
        "glassdoor": "corrupt_string",
        "indeed:pk.indeed.com": None,
    }}
    CircuitManager(state)
    # indeed legacy is dropped, doesn't crash
    assert "indeed" not in state["sources"]
