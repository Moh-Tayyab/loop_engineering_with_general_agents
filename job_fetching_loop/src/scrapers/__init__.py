"""Source registry + scraper discovery.

The abstract scraper contract lives in `src.scrapers.base` (single source of
truth); this module only owns registration so concrete scrapers can declare
themselves via `@register_scraper`.
"""
from __future__ import annotations

from src.models import RawJob
from .base import BaseScraper  # noqa: F401  (re-exported for callers)

# ── Registry ─────────────────────────────────────────────────────────────────

_REGISTRY: dict[str, type[BaseScraper]] = {}


def register_scraper(cls: type[BaseScraper]) -> type[BaseScraper]:
    """Decorator to register a scraper class by its name."""
    _REGISTRY[cls.name] = cls
    return cls


def get_scraper(name: str) -> BaseScraper:
    """Instantiate a registered scraper by name."""
    cls = _REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"no scraper registered for '{name}'. available: {list(_REGISTRY)}")
    return cls()


def all_scrapers() -> dict[str, type[BaseScraper]]:
    """Return a copy of the registry."""
    return dict(_REGISTRY)


def enabled_scrapers() -> list[str]:
    """Return names of sources that are both registered AND enabled via env."""
    from src.config import source_enabled
    return [name for name in _REGISTRY if source_enabled(name)]


def load_all_scrapers() -> None:
    """Import all concrete scraper modules to trigger @register_scraper.

    Called once at startup — keeps __init__ clean to avoid circular imports.

    A failing scraper import is logged loudly (not silently skipped) so a
    broken source is visible in the run log instead of vanishing from the
    registry without a trace.
    """
    import importlib
    import logging

    log = logging.getLogger(__name__)
    _modules = [
        "src.scrapers.remote_rocketship",
        "src.scrapers.working_nomads",
        "src.scrapers.linkedin",
        "src.scrapers.indeed",
        "src.scrapers.glassdoor",
        "src.scrapers.apac_remote",
        "src.scrapers.pakistan_remote",
        "src.scrapers.curated_boards",
    ]
    for mod in _modules:
        try:
            importlib.import_module(mod)
        except Exception as exc:  # noqa: BLE001 - keep the loop starting
            log.error("failed to import scraper module %s: %s", mod, exc)