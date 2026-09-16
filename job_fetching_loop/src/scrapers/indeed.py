"""Indeed (indeed.com) scraper — worldwide remote, aggressive anti-bot.

Strategy (human-in-the-loop CAPTCHA):
  1. Persistent, headed, system-Chrome profile → solved CAPTCHAs and session
     cookies persist in `.runtime/indeed-profile/`.
  2. Warm up on the homepage first (human-like), then search.
  3. When a Cloudflare/hCaptcha challenge appears the browser stays OPEN —
     the human solves it once in the visible window (`await_captcha_solve`),
     and every later run reuses the saved session.
  4. Longer variable delays (human cadence).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Iterator

import src.config as cfg
from src.browser import (
    CaptchaDetected,
    CaptchaTimeout,
    await_captcha_solve,
    check_captcha,
    has_captcha,
    human_delay,
    human_scroll,
    launch_browser,
    warm_up,
)
from src.log import get_logger
from src.models import RawJob
from . import register_scraper
from .base import BaseScraper

log = get_logger(__name__)


@register_scraper
class IndeedScraper(BaseScraper):
    name = "indeed"

    _BASE = "https://www.indeed.com"
    _HOME = "https://www.indeed.com/"
    _SEARCH = "https://www.indeed.com/jobs?q={kw}&l=remote&fromage={days}&remotejob=032b3046-06a3-4876-8dfd-474eb5e7ed11"

    def is_available(self) -> bool:
        return True

    def fetch(self, keywords: list[str], posted_after: datetime) -> Iterator[RawJob]:
        yield from asyncio.run(self._gather(keywords, posted_after))

    async def _gather(self, keywords, posted_after) -> list:
        return [j async for j in self._fetch_async(keywords, posted_after)]

    async def _fetch_async(self, keywords: list[str], posted_after: datetime) -> Iterator[RawJob]:
        diff_days = (datetime.now(timezone.utc) - posted_after).total_seconds() / 86400.0
        days = 1 if diff_days <= 1.25 else max(1, min(14, round(diff_days)))
        async with launch_browser(self.name, persistent=True, headless=False) as context:
            page = await context.new_page()
            await warm_up(page, self._HOME, self.name)
            for kw in keywords:
                url = self._SEARCH.format(kw=kw.replace(" ", "+"), days=days)
                try:
                    await page.goto(url, timeout=30_000, wait_until="domcontentloaded")
                    if await has_captcha(page):
                        if not await await_captcha_solve(page, self.name, page.url, cfg.captcha_solve_timeout()):
                            raise CaptchaTimeout(self.name, page.url, cfg.captcha_solve_timeout())
                        # re-navigate after the solve — the search page reloads clean
                        await page.goto(url, timeout=30_000, wait_until="domcontentloaded")
                    await check_captcha(page, self.name)
                    await human_scroll(page)
                    await human_delay(2.0, 5.0)
                    cards = await page.query_selector_all("div.job_seen_beacon, div.jobsearch-SerpJobCard, td.resultContent")
                    for card in cards:
                        job = await self._parse_card(card, kw)
                        if job:
                            yield job
                    await human_delay(3.0, 6.0)
                except (CaptchaDetected, CaptchaTimeout):
                    raise
                except Exception as e:
                    log.warning("[indeed] error scraping %r: %s", kw, e)
            await page.close()

    async def _parse_card(self, card, keyword: str) -> RawJob | None:
        title_el = await card.query_selector("h2.jobTitle a, a.jcs-JobTitle, h2 a")
        if not title_el:
            return None
        title = (await title_el.inner_text()).strip()
        href = await title_el.get_attribute("href") or ""
        jk = await card.get_attribute("data-jk") or await title_el.get_attribute("data-jk")
        if not jk and href:
            import re
            m = re.search(r"[?&]jk=([a-fA-F0-9]+)", href)
            if m:
                jk = m.group(1)
        if jk:
            url = f"https://www.indeed.com/viewjob?jk={jk}"
        else:
            url = self._BASE + href if href.startswith("/") else href
        company_el = await card.query_selector("span[data-testid='company-name'], span.companyName")
        company = (await company_el.inner_text()).strip() if company_el else "Unknown"
        location_el = await card.query_selector("div[data-testid='text-location'], div.companyLocation")
        location = (await location_el.inner_text()).strip() if location_el else None
        # Description: try job-snippet, then shelf, then table fallback
        desc = None
        for sel in ("div.job-snippet", "table.jobCardShelfContainer td", "div.jobsearch-SerpJobCard-snippet"):
            snippet_el = await card.query_selector(sel)
            if snippet_el:
                desc = (await snippet_el.inner_text()).strip()
                if desc:
                    break
        # Salary
        salary_el = await card.query_selector("div.salary-snippet-container, span.estimated-salary")
        salary = (await salary_el.inner_text()).strip() if salary_el else None
        # Posted date: Indeed shows relative dates like "Posted 3 days ago"
        posted_date = None
        date_el = await card.query_selector("span.date, span[data-testid='myJobsStateDate']")
        if date_el:
            raw_date = (await date_el.inner_text()).strip()
            posted_date = raw_date if raw_date else None
        return RawJob(
            source=self.name,
            title=title,
            company=company,
            url=url,
            location=location,
            salary=salary,
            description=desc,
            posted_date=posted_date,
            tags=[keyword],
        )