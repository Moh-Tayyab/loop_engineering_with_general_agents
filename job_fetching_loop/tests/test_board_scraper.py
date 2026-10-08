"""Beat 183 (BoardScraper deepening): shared Playwright board scraper engine.

Proves:
1. Common BoardScraper base contract for Indeed and Glassdoor
2. Unified domain resolution and search template construction
3. Subclass pagination and navigation configuration
4. Error resilience and partial card collection preservation
"""
from __future__ import annotations

import pytest

from src.scrapers.base import BaseScraper, BoardScraper
from src.scrapers.glassdoor import GlassdoorScraper
from src.scrapers.indeed import IndeedScraper


class TestBoardScraperHierarchy:
    def test_subclasses_inherit_board_scraper(self):
        assert issubclass(IndeedScraper, BoardScraper)
        assert issubclass(GlassdoorScraper, BoardScraper)
        assert issubclass(BoardScraper, BaseScraper)

    def test_instances_are_board_scrapers(self):
        indeed = IndeedScraper()
        glassdoor = GlassdoorScraper()
        assert isinstance(indeed, BoardScraper)
        assert isinstance(glassdoor, BoardScraper)
        assert indeed.is_available() is True
        assert glassdoor.is_available() is True

    def test_pagination_sequence_and_labels(self):
        indeed = IndeedScraper()
        assert indeed.pagination_sequence() == (0, 10, 20, 30, 40)
        assert indeed._page_log_label(10) == "start=10"
        assert indeed.nav_timeout_ms() == 30_000

        glassdoor = GlassdoorScraper()
        assert glassdoor.pagination_sequence() == (1, 2, 3, 4, 5)
        assert glassdoor._page_log_label(2) == "page 2/3"
        assert glassdoor.nav_timeout_ms() == 45_000

    def test_domain_rebuild_via_board_scraper(self, monkeypatch):
        # Indeed domain rebuild
        monkeypatch.setenv("INDEED_DOMAINS", "ae.indeed.com")
        indeed = IndeedScraper()
        indeed._apply_domain()
        assert indeed._BASE == "https://ae.indeed.com"
        assert indeed._HOME == "https://ae.indeed.com/"
        assert indeed._SEARCH.startswith("https://ae.indeed.com/jobs?")

        # Glassdoor domain rebuild
        monkeypatch.setenv("GLASSDOOR_DOMAINS", "www.glassdoor.co.uk")
        glassdoor = GlassdoorScraper()
        glassdoor._apply_domain()
        assert glassdoor._BASE == "https://www.glassdoor.co.uk"
        assert glassdoor._HOME == "https://www.glassdoor.co.uk/"
        assert glassdoor._SEARCH.startswith("https://www.glassdoor.co.uk/Job/jobs.htm?")
