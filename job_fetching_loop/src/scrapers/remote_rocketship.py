"""Remote Rocketship (remoterocketship.com) scraper — lightest source, good data."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Iterator

from src.browser import check_captcha, launch_browser, polite_delay
from src.models import RawJob
from src.scrapers import register_scraper
from src.scrapers.base import BaseScraper


@register_scraper
class RemoteRocketshipScraper(BaseScraper):
    name = "remote_rocketship"

    _BASE = "https://www.remoterocketship.com"
    # Jobs live under /publicjobs/company/{company}/jobs/{slug} — the
    # remote-jobs landing page lists them inside the /company/ sections.
    _JOBS_URL = "https://www.remoterocketship.com/remote-jobs/"
    # Job-listing links point into /publicjobs/company/.../jobs/<slug>/ —
    # WITHOUT the /jobs/ segment the href is a company profile or side-nav.
    _JOB_LINK_SELECTOR = "a[href*='/publicjobs/company/'][href*='/jobs/']"
    # Each listing row has the title anchor + company; wrap in the smallest
    # row container we found (the title <a>). We'll read the DOM for company
    # from the row context.

    def is_available(self) -> bool:
        return True

    def fetch(self, keywords: list[str], posted_after: datetime) -> Iterator[RawJob]:
        yield from asyncio.run(self._gather(keywords, posted_after))

    async def _gather(self, keywords, posted_after) -> list:
        return [j async for j in self._fetch_async(keywords, posted_after)]

    async def _fetch_async(self, keywords: list[str], posted_after: datetime):
        async with launch_browser(self.name) as context:
            page = await context.new_page()
            await page.goto(self._JOBS_URL, wait_until="domcontentloaded", timeout=30_000)
            await check_captcha(page, self.name)
            await polite_delay()

            links = await page.locator(self._JOB_LINK_SELECTOR).all()
            seen: set[str] = set()
            for link in links:
                href = await link.get_attribute("href") or ""
                if not href or href in seen:
                    continue
                seen.add(href)
                if not self._url_matches_keywords(href, keywords):
                    continue
                try:
                    title = (await link.inner_text()).strip()
                    if not title:
                        continue
                    job = self._parse_link(href, title, keywords)
                    if job:
                        yield job
                except Exception:
                    continue
            await page.close()

    def _url_matches_keywords(self, href: str, keywords: list[str]) -> bool:
        """Jobs are keyed by keyword in their URL slug (a cheap filter before
        any browser work). Slug tokens are '-'-joined, so match on the slug and
        title-aware normalised tokens."""
        slug = href.lower()
        for kw in keywords:
            token = kw.lower().replace(" ", "-")
            if token in slug:
                return True
        return False

    def _parse_link(self, href: str, title: str, keywords: list[str]) -> RawJob:
        url = href if href.startswith("http") else self._BASE + href
        company = self._company_from_href(href)
        location = self._location_from_href(href)
        return RawJob(
            source=self.name,
            title=title,
            company=company,
            url=url,
            location=location,
            tags=keywords[:1],
        )

    @staticmethod
    def _company_from_href(href: str) -> str:
        """Extract company slug from /publicjobs/company/{company}/jobs/..."""
        parts = href.split("/")
        try:
            idx = parts.index("company")
            if idx + 1 < len(parts):
                return parts[idx + 1].replace("-", " ").title()
        except ValueError:
            pass
        return "Unknown"

    @staticmethod
    def _location_from_href(href: str) -> str | None:
        """Job slugs carry a trailing location token, e.g.
        .../finance-analyst-iraq-remote-2/ -> 'Remote (Iraq?)'. We only mark
        Remote when the slug ends in '-remote' or contains 'remote'."""
        stem = href.rstrip("/").split("/")[-1]
        return "Remote" if "remote" in stem.lower() else None