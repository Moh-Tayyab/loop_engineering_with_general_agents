"""Base scraper interface — the abstract contract every source implements."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Iterator

from src.models import RawJob


class BaseScraper(ABC):
    """Abstract base for all job sources."""

    name: str  # "linkedin", "indeed", etc.

    @abstractmethod
    def fetch(self, keywords: list[str], posted_after: datetime) -> Iterator[RawJob]:
        """Yield jobs matching keywords, posted after the given datetime."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Pre-flight check: can we reach this source right now?"""
        ...

    def login_required(self) -> bool:
        """True for sources needing manual session (LinkedIn, Indeed)."""
        return False

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}({self.name})>"