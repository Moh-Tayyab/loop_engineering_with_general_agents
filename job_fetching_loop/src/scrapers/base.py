"""Base scraper interfaces — BaseScraper contract and BoardScraper engine."""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Iterator, Sequence

from src import config as cfg
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

log = get_logger(__name__)


class BaseScraper(ABC):
    """Abstract base for all job sources."""

    name: str  # "linkedin", "indeed", etc.
    active_domain: str | None = None

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


class BoardScraper(BaseScraper, ABC):
    """Deep parent for Playwright-driven job boards (Indeed, Glassdoor).

    Owns the shared browser automation lifecycle:
    - Domain rebuild from registry / active_domain
    - Persistent profile browser launch & closed-page recovery
    - Human-like homepage warm-up
    - Anti-bot CAPTCHA challenge detection & interactive solving
    - Multi-page pagination loop
    - Selector drift detection (0 cards on first page with large body)
    - Card parsing and error resilience (partial collection preserved)

    Subclasses provide selector tables, URL templates, and card parsing hooks.
    """

    _BASE: str
    _HOME: str
    _SEARCH: str

    def is_available(self) -> bool:
        return True

    def _apply_domain(self) -> None:
        """Phase 2 (A2): rebuild URL bases from active_domain or first registry domain."""
        domains = cfg.source_domains(self.name)
        domain = self.active_domain or (domains[0] if domains else None)
        if not domain:
            return
        base = f"https://{domain}"
        self._BASE = base
        self._HOME = base + "/"
        self._build_search_template(base)

    def _build_search_template(self, base: str) -> None:
        """Subclass hook to format self._SEARCH with the chosen base."""
        pass

    def fetch(self, keywords: list[str], posted_after: datetime) -> Iterator[RawJob]:
        self._apply_domain()
        yield from asyncio.run(self._gather(keywords, posted_after))

    async def _gather(self, keywords: list[str], posted_after: datetime) -> list[RawJob]:
        jobs: list[RawJob] = []
        try:
            async for j in self._fetch_async(keywords, posted_after):
                jobs.append(j)
        except (CaptchaDetected, CaptchaTimeout):
            raise
        except Exception as e:
            log.warning("[%s] fetch aborted early (%s), keeping %d collected jobs", self.name, e, len(jobs))
        return jobs

    def pagination_sequence(self) -> Sequence[Any]:
        """Sequence of pagination values (offsets or page numbers)."""
        raise NotImplementedError

    def _page_log_label(self, val: Any) -> str:
        return f"page={val}"

    def nav_timeout_ms(self) -> int:
        return 45_000

    @abstractmethod
    def _search_url(self, keyword: str, days: int, page_val: Any) -> str:
        ...

    @abstractmethod
    async def _apply_search_filters_ui(self, page: Any, days: int = 1) -> None:
        ...

    @abstractmethod
    async def _query_cards(self, page: Any) -> list[Any]:
        ...

    @abstractmethod
    async def _parse_card(self, card: Any, keyword: str, days: int = 1, page: Any = None) -> RawJob | None:
        ...

    async def _fetch_async(self, keywords: list[str], posted_after: datetime) -> AsyncIterator[RawJob]:
        diff_days = (datetime.now(timezone.utc) - posted_after).total_seconds() / 86400.0
        days = 1 if diff_days <= 1.25 else max(1, min(14, round(diff_days)))
        any_success = False
        errors: list[Exception] = []

        async with launch_browser(self.name, persistent=True, headless=cfg.board_headless()) as context:
            page = await context.new_page()
            try:
                await warm_up(page, self._HOME, self.name)
            except (CaptchaDetected, CaptchaTimeout):
                raise
            except Exception as e:
                log.debug("[%s] warm_up non-fatal error: %s", self.name, e)

            for kw in keywords:
                for page_idx, page_val in enumerate(self.pagination_sequence()):
                    url = self._search_url(kw, days, page_val)
                    log.info("[%s] searching %r (%s) ...", self.name, kw, self._page_log_label(page_val))
                    try:
                        if hasattr(page, "is_closed") and page.is_closed():
                            page = context.pages[-1] if (context.pages and not context.pages[-1].is_closed()) else await context.new_page()
                        try:
                            await page.goto(url, timeout=self.nav_timeout_ms(), wait_until="domcontentloaded")
                        except Exception as goto_err:
                            log.debug("[%s] page.goto note: %s", self.name, goto_err)

                        if await has_captcha(page):
                            if not await await_captcha_solve(page, self.name, page.url, cfg.captcha_solve_timeout()):
                                raise CaptchaTimeout(self.name, page.url, cfg.captcha_solve_timeout())
                        await check_captcha(page, self.name)
                        any_success = True
                        await human_scroll(page)
                        await human_delay(1.5, 3.5)

                        # UI filters on first page of every keyword
                        if page_idx == 0:
                            await self._apply_search_filters_ui(page, days)
                            await human_scroll(page)
                            await human_delay(1.0, 2.0)

                        cards = await self._query_cards(page)
                        log.info("[%s] %r (%s): found %d card(s)", self.name, kw, self._page_log_label(page_val), len(cards))

                        # B5: loaded page, 0 cards on page 1 -> selector drift
                        if not cards and page_idx == 0:
                            body_len = 0
                            try:
                                body_len = len(await page.content())
                            except Exception:
                                pass
                            if body_len > 5000:
                                errors.append(RuntimeError(
                                    f"parse_drift: {self.name.title()} page loaded ({body_len} bytes) but 0 cards for {kw!r}"
                                ))

                        for card in cards:
                            job = await self._parse_card(card, kw, days, page=page)
                            if job:
                                yield job

                        if not cards:
                            break

                        await human_delay(3.0, 6.0)
                    except (CaptchaDetected, CaptchaTimeout):
                        raise
                    except Exception as e:
                        errors.append(e)
                        log.warning("[%s] error scraping %r: %s", self.name, kw, e)
                        break

            await page.close()

        if not any_success and errors:
            raise errors[0]