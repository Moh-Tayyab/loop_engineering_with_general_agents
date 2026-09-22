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
import re
from datetime import date, datetime, timezone
from typing import Any, Iterator
from urllib.parse import quote_plus

import src.config as cfg
from src.browser import CaptchaDetected, check_captcha, launch_browser, polite_delay
from src.log import get_logger

log = get_logger(__name__)
from src.models import (
    _FOREIGN_RESTRICTED_COUNTRIES,
    RawJob,
    is_foreign_country_restricted,
    utc_now,
)
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
        if weekday == 4:  # Friday expands into #hiring and "we are hiring" scenes
            queries.append(f"#hiring {kw}")
            queries.append(f'"we are hiring" {kw}')
    return queries


_PHYSICAL_CITY_RE = re.compile(
    r"\b(?:(?:in|based\s+in|located\s+in|settled\s+in|position\s+in|work\s+from|across)\s+"
    r"(?:the\s+)?(?:dammam|al\s+khobar|khobar|riyadh|jeddah|abu\s+dhabi|dubai|"
    r"sharjah|doha|manama|muscat|kuwait(?:\s+city)?|istanbul)|"
    r"(?:dammam|al\s+khobar|khobar|riyadh|jeddah|abu\s+dhabi|dubai|sharjah|"
    r"doha|manama|muscat|kuwait(?:\s+city)?|istanbul)\s+(?:office|lab|hub|region|city))"
    r"(?:\b|,|\s+city)",
    re.I,
)


def _post_location(text: str | None) -> str:
    """Location guess for a hiring feed post (which has no structured location).

    Strict-location law (Rule 11):
    1. Explicit on-site / in-office wording maps to Hybrid (which SCRAPE_REMOTE_ONLY drops),
       preventing hashtag spam (#RemoteJobs) on an onsite post from masquerading as remote.
    2. Restricted foreign countries surface as restricted locations so downstream filters drop them.
    3. Explicit US restrictions (Tampa, FL, USA) surface as USA (Remote).
    4. Remote markers map to Remote.
    5. Physical cities without remote markers map to Hybrid.
    6. Fallback defaults to Remote.
    """
    t = (text or "").lower()
    if any(w in t for w in ("on-site", "onsite", "on site", "in-office", "in office",
                            "office-based", "at our office", "work from office",
                            "office only", "commute to the office")):
        return "Hybrid"

    if is_foreign_country_restricted(t):
        for c in sorted(_FOREIGN_RESTRICTED_COUNTRIES, key=len, reverse=True):
            if re.search(rf"\b{re.escape(c)}\b", t):
                label = "UK" if c == "uk" else c.title()
                return f"{label} (Remote)"
        return "Restricted (Remote)"

    from src.models import _is_us_restricted
    if _is_us_restricted(t):
        return "USA (Remote)"

    if any(w in t for w in ("remote", "wfh", "work from home", "work-from-home",
                            "anywhere", "worldwide", "location-agnostic")):
        return "Remote"

    if _PHYSICAL_CITY_RE.search(t):
        return "Hybrid"

    if "hybrid" in t:
        return "Hybrid"

    return "Remote"


_HIRING_MARKERS = re.compile(
    r"\bhir(?:ing|e|es)\b|\b(?:job|jobs)\b|\bvacanc\w*|\bopportunit\w*|\bopenings?\b|"
    r"\bwe(?:'|\u2019)?re\s+(?:are\s+)?(?:hiring|looking)\b|"
    r"\bwe\s+are\s+(?:hiring|looking)\b|\blooking\s+for\b|\bseeking\b|"
    r"\bjoin(?:ing)?\s+our\s+team\b|\b(?:apply|application|resume|cv)\b|"
    r"\b(?:role|position)s?\s*[:：]|\bposition\b",
    re.I,
)


def _is_hiring_post(text: str) -> bool:
    """A feed "post" is only a JOB when the post is explicitly hiring.

    The content-search page returns any post about AI/ML (educational deep
    dives, career commentary, news). Only keep posts whose body carries a
    hiring signal — an explicit "hiring"/"we're looking", an apply/role/posting
    marker, or a role keyword — so educational content never lands in the
    job digest."""
    return bool(_HIRING_MARKERS.search(text or ""))


def _post_title(text: str, headline: str | None) -> str:
    """A compact title for a feed post.

    Old feed DOM: LinkedIn rendered the author's "X is hiring..." line as the
    actor headline — that is a hiring title, use it. New content-search DOM:
    the "headline" is the actor's role line ("CTO", "• 3rd+", ...), which is
    NOT a job title — fall back to the post body's first sentence ("We're
    hiring — Junior AI Engineer ..."). Capped so the title stays a title."""
    header = (headline or "").strip()
    header = re.sub(r"^•?\s*[123](?:st|nd|rd)\+?\s*$", "", header).strip()
    body = (text or "").strip()
    if header and re.search(r"\b(hir(?:e|ing|es)|job|vacanc|opportunit|open(?:ing|ing s)?)\b",
                            header[:300], re.I):
        return header[:140]
    if body:
        for line in body.split("\n"):
            line = line.strip()
            if _is_hiring_post(line):
                return re.sub(r"\s+[…•·]+$", "", line)[:140]
        for sep in ("\n", ". "):
            part = body.split(sep, 1)[0].strip()
            if part:
                return part[:140]
    return (header or body or "Hiring")[:140]


def _feed_post_to_raw(post: dict[str, Any], kw: str,
                      posted_after: datetime | None = None) -> RawJob | None:
    """Map a scraped feed-post dict to a RawJob, skipping posts outside the
    fetch window when a parseable posted-date is present (no date → keep: the
    TTL dedup layer handles re-scrapes)."""
    text = (post.get("text") or "").strip()
    url = (post.get("url") or "").strip()
    if not text or not url or not _is_hiring_post(text):
        return None
    if "linkedin.com/in/" in url:
        return None

    loc = _post_location(text)
    if loc in ("Onsite", "Hybrid") or any(k in loc for k in ("Domestic", "Restricted", "USA", "UK", "India", "Germany", "Canada")):
        return None
    from src.models import is_worldwide_remote
    if not is_worldwide_remote(loc, description=text):
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
        location=loc,
        posted_date=posted or None,
        description=text[:2000],
        tags=[kw],
    )


@register_scraper
class LinkedInScraper(BaseScraper):
    name = "linkedin"

    _BASE = "https://www.linkedin.com"
    _SEARCH = "https://www.linkedin.com/jobs/search/?keywords={kw}&f_WT=2&location=Worldwide"
    _FEED = "https://www.linkedin.com/search/results/content/?keywords={kw}"

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

        # Secondary: authenticated feed pass (runs strictly on Friday, the designated hiring-feed day,
        # or when explicitly enabled via LINKEDIN_FEED_EVERYDAY=1).
        # Monday through Thursday exclusively scrape the structured Jobs board/section.
        is_feed_day = utc_now().weekday() == 4  # Friday only
        feed_allowed = cfg.linkedin_feed_enabled() and (is_feed_day or os.environ.get("LINKEDIN_FEED_EVERYDAY", "0") == "1")
        if self.has_authenticated_session() and feed_allowed:
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
                extra_params = ""
                if cfg.easy_apply_only():
                    extra_params += "&f_AL=true"
                exp_levels = cfg.linkedin_experience_levels()
                if exp_levels:
                    extra_params += f"&f_E={exp_levels}"
                url = (
                    f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?"
                    f"keywords={quote_plus(remote_query)}&location={loc_query}&f_WT=2&sortBy=DD&f_TPR={tpr_param}"
                    f"{extra_params}"
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
                            from src.models import (
                                is_language_restricted,
                                is_hybrid_work,
                                is_title_restricted,
                                is_description_restricted,
                                is_worldwide_remote,
                            )
                            if is_language_restricted(title) or is_language_restricted(real_desc):
                                log.debug("[linkedin] dropping language-restricted: %s", title)
                                continue
                            if is_hybrid_work(title) or is_hybrid_work(real_desc) or is_hybrid_work(loc):
                                log.debug("[linkedin] dropping hybrid: %s", title)
                                continue
                            if is_title_restricted(title) or is_description_restricted(real_desc):
                                log.debug("[linkedin] dropping restricted: %s", title)
                                continue
                            if not is_worldwide_remote(loc, source="linkedin", description=real_desc, title=title):
                                log.debug("[linkedin] dropping non-worldwide remote: %s (%s)", title, loc)
                                continue
                            if any(w in full_check for w in ("on-site", "onsite", "in-office", "office-based", "office only")):
                                log.debug("[linkedin] dropping onsite posting: %s (%s)", title, loc)
                                continue
                            title_loc = f"{title.lower()} {loc.lower()}"
                            has_remote_in_header = any(
                                w in title_loc
                                for w in ("remote", "work from home", "wfh", "anywhere", "telecommute", "virtual", "worldwide")
                            )
                            has_strict_remote_desc = (
                                any(w in real_desc.lower() for w in ("100% remote", "fully remote", "100% work from home", "fully work from home"))
                                or bool(re.search(r"\b(?:location|workplace|workplace\s+type)\s*:\s*remote\b", real_desc.lower()))
                                or bool(re.search(r"\bremote[,\s]+pakistan\b", real_desc.lower()))
                                or bool(re.search(r"\bpakistan[,\s]+remote\b", real_desc.lower()))
                            )
                            if not (has_remote_in_header or has_strict_remote_desc):
                                log.debug("[linkedin] dropping posting lacking explicit remote marker: %s (%s)", title, loc)
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

        LinkedIn switched this page to CSS-module hashed classes (the classic
        .feed-shared-update-v2 / [data-urn] nodes are gone and /search/content/
        now 404s), so the extractor locates each post structurally: the
        leaf-most container whose text opens with the "Feed post" label, then
        splits off author / headline / relative timestamp / body around the
        "Follow" marker. The author profile anchor provides the stable URL.
        """
        feed_url = LinkedInScraper._FEED.format(kw=quote_plus(query))
        await page.goto(feed_url, timeout=45_000, wait_until="domcontentloaded")
        await check_captcha(page, LinkedInScraper.name)
        await asyncio.sleep(6)
        try:
            posts = await page.evaluate("""() => {
                const isFeedRoot = (el) => {
                    const t = (el.innerText || "").trim();
                    if (!/^feed post/mi.test(t)) return false;
                    for (const c of el.querySelectorAll("div")) {
                        if (/^feed post/mi.test((c.innerText || "").trim())) return false;
                    }
                    return true;
                };
                const out = new Map();
                document.querySelectorAll("div").forEach(el => {
                    if (!isFeedRoot(el)) return;
                    const jobLink = el.querySelector("a[href*='/jobs/view/']");
                    const updateLink = el.querySelector("a[href*='/feed/update/'], a[href*='/posts/'], a[href*='urn:li:activity']");
                    const extLink = el.querySelector("a[href^='http']:not([href*='linkedin.com/in/']):not([href*='linkedin.com/company/']):not([href*='linkedin.com/search'])");
                    let url = "";
                    if (jobLink && jobLink.href) {
                        url = jobLink.href.split("?")[0];
                    } else if (updateLink && updateLink.href) {
                        url = updateLink.href.split("?")[0];
                    } else if (extLink && extLink.href) {
                        url = extLink.href.split("?")[0];
                    }
                    if (!url || url.includes("/in/")) return;
                    const t = el.innerText.replace(/\\u00a0/g, " ").trim();
                    const lines = t.split("\\n").map(l => l.trim()).filter(Boolean).slice(1);
                    if (!lines.length) return;
                    const author = (lines[0] || "").replace(/\\s*•.*$/, "").trim();
                    let posted = "";
                    let followIdx = -1;
                    for (let i = 0; i < lines.length; i++) {
                        const l = lines[i];
                        if (/^\\d+[dhwmo]\\b.*•/.test(l)) posted = (l.match(/^\\d+[dhwmo]/) || [""])[0];
                        if (l.toLowerCase() === "follow") followIdx = i;
                    }
                    const stopIdx = followIdx >= 0 ? followIdx : lines.length;
                    let headline = "";
                    for (let i = 1; i < stopIdx; i++) {
                        const l = lines[i];
                        if (!l || l === "Visit my website" || l === "Follow"
                            || /^\\d+[dhwmo]\\b.*•/.test(l)
                            || /^\\d+\\+?$/.test(l)
                            || /^•?\\s*[123](?:st|nd|rd)\\+?\\s*$/i.test(l)
                            || /^•+$/.test(l)) continue;
                        headline = l;
                        break;
                    }
                    const postBody = followIdx >= 0
                        ? lines.slice(followIdx + 1).join("\\n")
                        : lines.slice(1).join("\\n");
                    out.set(url, {
                        author,
                        headline,
                        text: postBody.trim() || t,
                        posted,
                        url,
                    });
                });
                return Array.from(out.values());
            }""")
        except Exception as exc:
            log.warning("[linkedin] feed-pass evaluate failed: %s", exc)
            posts = []
        for p in posts:
            raw = _feed_post_to_raw(p, query, posted_after)
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
            # `_feed_queries` already expands ALL keywords, so this must run ONCE
            # after the keyword loop — inline it used to re-scan every query per
            # keyword (7 keywords × 21 Friday queries = 147 page loads, blowing the
            # browser timeout and silently skipping the feed pass).
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