"""GateChain (Candidate #2) — the 9-gate qualification pipeline.

Decouples candidate job evaluation from orchestrator threads, timeouts,
circuit breakers, and domain fan-out. Maps one RawJob to a NormalizedJob
(if accepted) or a structured rejection verdict.

Pipeline Stages:
 1. ai_keyword   — target keyword relevance match
 2. expired      — closed / expired title or description
 3. normalize    — schema mapping, location classification, CV scoring
 4. window       — strict datetime / calendar date cutoff against posted_after
 5. recency      — strict 24h fail-closed if posted date cannot be determined
 6. url          — valid job URL check (drops recruiter/profile links)
 7. rule11       — LocationLaw remote eligibility (APAC/ME, Worldwide, B2B)
 8. cv_match     — profile matching threshold gate
 9. quality      — drops records missing both company and description
10. dedup        — exact (URL/hash) and fuzzy title+company suppression
11. link_health  — network HEAD verification on surviving links
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Iterable

from src import config as cfg
from src.dedup import SeenStore, dedup_job
from src.location_law import DAILY_DISQUALIFY, evaluate as evaluate_location
from src.models import (
    LOCATION_REMOTE,
    NormalizedJob,
    RawJob,
    ai_keyword_matches,
    canonical_job_url,
    check_link_health,
    classify_job_type,
    classify_location,
    is_expired_job,
    is_valid_job_url,
    is_worldwide_remote,
    job_id,
    normalize_text,
    parse_posted_date,
    parse_posted_datetime,
    parse_salary,
    utc_now,
)

if TYPE_CHECKING:
    import threading

log = logging.getLogger(__name__)


# ── Verdict & Audit Dataclasses ───────────────────────────────────────────────

@dataclass(frozen=True)
class GateResult:
    """Outcome of evaluating a RawJob through the gate chain."""
    accepted: bool
    job: NormalizedJob | None = None
    gate: str | None = None
    reason: str | None = None


def record_reject(sink: list[dict] | None, source: str, title: str, gate: str, reason: str) -> None:
    """Append a filter-rejection audit row (written to output/rejected.jsonl on real runs)."""
    if sink is None:
        return
    sink.append({
        "source": source,
        "title": (title or "")[:120],
        "gate": gate,
        "reason": reason,
        "ts": utc_now().isoformat(timespec="seconds"),
    })


# ── Normalization ────────────────────────────────────────────────────────────

def normalize_raw(raw: RawJob) -> NormalizedJob:
    """Convert a source-specific RawJob to the standard NormalizedJob schema."""
    url = canonical_job_url(raw.url, source=raw.source)
    salary_min, salary_max, salary_currency = parse_salary(raw.salary)
    location_type = classify_location(raw.location, title=raw.title)
    if location_type != LOCATION_REMOTE and raw.location:
        if is_worldwide_remote(raw.location, source=raw.source, description=raw.description, title=raw.title):
            location_type = LOCATION_REMOTE
    jid = job_id(url, raw.title, raw.company, source=raw.source)
    # Keep enough body for Rule 11 (location law / description restrictions)
    # without dumping multi-KB pages into every daily JSON row.
    snippet = (raw.description or "")[:2000]
    from src.matcher import passing_profiles
    scored = passing_profiles(raw.title, raw.description, raw.tags)
    profile_scores = {name: score for name, score, _ in scored}
    if scored:
        best_name, cv_score, cv_label = scored[0]
    else:
        best_name, cv_score, cv_label = "", 0, "Rejected (no pilot profile match)"
    return NormalizedJob(
        id=jid,
        title=raw.title,
        title_normalized=normalize_text(raw.title),
        company=raw.company,
        company_normalized=normalize_text(raw.company),
        url=url,
        source=raw.source,
        location=raw.location,
        location_type=location_type,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=salary_currency,
        job_type=classify_job_type(raw.job_type),
        posted_date=parse_posted_date(raw.posted_date),
        fetched_at=raw.fetched_at,
        tags=raw.tags,
        description_snippet=snippet,
        cv_match_score=cv_score,
        cv_match_label=cv_label,
        profile_scores=profile_scores,
        profile_best=best_name,
        raw=raw.to_dict(),
    )


def is_remotely_workable(
    location_type: str,
    location: str | None = None,
    source: str | None = None,
    description: str | None = None,
    title: str | None = None,
) -> bool:
    """True only when the job is clearly worldwide-remote per LocationLaw DAILY projection."""
    return evaluate_location(
        location, source, description, title,
        location_type=location_type, disqualify=DAILY_DISQUALIFY,
    ).ok


# ── The Gate Chain ────────────────────────────────────────────────────────────

class GateChain:
    """Autonomous qualification pipeline evaluating raw jobs through all 9 gates."""

    def __init__(
        self,
        posted_after: datetime,
        seen: SeenStore | None = None,
        keywords: list[str] | None = None,
        scrape_remote_only: bool | None = None,
        batch_ids: set[str] | None = None,
        batch_recent: list[dict] | None = None,
        rejects: list[dict] | None = None,
        check_link_health: bool = True,
    ) -> None:
        self.posted_after = posted_after
        self.seen = seen
        self.keywords = keywords if keywords is not None else cfg.scan_keywords()
        self.scrape_remote_only = scrape_remote_only if scrape_remote_only is not None else cfg.scrape_remote_only()
        self.batch_ids = batch_ids if batch_ids is not None else set()
        self.batch_recent = batch_recent if batch_recent is not None else []
        self.rejects = rejects
        self.check_link_health = check_link_health

    def _record(self, source: str, title: str, gate: str, reason: str) -> None:
        record_reject(self.rejects, source, title, gate, reason)

    def evaluate(self, raw: RawJob, source: str | None = None) -> GateResult:
        """Run a single RawJob through the gate chain.
        
        Returns GateResult(accepted=True, job=normalized) or GateResult(accepted=False, gate=..., reason=...).
        """
        source_name = source or raw.source

        # Gate 1: AI Keyword Match
        if not ai_keyword_matches(raw, self.keywords):
            self._record(source_name, raw.title, "ai_keyword", "no AI keyword match")
            return GateResult(accepted=False, gate="ai_keyword", reason="no AI keyword match")

        # Gate 2: Expiration / Closed Posting
        if is_expired_job(raw):
            log.info("[%s] skipping expired: %s", source_name, (raw.title or "")[:60])
            self._record(source_name, raw.title, "expired", "expired/closed title or body")
            return GateResult(accepted=False, gate="expired", reason="expired/closed title or body")

        # Gate 3: Schema Normalization & Profile Scoring
        normalized = normalize_raw(raw)

        # Gate 4: Window Comparison (strict datetime first, then calendar date)
        posted_dt = parse_posted_datetime(raw.posted_date)
        if posted_dt is not None:
            cmp_after = self.posted_after if self.posted_after.tzinfo is not None else self.posted_after.replace(tzinfo=timezone.utc)
            if posted_dt.tzinfo is None:
                posted_dt = posted_dt.replace(tzinfo=timezone.utc)
            if posted_dt < cmp_after:
                log.debug("[%s] skipping outside datetime window (%s < %s): %s",
                          source_name, posted_dt, cmp_after, (raw.title or "")[:50])
                self._record(source_name, raw.title, "window", "posted datetime before window")
                return GateResult(accepted=False, gate="window", reason="posted datetime before window")

        cutoff_date = self.posted_after.date()
        if normalized.posted_date and normalized.posted_date < cutoff_date:
            log.debug("[%s] skipping outside window (%s < %s): %s",
                      source_name, normalized.posted_date, cutoff_date, (raw.title or "")[:50])
            self._record(source_name, raw.title, "window", "posted date before window")
            return GateResult(accepted=False, gate="window", reason="posted date before window")

        # Gate 5: Strict 24h Fail-Closed (no parseable date)
        if posted_dt is None and normalized.posted_date is None:
            log.info("[%s] dropping job with no parseable posted date (strict 24h): %s",
                     source_name, (raw.title or "")[:60])
            self._record(source_name, raw.title, "recency", "no parseable posted date")
            return GateResult(accepted=False, gate="recency", reason="no parseable posted date")

        # Gate 6: URL Validity (drops recruiter / profile links)
        if not is_valid_job_url(raw.url):
            log.info("[%s] dropping job with invalid or profile URL: %s (%s)",
                     source_name, raw.url, (raw.title or "")[:50])
            reason = f"invalid URL: {raw.url}"
            self._record(source_name, raw.title, "url", reason)
            return GateResult(accepted=False, gate="url", reason=reason)

        # Gate 7: Rule 11 Location Law (Worldwide / APAC / Middle East remote only)
        if self.scrape_remote_only and not is_remotely_workable(
            normalized.location_type,
            raw.location,
            source=source_name,
            description=raw.description,
            title=raw.title,
        ):
            reason = f"not remotely workable: loc={raw.location!r}"
            self._record(source_name, raw.title, "rule11", reason)
            return GateResult(accepted=False, gate="rule11", reason=reason)

        # Gate 8: Profile Match Thresholds
        from src.matcher import meets_threshold
        gate_scores = normalized.profile_scores or (
            {normalized.profile_best: normalized.cv_match_score} if normalized.profile_best else {}
        )
        passed = any(meets_threshold(name, s) for name, s in gate_scores.items())
        if not passed:
            detail = ", ".join(f"{n}={s}" for n, s in sorted(gate_scores.items())) or f"score {normalized.cv_match_score}"
            log.debug("[%s] dropping role failing profile gates (%s): %s",
                      source_name, detail, (raw.title or "")[:50])
            reason = f"below profile thresholds: {detail}"
            self._record(source_name, raw.title, "cv_match", reason)
            return GateResult(accepted=False, gate="cv_match", reason=reason)

        # Gate 9: Quality Gate (drop missing company AND missing description)
        if (normalized.company in ("Unknown", "N/A", "n/a") or not normalized.company) and not raw.description:
            log.debug("[%s] quality-gate: dropping %s (no company + no description)", source_name, (raw.title or "")[:50])
            self._record(source_name, raw.title, "quality", "no company + no description")
            return GateResult(accepted=False, gate="quality", reason="no company + no description")

        # Gate 10: Deduplication (seen store + batch sets)
        if self.seen is not None:
            is_new, dedup_reason = dedup_job(normalized, self.seen, extra_ids=self.batch_ids, extra_recent=self.batch_recent)
            if not is_new:
                reason = dedup_reason or "duplicate"
                self._record(source_name, raw.title, "dedup", reason)
                return GateResult(accepted=False, gate="dedup", reason=reason)

        # Gate 11: Link Health (network HEAD verification only on unique surviving jobs)
        if self.check_link_health:
            if not check_link_health(raw.url):
                log.info("[%s] dropping job with dead URL: %s (%s)",
                         source_name, raw.url, (raw.title or "")[:50])
                reason = f"dead URL: {raw.url}"
                self._record(source_name, raw.title, "url", reason)
                return GateResult(accepted=False, gate="url", reason=reason)

        # Passed all gates: register in batch sets
        self.batch_ids.add(normalized.id)
        self.batch_recent.append(normalized.to_dict())
        return GateResult(accepted=True, job=normalized)
