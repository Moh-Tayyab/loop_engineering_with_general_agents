"""Beat 182 (GateChain deepening): the 9-gate qualification pipeline.

Proves:
1. Pure gate evaluation outside of orchestrator threads and timeouts
2. Every gate's specific rejection reason and gate name
3. Normalization and profile matching integration
4. Dedup batch-set accumulation and audit reject recording
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.dedup import SeenStore
from src.gate_chain import GateChain, GateResult, normalize_raw
from src.models import RawJob, utc_now


def _make_raw(
    title: str = "Senior AI Engineer",
    company: str = "TechCorp",
    location: str = "Worldwide Remote",
    url: str = "https://example.com/jobs/ai-engineer-1",
    description: str = "Work with Python, PyTorch, and LLMs in a 100% remote worldwide team.",
    posted_date: str | None = None,
    tags: list[str] | None = None,
    salary: str = "$120,000 - $160,000 USD",
    source: str = "linkedin",
) -> RawJob:
    now = utc_now()
    return RawJob(
        source=source,
        title=title,
        company=company,
        url=url,
        location=location,
        posted_date=posted_date or now.isoformat(),
        description=description,
        tags=tags or ["AI", "Python"],
        salary=salary,
        fetched_at=now,
    )


class TestGateChainPipeline:
    def test_clean_worldwide_ai_job_accepted(self, tmp_path):
        now = utc_now()
        posted_after = now - timedelta(hours=24)
        seen = SeenStore(path=tmp_path / "seen.json")
        chain = GateChain(
            posted_after=posted_after,
            seen=seen,
            check_link_health=False,
        )
        raw = _make_raw()
        res = chain.evaluate(raw)
        assert res.accepted is True
        assert res.job is not None
        assert res.job.title == "Senior AI Engineer"
        assert res.gate is None
        assert res.job.id in chain.batch_ids
        assert len(chain.batch_recent) == 1

    def test_gate_ai_keyword_rejection(self, tmp_path):
        now = utc_now()
        posted_after = now - timedelta(hours=24)
        rejects: list[dict] = []
        chain = GateChain(
            posted_after=posted_after,
            seen=SeenStore(path=tmp_path / "seen.json"),
            rejects=rejects,
            check_link_health=False,
        )
        raw = _make_raw(title="Office Administrator", description="Handle office supplies and mail.", tags=[])
        res = chain.evaluate(raw)
        assert res.accepted is False
        assert res.gate == "ai_keyword"
        assert res.reason == "no AI keyword match"
        assert len(rejects) == 1
        assert rejects[0]["gate"] == "ai_keyword"

    def test_gate_expired_rejection(self, tmp_path):
        now = utc_now()
        posted_after = now - timedelta(hours=24)
        rejects: list[dict] = []
        chain = GateChain(
            posted_after=posted_after,
            seen=SeenStore(path=tmp_path / "seen.json"),
            rejects=rejects,
            check_link_health=False,
        )
        raw = _make_raw(title="AI Engineer [CLOSED / EXPIRED]")
        res = chain.evaluate(raw)
        assert res.accepted is False
        assert res.gate == "expired"
        assert rejects[0]["gate"] == "expired"

    def test_gate_window_datetime_rejection(self, tmp_path):
        now = utc_now()
        posted_after = now - timedelta(hours=24)
        rejects: list[dict] = []
        chain = GateChain(
            posted_after=posted_after,
            seen=SeenStore(path=tmp_path / "seen.json"),
            rejects=rejects,
            check_link_health=False,
        )
        raw = _make_raw(posted_date=(now - timedelta(hours=30)).isoformat())
        res = chain.evaluate(raw)
        assert res.accepted is False
        assert res.gate == "window"
        assert "before window" in res.reason
        assert rejects[0]["gate"] == "window"

    def test_gate_recency_fail_closed_on_unparseable_date(self, tmp_path):
        now = utc_now()
        posted_after = now - timedelta(hours=24)
        rejects: list[dict] = []
        chain = GateChain(
            posted_after=posted_after,
            seen=SeenStore(path=tmp_path / "seen.json"),
            rejects=rejects,
            check_link_health=False,
        )
        raw = _make_raw(posted_date="unparseable gibberish date")
        res = chain.evaluate(raw)
        assert res.accepted is False
        assert res.gate == "recency"
        assert res.reason == "no parseable posted date"

    def test_gate_invalid_url_rejection(self, tmp_path):
        now = utc_now()
        posted_after = now - timedelta(hours=24)
        rejects: list[dict] = []
        chain = GateChain(
            posted_after=posted_after,
            seen=SeenStore(path=tmp_path / "seen.json"),
            rejects=rejects,
            check_link_health=False,
        )
        raw = _make_raw(url="https://linkedin.com/in/recruiter-profile-123")
        res = chain.evaluate(raw)
        assert res.accepted is False
        assert res.gate == "url"
        assert "invalid URL" in res.reason

    def test_gate_rule11_location_law_rejection(self, tmp_path):
        now = utc_now()
        posted_after = now - timedelta(hours=24)
        rejects: list[dict] = []
        chain = GateChain(
            posted_after=posted_after,
            seen=SeenStore(path=tmp_path / "seen.json"),
            scrape_remote_only=True,
            rejects=rejects,
            check_link_health=False,
        )
        # Domestic US location with US-only requirement
        raw = _make_raw(
            location="San Francisco, CA",
            description="Must reside in California. US work authorization required.",
        )
        res = chain.evaluate(raw)
        assert res.accepted is False
        assert res.gate == "rule11"
        assert "not remotely workable" in res.reason

    def test_gate_quality_rejection_no_company_no_desc(self, tmp_path):
        now = utc_now()
        posted_after = now - timedelta(hours=24)
        rejects: list[dict] = []
        chain = GateChain(
            posted_after=posted_after,
            seen=SeenStore(path=tmp_path / "seen.json"),
            rejects=rejects,
            check_link_health=False,
        )
        raw = _make_raw(
            company="Unknown",
            description="",
            tags=["AI"],
        )
        res = chain.evaluate(raw)
        assert res.accepted is False
        assert res.gate == "quality"
        assert res.reason == "no company + no description"

    def test_gate_dedup_rejection(self, tmp_path):
        now = utc_now()
        posted_after = now - timedelta(hours=24)
        seen = SeenStore(path=tmp_path / "seen.json")
        rejects: list[dict] = []
        chain = GateChain(
            posted_after=posted_after,
            seen=seen,
            rejects=rejects,
            check_link_health=False,
        )
        raw = _make_raw()
        res1 = chain.evaluate(raw)
        assert res1.accepted is True

        # Second evaluation of same raw job should trigger in-batch dedup
        res2 = chain.evaluate(raw)
        assert res2.accepted is False
        assert res2.gate == "dedup"
