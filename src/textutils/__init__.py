"""textutils — small text-processing utilities with strict input validation."""

from __future__ import annotations

import re
import textwrap

__all__ = ["slugify", "truncate", "count_words", "redact_secrets", "wrap_text"]


def slugify(text: str, *, max_len: int = 64) -> str:
    """Convert arbitrary text into a URL-safe slug.

    - Lowercases, strips non-alphanumeric runs, keeps hyphens.
    - Truncates to ``max_len`` on a word boundary (never splits a word).
    - Raises ``ValueError`` for empty/non-string input.
    """
    _require_str(text)
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
    re.compile(r"\b(sk|pk|ghp|gho|ghu|ghs|github_pat|AKIA)[A-Za-z0-9_]{16,}\b"),
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


def wrap_text(text: str, width: int = 80) -> str:
    """Wrap ``text`` to ``width`` columns, joining wrapped lines with ``"\\n"``.

    - Existing line breaks are preserved (each paragraph is wrapped separately).
    - Paragraphs are trimmed of surrounding whitespace; interior spacing is kept.
    - Words longer than ``width`` are hard-broken, never left overflowing.
    - ``""`` / whitespace-only input returns ``""`` (no trailing newline).
    - Raises ``ValueError`` for non-str input or invalid ``width``.
    """
    _require_str(text)
    if not isinstance(width, int) or isinstance(width, bool):
        raise ValueError("width must be an int")
    if width < 1:
        raise ValueError("width must be >= 1")

    if text.strip() == "":
        return ""

    return "\n".join(
        textwrap.fill(paragraph.strip(), width=width)
        for paragraph in text.split("\n")
    )


def _require_str(value: object) -> None:
    if not isinstance(value, str):
        raise ValueError(f"expected str, got {type(value).__name__}")