"""Glassdoor (glassdoor.com) scraper — salary data available, aggressive anti-bot.

Strategy (human-in-the-loop CAPTCHA):
  1. Persistent, headed, system-Chrome profile → solved CAPTCHAs and session
     cookies persist in `.runtime/glassdoor-profile/`.
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
class GlassdoorScraper(BaseScraper):
    name = "glassdoor"

    _BASE = "https://www.glassdoor.com"
    _HOME = "https://www.glassdoor.com/"
    _SEARCH = "https://www.glassdoor.com/Job/jobs.htm?sc.keyword={kw}&locT=&locId=&locKeyword=Remote&jobType=&fromAge={days}"

    def is_available(self) -> bool:
        return True

    def fetch(self, keywords: list[str], posted_after: datetime) -> Iterator[RawJob]:
        yield from asyncio.run(self._gather(keywords, posted_after))

    async def _gather(self, keywords, posted_after) -> list:
        return [j async for j in self._fetch_async(keywords, posted_after)]

    async def _fetch_async(self, keywords: list[str], posted_after: datetime) -> Iterator[RawJob]:
        days = max(1, min(14, int((datetime.now(timezone.utc) - posted_after).total_seconds() / 86400) + 1))
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
                        await page.goto(url, timeout=30_000, wait_until="domcontentloaded")
                    await check_captcha(page, self.name)
                    await human_scroll(page)
                    await human_delay(2.0, 5.0)
                    cards = await page.query_selector_all("li.JobsList_jobListItem__wjTHv, li[data-test='jobListing'], li.job-card")
                    for card in cards:
                        job = await self._parse_card(card, kw)
                        if job:
                            yield job
                    await human_delay(3.0, 6.0)
                except (CaptchaDetected, CaptchaTimeout):
                    raise
                except Exception as e:
                    log.warning("[glassdoor] error scraping %r: %s", kw, e)
            await page.close()

    async def _parse_card(self, card, keyword: str) -> RawJob | None:
        title_el = await card.query_selector("a[data-test='job-title'], a.JobCard_jobTitle__GLyJ1, a.jobTitle")
        if not title_el:
            return None
        title = (await title_el.inner_text()).strip()
        href = await title_el.get_attribute("href") or ""
        url = self._BASE + href if href.startswith("/") else href
        # Company: try multiple selector patterns (Glassdoor A/B tests heavily)
        company = "Unknown"
        for sel in (
            "span.EmployerProfile_compactEmployerName__LE242",
            "a.employerName",
            "span.employerName",
            "div.EmployerProfile_employerInfo__GaPbq a",
            "a[data-test='employer-short-name']",
            "span[class*='EmployerName']",
        ):
            el = await card.query_selector(sel)
            if el:
                company = (await el.inner_text()).strip()
                if company and company != "Unknown":
                    break
        location_el = await card.query_selector("div[data-test='emp-location'], span.JobCard_location__rCz3x, span[data-test='job-location']")
        location = (await location_el.inner_text()).strip() if location_el else None
        salary_el = await card.query_selector("div.JobCard_salaryEstimate__arV5J, span.salary, span[data-test='attribute_snippet_testid']")
        salary = (await salary_el.inner_text()).strip() if salary_el else None
        # Description: Glassdoor cards show a short snippet
        desc = None
        for sel in ("div.JobCard_jobDescription__v_1k2", "p[data-test='jobDescriptionText']", "div.jobDescription"):
            desc_el = await card.query_selector(sel)
            if desc_el:
                desc = (await desc_el.inner_text()).strip()
                if desc:
                    break
        # Posted date
        posted_date = None
        date_el = await card.query_selector("div[data-test='job-age'], span[data-test='job-age']")
        if date_el:
            posted_date = (await date_el.inner_text()).strip() or None
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