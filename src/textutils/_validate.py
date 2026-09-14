"""Internal input-validation helper shared across textutils modules."""

from __future__ import annotations


def require_str(value: object, *, name: str = "value") -> None:
    """Raise ``ValueError`` unless ``value`` is a ``str``.

    Raising (rather than coercing) keeps the library strict and predictable:
    callers that pass non-text get an immediate, explicit error.
    """
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a str, got {type(value).__name__}")
