"""Location law (Rule 11) — one evaluator for worldwide-remote eligibility.

Three pipeline stages used to evaluate the same Rule-11 predicates in different
places with different input shapes: the LinkedIn guest pre-filter (inline
chain), the daily gate (`main.is_remotely_workable`), and the weekly gate
(`digest.is_valid_digest_job`). The booleans differ by stage ON PURPOSE (a
scraper pre-filter is stricter in some axes, looser in others), but predicate
evaluation had no locality — "which text, which order" questions bounced across
`models` → `main` → `digest` → `linkedin`, and the daily/digest parity bug
class lived at call sites, never in helpers.

This module owns predicate evaluation: one call computes every restriction
flag from the given inputs. Each stage keeps its own verdict projection (the
set of flags that disqualify THERE), so behavior is unchanged while the law
gains a single test surface. Text budgets are the caller's (pass what the
stage passes today); the module never truncates, never fetches.

Flag semantics mirror the helpers in `src/models.py` exactly — this module
adds no new restrictions, it only evaluates the existing ones in one place.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Stable flag names (public API for projections, reasons, and tests).
TITLE = "title"
DESCRIPTION = "description"
US_DESCRIPTION = "us_description"
US_LOCATION = "us_location"
LANGUAGE_TITLE = "language_title"
LANGUAGE_DESCRIPTION = "language_description"
LANGUAGE_FULL = "language_full"
HYBRID_TITLE = "hybrid_title"
HYBRID_DESCRIPTION = "hybrid_description"
HYBRID_LOCATION = "hybrid_location"
HYBRID_FULL = "hybrid_full"
FOREIGN = "foreign"
WORLDWIDE = "worldwide"
WORLDWIDE_PRESENT = "worldwide_present"
ONSITE = "onsite"
LOCATION_TYPE = "location_type"
MISSING_LOCATION = "missing_location"

# Reason priority: first hit in this order is reported (booleans are
# order-free conjunctions; only the reported reason depends on order).
CANONICAL_ORDER = (
    LANGUAGE_TITLE, LANGUAGE_DESCRIPTION, LANGUAGE_FULL,
    HYBRID_TITLE, HYBRID_DESCRIPTION, HYBRID_LOCATION, HYBRID_FULL,
    TITLE, DESCRIPTION,
    FOREIGN, US_DESCRIPTION, US_LOCATION,
    WORLDWIDE, WORLDWIDE_PRESENT, ONSITE,
    LOCATION_TYPE, MISSING_LOCATION,
)

# Stage projections: which flags disqualify at each gate. Deliberately
# different (strictness lives here, visibly, not scattered across call sites):
# - DAILY: no language/hybrid/us-location checks (unchanged from
#   `is_remotely_workable`); missing location needs strong eligibility proof.
# - DIGEST: full-text language/hybrid + both US checks (unchanged from
#   `is_valid_digest_job`'s location subset; its URL/CV rules stay in digest).
# - GUEST: per-input language/hybrid + onsite words (unchanged from the
#   LinkedIn guest chain; expired/closed/marker rules stay in the scraper).
DAILY_DISQUALIFY = frozenset({
    TITLE, DESCRIPTION, US_DESCRIPTION,
    LOCATION_TYPE, MISSING_LOCATION, FOREIGN, WORLDWIDE_PRESENT,
    # Beat 179 (owner: never fetch Pakistan onsite/hybrid): explicit markers
    # in the LOCATION label drop at every gate.
    HYBRID_LOCATION, ONSITE,
})
DIGEST_DISQUALIFY = frozenset({
    TITLE, LANGUAGE_FULL, HYBRID_FULL, DESCRIPTION,
    FOREIGN, US_DESCRIPTION, US_LOCATION, WORLDWIDE,
    HYBRID_LOCATION, ONSITE,  # Beat 179: location-label markers
})
GUEST_DISQUALIFY = frozenset({
    LANGUAGE_TITLE, LANGUAGE_DESCRIPTION,
    HYBRID_TITLE, HYBRID_DESCRIPTION, HYBRID_LOCATION,
    TITLE, DESCRIPTION, WORLDWIDE, ONSITE,
})
# Beat 178 (guest budget): card-level PRE-filter. Title-only flags are
# description-independent — a card hitting one can never survive the full
# chain no matter what its JD says — so the scraper may skip its detail HTTP
# (the 180s-budget burn) with the identical verdict. SOUNDNESS CONTRACT: this
# set must stay a subset of title-only flags; location/description flags here
# would drop B3-escape jobs (strong-desc proof) the full chain keeps.
GUEST_PREFILTER_DISQUALIFY = frozenset({
    TITLE, LANGUAGE_TITLE, HYBRID_TITLE,
})

# Onsite words: the guest chain's inline list, owned here now (single copy).
# Beat 179: spaced "on site" added — "Lahore (On Site)" slipped every gate.
ONSITE_WORDS = ("on-site", "onsite", "on site", "in-office", "office-based", "office only")


@dataclass(frozen=True)
class LawVerdict:
    """One gate decision: `ok`, the first-hit `reason` ("" when ok), and the
    full `flags` hit-set for audit matrices and parity tests."""
    ok: bool
    reason: str = ""
    flags: frozenset = field(default_factory=frozenset)


def _location_says_hybrid(location) -> bool:
    """Beat 179: explicit hybrid marker in a LOCATION label.

    `is_hybrid_work` is prose-tuned (Beat 105: bare "hybrid" needs office
    context, so "hybrid of X and Y" in a JD doesn't kill worldwide jobs) and
    misses short labels like "Lahore (Hybrid)". A location field is a
    workplace designation, not prose — a bare `hybrid` token there always
    means the workplace, so it matches unconditionally here. The frozen
    helper is left untouched for title/description evaluation.
    """
    from src.models import is_hybrid_work

    if is_hybrid_work(location):
        return True
    return bool(isinstance(location, str) and re.search(r"\bhybrid\b", location, re.IGNORECASE))


def inspect(
    location=None,
    source=None,
    description=None,
    title=None,
    *,
    location_type=None,
) -> dict[str, bool]:
    """Evaluate every Rule-11 restriction flag for the given inputs.

    Values pass straight through to the `src/models.py` helpers exactly as
    the three call sites pass them today (including None) — no coercion, no
    truncation, no new restrictions.
    """
    from src.models import (
        _has_strong_worldwide_eligibility,
        _is_us_restricted,
        is_description_restricted,
        is_foreign_country_restricted,
        is_hybrid_work,
        is_language_restricted,
        is_title_restricted,
        is_worldwide_remote,
    )
    from src.models import LOCATION_REMOTE

    title_s = title if isinstance(title, str) else ""
    desc_s = description if isinstance(description, str) else ""
    loc_s = location if isinstance(location, str) else ""
    full_s = f"{title_s} {desc_s}".strip()
    # Missing-location test mirrors main.is_remotely_workable byte-for-byte
    # (`location is None or not str(location).strip()`).
    loc_missing = location is None or not str(location).strip()

    strong = _has_strong_worldwide_eligibility(description)
    # Mirror main.is_remotely_workable exactly: foreign is only evaluated for
    # truthy locations (the helper raises on None and is never called with it).
    foreign_hit = (not loc_missing) and bool(is_foreign_country_restricted(location)) and not strong
    worldwide = is_worldwide_remote(location if location is not None else "", source, description, title)

    flags: dict[str, bool] = {
        TITLE: bool(is_title_restricted(title)),
        DESCRIPTION: bool(is_description_restricted(description)),
        US_DESCRIPTION: bool(description and _is_us_restricted(description)),
        US_LOCATION: bool(_is_us_restricted(location)),
        LANGUAGE_TITLE: bool(is_language_restricted(title)),
        LANGUAGE_DESCRIPTION: bool(is_language_restricted(description)),
        LANGUAGE_FULL: bool(is_language_restricted(full_s)),
        HYBRID_TITLE: bool(is_hybrid_work(title)),
        HYBRID_DESCRIPTION: bool(is_hybrid_work(description)),
        HYBRID_LOCATION: bool(_location_says_hybrid(location)),
        HYBRID_FULL: bool(is_hybrid_work(full_s)),
        FOREIGN: foreign_hit,
        WORLDWIDE: not worldwide,
        WORLDWIDE_PRESENT: (not loc_missing) and not worldwide,
        ONSITE: any(w in f"{title_s.lower()} {loc_s.lower()} {desc_s.lower()}" for w in ONSITE_WORDS),
        LOCATION_TYPE: location_type != LOCATION_REMOTE,
        MISSING_LOCATION: loc_missing and not strong,
    }
    return flags


def evaluate(
    location=None,
    source=None,
    description=None,
    title=None,
    *,
    location_type=None,
    disqualify=frozenset(),
) -> LawVerdict:
    """One-call gate: `ok` unless any flag in `disqualify` hits.

    `reason` is the first hit in canonical order (deterministic for logs and
    the rejected.jsonl audit trail). Use the stage sets (DAILY/DIGEST/GUEST)
    to preserve each gate's exact strictness.
    """
    flags = inspect(location, source, description, title, location_type=location_type)
    wanted = frozenset(disqualify)
    hit = frozenset(f for f, on in flags.items() if on and f in wanted)
    if not hit:
        return LawVerdict(ok=True, flags=hit)
    reason = next((f for f in CANONICAL_ORDER if f in hit), sorted(hit)[0])
    return LawVerdict(ok=False, reason=reason, flags=hit)
