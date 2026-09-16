"""Candidate CV Profile Matcher for Muhammad Usama.

Profile: Senior AI Engineer | Generative AI | LLMs | RAG | MLOps (6+ years experience)
Core Stack: Python, PyTorch, FastAPI, Django, LangGraph, CrewAI, AWS Bedrock,
            Kubernetes, Docker, MLflow, Vector DBs (FAISS, Pinecone), CV (YOLO).

Ensures only relevant AI/ML/Data roles match, strictly eliminating non-technical roles
(Client Success, Account Manager, Sales) and unrelated tech stacks (Java, .NET, Vue, etc.).
"""
from __future__ import annotations

import re
from typing import Any

# Non-technical / business roles that must NEVER match for an AI engineer
NEGATIVE_TITLE_PATTERNS: list[str] = [
    r"\bclient\s+success\b",
    r"\bcustomer\s+success\b",
    r"\bcustomer\s+support\b",
    r"\baccount\s+manager\b",
    r"\baccount\s+executive\b",
    r"\bbilingual\b",
    r"\bsales\b",
    r"\bbusiness\s+development\b",
    r"\bbd\s+manager\b",
    r"\bmarketing\b",
    r"\bgrowth\s+manager\b",
    r"\brecruiter\b",
    r"\btalent\s+acquisition\b",
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
    (r"\b(generative\s+ai|genai)\b", "Generative AI", 95),
    (r"\b(llm|large\s+language\s+model)s?\b", "LLMs / Prompting", 95),
    (r"\b(rag|retrieval\s+augmented)\b", "RAG Systems", 95),
    (r"\b(agentic\s+ai|ai\s+agents?|multi-agent)\b", "Agentic AI", 95),
    (r"\b(senior\s+ai\s+engineer|lead\s+ai\s+engineer|staff\s+ai\s+engineer)\b", "Senior AI Engineer", 95),
    (r"\bai\s+engineer\b", "AI Engineer", 90),
    (r"\bmlops\b", "MLOps / Infra", 92),
    (r"\b(machine\s+learning\s+engineer|ml\s+engineer)\b", "Machine Learning", 90),
    (r"\b(ai\s+research|ai\s+scientist|applied\s+scientist)\b", "AI Science", 90),
    (r"\b(computer\s+vision|cv\s+engineer)\b", "Computer Vision", 90),
    (r"\b(deep\s+learning|nlp\s+engineer|natural\s+language)\b", "Deep Learning / NLP", 90),
    (r"\bai\s+fde\b", "AI Forward Deployed", 90),
    (r"\bai\s+solutions?\s+engineer\b", "AI Solutions", 88),
]

# Secondary AI/Data roles (75% - 85% match)
TIER2_AI_ROLES: list[tuple[str, str, int]] = [
    (r"\bdata\s+scientist\b", "Data Science", 85),
    (r"\b(python\s+ai|python\s+ml)\b", "Python AI/ML", 85),
    (r"\bdata\s+engineer\b", "Data Engineering", 75),
    (r"\bpython\s+(?:backend\s+)?(?:developer|engineer)\b", "Python Backend", 75),
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
    """Evaluates whether a job matches Muhammad Usama's Senior AI Engineer CV.

    Returns (is_match, match_percentage, primary_category).
    - Threshold: match_percentage >= 70 is considered a valid match.
    """
    title_clean = title.strip().lower()
    desc_clean = (description or "").strip().lower()
    tags_clean = " ".join([t.lower() for t in (tags or [])])
    haystack = f"{title_clean}\n{tags_clean}\n{desc_clean[:2000]}"

    # Step 1: Strict negative blacklist check
    blacklisted, reason = is_blacklisted_title(title)
    if blacklisted:
        return False, 0, f"Rejected ({reason})"

    # Step 2: Check primary AI role in TITLE first (highest weight)
    for pat, label, score in TIER1_AI_ROLES:
        if re.search(pat, title_clean):
            # Bonus for senior-level or matching exact keywords in Usama's stack
            if any(k in haystack for k in ("langgraph", "crewai", "bedrock", "pytorch", "fastapi", "rag")):
                score = min(100, score + 5)
            return True, score, f"{label} ({score}%)"

    for pat, label, score in TIER2_AI_ROLES:
        if re.search(pat, title_clean):
            # For Python/Data roles, require AI/ML terms in description to qualify
            if "python" in pat or "data" in pat:
                has_ai_context = any(
                    k in haystack
                    for k in ("machine learning", "deep learning", "llm", "ai", "pytorch", "fastapi", "rag")
                )
                if not has_ai_context:
                    return False, 0, "Rejected (Python/Data role lacking AI/ML core)"
            return True, score, f"{label} ({score}%)"

    # Step 3: If title is generic (e.g. "Software Engineer" / "Backend Engineer"),
    # require explicit, heavy AI/ML presence in description and Python backend
    generic_tech_title = bool(re.search(r"\b(software\s+engineer|backend\s+engineer|systems\s+engineer)\b", title_clean))
    if generic_tech_title:
        core_ai_hits = sum(
            1
            for k in (
                "large language model",
                "generative ai",
                "machine learning",
                "rag",
                "agentic",
                "pytorch",
                "langchain",
                "langgraph",
            )
            if k in haystack
        )
        if core_ai_hits >= 2 and ("python" in haystack or "fastapi" in haystack):
            return True, 75, "AI Systems / Backend (75%)"

    return False, 0, "Rejected (Does not match AI/ML candidate profile)"
