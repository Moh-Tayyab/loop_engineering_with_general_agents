"""Circuit breaker: prevents hammering a failing source.

Three states per source:
  CLOSED  → normal operation; failures counted.
  OPEN    → failure threshold hit; skip this source for `reset_after`.
  HALF-OPEN → after `reset_after`, allow ONE probe request.
              Success → CLOSED; Failure → OPEN again.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import src.config as cfg
from src.state import LoopState


@dataclass
class CircuitState:
    source: str
    consecutive_fails: int = 0
    open_until: datetime | None = None
    total_fails: int = 0
    total_successes: int = 0

    def is_open(self, now: datetime | None = None) -> bool:
        """Pure read: True while a reset deadline is still in the future.

        Never mutates state — reopening the circuit after the timeout is a
        separate, explicit step so a read can't change the world."""
        if self.open_until is None:
            return False
        now = now or datetime.now(timezone.utc)
        return now < self.open_until

    def clear_if_due(self, now: datetime | None = None) -> bool:
        """Close the circuit if the reset deadline has passed.

        Returns True when it actually closed (callers can flush to disk)."""
        if self.open_until is None:
            return False
        now = now or datetime.now(timezone.utc)
        if now >= self.open_until:
            self.open_until = None
            return True
        return False

    def record_success(self) -> None:
        self.consecutive_fails = 0
        self.open_until = None
        self.total_successes += 1

    def record_failure(self, now: datetime | None = None) -> None:
        self.consecutive_fails += 1
        self.total_fails += 1
        threshold = cfg.circuit_breaker_threshold()
        if self.consecutive_fails >= threshold:
            reset_hours = cfg.circuit_breaker_reset_hours()
            self.open_until = (now or datetime.now(timezone.utc)) + timedelta(hours=reset_hours)

    def to_dict(self) -> dict[str, Any]:
        return {
            "consecutive_fails": self.consecutive_fails,
            "open_until": self.open_until.isoformat(timespec="seconds") if self.open_until else None,
            "total_fails": self.total_fails,
            "total_successes": self.total_successes,
        }

    @classmethod
    def from_dict(cls, source: str, d: dict[str, Any]) -> "CircuitState":
        open_until = None
        raw = d.get("open_until")
        if raw:
            try:
                open_until = datetime.fromisoformat(str(raw))
            except ValueError:
                pass
        return cls(
            source=source,
            consecutive_fails=int(d.get("consecutive_fails", 0)),
            open_until=open_until,
            total_fails=int(d.get("total_fails", 0)),
            total_successes=int(d.get("total_successes", 0)),
        )


def domain_key(source: str, domain: str | None) -> str:
    """Per-domain circuit key (Phase 2 / A2): `source:domain`, or the plain
    source key when the source has no domain scoping (legacy behaviour)."""
    return f"{source}:{domain}" if domain else source


class CircuitManager:
    """Manage circuit breakers for all sources, persisted via LoopState.

    Accepts either a LoopState (preferred) or a plain dict. Holding the
    container — not a snapshot of its dict — keeps the manager correct across
    `LoopState.reload()`, which swaps in a fresh dict under the lock.
    """

    def __init__(self, state: LoopState | dict[str, Any]) -> None:
        self._container = state
        self._circuits: dict[str, CircuitState] = {}
        self._migrate_legacy_domain_keys()
        for name, data in self._sources().items():
            if isinstance(data, dict):
                self._circuits[name] = CircuitState.from_dict(name, data)

    def _migrate_legacy_domain_keys(self) -> None:
        """Phase 2 (A2) state-shape migration: legacy plain `source` entries
        for domain-scoped sources become `source:<default-domain>` in place,
        carrying failure history. Runs once at construction; idempotent
        (composite keys and non-registry sources are untouched)."""
        current = self._sources()
        defaults: dict[str, str] = {}
        for src in cfg.DOMAIN_SOURCES:
            domains = cfg.source_domains(src)
            if domains:
                defaults[src] = domains[0]
        for key in list(current):
            if ":" in key or key not in defaults:
                continue
            new_key = f"{key}:{defaults[key]}"
            value = current.pop(key)
            if new_key not in current:  # first write wins; never clobber
                current[new_key] = value

    def _sources(self) -> dict[str, Any]:
        current = self._container.state if isinstance(self._container, LoopState) else self._container
        return current.get("sources", {})

    def _get(self, source: str) -> CircuitState:
        if source not in self._circuits:
            self._circuits[source] = CircuitState(source=source)
        return self._circuits[source]

    def is_available(self, source: str) -> bool:
        """True when the source may be hit; closes an expired circuit first."""
        c = self._get(source)
        if c.clear_if_due():
            self._flush()
        return not c.is_open()

    def record_success(self, source: str) -> None:
        self._get(source).record_success()
        self._flush()

    def record_failure(self, source: str, *, dry_run: bool = False) -> None:
        c = self._get(source)
        was_open = c.is_open()
        c.record_failure()
        self._flush()
        # C1: alert the moment a circuit opens (CAPTCHA/timeout outage is
        # otherwise silent). CodeRabbit CR: dry runs have no side effects —
        # never send a real ops alert from one (AGENTS.md §2 rule 6).
        if c.is_open() and not was_open and not dry_run:
            try:
                from src.notifier import send_ops_alert
                send_ops_alert(
                    f"circuit OPEN for `{source}` after {c.consecutive_fails} consecutive failures "
                    f"(resets {c.open_until.isoformat(timespec='seconds') if c.open_until else 'n/a'}). "
                    f"Local headed run or --reset-circuit to recover."
                )
            except Exception:
                pass  # alerting must never break the scrape path

    def reset_all(self) -> None:
        for c in self._circuits.values():
            c.consecutive_fails = 0
            c.open_until = None
        self._flush()

    def prune_unknown(self, known: frozenset[str] | set[str]) -> list[str]:
        """Drop circuit entries for sources that no longer exist (post-purge).

        Phase 2: composite `source:domain` keys compare by their base source
        part, so per-domain entries survive pruning while entries for removed
        sources (any domain) are still dropped. Returns the keys removed."""
        stale = [
            name for name in list(self._circuits)
            if name.split(":", 1)[0] not in known
        ]
        for name in stale:
            del self._circuits[name]
        if stale:
            self._flush()
        return stale

    def _flush(self) -> None:
        out = {}
        for name, c in self._circuits.items():
            out[name] = c.to_dict()
        current = self._container.state if isinstance(self._container, LoopState) else self._container
        current["sources"] = out

    def summary(self) -> list[dict[str, Any]]:
        out = []
        for c in self._circuits.values():
            if c.clear_if_due():
                self._flush()
            out.append({
                "source": c.source,
                "status": "OPEN" if c.is_open() else "CLOSED",
                "consecutive_fails": c.consecutive_fails,
                "open_until": c.open_until.isoformat() if c.open_until else None,
                "total_ok": c.total_successes,
                "total_fail": c.total_fails,
            })
        return out

def pick_domain_key(circuit: CircuitManager, source: str) -> str | None:
    """Resolve the circuit key to run `source` under (Phase 2 / A2).

    Registry sources: first domain whose `source:domain` circuit is closed →
    that composite key (per-domain breakers — one domain's CAPTCHA/timeout no
    longer takes the whole source down). No available domain → None (skip).
    Non-registry sources: the plain source key when closed, else None."""
    domains = cfg.source_domains(source)
    if not domains:
        return source if circuit.is_available(source) else None
    for dom in domains:
        key = domain_key(source, dom)
        if circuit.is_available(key):
            return key
    return None
