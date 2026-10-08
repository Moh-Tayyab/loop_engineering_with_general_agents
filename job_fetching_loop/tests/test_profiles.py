"""Tests for the multi-profile pilot layer (profiles/*.yaml + match_profile)."""
import pytest

from src.matcher import (
    Profile,
    list_profiles,
    load_profile,
    match_profile,
    match_usama_cv,
    meets_threshold,
    passing_profiles,
    profile_keywords,
)
from src.models import NormalizedJob, RawJob, ai_keyword_matches, utc_now


@pytest.fixture(scope="module")
def ai_profile() -> Profile:
    return load_profile("senior_ai_engineer")


@pytest.fixture(scope="module")
def awais_profile() -> Profile:
    return load_profile("awais_odifccm")


class TestProfileLoading:
    def test_both_pilot_profiles_discoverable(self):
        names = list_profiles()
        assert "senior_ai_engineer" in names
        assert "awais_odifccm" in names

    def test_unknown_profile_raises_loudly(self):
        with pytest.raises(FileNotFoundError):
            load_profile("no_such_profile_xyz")

    def test_ai_profile_fields(self, ai_profile):
        assert ai_profile.keywords  # scrape steering must never be empty
        assert ai_profile.tier1 and ai_profile.tier2
        assert ai_profile.min_experience_years == 5

    def test_awais_profile_fields(self, awais_profile):
        assert awais_profile.min_experience_years == 10
        assert any("ODI" in k.upper() or "FCCM" in k.upper() for k in awais_profile.keywords)

    def test_combined_keywords_cover_both_domains(self):
        primary, roles = profile_keywords()
        joined = " ".join(primary).lower()
        assert "llm" in joined or "ai engineer" in joined
        assert "odi" in joined or "ofsa" in joined or "fcc" in joined
        assert roles  # role keywords present


class TestCrossProfileIsolation:
    """Each profile must accept its own roles and reject the other's."""

    def test_ai_engineer_matches_ai_profile(self, ai_profile):
        ok, score, label = match_profile(
            "Senior AI Engineer (LLM/RAG)",
            description="Build LLM and RAG pipelines with Python and FastAPI.",
            profile=ai_profile,
        )
        assert ok and score >= 90

    def test_ai_engineer_rejected_by_awais_profile(self, awais_profile):
        ok, score, _ = match_profile(
            "Senior AI Engineer (LLM/RAG)",
            description="Build LLM and RAG pipelines with Python and FastAPI.",
            profile=awais_profile,
        )
        assert not ok and score == 0

    def test_odi_developer_matches_awais_profile(self, awais_profile):
        ok, score, label = match_profile(
            "Oracle ODI Developer — Remote",
            description="ODI mappings, FSDM data model, ETL for FCCM AML monitoring.",
            profile=awais_profile,
        )
        assert ok and score >= 90
        assert "ODI" in label

    def test_odi_developer_rejected_by_ai_profile(self, ai_profile):
        ok, score, _ = match_profile(
            "Oracle ODI Developer — Remote",
            description="ODI mappings, FSDM data model, ETL for FCCM AML monitoring.",
            profile=ai_profile,
        )
        assert not ok and score == 0

    def test_fccm_consultant_matches_awais(self, awais_profile):
        ok, score, label = match_profile(
            "OFSAA FCCM Consultant (Remote)",
            description="Deliver AML and KYC scenarios, ECM batch support, Oracle Mantas.",
            profile=awais_profile,
        )
        assert ok and score >= 90

    def test_client_success_rejected_by_both(self, ai_profile, awais_profile):
        for p in (ai_profile, awais_profile):
            ok, score, label = match_profile("Client Success Manager", profile=p)
            assert not ok and score == 0
            assert "blacklisted_role" in label

    def test_branch_banking_rejected_by_awais(self, awais_profile):
        ok, score, label = match_profile(
            "Branch Banking Compliance Officer",
            description="FCCM alerts review at branch level.",
            profile=awais_profile,
        )
        assert not ok and score == 0
        assert "blacklisted_role" in label


class TestBackwardsCompat:
    def test_match_usama_cv_still_works(self):
        ok, score, _ = match_usama_cv(
            "Senior AI Engineer",
            description="LLM, RAG, FastAPI, PyTorch.",
        )
        assert ok and score >= 90

    def test_match_usama_cv_still_rejects(self):
        ok, score, _ = match_usama_cv("Senior Vue Developer", description="Vue 3 frontend.")
        assert not ok and score == 0

    def test_default_profile_is_ai(self):
        ok, score, _ = match_profile("ML Engineer", description="Machine learning in Python.")
        assert ok and score >= 90


class TestThresholds:
    def test_ai_threshold_70_awais_60(self):
        assert meets_threshold("senior_ai_engineer", 70)
        assert not meets_threshold("senior_ai_engineer", 69)
        assert meets_threshold("awais_odifccm", 60)
        assert not meets_threshold("awais_odifccm", 59)

    def test_unknown_profile_falls_back_to_70(self):
        assert meets_threshold("no_such_profile", 70)
        assert not meets_threshold("no_such_profile", 69)

    def test_passing_profiles_best_first(self):
        # A FCCM-flavoured data title: awais should outrank nothing else here.
        ranked = passing_profiles(
            "OFSAA FCCM Consultant",
            description="AML KYC ECM batch, Oracle ODI ETL.",
        )
        assert ranked and ranked[0][0] == "awais_odifccm"

    def test_passing_profiles_empty_for_junk(self):
        assert passing_profiles("Client Success Manager", description="accounts") == []


def _raw(title: str, desc: str = "") -> RawJob:
    return RawJob(
        source="linkedin", title=title, company="Acme", url="https://example.com/j/1",
        location="Worldwide", salary=None, posted_date=None,
        description=desc, tags=[], fetched_at=utc_now(),
    )


class TestPipelineWiring:
    def test_ai_keyword_gate_opens_for_awais_roles(self):
        # Beat 155 root-cause fix: the old gate only ran match_usama_cv, so
        # ODI/FCCM leads died before scoring. Any profile match must pass.
        assert ai_keyword_matches(_raw("Oracle ODI Developer", "ODI ETL FCCM"), ["x"], ["y"])
        assert ai_keyword_matches(_raw("Senior AI Engineer", "LLM RAG"), ["x"], ["y"])
        assert not ai_keyword_matches(_raw("Client Success Manager", "accounts"), ["x"], ["y"])

    def test_normalize_raw_fills_profile_fields(self):
        from src.main import normalize_raw
        j = normalize_raw(_raw("OFSAA FCCM Consultant", "AML KYC ODI ETL Oracle"))
        assert j.profile_scores.get("awais_odifccm", 0) >= 60
        assert j.profile_best == "awais_odifccm"
        assert j.cv_match_score == j.profile_scores["awais_odifccm"]

    def test_normalize_raw_no_match_leaves_blank(self):
        from src.main import normalize_raw
        j = normalize_raw(_raw("Client Success Manager", "accounts and renewals"))
        assert j.profile_scores == {}
        assert j.profile_best == ""
        assert j.cv_match_score == 0

    def test_job_dict_roundtrip_keeps_profile_fields(self):
        from src.main import normalize_raw
        j = normalize_raw(_raw("ML Engineer", "machine learning python"))
        j2 = NormalizedJob.from_dict(j.to_dict())
        assert j2.profile_scores == j.profile_scores
        assert j2.profile_best == j.profile_best

    def test_pilot_telegram_has_both_sections(self):
        import os
        from src.main import normalize_raw
        from src.notifier import TelegramNotifier
        jobs = [
            normalize_raw(_raw("Senior AI Engineer", "LLM RAG FastAPI pytorch")),
            normalize_raw(_raw("Oracle ODI Developer", "ODI ETL FCCM AML Oracle")),
        ]
        jobs = [j for j in jobs if j.profile_best]  # only survivors get delivered
        n = TelegramNotifier("dummy", "dummy")
        text = n._format_pilot_daily(jobs, {"total_this_week": 2})
        assert "Senior AI Engineer" in text
        assert "ODI" in text
        assert "kyun:" in text

    def test_pilot_telegram_empty_section_is_honest(self):
        from src.notifier import TelegramNotifier
        n = TelegramNotifier("dummy", "dummy")
        text = n._format_pilot_daily([], {"total_this_week": 0, "rejects_by_profile": {"awais_odifccm": 4}})
        assert "aaj koi match nahi" in text
        assert "Senior AI Engineer" in text and "Awais" in text


class TestVolumeAndFullDescription:
    """Beat 158 — maximum fetch: profile keywords must be searched, and
    restriction/context text buried late in a full JD must still decide."""

    def test_all_scan_keywords_union_covers_both_profiles(self):
        import src.config as cfg
        kws = cfg.all_scan_keywords()
        joined = " ".join(kws).lower()
        assert "llm engineer" in joined or "ai engineer" in joined
        assert "odi" in joined and "fcc" in joined.replace("fcc", "fcc")
        assert len(kws) == len(set(kws))  # order-preserving dedup
        assert len(kws) >= len(cfg.scan_keywords()) + 1

    def test_tech_context_buried_past_2000_chars_still_matches(self):
        awais = load_profile("awais_odifccm")
        filler = "great opportunity join our team. " * 80  # ~2500 chars
        desc = filler + " oracle etl sql data integration fccm workflows"
        ok, score, _ = match_profile("Data Engineer", description=desc, profile=awais)
        assert ok and score >= 70  # old [:2000] cap would reject (no context seen)

    def test_bonus_skill_buried_late_still_boosts(self):
        ai = load_profile("senior_ai_engineer")
        filler = "exciting role. " * 160  # ~2200 chars
        ok, score, _ = match_profile(
            "AI Engineer", description=filler + " we use langgraph and bedrock daily",
            profile=ai,
        )
        assert ok and score == 97  # 92 base + 5 stack bonus

    def test_normalize_keeps_full_desc_but_capped_snippet(self):
        from src.main import normalize_raw
        long_desc = "x" * 3500 + " oracle etl"
        j = normalize_raw(_raw("ODI Developer", long_desc))
        assert len(j.description_snippet) <= 2000
        assert "oracle etl" in (j.raw.get("description") or "")


# ── Beat 171: roles are data, not code — new profile = new role, zero changes ─

def test_new_profile_yaml_auto_discovered_no_code_change(tmp_path, monkeypatch):
    """Owner: today's 2 profiles are just test roles — dropping a third yaml
    must steer the scrape (keywords) with no code edit. Proves it with an
    isolated PROFILES_DIR so the repo is never polluted."""
    import src.matcher as m

    (tmp_path / "mlops_lead.yaml").write_text(
        "name: mlops_lead\n"
        "display_name: MLOps Lead\n"
        "min_experience_years: 6\n"
        "match_threshold: 65\n"
        "keywords:\n"
        "  - MLOps Engineer\n"
        "role_keywords:\n"
        "  - Engineer\n"
        "tier1:\n"
        "  - {pattern: 'mlops', label: 'MLOps', score: 90}\n"
        "tier2:\n"
        "  - {pattern: 'kubernetes', label: 'K8s', score: 70}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(m, "PROFILES_DIR", tmp_path)
    assert m.list_profiles() == ["mlops_lead"]
    primary, roles = m.profile_keywords()
    assert "MLOps Engineer" in primary
    assert "Engineer" in roles
    prof = m.load_profile("mlops_lead")
    assert prof.match_threshold == 65
