"""Glassdoor (glassdoor.com) scraper — salary data available, aggressive anti-bot.

Strategy (human-in-the-loop CAPTCHA):
  1. Persistent, headed, system-Chrome profile (headless=cfg.board_headless()) →
     solved CAPTCHAs and session cookies persist in `.runtime/glassdoor-profile/`.
  2. Warm up on the homepage first (human-like), then search.
  3. When a Cloudflare/hCaptcha challenge appears the browser stays OPEN —
     the human solves it once in the visible window (`await_captcha_solve`),
     and every later run reuses the saved session.
  4. Longer variable delays (human cadence).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Iterator

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
from .base import BoardScraper

log = get_logger(__name__)


@register_scraper
class GlassdoorScraper(BoardScraper):
    name = "glassdoor"

    _BASE = "https://www.glassdoor.com"
    _HOME = "https://www.glassdoor.com/"
    _SEARCH = "https://www.glassdoor.com/Job/jobs.htm?sc.keyword={kw}&locT=&locId=&locKeyword=Remote&jobType=&fromAge={days}"
    # Beat 171 (owner: worldwide fully-remote MAXIMUM jobs): deep pagination.
    _PAGES = (1, 2, 3, 4, 5)

    def _build_search_template(self, base: str) -> None:
        self._SEARCH = base + "/Job/jobs.htm?sc.keyword={kw}&locT=&locId=&locKeyword=Remote&jobType=&fromAge={days}"

    def pagination_sequence(self) -> tuple[int, ...]:
        return self._PAGES

    def _page_log_label(self, val: Any) -> str:
        return f"page {val}/3"

    def nav_timeout_ms(self) -> int:
        return 45_000

    def _search_url(self, keyword: str, days: int, page_no: int = 1) -> str:
        """Search URL with the Beat-164 backstop baked in: `fromAge` (last-day
        window), `locKeyword=Remote` (worldwide remote), and `easyApplyOnly`
        only when `EASY_APPLY_ONLY=1` (owner removed the Easy Apply filter).
        """
        from urllib.parse import quote_plus
        ea_filter = "&easyApplyOnly=true" if cfg.easy_apply_only() else ""
        return (
            self._SEARCH.format(kw=quote_plus(keyword), days=days) + ea_filter
            + f"&page={page_no}"
        )

    async def _query_cards(self, page: Any) -> list[Any]:
        cards = []
        for _ in range(6):
            cards = await page.query_selector_all(
                "li[data-test='jobListing'], article[data-test='job-listing-card'], "
                "li.JobsList_jobListItem__wjTHv, li.job-card, div[data-test='job-card']"
            )
            if cards:
                break
            await asyncio.sleep(1.0)
        return cards

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

    async def _apply_search_filters_ui(self, page, days: int = 1) -> None:
        """Beat 164 (owner): per-keyword UI filters — Date posted (last day) +
        Remote only, then the 'Apply filters' button.

        Best-effort with fallback selectors: the search URL already carries
        `fromAge` + `locKeyword=Remote` as a backstop, so a missing/renamed
        button degrades to URL-level filtering, never to a crash.
        Only called on page 1 of each keyword (filters persist across pages).
        """
        try:
            await self._apply_date_filter_ui(page, days)
            # Beat 167 (checker MINOR #1): stable hooks first — a page-wide
            # text selector can hit decoys (job-pane "Apply now"), so
            # `[data-test]` leads and the bare 'Apply' fallback is gone
            # (exact `:text-is` only, still exception-safe if unsupported).
            for label, sels in (
                ("remote-only", [
                    "[data-test*='remote']",
                    "button:has-text('Remote only')",
                    "button:has-text('Remote Only')",
                    "label:has-text('Remote only')",
                ]),
            ):
                clicked = False
                for sel in sels:
                    try:
                        el = await page.query_selector(sel)
                        if el and await el.is_visible():
                            await human_click(page, el)
                            await asyncio.sleep(1.0)
                            log.info("[glassdoor] clicked UI filter: %s (%s)", label, sel)
                            clicked = True
                            break
                    except Exception:
                        continue
                if not clicked:
                    log.debug("[glassdoor] UI filter not found (URL backstop holds): %s", label)
            # "Apply filters" — commits the panel; absent on auto-apply layouts.
            # Beat 167: exact `:text-is('Apply')` instead of substring
            # `:has-text('Apply')` so a job "Apply now" button never matches.
            for sel in (
                "button:has-text('Apply filters')",
                "button:has-text('Apply Filters')",
                "[data-test*='apply-filter']",
                "button:text-is('Apply')",
            ):
                try:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        await human_click(page, el)
                        await asyncio.sleep(2.0)
                        log.info("[glassdoor] clicked Apply filters (%s)", sel)
                        break
                except Exception:
                    continue
        except Exception as e:
            log.debug("[glassdoor] UI search filters failed (URL backstop holds): %s", e)

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
            url = f"{self._BASE}/job-listing/?jl={m.group(1)}"
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

        # Beat 164 (owner): read the FULL description of EVERY card — click it
        # open, expand "Show more", take the right-pane JD. Snippet stays as
        # the fallback so a slow/changed pane never drops the job. Fetch-vs-skip
        # stays downstream (matcher + Rule 11); here we just stop flying blind.
        if page and title_el:
            try:
                await human_click(page, title_el)
                await human_read_pause(0.5, 1.5)
                try:
                    more = await page.query_selector(
                        "div.JobDetails_jobDescription__uWshU button:has-text('Show more'), "
                        "div[data-test='job-description'] button:has-text('Show more')"
                    )
                    if more and await more.is_visible():
                        await human_click(page, more)
                        await asyncio.sleep(0.8)
                except Exception:
                    pass
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
                # A2 (PR #13 nit): NEVER invent "Remote" when the location
                # element is missing — same fail-closed contract as Indeed.
                # Leave None → domestic-board / unknown-location gates drop it.
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
                # No badge → None (strict 24h fail-closed); never invent a date.
            except Exception:
                posted_date = None
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