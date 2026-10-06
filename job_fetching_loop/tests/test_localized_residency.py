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


# ── M1 (checker, Beat 144): common FR/DE wording the English counterparts cover ──

def test_m1_common_residency_wording_restricts():
    assert is_description_restricted("Poste basé en France.")
    assert is_description_restricted("Candidats basés en France.")
    assert is_description_restricted("Vous devez être basée en France.")
    assert is_description_restricted("Résidente en France uniquement.")
    assert is_description_restricted("Résidents en France")
    assert is_description_restricted("Vous résiderez en France.")
    assert is_description_restricted("Domiciliation en France obligatoire.")
    assert is_description_restricted("Wohnort in Deutschland.")
    assert is_description_restricted("Ihr Wohnort muss in Deutschland liegen.")
    assert is_description_restricted("Aufenthaltserlaubnis für Deutschland erforderlich.")


# ── M2: muss…wohnen fires only with a country in the same clause ────────────

def test_m2_muss_wohnen_clause_requires_country():
    # direct-fire: no contiguous "in Deutschland wohnen" → muss branch must work
    assert is_description_restricted("Sie müssen in Deutschland arbeiten und wohnen.")
    # country-less living clauses stay open (country required, M2)
    assert not is_description_restricted(
        "Flexible working; no need to live in a specific city."
    )


# ── M3 + CodeRabbit: same-sentence exemptions stay open ─────────────────────

def test_m3_localized_negation_exemptions_open():
    assert not is_description_restricted("Muss nicht in Deutschland wohnen — weltweit möglich.")
    assert not is_description_restricted("Ansässigkeit in Deutschland nicht erforderlich.")
    assert not is_description_restricted("Ohne Wohnsitz in Deutschland möglich.")
    assert not is_description_restricted("Résidence en France non requise pour ce poste.")
    assert not is_description_restricted(
        "Ce poste fonctionne partout; résidence en France non requise."
    )
    # paired: an independent pin in ANOTHER sentence still restricts
    assert is_description_restricted(
        "Résidence en France non requise. Cependant Wohnsitz in Deutschland verpflichtend."
    )


# ── Round-2 (adversarial, run 36712129823): clause-anchored polarity ────────

def test_r2_m1_exemption_is_clause_local_not_sentence_global():
    # pin + unrelated exemption about ANOTHER subject/country in same sentence
    assert is_description_restricted(
        "Wohnsitz in Deutschland erforderlich, Deutschkenntnisse nicht erforderlich."
    )
    assert is_description_restricted(
        "Wohnsitz in Deutschland erforderlich; Berufserfahrung nicht benötigt."
    )
    assert is_description_restricted(
        "Sie müssen in Deutschland wohnen; der Führerschein ist nicht erforderlich."
    )
    assert is_description_restricted(
        "Muss in Deutschland wohnen, aber ein Auto ist nicht erforderlich."
    )
    assert is_description_restricted("expérience non requise, résidence en France requise")
    assert is_description_restricted(
        "No residence requirement for Germany roles, but Wohnsitz in Deutschland ist Pflicht."
    )
    assert is_description_restricted("Ohne Wohnsitz Österreich — Wohnsitz in Deutschland ist Pflicht.")
    assert is_description_restricted(
        "Kein Wohnsitz Österreich erforderlich; Wohnsitz in Deutschland verpflichtend."
    )
    # genuinely exempt SAME clause still open
    assert not is_description_restricted(
        "Wohnsitz in Deutschland nicht erforderlich, weltweit möglich."
    )


def test_r2_m2_boundary_match_fails_closed_not_whole_text_exempt():
    d = "Ohne Wohnsitz in Österreich möglich.\nWohnsitz\nin Deutschland ist Pflicht."
    assert is_description_restricted(d)
    assert is_description_restricted(
        "Ohne Wohnsitz Österreich. Wir suchen mit\nWohnsitz Deutschland."
    )
    assert is_description_restricted(
        "Es ist nicht erforderlich, in Österreich zu wohnen. Richtig: in Deutschland\nwohnen ist Pflicht."
    )


def test_r2_m3_english_parity_ansassig_leben():
    assert is_description_restricted("Sie müssen in Deutschland ansässig sein.")
    assert is_description_restricted("Der Bewerber muss in Deutschland leben.")


def test_r2_m4_exempt_gaps_worldwide_roles_stay_open():
    assert not is_description_restricted(
        "Du musst nicht in Deutschland wohnen — wir sind weltweit vertreten."
    )
    assert not is_description_restricted("Wir mussten nicht in Deutschland wohnen.")
    assert not is_description_restricted(
        "Il n'est pas obligatoire de résider en France pour ce poste."
    )
    assert not is_description_restricted(
        "Pas besoin de résider en France, le poste est ouvert au monde entier."
    )
    assert not is_description_restricted(
        "Worldwide remote role. Notre client, basé en France, recrute pour le monde entier."
    )
    assert not is_description_restricted(
        "Work from anywhere. Du kannst in Deutschland wohnen oder remote aus dem Ausland arbeiten."
    )
    assert not is_description_restricted(
        "Global remote. Wohnort frei — auch in Deutschland wohnen möglich."
    )


def test_r2_low1_fr_masculine_non_requis_exempt():
    from src.models import _LOCALIZED_RESIDENCY_EXEMPT
    assert _LOCALIZED_RESIDENCY_EXEMPT.search("non requis")
    assert not is_description_restricted("Poste ouvert; résidence en France non requis.")


def test_r2_low2_newline_straddling_pin_catches():
    assert is_description_restricted("Ohne Wohnsitz Österreich. Der Wohnort\nmuss in Deutschland sein.")


def test_r2_low3_nfd_accents_normalize():
    # NFD decomposition of "résident" = e + COMBINING ACUTE on the FIRST vowel
    assert is_description_restricted("re\u0301sident en France")  # NFD
    assert is_description_restricted("RÉSIDENCE EN FRANCE")  # case handled by .lower()


# ── Round-3 (adversarial, run 36715127038): M1, M2, M3, B2 regressions ─────

def test_r3_m1_company_word_does_not_suppress_pins():
    cases = [
        "Unsere Firma sucht Entwickler mit Wohnsitz in Deutschland.",
        "Die Firma verlangt Ansässigkeit in Deutschland.",
        "Unser Unternehmen sucht Remote-Entwickler mit Ansässigkeit in Deutschland.",
        "Unser Kunde sucht Mitarbeiter mit Wohnsitz in Deutschland.",
        "Notre entreprise recherche un professeur résidant en France.",
        "Notre client cherche un professeur résidant en France pour ce poste.",
        "La société recherche des professeurs résidant en France.",
        "The company requires candidates with a Wohnsitz in Germany.",
        "Our customer seeks talent with Wohnsitz in Deutschland.",
        "Unsere Firma sucht Projektleiter, Wohnort in Deutschland.",
    ]
    for c in cases:
        assert is_description_restricted(c), f"Failed to restrict: {c}"


def test_r3_m2_conjunction_joined_negation_does_not_suppress_pins():
    cases = [
        "Worldwide remote. Sie müssen in Deutschland wohnen und Deutschkenntnisse sind nicht erforderlich.",
        "Wohnsitz in Deutschland erforderlich und Englisch ist nicht erforderlich.",
        "Kein Wohnsitz Österreich erforderlich aber Wohnsitz in Deutschland ist Pflicht.",
        "Résidence en France requise mais l'expérience non requise.",
        "Résidence en France requise et l'expérience non requise pour ce poste.",
    ]
    for c in cases:
        assert is_description_restricted(c), f"Failed to restrict: {c}"


def test_r3_m3_missing_exempt_forms_stay_open():
    cases = [
        "Worldwide remote. Wohnsitz in Deutschland ist nicht zwingend.",
        "Global remote. Wohnsitz in Deutschland ist hier nicht Pflicht.",
        "Résidence en France non obligatoire pour ce poste, ouvert au monde entier.",
        "Poste ouvert au monde entier, résidence en France pas obligatoire.",
        "Worldwide. In Deutschland wohnen ist möglich.",
        "Global remote. Wohnsitz in Deutschland möglich für alle Kandidaten.",
    ]
    for c in cases:
        assert not is_description_restricted(c), f"Failed to stay open: {c}"


def test_r3_b2_german_localities_muss_wohnen():
    assert is_description_restricted("Der Kandidat muss in Berlin wohnen.")
    assert is_description_restricted("Die Bewerberin muss in Hamburg wohnen.")
    assert is_description_restricted("Bewerber müssen in NRW wohnen.")



# ── Round-3 (adversarial run 36715127038, human-authorized §7 exception) ────

def test_r3_m1_company_word_before_pin_does_not_skip():
    # context-skip regression: company word near a pin is NOT an HQ appositive
    assert is_description_restricted("Unsere Firma sucht Entwickler mit Wohnsitz in Deutschland.")
    assert is_description_restricted(
        "Ein wachsendes Unternehmen sucht Mitarbeitende mit Wohnsitz in Deutschland."
    )
    assert is_description_restricted("Die Firma verlangt Ansässigkeit in Deutschland.")
    assert is_description_restricted("Die Firma verlangt, dass der Bewerber in Deutschland wohnen muss.")
    assert is_description_restricted("Notre entreprise recherche un professeur résidant en France.")
    assert is_description_restricted("Notre client cherche un professeur résidant en France pour ce poste.")
    assert is_description_restricted("La société recherche des professeurs résidant en France.")
    assert is_description_restricted("The company requires candidates with a Wohnsitz in Germany.")
    assert is_description_restricted("Our customer seeks talent with Wohnsitz in Deutschland.")
    assert is_description_restricted("Unsere Firma sucht Projektleiter, Wohnort in Deutschland.")


def test_r3_m1_appositive_hq_pin_stays_open():
    # the ONE shape the skip was written for: client, <pin>, recrute
    assert not is_description_restricted(
        "Worldwide remote role. Notre client, basé en France, recrute pour le monde entier."
    )


def test_r3_m2_conjunction_joined_negation_does_not_suppress_pin():
    assert is_description_restricted(
        "Worldwide remote. Sie müssen in Deutschland wohnen und Deutschkenntnisse sind nicht erforderlich."
    )
    assert is_description_restricted(
        "Wohnsitz in Deutschland erforderlich und Englisch ist nicht erforderlich."
    )
    assert is_description_restricted(
        "Kein Wohnsitz Österreich erforderlich aber Wohnsitz in Deutschland ist Pflicht."
    )
    assert is_description_restricted("Résidence en France requise mais l'expérience non requise.")
    assert is_description_restricted(
        "Résidence en France requise et l'expérience non requise pour ce poste."
    )
    # same-clause (conjunction-joined) genuine exemption still opens
    assert not is_description_restricted(
        "Wohnsitz in Deutschland nicht erforderlich und weltweit möglich."
    )


def test_r3_m3_exempt_gap_forms_worldwide_stay_open():
    assert not is_description_restricted("Worldwide remote. Wohnsitz in Deutschland ist nicht zwingend.")
    assert not is_description_restricted("Global remote. Wohnsitz in Deutschland ist hier nicht Pflicht.")
    assert not is_description_restricted(
        "Résidence en France non obligatoire pour ce poste, ouvert au monde entier."
    )
    assert not is_description_restricted(
        "Poste ouvert au monde entier, résidence en France pas obligatoire."
    )
    assert not is_description_restricted("Worldwide. In Deutschland wohnen ist möglich.")
    assert not is_description_restricted(
        "Global remote. Wohnsitz in Deutschland möglich für alle Kandidaten."
    )


def test_r3_low2_wohnssitz_country_without_in_restricts():
    assert is_description_restricted("Wohnsitz Deutschland erforderlich.")


def test_r3_low3_title_path_localized_pins_restrict():
    from src.models import is_title_restricted
    assert is_title_restricted("Engineer – Remote, Wohnsitz in Deutschland")
    assert is_title_restricted("Dev (Wohnsitz in Deutschland)")


# ── Beat 152 (Production Hardening & Residual LOWs) ─────────────────────────

def test_beat152_precision_wohnsitz_no_prep():
    """Bare Wohnsitz + locality requires requirement phrasing so non-restrictive forms stay open."""
    assert not is_description_restricted("Bitte geben Sie Ihren Wohnsitz Deutschland an.")
    assert not is_description_restricted("Unser Standort: Wohnsitz Deutschland")
    assert not is_description_restricted("Wohnsitz Deutschland Erfahrung von Vorteil.")
    assert is_description_restricted("Wohnsitz Deutschland erforderlich.")
    assert is_description_restricted("Wohnsitz Deutschland zwingend.")


def test_beat152_german_post_verb_locality():
    """müssen wohnen in <country> with post-verb locality must restrict."""
    assert is_description_restricted("Bewerber müssen wohnen in Deutschland")
    assert is_description_restricted("Sie müssen leben in Berlin")


def test_beat152_french_europe_residency():
    """FR residency expanded to Europe / EU."""
    assert is_description_restricted("Résidence en Europe requise.")
    assert is_description_restricted("Résidant en Europe uniquement.")


def test_beat152_english_residency_in_description_and_title():
    from src.models import is_title_restricted
    assert is_description_restricted("Residence in Germany required.")
    assert is_description_restricted("Residence in Europe required.")
    assert is_title_restricted("AI Engineer (Must reside in Germany)")
    assert is_title_restricted("Dev (Residence in Germany required)")
    assert is_title_restricted("Staff ML Engineer (Must reside in Europe)")
    assert is_title_restricted("Engineer (Wohnsitz Deutschland)")


def test_beat152_negative_title_fixture():
    """LOW1: Ensure fail-closed title scan never drops legitimate Worldwide/Global remote titles."""
    from src.models import is_title_restricted
    assert not is_title_restricted("Senior AI Engineer - Worldwide Remote")
    assert not is_title_restricted("Staff ML Engineer (Remote, Work from Anywhere)")
    assert not is_title_restricted("AI/ML Research Scientist - Global Remote")
    assert not is_title_restricted("Full Stack Engineer - 100% Remote")

