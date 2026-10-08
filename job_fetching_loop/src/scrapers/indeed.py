"""Indeed (indeed.com) scraper — worldwide remote, aggressive anti-bot.

Strategy (human-in-the-loop CAPTCHA):
  1. Persistent, headed, system-Chrome profile (headless=cfg.board_headless()) →
     solved CAPTCHAs and session cookies persist in `.runtime/indeed-profile/`.
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
class IndeedScraper(BoardScraper):
    name = "indeed"

    _BASE = "https://pk.indeed.com"
    _HOME = "https://pk.indeed.com/"
    _SEARCH = "https://pk.indeed.com/jobs?q={kw}&l=Remote&fromage={days}"
    # Beat 171 (owner: worldwide fully-remote MAXIMUM jobs): deep pagination.
    _STARTS = (0, 10, 20, 30, 40)

    # Indeed's remote-only search facet: jobs whose location attribute is
    # remote (`attr(DSQF7)`). Combined with `l=Remote` so both the query and
    # the facet enforce worldwide-remote (Beat 165 parity with Glassdoor).
    _REMOTE_FACET = "&sc=0kf%3Aattr%28DSQF7%29%3B"

    def _build_search_template(self, base: str) -> None:
        self._SEARCH = base + "/jobs?q={kw}&l=Remote&fromage={days}"

    def pagination_sequence(self) -> tuple[int, ...]:
        return self._STARTS

    def _page_log_label(self, val: Any) -> str:
        return f"start={val}"

    def nav_timeout_ms(self) -> int:
        return 30_000

    def _search_url(self, keyword: str, days: int, start: int = 0) -> str:
        """Search URL with the Beat-165 backstop baked in: `fromage` (last-day
        window), `l=Remote` + remote-only facet, and `iaFilter` (Easy Apply)
        only when `EASY_APPLY_ONLY=1` (owner removed the Easy Apply filter).
        """
        from urllib.parse import quote_plus
        ia_filter = "&iaFilter=1" if cfg.easy_apply_only() else ""
        return (
            self._SEARCH.format(kw=quote_plus(keyword), days=days) + ia_filter
            + self._REMOTE_FACET + f"&start={start}"
        )

    async def _query_cards(self, page: Any) -> list[Any]:
        cards = await page.query_selector_all("div.cardOutline, div.job_seen_beacon, div.jobsearch-SerpJobCard")
        if not cards:
            cards = await page.query_selector_all("td.resultContent")
        return cards

    async def _apply_search_filters_ui(self, page, days: int = 1) -> None:
        """Beat 165 (owner): per-keyword UI filters — Date posted (last 24h)
        + Remote facet, mirroring the Glassdoor beat-164 flow.

        Best-effort with fallback selectors: the search URL already carries
        `fromage` + `l=Remote` + the remote-only facet as a backstop, so a
        missing/renamed control degrades to URL-level filtering, never to a
        crash. Only called on the first page of each keyword.
        """
        try:
            # Date posted → "Last 24 hours" (daily) else "Last 3 days".
            try:
                btn = await page.query_selector(
                    "#filter-dateposted button, button:has-text('Date posted'), "
                    "[data-testid='filter-dateposted'] button, #filter-dateposted"
                )
                if btn and await btn.is_visible():
                    await human_click(page, btn)
                    await asyncio.sleep(0.8)
                    want = "24 hours" if days <= 1 else "3 days"
                    opt = await page.query_selector(
                        f"#filter-dateposted li:has-text('{want}'), "
                        f"[role='option']:has-text('{want}'), "
                        f"li:has-text('Last {want}')"
                    )
                    if opt and await opt.is_visible():
                        await human_click(page, opt)
                        await asyncio.sleep(1.5)
                        log.info("[indeed] clicked UI date filter (days=%d)", days)
            except Exception as e:
                log.debug("[indeed] UI date filter click failed: %s", e)
            # Remote facet chip (URL facet is the backstop).
            # Beat 167 (checker MINOR #1): stable `[data-testid]` hook first —
            # page-wide text selectors can hit decoy links, so the hook leads.
            for sel in (
                "[data-testid*='remote']",
                "a:has-text('Remote')",
                "button:has-text('Remote')",
                "li:has-text('Remote')",
            ):
                try:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        await human_click(page, el)
                        await asyncio.sleep(1.5)
                        log.info("[indeed] clicked UI remote filter (%s)", sel)
                        break
                except Exception:
                    continue
        except Exception as e:
            log.debug("[indeed] UI search filters failed (URL backstop holds): %s", e)

    async def _parse_card(self, card, keyword: str, days: int = 1, page: Any = None) -> RawJob | None:
        title_el = await card.query_selector("h2.jobTitle a, a.jcs-JobTitle, h2.jobTitle span, h2 a")
        if not title_el:
            return None
        title = (await title_el.get_attribute("title") or await title_el.inner_text()).strip()
        if not title:
            return None
        href = await title_el.get_attribute("href") or ""
        jk = await card.get_attribute("data-jk") or await title_el.get_attribute("data-jk")
        if not jk and href:
            import re
            m = re.search(r"[?&]jk=([a-fA-F0-9]+)", href)
            if m:
                jk = m.group(1)
        if jk:
            url = f"{self._BASE}/viewjob?jk={jk}"
        else:
            url = self._BASE + href if href.startswith("/") else href
        company_el = await card.query_selector("span[data-testid='company-name'], span.companyName, a[data-testid='company-name'], [data-testid='company-name']")
        company = (await company_el.inner_text()).strip() if company_el else "Unknown"
        location_el = await card.query_selector("div[data-testid='text-location'], div.companyLocation, span[data-testid='text-location'], [data-testid='text-location']")
        location = (await location_el.inner_text()).strip() if location_el else None
        # Description: try job-snippet, then shelf, then table fallback, then card inner text
        desc = None
        for sel in ("div.job-snippet", "table.jobCardShelfContainer td", "div.jobsearch-SerpJobCard-snippet", "ul.css-9446fg", "div.css-10pe3me"):
            snippet_el = await card.query_selector(sel)
            if snippet_el:
                desc = (await snippet_el.inner_text()).strip()
                if desc:
                    break
        card_text = ""
        if not desc:
            try:
                card_text = await card.inner_text()
                lines = [l.strip() for l in card_text.splitlines() if l.strip()]
                desc = " ".join(lines[3:]) if len(lines) > 3 else card_text
            except Exception:
                pass
        try:
            card_text = await card.inner_text()
        except Exception:
            pass

        # Beat 165 (owner, Glassdoor-164 parity): read the FULL description of
        # EVERY card — click it open, take the right-pane JD. Snippet stays as
        # the fallback so a slow/changed pane never drops the job. Fetch-vs-skip
        # stays downstream (matcher + Rule 11); here we just stop flying blind.
        if page and title_el:
            try:
                await human_click(page, title_el)
                await human_read_pause(0.5, 1.5)
                full_desc_el = await page.query_selector("#jobDescriptionText, div.jobsearch-jobDescriptionText")
                if full_desc_el:
                    full_text = (await full_desc_el.inner_text()).strip()
                    if full_text and len(full_text) > len(desc or ""):
                        desc = full_text[:3500]
            except Exception:
                pass

        # Remote detection: on pk.indeed.com with l=Remote, preserve Remote location
        comb = f"{card_text} {desc or ''}".lower()
        if not any(w in comb for w in ("hybrid", "onsite", "on-site", "in-office", "office-based")):
            if any(w in comb for w in ("remote", "work from home", "wfh")):
                if location and "remote" not in location.lower():
                    location = f"{location} (Remote)"
                # A2: NEVER invent "Pakistan (Remote)" when the location element is
                # missing — that string is an in-scope marker that bypasses the
                # US-domestic-board gate. Leave None → fail-closed drop downstream.
        # Salary
        salary_el = await card.query_selector("div.salary-snippet-container, span.estimated-salary, div.metadata.salary-snippet-container, [data-testid='attribute_snippet_testid']")
        salary = (await salary_el.inner_text()).strip() if salary_el else None
        # Posted date: Indeed shows relative dates like "Posted 3 days ago", "Just posted", "Active today"
        posted_date = None
        date_el = await card.query_selector("span.date, span[data-testid='myJobsStateDate'], span[class*='myJobsStateDate'], span.css-10pe3me")
        if date_el:
            raw_date = (await date_el.inner_text()).strip()
            if raw_date:
                import re
                cleaned = re.sub(r"^(?:employer\s+active|active|posted)\s+", "", raw_date, flags=re.IGNORECASE).strip()
                posted_date = cleaned or raw_date

        if not posted_date:
            try:
                card_text = await card.inner_text()
                import re
                m = re.search(r"\b(just posted|active today|posted today|today|\d+\s+days?\s+ago|\d+d\b)", card_text, re.IGNORECASE)
                if m:
                    posted_date = m.group(1).strip()
                # A11: no badge → None (strict 24h fail-closed in main). Do NOT
                # fabricate "today"/"N days ago" — that defeats the recency gate.
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