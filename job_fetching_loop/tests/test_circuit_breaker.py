"""Tests for the circuit breaker resilience pattern."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.circuit_breaker import CircuitManager, CircuitState


def _now():
    return datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


def test_initial_closed():
    c = CircuitState("indeed")
    assert not c.is_open(_now())


def test_opens_after_threshold(monkeypatch):
    monkeypatch.setenv("CIRCUIT_BREAKER_THRESHOLD", "3")
    c = CircuitState("indeed")
    c.record_failure(_now())
    c.record_failure(_now())
    assert not c.is_open(_now())
    c.record_failure(_now())
    assert c.is_open(_now())


def test_resets_after_timeout(monkeypatch):
    monkeypatch.setenv("CIRCUIT_BREAKER_THRESHOLD", "2")
    monkeypatch.setenv("CIRCUIT_BREAKER_RESET_HOURS", "1")
    c = CircuitState("indeed")
    c.record_failure(_now())
    c.record_failure(_now())
    earlier = _now()
    later = earlier + timedelta(hours=2)
    assert c.is_open(earlier)
    assert not c.is_open(later)  # open expired


def test_success_closes_circuit(monkeypatch):
    monkeypatch.setenv("CIRCUIT_BREAKER_THRESHOLD", "2")
    c = CircuitState("indeed")
    c.record_failure(_now())
    c.record_failure(_now())
    assert c.is_open(_now())
    c.record_success()
    assert not c.is_open(_now())


def test_manager_skip_open_source(monkeypatch):
    monkeypatch.setenv("CIRCUIT_BREAKER_THRESHOLD", "2")
    mgr = CircuitManager({"sources": {}})
    for _ in range(2):
        mgr.record_failure("indeed")
    assert not mgr.is_available("indeed")
    assert mgr.is_available("glassdoor")  # untouched


def test_manager_persists_via_state():
    backing = {"sources": {}}
    mgr = CircuitManager(backing)
    mgr.record_failure("indeed")
    mgr.record_failure("indeed")
    assert "indeed" in backing["sources"]
    assert backing["sources"]["indeed"]["consecutive_fails"] == 2


def test_manager_reset_all():
    mgr = CircuitManager({"sources": {}})
    mgr.record_failure("indeed")
    mgr.record_failure("glassdoor")
    mgr.reset_all()
    assert mgr.is_available("indeed")
    assert mgr.is_available("glassdoor")