"""Candidate profile matcher — multi-profile engine + bundled AI profile.

Each pilot/client profile lives in ``profiles/*.yaml`` (tiers, skills,
blacklist extras, keywords). The engine below is shared; YAML owns the data.
``match_usama_cv`` is kept as a thin backwards-compatible wrapper over the
bundled ``senior_ai_engineer`` profile — existing callers and tests are safe.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

# Non-technical / business roles that must NEVER match for an AI engineer
NEGATIVE_TITLE_PATTERNS: list[str] = [
    r"\bclient\s+success\b",
    r"\bcustomer\s+success\b",
    r"\bcustomer\s+support\b",
    r"\baccount\s+manager\b",
    r"\baccount\s+executive\b",
    r"\bbilingual\b",
    r"\bbusiness\s+leader\b",
    r"\bbusiness\s+development\b",
    r"\bbd\s+manager\b",
    r"\btalent\s+intelligence\b",
    r"\btalent\s+acquisition\b",
    r"\btalent\s+(?:partner|scout|lead|specialist)\b",
    r"\brecruiter\b",
    r"\brecruit\w*\b",
    r"\bheadhunter\b",
    r"\bmultimedia\b",
    r"\bmarketing\b",
    r"\bgrowth\s+manager\b",
    r"\bhuman\s+resources\b",
    r"\boperations\s+manager\b",
    r"\bcontent\s+writer\b",
    r"\bcopywriter\b",
    r"\bsocial\s+media\b",
    r"\blegal\b",
    r"\bfinance\b",
    r"\baccounting\b",
    r"\bevent\s+manager\b",
    r"\boffice\s+manager\b",
    r"\bproduct\s+manager\b",  # Unless explicitly Technical AI PM
    r"\bscrum\s+master\b",
    r"\bagile\s+coach\b",
    r"\bpostdoctoral\b",
    r"\bphd\s+(?:student|researcher|fellow)\b",
    r"\bventure\b",
    r"\bsales\b",
]

# Unrelated engineering stacks that indicate non-AI roles when in title
UNRELATED_STACK_PATTERNS: list[str] = [
    r"\bjava\b",
    r"\bspring\s*boot\b",
    r"(?:^|[\s,/(])\.net(?:\b|[\s,/)]|$)",
    r"\bdotnet\b",
    r"(?:^|[\s,/(])c#(?:\b|[\s,/)]|$)",
    r"\bvue(?:\.js)?\b",
    r"\bangular(?:\.js)?\b",
    r"\bphp\b",
    r"\blaravel\b",
    r"\bruby\b",
    r"\brails\b",
    r"\bios\s+developer\b",
    r"\bswift\s+developer\b",
    r"\bandroid\s+developer\b",
    r"\bkotlin\s+developer\b",
    r"\breact\s+native\b",
    r"\bflutter\b",
    r"\bsalesforce\b",
    r"\bwordpress\b",
    r"\bsap\b",
]

# High-priority core AI roles matching Usama's CV directly (90% - 95% match)
TIER1_AI_ROLES: list[tuple[str, str, int]] = [
    (r"\b(?:generative\s+ai|gen\s*ai)\b", "Generative AI", 95),
    (r"\b(?:llm|large\s+language\s+model)s?\b", "LLMs / Prompting", 95),
    (r"\b(?:rag|retrieval\s+augmented)\b", "RAG Systems", 95),
    (r"\b(?:agentic(?:\s+ai)?|ai\s+agents?|multi-agent)\b", "Agentic AI", 95),
    (r"\b(?:senior\s+ai\s+engineer|lead\s+ai\s+engineer|staff\s+ai\s+engineer|principal\s+ai\s+engineer)\b", "Senior AI Engineer", 95),
    (r"\b(?:ai|artificial\s+intelligence)\s+(?:software\s+|prompt\s+|eval(?:uation)?\s+|integration\s+|platform\s+|infra(?:structure)?\s+|research\s+|agentic\s+)?(?:engineer|developer|architect|specialist|lead|researcher|scientist|expert|solutions?|systems?|native)\b", "AI Engineer", 92),
    (r"\b(?:prompt\s+engineer(?:ing)?|(?:ai\s+)?prompt\s+specialist)\b", "Prompt Engineering", 92),
    (r"\bai\s+(?:engineer|developer|architect|specialist|lead)\b", "AI Engineer", 90),
    (r"\b(?:head\s+of\s+ai|ai\s+lead|lead\s+ai)\b", "AI Leadership", 95),
    (r"\bmlops\b", "MLOps / Infra", 92),
    (r"\b(?:machine\s+learning|ml)\s+(?:engineer|developer|specialist|expert|lead|architect|scientist|researcher)\b", "Machine Learning", 90),
    (r"\b(?:ai\s+research|ai\s+scientist|applied\s+scientist|applied\s+(?:ml|ai))\b", "AI Science", 90),
    (r"\b(?:computer\s+vision|cv)\s*(?:engineer|developer|specialist|scientist)?\b", "Computer Vision", 90),
    (r"\b(?:deep\s+learning|nlp)\s*(?:engineer|developer|specialist|scientist)?\b", "Deep Learning / NLP", 90),
    (r"\b(?:ai\s+fde|forward\s+deployed\s+(?:ai|ml|engineer))\b", "AI Forward Deployed", 90),
    (r"\bai\s+solutions?\s+(?:engineer|architect)\b", "AI Solutions", 90),
]

# Secondary AI/Data/Tech roles (75% - 85% match)
TIER2_AI_ROLES: list[tuple[str, str, int]] = [
    (r"\bdata\s+scientist\b", "Data Science", 85),
    (r"\b(python\s+ai|python\s+ml)\b", "Python AI/ML", 85),
    (r"\bdata\s+engineer\b", "Data Engineering", 80),
    (r"\bpython\s+(?:backend\s+)?(?:developer|engineer|software)\b", "Python Backend", 75),
    (r"\b(?:backend|software|platform|cloud|devops)\s+(?:engineer|developer|architect)\b", "Software & Systems", 75),
]


def is_blacklisted_title(title: str) -> tuple[bool, str]:
    """Check if title contains blacklisted negative roles or unrelated stacks.

    Returns (is_blacklisted, reason).
    """
    title_clean = title.lower()

    # 1. Non-technical / business roles check
    for pat in NEGATIVE_TITLE_PATTERNS:
        if re.search(pat, title_clean):
            return True, f"blacklisted_role: {pat.replace(r'\b', '').strip()}"

    # 2. Unrelated stacks check
    for pat in UNRELATED_STACK_PATTERNS:
        if re.search(pat, title_clean):
            # Exception: if title clearly contains an explicit AI/ML role token,
            # e.g., "AI Engineer (with some Java)", check if it's primary
            if not any(re.search(r"\b(ai\s+engineer|ml\s+engineer|machine\s+learning)\b", title_clean) for _ in [1]):
                return True, f"unrelated_stack: {pat.replace(r'\b', '').strip()}"

    return False, ""


def match_usama_cv(
    title: str,
    description: str | None = None,
    tags: list[str] | None = None,
) -> tuple[bool, int, str]:
    """Backwards-compatible wrapper: scores against the bundled AI profile.

    New code should call ``match_profile(..., load_profile("senior_ai_engineer"))``
    (or any pilot profile) directly.
    """
    return match_profile(title, description, tags, load_profile("senior_ai_engineer"))


# ── Multi-profile engine (pilot layer) ───────────────────────────────────────

PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"

#: Shared business-role rejects applied to EVERY profile (a Client Success
#: Manager is not a fit for any engineering candidate).
SHARED_NEGATIVE_TITLES: list[str] = NEGATIVE_TITLE_PATTERNS


@dataclass
class Tier:
    pattern: str
    label: str
    score: int


@dataclass
class Profile:
    name: str
    display_name: str
    min_experience_years: int = 0
    match_threshold: int = 70
    keywords: list[str] = field(default_factory=list)
    role_keywords: list[str] = field(default_factory=list)
    negative_title_patterns: list[str] = field(default_factory=list)
    unrelated_stack_patterns: list[str] = field(default_factory=list)
    tier1: list[Tier] = field(default_factory=list)
    tier2: list[Tier] = field(default_factory=list)
    bonus_keywords: list[str] = field(default_factory=list)
    bonus_points: int = 5
    tech_context_keywords: list[str] = field(default_factory=list)
    generic_title_pattern: str = ""
    generic_required_hits: list[str] = field(default_factory=list)
    generic_required_count: int = 2
    generic_required_any: list[str] = field(default_factory=list)
    generic_fallback_score: int = 70
    generic_fallback_label: str = "Generalist fallback"


def _compile_tiers(raw: Any, profile_name: str, tier_name: str) -> list[Tier]:
    tiers: list[Tier] = []
    for i, item in enumerate(raw or []):
        try:
            pattern = str(item["pattern"])
            label = str(item["label"])
            score = int(item["score"])
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"[profiles] {profile_name}.{tier_name}[{i}] malformed: {e}")
        if not 0 <= score <= 100:
            raise ValueError(f"[profiles] {profile_name}.{tier_name}[{i}] score {score} out of 0-100")
        try:
            re.compile(pattern)
        except re.error as e:
            raise ValueError(f"[profiles] {profile_name}.{tier_name}[{i}] bad regex {pattern!r}: {e}")
        tiers.append(Tier(pattern=pattern, label=label, score=score))
    if not tiers:
        raise ValueError(f"[profiles] {profile_name}.{tier_name} must not be empty")
    return tiers


def _compile_patterns(raw: Any, profile_name: str, key: str) -> list[str]:
    out: list[str] = []
    for i, pat in enumerate(raw or []):
        try:
            re.compile(str(pat))
        except re.error as e:
            raise ValueError(f"[profiles] {profile_name}.{key}[{i}] bad regex {pat!r}: {e}")
        out.append(str(pat))
    return out


def _profile_from_dict(data: dict[str, Any]) -> Profile:
    name = str(data.get("name", "")).strip()
    if not name:
        raise ValueError("[profiles] profile missing required 'name'")
    keywords = [str(k).strip() for k in (data.get("keywords") or []) if str(k).strip()]
    if not keywords:
        raise ValueError(f"[profiles] {name} must define at least one keyword")
    return Profile(
        name=name,
        display_name=str(data.get("display_name", name)),
        min_experience_years=int(data.get("min_experience_years", 0) or 0),
        match_threshold=int(data.get("match_threshold", 70) or 0),
        keywords=keywords,
        role_keywords=[str(k) for k in (data.get("role_keywords") or [])],
        negative_title_patterns=_compile_patterns(data.get("negative_title_patterns"), name, "negative_title_patterns"),
        unrelated_stack_patterns=_compile_patterns(data.get("unrelated_stack_patterns"), name, "unrelated_stack_patterns"),
        tier1=_compile_tiers(data.get("tier1"), name, "tier1"),
        tier2=_compile_tiers(data.get("tier2"), name, "tier2"),
        bonus_keywords=[str(k).lower() for k in (data.get("bonus_keywords") or [])],
        bonus_points=int(data.get("bonus_points", 5) or 0),
        tech_context_keywords=[str(k).lower() for k in (data.get("tech_context_keywords") or [])],
        generic_title_pattern=str(data.get("generic_title_pattern", "") or ""),
        generic_required_hits=[str(k).lower() for k in (data.get("generic_required_hits") or [])],
        generic_required_count=int(data.get("generic_required_count", 2) or 0),
        generic_required_any=[str(k).lower() for k in (data.get("generic_required_any") or [])],
        generic_fallback_score=int(data.get("generic_fallback_score", 70) or 0),
        generic_fallback_label=str(data.get("generic_fallback_label", "Generalist fallback")),
    )


@lru_cache(maxsize=32)
def load_profile(name: str) -> Profile:
    """Load + validate ``profiles/<name>.yaml`` (cached — safe per-job).

    Fail-fast: missing file, bad YAML, bad regex, or empty tiers raise
    loudly instead of silently degrading matching.
    """
    import yaml

    path = PROFILES_DIR / f"{name}.yaml"
    if not path.exists():
        available = sorted(p.stem for p in PROFILES_DIR.glob("*.yaml"))
        raise FileNotFoundError(f"[profiles] no profile {name!r} at {path}; available: {available}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"[profiles] {path.name} is not valid YAML: {e}")
    if not isinstance(data, dict):
        raise ValueError(f"[profiles] {path.name} must be a mapping at top level")
    profile = _profile_from_dict(data)
    if profile.name != name:
        raise ValueError(f"[profiles] {path.name} declares name {profile.name!r}, expected {name!r}")
    return profile


def list_profiles() -> list[str]:
    """Names of all loadable pilot profiles."""
    if not PROFILES_DIR.exists():
        return []
    return sorted(p.stem for p in PROFILES_DIR.glob("*.yaml"))


def profile_keywords(names: list[str] | None = None) -> tuple[list[str], list[str]]:
    """Combined (primary, role) keywords across profiles — scrape once, match twice."""
    names = names or list_profiles()
    primary: list[str] = []
    roles: list[str] = []
    for n in names:
        p = load_profile(n)
        for k in p.keywords:
            if k not in primary:
                primary.append(k)
        for k in p.role_keywords:
            if k not in roles:
                roles.append(k)
    return primary, roles


def is_blacklisted_title_for(title: str, profile: Profile) -> tuple[bool, str]:
    """Shared business-role rejects + profile extras + profile stack rejects."""
    title_clean = title.lower()
    for pat in list(SHARED_NEGATIVE_TITLES) + profile.negative_title_patterns:
        if re.search(pat, title_clean):
            return True, f"blacklisted_role: {pat.replace(chr(92) + 'b', '').strip()}"
    for pat in profile.unrelated_stack_patterns:
        if re.search(pat, title_clean):
            return True, f"unrelated_stack: {pat.replace(chr(92) + 'b', '').strip()}"
    return False, ""


def match_profile(
    title: str,
    description: str | None = None,
    tags: list[str] | None = None,
    profile: Profile | None = None,
) -> tuple[bool, int, str]:
    """Score a job against a pilot profile. Returns (is_match, score, reason)."""
    if profile is None:
        profile = load_profile("senior_ai_engineer")
    if not title:
        return False, 0, "Empty title"

    title_clean = title.strip().lower()
    # Full-description matching (Beat 158): restriction text past any truncate
    # point must still be seen — a "US work authorization required" buried at
    # char 2500 decides hireability for a Pakistan-based candidate.
    desc_clean = (description or "").strip().lower()
    tags_clean = " ".join([t.lower() for t in (tags or [])])
    haystack = f"{title_clean}\n{tags_clean}\n{desc_clean}"

    blacklisted, reason = is_blacklisted_title_for(title, profile)
    if blacklisted:
        return False, 0, f"Rejected ({reason})"

    for tier in profile.tier1:
        if re.search(tier.pattern, title_clean):
            score = tier.score
            if profile.bonus_keywords and any(k in haystack for k in profile.bonus_keywords):
                score = min(100, score + profile.bonus_points)
            return True, score, f"{tier.label} ({score}%)"

    for tier in profile.tier2:
        if re.search(tier.pattern, title_clean):
            if profile.tech_context_keywords and not any(
                k in haystack for k in profile.tech_context_keywords
            ):
                return False, 0, "Rejected (Technical role lacking core stack context)"
            return True, tier.score, f"{tier.label} ({tier.score}%)"

    if profile.generic_title_pattern and re.search(profile.generic_title_pattern, title_clean):
        hits = sum(1 for k in profile.generic_required_hits if k in haystack)
        has_any = not profile.generic_required_any or any(
            k in haystack for k in profile.generic_required_any
        )
        if hits >= profile.generic_required_count and has_any:
            score = profile.generic_fallback_score
            return True, score, f"{profile.generic_fallback_label} ({score}%)"

    return False, 0, f"Rejected (Does not match {profile.display_name} profile)"


def passing_profiles(
    title: str,
    description: str | None = None,
    tags: list[str] | None = None,
    names: list[str] | None = None,
) -> list[tuple[str, int, str]]:
    """Score a job against every pilot profile. Returns (name, score, label)
    for profiles with score > 0, best first. Empty = no profile wants it."""
    out: list[tuple[str, int, str]] = []
    for name in names or list_profiles():
        try:
            profile = load_profile(name)
        except (FileNotFoundError, ValueError):
            continue
        ok, score, label = match_profile(title, description, tags, profile)
        if ok and score > 0:
            out.append((name, score, label))
    out.sort(key=lambda t: t[1], reverse=True)
    return out


def meets_threshold(profile_name: str, score: int) -> bool:
    """Delivery gate: score >= this profile's match_threshold."""
    try:
        return score >= load_profile(profile_name).match_threshold
    except (FileNotFoundError, ValueError):
        return score >= 70  # legacy fallback when profiles are unavailable
