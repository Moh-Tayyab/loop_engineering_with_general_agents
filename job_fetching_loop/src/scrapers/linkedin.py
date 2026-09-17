"""LinkedIn scraper — two surfaces behind a login-gated session.

1. Jobs board (linkedin.com/jobs/search): structured job cards.
2. Hiring FEED POSTS (linkedin.com/search/content/all): the status updates
   where people announce "we're hiring an ML engineer" — an unofficial but
   large channel. Each such post is mapped to a RawJob (title = headline or
   first sentence, company = author, url = update permalink).

Both are login-gated and the most anti-bot-protected surface. This scraper:
  1. Requires a manually authenticated session (--linkedin-login first)
  2. Uses the persistent profile dir for session reuse
  3. Detects CAPTCHA immediately and escalates
  4. Uses longer delays between requests (3-5s)
The feed pass is fully guarded: a feed markup drift logs and skips instead of
failing the whole source after the jobs board already succeeded.
"""
from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timezone
from typing import Any, Iterator
from urllib.parse import quote_plus

import src.config as cfg
from src.browser import CaptchaDetected, check_captcha, launch_browser, polite_delay
from src.log import get_logger

log = get_logger(__name__)
from src.models import RawJob, utc_now
from . import register_scraper
from .base import BaseScraper


def _feed_queries(keywords: list[str], weekday: int) -> list[str]:
    """Hiring-feed search phrases per keyword.

    Mon-Thu: plain keyword feed search. Friday is the spec'd LinkedIn feed day
    ("scrape and fetch posts directly from the LinkedIn feed containing 'we are
    hiring' keywords/scenes"), so Friday ADDS two hiring-scene phrases per
    keyword (#hiring <kw>, "we are hiring" <kw>). Overlap between plain and
    phrased searches is clipped by URL dedup in _scrape_feed_posts.
    """
    queries: list[str] = []
    for kw in keywords:
        queries.append(kw)
        if weekday == 4:
            queries.append(f"#hiring {kw}")
            queries.append(f'"we are hiring" {kw}')
    return queries


def _post_location(text: str | None) -> str:
    """Location guess for a hiring feed post (which has no structured location).

    Heuristic (documented): remote markers win; explicit on-site/hybrid wording
    with no remote marker maps to Hybrid (rejected by SCRAPE_REMOTE_ONLY so it
    can't pollute the digest); otherwise default Remote — hiring posts are
    usually written location-agnostic ("looking for an ML engineer").
    """
    t = (text or "").lower()
    if any(w in t for w in ("remote", "wfh", "work from home", "work-from-home",
                            "anywhere", "worldwide", "location-agnostic")):
        return "Remote"
    if any(w in t for w in ("on-site", "onsite", "on site", "in-office", "in office",
                            "hybrid", "office-based", "at our office", "work from office")):
        return "Hybrid"
    return "Remote"


def _post_title(text: str, headline: str | None) -> str:
    """A compact title for a feed post: the actor headline when present
    (LinkedIn renders the author's "X is hiring..." line in it), else the first
    sentence/line of the post body. Capped so the title stays a title."""
    if headline and headline.strip():
        return headline.strip()[:140]
    body = (text or "").strip()
    if not body:
        return "Hiring"
    for sep in ("\n", ". "):
        part = body.split(sep, 1)[0].strip()
        if part:
            return part[:140]
    return body[:140] or "Hiring"


def _feed_post_to_raw(post: dict[str, Any], kw: str,
                      posted_after: datetime | None = None) -> RawJob | None:
    """Map a scraped feed-post dict to a RawJob, skipping posts outside the
    fetch window when a parseable posted-date is present (no date → keep: the
    TTL dedup layer handles re-scrapes)."""
    text = (post.get("text") or "").strip()
    url = (post.get("url") or "").strip()
    if not text or not url:
        return None

    posted = (post.get("posted") or "")[:10]
    if posted_after is not None and posted:
        try:
            if date.fromisoformat(posted) < posted_after.date():
                return None
        except ValueError:
            pass  # relative date text ("2d") — can't filter, keep

    return RawJob(
        source="linkedin",
        title=_post_title(text, post.get("headline")),
        company=(post.get("author") or "").strip() or "Unknown",
        url=url,
        location=_post_location(text),
        posted_date=posted or None,
        description=text[:2000],
        tags=[kw],
    )


@register_scraper
class LinkedInScraper(BaseScraper):
    name = "linkedin"

    _BASE = "https://www.linkedin.com"
    _SEARCH = "https://www.linkedin.com/jobs/search/?keywords={kw}&f_WT=2&location=Worldwide"
    _FEED = "https://www.linkedin.com/search/content/all/?origin=GLOBAL_SEARCH_HEADER&keywords={kw}"

    def login_required(self) -> bool:
        # Graceful degradation: if no authenticated session exists, fallback to
        # public guest search instead of skipping the source entirely.
        return False

    def has_authenticated_session(self) -> bool:
        marker = cfg.RUNTIME_DIR / ".linkedin-session"
        profile = cfg.RUNTIME_DIR / "linkedin-profile"
        return marker.exists() and profile.exists() and any(profile.iterdir())

    def is_available(self) -> bool:
        return True

    def fetch(self, keywords: list[str], posted_after: datetime) -> Iterator[RawJob]:
        # Primary high-reliability collector: LinkedIn public guest search (fast, zero CAPTCHA, canonical URLs)
        yield from self._fetch_guest_public(keywords, posted_after)

        # Secondary: authenticated feed pass (only if explicitly enabled or non-cron)
        if self.has_authenticated_session() and cfg.linkedin_feed_enabled() and os.environ.get("LINKEDIN_FEED_PASS", "0") == "1":
            try:
                yield from asyncio.run(asyncio.wait_for(
                    self._gather(keywords, posted_after),
                    timeout=cfg.linkedin_browser_timeout_s(),
                ))
            except BaseException as exc:
                log.warning("[linkedin] authenticated feed pass skipped (%s) — guest jobs preserved", exc)

    @classmethod
    def _fetch_guest_public(cls, keywords: list[str], posted_after: datetime) -> Iterator[RawJob]:
        """Scrape LinkedIn public guest endpoint (no login required, high yield).

        Bounded internally: 13 keywords × 2 locations is up to 26 sequential
        requests; if LinkedIn throttles (each request can stall up to its 15s
        timeout) an unbounded pass can eat 390s and starve the whole source.
        A monotonic deadline (cfg.linkedin_guest_timeout_s(), 45s) yields what
        was already collected and stops, leaving room for the browser pass.
        """
        import html
        import re
        from time import monotonic

        import requests

        seen_urls: set[str] = set()
        deadline = monotonic() + cfg.linkedin_guest_timeout_s()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        seconds = int(max(86400, (utc_now() - posted_after).total_seconds()))
        tpr_param = f"r{seconds}"
        any_success = False
        errors: list[Exception] = []
        for kw in keywords:
            if monotonic() > deadline:
                log.info("[linkedin] guest pass budget exhausted — stopping (kept %d collected jobs)",
                         len(seen_urls))
                break
            for loc_query in ("Worldwide", "Pakistan"):
                if monotonic() > deadline:
                    log.info("[linkedin] guest pass budget exhausted — stopping (kept %d collected jobs)",
                             len(seen_urls))
                    break
                remote_query = f"remote {kw}" if "remote" not in kw.lower() else kw
                url = (
                    f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?"
                    f"keywords={quote_plus(remote_query)}&location={loc_query}&f_WT=2&sortBy=DD&f_TPR={tpr_param}"
                )
                try:
                    r = requests.get(url, headers=headers, timeout=15)
                    if r.status_code != 200:
                        errors.append(requests.HTTPError(f"HTTP {r.status_code} from LinkedIn guest search", response=r))
                        continue
                    any_success = True
                    titles = re.findall(r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>\s*([^<]+?)\s*</h3>', r.text)
                    companies = re.findall(r'<h4[^>]*class="[^"]*base-search-card__subtitle[^"]*"[^>]*>\s*<a[^>]*>([^<]+?)</a>', r.text)
                    locations = re.findall(r'<span[^>]*class="[^"]*job-search-card__location[^"]*"[^>]*>\s*([^<]+?)\s*</span>', r.text)
                    links = re.findall(r'<a[^>]*class="[^"]*base-card__full-link[^"]*"[^>]*href="([^"]+)"', r.text)
                    dates = re.findall(r'<time[^>]*datetime="([^"]+)"', r.text)
                    for i in range(len(titles)):
                        if monotonic() > deadline:
                            break
                        title = html.unescape(titles[i].strip())
                        comp = html.unescape(companies[i].strip()) if i < len(companies) else "Unknown"
                        loc = html.unescape(locations[i].strip()) if i < len(locations) else "Remote"
                        raw_lnk = links[i].split("?")[0] if i < len(links) else ""
                        if not raw_lnk or raw_lnk in seen_urls:
                            continue
                        seen_urls.add(raw_lnk)

                        # Deep verification: ensure job is not expired and is genuinely remote
                        jid_m = re.search(r"-(\d+)$", raw_lnk)
                        if not jid_m:
                            continue
                        detail_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{jid_m.group(1)}"
                        try:
                            r2 = requests.get(detail_url, headers=headers, timeout=4)
                            if r2.status_code != 200 or "expired_jd_redirect" in r2.url:
                                log.debug("[linkedin] dropping expired/redirected: %s", raw_lnk)
                                continue
                            desc_m = re.search(r'<div class="show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>', r2.text, re.DOTALL)
                            real_desc = re.sub(r"<[^>]+>", " ", desc_m.group(1)).strip() if desc_m else f"{title} at {comp}"
                            full_check = f"{title.lower()} {loc.lower()} {real_desc.lower()}"
                            if any(w in full_check for w in ("no longer accepting applications", "this job is closed")):
                                log.debug("[linkedin] dropping closed posting: %s", title)
                                continue
                            if "hybrid" in full_check and "remote" not in full_check:
                                log.debug("[linkedin] dropping hybrid job: %s", title)
                                continue
                            if "on-site" in full_check and "remote" not in full_check:
                                log.debug("[linkedin] dropping on-site job: %s", title)
                                continue
                            if not any(w in full_check for w in ("remote", "work from home", "wfh", "telecommute", "anywhere")):
                                log.debug("[linkedin] dropping job without remote marker: %s", title)
                                continue
                        except Exception:
                            continue

                        posted = dates[i][:10] if i < len(dates) else None
                        yield RawJob(
                            source="linkedin",
                            title=title,
                            company=comp,
                            url=raw_lnk,
                            location=loc,
                            description=real_desc[:2500],
                            posted_date=posted,
                            tags=[kw],
                            fetched_at=utc_now(),
                        )
                except Exception as exc:
                    errors.append(exc)
                    log.info("[linkedin] guest public search failed (kw=%r, loc=%r): %s", kw, loc_query, exc)
        if not any_success and errors:
            raise errors[0]

    async def _gather(self, keywords, posted_after) -> list:
        return [j async for j in self._fetch_async(keywords, posted_after)]

    @staticmethod
    async def _scrape_feed_posts(page, query: str, posted_after: datetime) -> Iterator[RawJob]:
        """Content search for HIRING FEED POSTS ("we're hiring..." updates).

        Navigates the keyword content search and extracts posts in ONE
        page-context evaluate (LinkedIn's SPA destroys element handles across
        steps, so DOM access must happen in a single evaluate, same as the
        jobs board). Raise on CAPTCHA; the caller decides how to degrade.
        """
        feed_url = LinkedInScraper._FEED.format(kw=quote_plus(query))
        await page.goto(feed_url, timeout=45_000, wait_until="domcontentloaded")
        await check_captcha(page, LinkedInScraper.name)
        await asyncio.sleep(6)
        try:
            posts = await page.evaluate("""() => {
                const seen = new Map();
                const push = (url, rec) => { if (url && !seen.has(url)) seen.set(url, rec); };
                document.querySelectorAll(
                    ".feed-shared-update-v2, [data-urn*='activity']"
                ).forEach(el => {
                    let urn = el.getAttribute("data-urn") || "";
                    const a = el.querySelector("a[href*='/feed/update/'], a[href*='urn:li:activity']");
                    let url = "";
                    if (a && a.href) url = a.href.split("?")[0];
                    else if (urn) url = "https://www.linkedin.com/feed/update/" + urn;
                    if (!url) return;
                    const textEl = el.querySelector(
                        ".update-components-text, .feed-shared-inline-show-more-text, [class*='inline-show-more-text']"
                    );
                    const authorEl = el.querySelector(
                        ".update-components-actor__name, .feed-shared-actor__name, [class*='actor__name']"
                    );
                    const headlineEl = el.querySelector(
                        ".update-components-actor__sub-description, [class*='actor__sub-description'], [class*='actor__description']"
                    );
                    const timeEl = el.querySelector("time");
                    push(url, {
                        author: authorEl ? authorEl.innerText.trim() : "",
                        headline: headlineEl ? headlineEl.innerText.trim() : "",
                        text: textEl ? textEl.innerText.trim() : el.innerText.trim(),
                        posted: timeEl ? (timeEl.getAttribute("datetime") || timeEl.innerText.trim()) : "",
                        url,
                    });
                });
                return Array.from(seen.values());
            }""")
        except Exception:
            posts = []
        for p in posts:
            raw = _feed_post_to_raw(p, kw, posted_after)
            if raw is not None:
                yield raw

    async def _fetch_async(self, keywords: list[str], posted_after: datetime) -> Iterator[RawJob]:
        if not self.is_available():
            log.warning("[linkedin] no authenticated session — run --linkedin-login first")
            return

        async with launch_browser(self.name, persistent=True, headless=cfg.scrape_headless()) as context:
            page = await context.new_page()
            for kw in keywords:
                url = self._SEARCH.format(kw=kw.replace(" ", "+"))
                await page.goto(url, timeout=45_000, wait_until="domcontentloaded")
                await check_captcha(page, self.name)
                try:
                    await page.wait_for_selector(
                        "li[data-occludable-job-id], .job-card-container",
                        timeout=25_000, state="attached",
                    )
                except Exception:
                    pass
                # LinkedIn lazy-renders the results list in waves; give it time
                # to settle before reading the DOM (SPA navigations destroy
                # element handles, so the read must also be one evaluate()).
                await asyncio.sleep(8)

                # Extract all cards in ONE page-context evaluate — LinkedIn's SPA
                # keeps navigating, which destroys Playwright element handles
                # between steps. evaluate() returns plain data, so no handles die.
                try:
                    cards = await page.evaluate("""() => {
                        const out = [];
                        document.querySelectorAll("li[data-occludable-job-id]").forEach(li => {
                            const a = li.querySelector("a[href*='/jobs/view/'], a[href*='/jobs/']");
                            if (!a) return;
                            const titleEl = li.querySelector("a.job-card-container__link, .job-card-list__entity-lockup-title, [class*='job-card-container__link']");
                            const compEl = li.querySelector(".job-card-container__primary-description, .job-card-list__primary-description, [class*='primary-description'], [class*='subtitle']");
                            const locEl = li.querySelector(".job-card-container__metadata-wrapper, .job-card-container__metadata-item, .job-card-list__metadata-item, [class*='metadata-item'], [class*='metadata-wrapper']");
                            const timeEl = li.querySelector("time");
                            out.push({
                                title: (titleEl ? titleEl.innerText : a.innerText || "").trim(),
                                url: a.href.split("?")[0],
                                company: (compEl ? compEl.innerText : "").trim() || "Unknown",
                                location: (locEl ? locEl.innerText : "").trim() || null,
                                posted: (timeEl ? timeEl.getAttribute("datetime") : "") || null,
                            });
                        });
                        return out;
                    }""")
                except Exception:
                    cards = []

                for c in cards:
                    if not c["title"] or not c["url"]:
                        continue
                    try:
                        yield RawJob(
                            source=self.name,
                            title=c["title"],
                            company=c["company"],
                            url=c["url"],
                            location=c["location"],
                            posted_date=(c["posted"] or "")[:10] or None,
                            tags=[kw],
                        )
                    except Exception:
                        continue

                await polite_delay()
                await asyncio.sleep(2)

                # ── hiring feed posts (guarded: never fail the whole source) ──
                if cfg.linkedin_feed_enabled():
                    for query in _feed_queries(keywords, utc_now().weekday()):
                        try:
                            async for raw in self._scrape_feed_posts(page, query, posted_after):
                                yield raw
                        except CaptchaDetected:
                            log.warning("[linkedin] feed CAPTCHA for '%s' — skipping feed pass", query)
                            break
                        except Exception as exc:
                            log.warning("[linkedin] feed scrape failed for '%s': %s", query, exc)

            await page.close()