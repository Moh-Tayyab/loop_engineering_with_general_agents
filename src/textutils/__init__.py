"""textutils — small text-processing utilities with strict input validation."""

from __future__ import annotations

import re

from ._validate import require_str as _require_str
from .diff import diff, render_unified, similarity

__all__ = [
    "slugify",
    "truncate",
    "count_words",
    "redact_secrets",
    "diff",
    "render_unified",
    "similarity",
]


def slugify(text: str, *, max_len: int = 64) -> str:
    """Convert arbitrary text into a URL-safe slug.

    - Lowercases, strips non-alphanumeric runs, keeps hyphens.
    - Truncates to ``max_len`` on a word boundary (never splits a word).
    - Raises ``ValueError`` for empty/non-string input.
    """
    _require_str(text)
    if not isinstance(max_len, int) or isinstance(max_len, bool):
        raise ValueError(f"max_len must be an int, got {type(max_len).__name__}")
    if max_len < 1:
        raise ValueError("max_len must be >= 1")

    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not slug:
        return ""

    if len(slug) <= max_len:
        return slug

    head = slug[: max_len + 1]
    if "-" not in head:
        return slug[:max_len].rstrip("-")
    head = head.rsplit("-", 1)[0]
    return head.rstrip("-")


def truncate(text: str, *, max_chars: int = 80, ellipsis: str = "...") -> str:
    """Truncate ``text`` to ``max_chars``, appending ``ellipsis`` when cut.

    Raises ``ValueError`` if ``max_chars`` is less than the ellipsis length.
    """
    _require_str(text)
    _require_str(ellipsis)
    if not isinstance(max_chars, int) or isinstance(max_chars, bool):
        raise ValueError(f"max_chars must be an int, got {type(max_chars).__name__}")
    if max_chars < 0:
        raise ValueError("max_chars must be >= 0")
    if len(ellipsis) > max_chars:
        raise ValueError("ellipsis is longer than max_chars")

    if len(text) <= max_chars:
        return text
    return text[: max_chars - len(ellipsis)] + ellipsis


def count_words(text: str) -> int:
    """Return the number of whitespace-separated words in ``text``.

    ``""`` and ``"   "`` count as 0 words. Raises ``ValueError`` on non-str.
    """
    _require_str(text)
    return len(text.split())


_SECRET_PATTERNS = [
    re.compile(
        r"\b(sk|pk|ghp|gho|ghu|ghs|github_pat|AKIA)[A-Za-z0-9_-]{16,}\b",
        re.IGNORECASE,
    ),
    re.compile(r"bearer\s+[a-z0-9._~+/=-]{20,}", re.IGNORECASE),
]


def redact_secrets(text: str, *, replacement: str = "[REDACTED]") -> str:
    """Replace likely API keys / bearer tokens with ``replacement``.

    Best-effort heuristics; never a guarantee. Raises ``ValueError`` on non-str.
    """
    _require_str(text)
    _require_str(replacement)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text