"""Beat 177 (LocationLaw deepening): one evaluator, three stage projections.

Proves the migration preserved each gate's exact strictness — including the
DELIBERATE differences between stages (guest pre-filter vs daily vs digest).
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.location_law import (
    DAILY_DISQUALIFY,
    DIGEST_DISQUALIFY,
    GUEST_DISQUALIFY,
    evaluate,
    inspect,
)
from src.main import is_remotely_workable
from src.models import LOCATION_REMOTE


def _desc(text: str) -> str:
    return text


WW_DESC = "We are a worldwide remote team hiring across time zones. 100% remote."
US_DESC = "Must be based in California. US work authorization required."
HYBRID_TITLE = "Senior AI Engineer (Hybrid)"
US_TITLE = "AI Engineer (100% Remote - USA Only)"


class TestSingleSurface:
    def test_evaluate_ok_on_clean_worldwide(self):
        v = evaluate("Remote (Worldwide)", "linkedin", WW_DESC, "Senior AI Engineer",
                     location_type=LOCATION_REMOTE, disqualify=DAILY_DISQUALIFY)
        assert v.ok and v.reason == ""

    def test_reason_reports_first_canonical_hit(self):
        v = evaluate("New York, NY", "indeed", US_DESC, US_TITLE,
                     location_type=LOCATION_REMOTE, disqualify=DAILY_DISQUALIFY)
        assert not v.ok and v.reason in ("title", "description", "us_description", "worldwide_present")

    def test_inspect_computes_all_flags_without_raising_on_nones(self):
        flags = inspect(None, None, None, None, location_type=None)
        assert flags["location_type"] is True  # None != LOCATION_REMOTE
        assert flags["missing_location"] is True  # no strong proof in None desc
        assert flags["worldwide_present"] is False  # never consulted when missing


class TestStageStrictnessMatrix:
    """The three stages deliberately disagree — this table pins HOW, so a
    future refactor cannot silently converge them."""

    def test_missing_location_daily_passes_digest_subset_drops(self):
        """Daily accepts strong-eligibility proof without a location label;
        the digest subset strictly requires worldwide-remote (its pk/desc and
        CV rules live outside the law). The difference is deliberate."""
        daily = evaluate(None, "indeed", WW_DESC, "AI Engineer",
                         location_type=LOCATION_REMOTE, disqualify=DAILY_DISQUALIFY)
        digest = evaluate("", "indeed", WW_DESC, "AI Engineer",
                          disqualify=DIGEST_DISQUALIFY)
        assert daily.ok
        assert not digest.ok and digest.reason == "worldwide"

    def test_same_verdict_different_reported_reason(self):
        """'Remote - California' fails everywhere, but daily blames
        worldwide_present while digest blames us_location — projections
        report through their own lens (audit-trail fidelity)."""
        daily = evaluate("Remote - California", "glassdoor", WW_DESC, "ML Engineer",
                         location_type=LOCATION_REMOTE, disqualify=DAILY_DISQUALIFY)
        digest = evaluate("Remote - California", "glassdoor", WW_DESC, "ML Engineer",
                          disqualify=DIGEST_DISQUALIFY)
        assert not daily.ok and daily.reason == "worldwide_present"
        assert not digest.ok and digest.reason == "us_location"

    def test_hybrid_title_reason_differs_by_stage(self):
        """Hybrid-titled role: daily fires the title gate, guest fires the
        hybrid flag — same drop, honest reason per stage."""
        title = "AI Engineer - Hybrid Remote"
        daily = evaluate("Remote (Worldwide)", "linkedin", WW_DESC, title,
                         location_type=LOCATION_REMOTE, disqualify=DAILY_DISQUALIFY)
        guest = evaluate("Remote (Worldwide)", "linkedin", WW_DESC, title,
                         disqualify=GUEST_DISQUALIFY)
        assert not daily.ok and daily.reason == "title"
        assert not guest.ok and guest.reason == "hybrid_title"

    def test_missing_location_needs_strong_proof_daily(self):
        assert not evaluate(None, "indeed", "Nice team.", "AI Engineer",
                            location_type=LOCATION_REMOTE,
                            disqualify=DAILY_DISQUALIFY).ok
        assert evaluate(None, "indeed", WW_DESC, "AI Engineer",
                        location_type=LOCATION_REMOTE,
                        disqualify=DAILY_DISQUALIFY).ok


class TestWrapperEquivalence:
    """The public daily gate delegates without changing verdicts."""

    def test_wrapper_matches_projection_spot_checks(self):
        cases = [
            ("Remote (Worldwide)", "linkedin", WW_DESC, "Senior AI Engineer", LOCATION_REMOTE),
            ("New York, NY", "indeed", US_DESC, US_TITLE, LOCATION_REMOTE),
            (None, "indeed", WW_DESC, "AI Engineer", LOCATION_REMOTE),
            (None, "indeed", "Nice team.", "AI Engineer", LOCATION_REMOTE),
            ("San Francisco, CA (Remote)", "glassdoor", WW_DESC, "ML Engineer", LOCATION_REMOTE),
            ("Berlin, Germany", "glassdoor", WW_DESC, "AI Engineer", LOCATION_REMOTE),
            ("Lahore, Punjab, Pakistan", "linkedin", WW_DESC, "AI Engineer", LOCATION_REMOTE),
            ("Onsite", "linkedin", WW_DESC, "AI Engineer", "onsite"),
        ]
        for loc, src, desc, title, ltype in cases:
            expected = evaluate(loc, src, desc, title,
                                location_type=ltype, disqualify=DAILY_DISQUALIFY).ok
            assert is_remotely_workable(ltype, loc, src, desc, title) is expected


# ── Beat 178: prefilter soundness contract ────────────────────────────────────

def test_guest_prefilter_is_title_only_subset():
    """The prefilter set must stay a subset of title-only flags — anything
    else would drop B3-escape jobs the full chain keeps."""
    from src.location_law import GUEST_PREFILTER_DISQUALIFY, GUEST_DISQUALIFY

    assert GUEST_PREFILTER_DISQUALIFY <= {"title", "language_title", "hybrid_title"}
    assert GUEST_PREFILTER_DISQUALIFY <= GUEST_DISQUALIFY


def test_prefilter_hit_implies_full_chain_hit_for_any_description():
    """Soundness: a prefilter drop can never survive the full guest chain,
    no matter what the (unfetched) JD says."""
    from src.location_law import GUEST_DISQUALIFY, GUEST_PREFILTER_DISQUALIFY, evaluate

    descs = [
        "100% remote worldwide contractor role, apply now.",
        "Must be based in California.",
        "Work from our Berlin office, German required.",
        "",
    ]
    titles = ["AI Engineer (Onsite)", "Senior AI Engineer (Hybrid)", "AI Engineer - Hybrid Remote"]
    for title in titles:
        pre = evaluate("Denver, CO", "linkedin", None, title,
                       disqualify=GUEST_PREFILTER_DISQUALIFY)
        assert not pre.ok, f"expected prefilter hit for {title!r}"
        for desc in descs:
            full = evaluate("Denver, CO", "linkedin", desc, title,
                            disqualify=GUEST_DISQUALIFY)
            assert not full.ok, f"full chain must also drop {title!r} (desc={desc!r})"


# ── Beat 179: Pakistan onsite/hybrid is never fetched ─────────────────────────

PAK_ONSITE_HYBRID_LOCS = [
    "Lahore (Hybrid)",
    "Karachi (Onsite)",
    "Islamabad - Hybrid",
    "Pakistan (On-site)",
    "Lahore (On Site)",
    "Hybrid - Lahore",
    "Onsite - Karachi, Pakistan",
    "Dubai (Hybrid)",
    "Riyadh onsite",
]

PAK_REMOTE_LOCS = [
    "Pakistan (Remote)",
    "Lahore, Pakistan",  # bare city + WW-strong desc: B3 escape, unchanged
    "Pakistan",
]


def test_explicit_onsite_hybrid_location_drops_at_every_gate():
    """Owner law: no Pakistan (or anywhere) onsite/hybrid is ever fetched —
    explicit markers in the LOCATION label drop at daily, digest, and guest."""
    from src.location_law import DIGEST_DISQUALIFY, GUEST_DISQUALIFY
    from src.main import is_remotely_workable
    from src.models import LOCATION_REMOTE

    WW = "We are a worldwide remote team hiring across time zones. 100% remote."
    for loc in PAK_ONSITE_HYBRID_LOCS:
        assert is_remotely_workable(LOCATION_REMOTE, loc, "linkedin", WW, "AI Engineer") is False, loc
        dg = evaluate(loc, "linkedin", WW, "AI Engineer", disqualify=DIGEST_DISQUALIFY)
        assert not dg.ok, loc
        assert dg.reason in ("hybrid_location", "onsite", "worldwide"), (loc, dg.reason)
        gu = evaluate(loc, "linkedin", WW, "AI Engineer", disqualify=GUEST_DISQUALIFY)
        assert not gu.ok, loc


def test_clean_pakistan_remote_still_passes():
    """The fix must not touch genuine remote roles — Pakistan (Remote) keeps
    flowing at every gate."""
    from src.location_law import DIGEST_DISQUALIFY, GUEST_DISQUALIFY
    from src.main import is_remotely_workable
    from src.models import LOCATION_REMOTE

    WW = "We are a worldwide remote team hiring across time zones. 100% remote."
    assert is_remotely_workable(LOCATION_REMOTE, "Pakistan (Remote)", "linkedin", WW, "AI Engineer") is True
    for loc in PAK_REMOTE_LOCS:
        assert evaluate(loc, "linkedin", WW, "AI Engineer",
                        disqualify=DIGEST_DISQUALIFY).ok, loc
        assert evaluate(loc, "linkedin", WW, "AI Engineer",
                        disqualify=GUEST_DISQUALIFY).ok, loc
