"""APAC Remote (remotearmy.io Asia) scraper — Asia-Pacific focus."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Iterator

from src.browser import check_captcha, launch_browser, polite_delay
from src.models import RawJob
from . import register_scraper
from .base import BaseScraper

_KNOWN_COMPANIES = ("Netomi", "Mactores", "AlphaSense", "Speechify", "GitLab")


@register_scraper
class APACRemoteScraper(BaseScraper):
    name = "apac_remote"

    _BASE = "https://remotearmy.io"
    _JOBS = "https://remotearmy.io/region/remote-jobs-in-asia"

    def is_available(self) -> bool:
        return True

    def fetch(self, keywords: list[str], posted_after: datetime) -> Iterator[RawJob]:
        yield from asyncio.run(self._gather(keywords, posted_after))

    async def _gather(self, keywords, posted_after) -> list:
        return [j async for j in self._fetch_async(keywords, posted_after)]

    async def _fetch_async(self, keywords: list[str], posted_after: datetime) -> Iterator[RawJob]:
        async with launch_browser(self.name) as context:
            page = await context.new_page()
            await page.goto(self._JOBS, timeout=30_000)
            await check_captcha(page, self.name)

            cards = await page.query_selector_all(f"li[id^='li-'] a[href*='/jobs/']")
            for card in cards:
                job = await self._parse_card(card, keywords)
                if job:
                    yield job
            await polite_delay()
            await page.close()

    def _parse_company(self, card) -> str:
        card_html_company = card.query_selector("img.company-list-img, img[src*='s3.amazonaws']")
        return "Unknown (APAC)"

    async def _parse_card(self, card, keywords: list[str]) -> RawJob | None:
        # structure: company / date / type / TITLE / location / salary / tags
        title_el = await card.query_selector("div.text-sm.text-gray-700.font-semibold")
        if not title_el:
            return None
        title = (await title_el.inner_text()).strip().split("\n")[0].strip()
        if not title:
            return None

        href = await card.get_attribute("href") or ""
        url = href if href.startswith("http") else self._BASE + href

        company_el = await card.query_selector("div.text-xs.text-gray-500.truncate")
        company = (await company_el.inner_text()).strip() if company_el else "Unknown (APAC)"

        location_el = await card.query_selector("div.text-xs.font-semibold.text-gray-500")
        location = (await location_el.inner_text()).strip() if location_el else "Remote (APAC)"
        if not location or "icon" in location.lower():
            location = "Remote (APAC)"

        return RawJob(
            source=self.name,
            title=title,
            company=company,
            url=url,
            location=location,
            tags=keywords[:1],
        )