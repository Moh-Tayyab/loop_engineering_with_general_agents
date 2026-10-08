"""Beat 158 — hireability gates: US-metro leaks + missing-location fail-closed.

Locks the Day-1 pilot finding: a "San Francisco, CA (Remote)" role with
worldwide-eligibility marketing in the description passed Rule 11, and jobs
with no scraped location skipped every location check. A Pakistan-based
candidate cannot work those jobs — the loop must fail closed, while keeping
PK-remote, worldwide-contractor, and proven-strong foreign roles open.
"""
from src.main import is_remotely_workable
from src.models import (
    LOCATION_REMOTE,
    _is_us_restricted,
    is_worldwide_remote,
)

STRONG = "Fully remote worldwide team. Work from anywhere in the world, no location requirements."
WEAK = "Great role with a nice team."


class TestUsMetroShortStringRule:
    def test_sf_remote_restricts_despite_strong_desc(self):
        assert _is_us_restricted("San Francisco, CA (Remote)")
        assert not is_worldwide_remote(
            "San Francisco, CA (Remote)", source="linkedin",
            description=STRONG, title="Senior Research Scientist LLM",
        )
        assert not is_remotely_workable(
            LOCATION_REMOTE, "San Francisco, CA (Remote)", source="linkedin",
            description=STRONG, title="Senior Research Scientist LLM",
        )

    def test_bare_city_state_restricts(self):
        assert _is_us_restricted("Austin, TX")
        assert _is_us_restricted("Seattle, WA")

    def test_multilocality_guards_hold(self):
        assert not _is_us_restricted("Remote - Austin and Berlin")
        assert not _is_us_restricted("hubs in Austin, TX and Berlin")
        assert not _is_us_restricted("Worldwide; hubs in Austin and Berlin")

    def test_proven_strong_foreign_stays_open(self):
        # Rule 11 B3 escape is for non-US geos only — unchanged.
        assert is_remotely_workable(
            LOCATION_REMOTE, "São Paulo", source="linkedin",
            description="Work from anywhere — worldwide remote team", title="AI Engineer",
        )


class TestMissingLocationFailClosed:
    def test_none_location_weak_desc_rejected(self):
        assert not is_remotely_workable(
            LOCATION_REMOTE, None, source="linkedin",
            description=WEAK, title="AI Engineer",
        )

    def test_empty_location_weak_desc_rejected(self):
        assert not is_remotely_workable(
            LOCATION_REMOTE, "  ", source="linkedin",
            description=WEAK, title="AI Engineer",
        )

    def test_none_location_strong_desc_stays_open(self):
        assert is_remotely_workable(
            LOCATION_REMOTE, None, source="linkedin",
            description=STRONG, title="AI Engineer",
        )


class TestRealisticSegmentsStillPass:
    def test_pk_remote_passes(self):
        assert is_remotely_workable(
            LOCATION_REMOTE, "Remote, Pakistan", source="linkedin",
            description=WEAK, title="ML Engineer",
        )

    def test_worldwide_contractor_passes(self):
        assert is_remotely_workable(
            LOCATION_REMOTE, "Worldwide (Contractor)", source="linkedin",
            description=WEAK, title="ODI Developer",
        )

    def test_bare_worldwide_passes(self):
        assert is_remotely_workable(
            LOCATION_REMOTE, "Worldwide", source="linkedin",
            description=WEAK, title="AI Engineer",
        )
