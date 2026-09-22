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
    human_click,
    human_delay,
    human_hover,
    human_read_pause,
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
        diff_days = (datetime.now(timezone.utc) - posted_after).total_seconds() / 86400.0
        days = 1 if diff_days <= 1.25 else max(1, min(14, round(diff_days)))
        any_success = False
        errors: list[Exception] = []
        async with launch_browser(self.name, persistent=True, headless=cfg.board_headless()) as context:
            page = await context.new_page()
            for kw in keywords:
                from urllib.parse import quote_plus
                ea_filter = "&easyApplyOnly=true" if cfg.easy_apply_only() else ""
                url = self._SEARCH.format(kw=quote_plus(kw), days=days) + ea_filter
                try:
                    try:
                        await page.goto(url, timeout=45_000, wait_until="domcontentloaded")
                    except Exception as goto_err:
                        log.debug("[glassdoor] page.goto warning: %s", goto_err)
                    if await has_captcha(page):
                        if not await await_captcha_solve(page, self.name, page.url, cfg.captcha_solve_timeout()):
                            raise CaptchaTimeout(self.name, page.url, cfg.captcha_solve_timeout())
                    any_success = True
                    await human_scroll(page)
                    await human_delay(1.5, 3.5)
                    cards = []
                    for _ in range(6):
                        cards = await page.query_selector_all("li[data-test='jobListing'], article[data-test='job-listing-card'], li.JobsList_jobListItem__wjTHv, li.job-card, div[data-test='job-card']")
                        if cards:
                            break
                        await asyncio.sleep(1.0)
                    for card in cards:
                        job = await self._parse_card(card, kw, days, page=page)
                        if job:
                            yield job
                    await human_delay(3.0, 6.0)
                except (CaptchaDetected, CaptchaTimeout):
                    raise
                except Exception as e:
                    errors.append(e)
                    log.warning("[glassdoor] error scraping %r: %s", kw, e)
            await page.close()
        if not any_success and errors:
            raise errors[0]

    async def _apply_date_filter_ui(self, page, days: int = 1) -> None:
        """Click 'Date posted' -> 'Past 24 hours' or 'Past 3 days' in Glassdoor's UI when available."""
        try:
            btn = await page.query_selector("button[data-test='fromAge'], [data-test='filter-fromAge'], button:has-text('Date posted'), button:has-text('Date Posted')")
            if btn:
                await human_click(page, btn)
                await asyncio.sleep(0.8)
                if days <= 1:
                    opt = await page.query_selector("li:has-text('24 hours'), [role='option']:has-text('24 hours'), [role='menuitem']:has-text('24 hours'), li:has-text('Past Day'), li:has-text('Past 24 Hours')")
                else:
                    opt = await page.query_selector("li:has-text('3 days'), [role='option']:has-text('3 days'), [role='menuitem']:has-text('3 days'), li:has-text('Past 3 days'), li:has-text('Past 3 Days')")
                if opt:
                    await human_click(page, opt)
                    await asyncio.sleep(1.5)
                    log.info("[glassdoor] successfully clicked date filter in UI (days=%d)", days)
        except Exception as e:
            log.debug("[glassdoor] UI date filter click failed: %s", e)

    async def _parse_card(self, card, keyword: str, days: int = 1, page: Any = None) -> RawJob | None:
        title_el = await card.query_selector("a[data-test='job-title'], a.JobCard_jobTitle__GLyJ1, a.jobTitle, [data-test='job-title']")
        if not title_el:
            return None
        title = (await title_el.inner_text()).strip()
        if not title:
            return None
        href = await title_el.get_attribute("href") or ""
        import re
        m = re.search(r"[?&](?:jl|jobListingId)=(\d+)", href)
        if m:
            url = f"https://www.glassdoor.com/job-listing/?jl={m.group(1)}"
        else:
            url = self._BASE + href if href.startswith("/") else href
        # Company: try multiple selector patterns (Glassdoor A/B tests heavily)
        company = "Unknown"
        for sel in (
            "span.EmployerProfile_compactEmployerName__LE242",
            "a.employerName",
            "span.employerName",
            "div.EmployerProfile_employerInfo__GaPbq a",
            "a[data-test='employer-short-name']",
            "span[data-test='employer-short-name']",
            "span[class*='EmployerName']",
        ):
            el = await card.query_selector(sel)
            if el:
                company = (await el.inner_text()).strip()
                if company and company != "Unknown":
                    break
        location_el = await card.query_selector("div[data-test='emp-location'], span.JobCard_location__rCz3x, span[data-test='job-location'], [data-test='emp-location']")
        location = (await location_el.inner_text()).strip() if location_el else None
        salary_el = await card.query_selector("div.JobCard_salaryEstimate__arV5J, span.salary, span[data-test='attribute_snippet_testid'], [data-test='detailSalary']")
        salary = (await salary_el.inner_text()).strip() if salary_el else None
        # Description: Glassdoor cards show a short snippet
        desc = None
        for sel in ("div.JobCard_jobDescription__v_1k2", "p[data-test='jobDescriptionText']", "div.jobDescription", "[data-test='descSnippet']"):
            desc_el = await card.query_selector(sel)
            if desc_el:
                desc = (await desc_el.inner_text()).strip()
                if desc:
                    break

        card_text = ""
        if not desc:
            try:
                card_text = await card.inner_text()
                lines = [l.strip() for l in card_text.splitlines() if l.strip()]
                desc = " ".join(lines[2:]) if len(lines) > 2 else card_text
            except Exception:
                pass
        try:
            card_text = await card.inner_text()
        except Exception:
            pass

        # Try reading full description from right pane if card matches profile
        if page and title_el:
            try:
                from src.matcher import match_usama_cv
                is_match, _, _ = match_usama_cv(title, description=desc)
                if is_match:
                    await title_el.click()
                    await asyncio.sleep(0.5)
                    full_desc_el = await page.query_selector("div.JobDetails_jobDescription__uWshU, div[data-test='job-description'], div#JobDescriptionContainer")
                    if full_desc_el:
                        full_text = (await full_desc_el.inner_text()).strip()
                        if full_text and len(full_text) > len(desc or ""):
                            desc = full_text[:3500]
            except Exception:
                pass

        comb = f"{card_text} {desc or ''}".lower()
        if not any(w in comb for w in ("hybrid", "onsite", "on-site", "in-office", "office-based")):
            if any(w in comb for w in ("remote", "work from home", "wfh")):
                if location and "remote" not in location.lower():
                    location = f"{location} (Remote)"
                elif not location:
                    location = "Remote"
        # Posted date: "24h", "1d", "30d+", "Just now", etc.
        posted_date = None
        date_el = await card.query_selector("div[data-test='job-age'], span[data-test='job-age'], div.JobCard_listingAge__jJsuc, [data-test='job-age']")
        if date_el:
            raw_date = (await date_el.inner_text()).strip()
            if raw_date:
                posted_date = raw_date

        if not posted_date:
            try:
                card_text = await card.inner_text()
                import re
                m = re.search(r"\b(just now|today|\d+h\b|\d+d\b|\d+\s+hours?\s+ago|\d+\s+days?\s+ago)", card_text, re.IGNORECASE)
                if m:
                    posted_date = m.group(1).strip()
                else:
                    # Glassdoor search is filtered by `fromAge={days}`; if no badge is shown, it falls in window
                    posted_date = "today" if days <= 1 else f"{days}d"
            except Exception:
                posted_date = "today" if days <= 1 else f"{days}d"
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