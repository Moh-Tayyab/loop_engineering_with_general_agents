"""Internal input-validation helper shared across textutils modules."""

from __future__ import annotations


def require_str(value: object, *, name: str = "value") -> None:
    """Raise ``ValueError`` unless ``value`` is a ``str``.

    Raising (rather than coercing) keeps the library strict and predictable:
    callers that pass non-text get an immediate, explicit error.
    """
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a str, got {type(value).__name__}")


def require_int(value: object, *, name: str = "value") -> None:
    """Raise ``ValueError`` unless ``value`` is an ``int`` (not a bool or float).

    Lengths/widths must be whole numbers; accepting ``None``, ``"5"`` or ``2.5``
    silently would turn arithmetic bugs into confusing downstream errors.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an int, got {type(value).__name__}")
