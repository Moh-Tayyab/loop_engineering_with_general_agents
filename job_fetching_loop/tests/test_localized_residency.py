"""Phase 3 (A3): localized residency filters — DE/FR pins vs Worldwide/APAC.

TDD: the DE/FR assertions below failed before the A3 pattern set was added
(no `Wohnsitz`/`résidant` coverage in `_DESCRIPTION_RESTRICTION_PATTERNS`);
the pass fixtures lock that Worldwide/Global and APAC au/sg wording stays open.
"""
from __future__ import annotations

from src.models import is_description_restricted


# ── RED-first: German residency pins must restrict ──────────────────────────

def test_german_residency_pins_restrict():
    assert is_description_restricted("Wohnsitz in Deutschland")
    assert is_description_restricted("Gesucht: Mitarbeiter mit Wohnsitz in Deutschland")
    assert is_description_restricted("Sie müssen in Deutschland wohnen.")
    assert is_description_restricted("Muss in Deutschland wohnen")
    assert is_description_restricted("Ansässigkeit in Deutschland erforderlich.")
    assert is_description_restricted("Candidate must have a Wohnsitz in Germany.")


# ── RED-first: French residency pins must restrict ──────────────────────────

def test_french_residency_pins_restrict():
    assert is_description_restricted("Résidant en France")
    assert is_description_restricted("Le candidat doit résider en France.")
    assert is_description_restricted("Résidence en France exigée pour ce poste.")
    assert is_description_restricted("Poste ouvert aux ingénieurs résidant en France.")


def test_localized_pin_beats_worldwide_claim():
    """A worldwide blurb must not suppress a hard DE/FR residency pin."""
    assert is_description_restricted("Worldwide remote — but Wohnsitz in Deutschland required.")
    assert is_description_restricted("Global remote role; résidant en France uniquement.")


# ── PASS: Worldwide / Global wording stays open ─────────────────────────────

def test_worldwide_global_remote_stays_open():
    assert not is_description_restricted(
        "Work from anywhere in the world. Global remote team; no domicile restrictions."
    )
    assert not is_description_restricted(
        "Worldwide remote role — location flexible, no in-country residency requirement."
    )
    assert not is_description_restricted(
        "We are an all-remote global team building AI tools. Anyone anywhere can apply."
    )


# ── PASS: APAC (au/sg) worldwide-style wording stays open ───────────────────

def test_apac_au_sg_worldwide_pass():
    assert not is_description_restricted(
        "Fully remote; we hire across APAC including Australia and Singapore."
    )
    assert not is_description_restricted(
        "Remote-first team with teammates in Sydney, Melbourne, and Singapore; no office."
    )
    assert not is_description_restricted(
        "Global remote position; candidates from any country, including AU and SG."
    )
