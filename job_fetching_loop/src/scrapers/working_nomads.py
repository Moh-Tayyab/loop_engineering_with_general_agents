"""Working Nomads (workingnomads.com) scraper — remote-only jobs.

The source exposes a JSON API (`/api/exposed_jobs`). We call it with plain
`requests` — launching a whole Chromium for an HTTP GET is wasteful. Only when
the API is unreachable do we fall back to a Playwright crawl of the HTML
listing, so the source keeps working under anti-bot drift.
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime
from typing import Iterator

import requests

from src.browser import USER_AGENTS, check_captcha, launch_browser
from src.models import RawJob
from . import register_scraper
from .base import BaseScraper

log = logging.getLogger(__name__)


@register_scraper
class WorkingNomadsScraper(BaseScraper):
    name = "working_nomads"

    _BASE = "https://www.workingnomads.com"
    _JOBS_URL = "https://www.workingnomads.com/api/exposed_jobs"

    def is_available(self) -> bool:
        return True

    def fetch(self, keywords: list[str], posted_after: datetime) -> Iterator[RawJob]:
        data = self._api_fetch()
        if data is not None:
            for item in data:
                job = self._parse_json_item(item, keywords)
                if job:
                    yield job
            return
        log.warning("working_nomads API unreachable — falling back to HTML crawl")
        yield from asyncio.run(self._html_gather(keywords, posted_after))

    def _api_fetch(self) -> list[dict] | None:
        """Return the job list from the JSON API, or None on any failure."""
        try:
            resp = requests.get(
                self._JOBS_URL,
                timeout=20,
                headers={"User-Agent": random.choice(USER_AGENTS)},
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                data = data.get("data", data.get("jobs", []))
            return data if isinstance(data, list) else None
        except (requests.RequestException, ValueError) as exc:
            log.info("working_nomads API fetch failed: %s", exc)
            return None

    async def _html_gather(self, keywords, posted_after) -> Iterator[RawJob]:
        async with launch_browser(self.name) as context:
            page = await context.new_page()
            await page.goto(self._BASE + "/jobs", timeout=30_000)
            await check_captcha(page, self.name)
            cards = await page.query_selector_all("div.job-item, div.card, article")
            for card in cards:
                job = await self._parse_html_card(card, keywords)
                if job:
                    yield job
            await page.close()

    def _parse_json_item(self, item: dict, keywords: list[str]) -> RawJob | None:
        title = item.get("title", "").strip()
        company = item.get("company_name", item.get("company", "Unknown")).strip()
        url = item.get("url", item.get("link", ""))
        if url and not url.startswith("http"):
            url = self._BASE + url
        location = item.get("location", "Remote")
        tags = item.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        desc = item.get("description", item.get("short_description", ""))
        posted = item.get("date", item.get("created_at"))
        return RawJob(
            source=self.name,
            title=title,
            company=company,
            url=url,
            location=location,
            posted_date=str(posted) if posted else None,
            description=desc,
            tags=tags if tags else keywords[:1],
        )

    async def _parse_html_card(self, card, keywords: list[str]) -> RawJob | None:
        title_el = await card.query_selector("h4, h3, a")
        if not title_el:
            return None
        title = (await title_el.inner_text()).strip()
        company_el = await card.query_selector(".company, span")
        company = (await company_el.inner_text()).strip() if company_el else "Unknown"
        link_el = await card.query_selector("a[href]")
        url = await link_el.get_attribute("href") if link_el else ""
        if url and not url.startswith("http"):
            url = self._BASE + url
        return RawJob(
            source=self.name,
            title=title,
            company=company,
            url=url,
            location="Remote",
            tags=keywords[:1],
        )