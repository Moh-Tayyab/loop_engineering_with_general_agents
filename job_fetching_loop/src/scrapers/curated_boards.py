"""Curated remote job boards — lightweight sources.

Three tiers:

LIVE JSON-API (requests only; wired + unit-tested against confirmed shapes):
  remotive  — https://remotive.com/api/remote-jobs?search=<kw>
              ("jobs": [{title, url, company_name, candidate_required_location,
              publication_date, salary, job_type, tags, description}])
  himalayas — https://himalayas.app/jobs/api/search?q=<kw>
              ("jobs": [{title, companyName, applicationLink, pubDate (unix),
              locationRestrictions[], employmentType, excerpt, min/maxSalary}])

LIVE render/embedded-data (live-verified 2026-09-15):
  wellfound — https://wellfound.com/jobs embeds the job listings in the
              page's __NEXT_DATA__ apolloState (JobListing:* + Startup:*); job
              URLs are the REAL rendered hrefs (`/jobs/<id>-<slug>`), never
              guessed. acceptedRemoteLocationNames empty -> Remote/worldwide;
              country list -> restricted (dropped by SCRAPE_REMOTE_ONLY).
  justremote — https://justremote.co/ renders job links
              (<https://justremote.co/remote-jobs/remote-*/<title>-<co>>);
              title/company are derived from the URL slug + anchor text.

LIVE RSS/XML feeds:
  weworkremotely — https://weworkremotely.com/categories/remote-*.rss
  nodesk         — https://nodesk.co/remote-jobs/index.xml

Remote honesty: these are remote-native boards, but SCRAPE_REMOTE_ONLY must
stay STRICT. A Himalayas job whose locationRestrictions is a country list
("United States", "Portugal") maps to a plain-country location -> on-site by
classify_location -> dropped. Only worldwide/empty restrictions become
"Remote". The spec targets worldwide/APAC/Pakistan remote with location
restrictions taken seriously.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from datetime import datetime, timezone
from typing import Iterator
from urllib.parse import quote_plus

import requests

try:
    import defusedxml.ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET

from src.browser import USER_AGENTS, launch_browser
from src.models import RawJob
from . import register_scraper
from .base import BaseScraper

log = logging.getLogger(__name__)


def _unix_to_date(value) -> str | None:
    """Unix-epoch seconds -> 'YYYY-MM-DD' (Himalayas pubDate is an epoch int)."""
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).date().isoformat()


class CuratedBoardScraper(BaseScraper):
    """Keyword-driven remote board with a public JSON API (requests only).

    Subclasses implement `_parse_item`; the API call, keyword loop, and
    intra-source URL dedup live here. Never launches a browser — a plain HTTP
    GET is all these boards need (cheap and fail-closed).
    """

    name: str = "curated"
    _API: str = ""
    _JOBS_KEY: str = "jobs"

    def is_available(self) -> bool:
        return True

    def fetch(self, keywords: list[str], posted_after) -> Iterator[RawJob]:
        seen_urls: set[str] = set()
        errors: list[Exception] = []
        any_success = False
        for kw in keywords:
            try:
                items = self._get(kw)
                any_success = True
                for item in items:
                    job = self._parse_item(item, kw)
                    if job is None:
                        continue
                    if job.url in seen_urls:
                        continue
                    seen_urls.add(job.url)
                    yield job
            except (requests.RequestException, ValueError) as exc:
                errors.append(exc)
        if not any_success and errors:
            raise errors[0]

    def _get(self, kw: str) -> list[dict]:
        """Return parsed job objects, raising on HTTP or connection failures."""
        resp = requests.get(
            self._API.format(kw=quote_plus(kw)),
            timeout=20,
            headers={"User-Agent": random.choice(USER_AGENTS)},
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            data = data.get(self._JOBS_KEY) or data.get("data") or []
        return data if isinstance(data, list) else []

    def _parse_item(self, item: dict, kw: str) -> RawJob | None:
        raise NotImplementedError  # pragma: no cover - abstract


@register_scraper
class RemotiveScraper(CuratedBoardScraper):
    name = "remotive"
    _API = "https://remotive.com/api/remote-jobs?search={kw}"

    def _parse_item(self, item: dict, kw: str) -> RawJob | None:
        title = (item.get("title") or "").strip()
        url = (item.get("url") or "").strip()
        if not title or not url:
            return None
        loc = (item.get("candidate_required_location") or "").strip() or "Remote"
        salary = str(item.get("salary") or "").strip() or None
        return RawJob(
            source=self.name,
            title=title,
            company=(item.get("company_name") or "Unknown").strip(),
            url=url,
            location=loc,
            salary=salary,
            posted_date=str(item.get("publication_date") or "")[:10] or None,
            description=(item.get("description") or "")[:2000],
            job_type=item.get("job_type") or None,
            tags=[kw],
        )


@register_scraper
class RemoteokScraper(CuratedBoardScraper):
    name = "remoteok"
    _API = "https://remoteok.com/api?tag={kw}"

    def fetch(self, keywords: list[str], posted_after: datetime) -> Iterator[RawJob]:
        tags = ["ai", "python", "data", "engineer", "dev"]
        seen_urls: set[str] = set()
        any_success = False
        errors: list[Exception] = []
        for tag in tags:
            try:
                items = self._get(tag)
                any_success = True
                for item in items:
                    job = self._parse_item(item, tag)
                    if job is None or job.url in seen_urls:
                        continue
                    seen_urls.add(job.url)
                    yield job
            except (requests.RequestException, ValueError) as exc:
                errors.append(exc)
        if not any_success and errors:
            raise errors[0]

    def _get(self, kw: str) -> list[dict]:
        """Fetch RemoteOK public JSON API with human User-Agent."""
        resp = requests.get(
            self._API.format(kw=quote_plus(kw.lower())),
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            # RemoteOK item 0 is a legal notice dictionary
            return [it for it in data if isinstance(it, dict) and "id" in it]
        return []

    def _parse_item(self, item: dict, kw: str) -> RawJob | None:
        if not isinstance(item, dict) or "id" not in item:
            return None
        title = (item.get("position") or "").strip()
        url = (item.get("url") or "").strip()
        if not title or not url:
            return None
        loc = (item.get("location") or "").strip() or "Worldwide"
        sal_min = item.get("salary_min")
        sal_max = item.get("salary_max")
        salary = None
        if sal_min or sal_max:
            salary = f"${sal_min or 0} - ${sal_max or 0}"
        tags = list(item.get("tags") or [])
        if kw not in tags:
            tags.append(kw)
        posted = str(item.get("date") or "")[:10] or None
        return RawJob(
            source=self.name,
            title=title,
            company=(item.get("company") or "Unknown").strip(),
            url=url,
            location=loc,
            salary=salary,
            posted_date=posted,
            description=(item.get("description") or "")[:2000],
            job_type="full-time",
            tags=tags,
        )


@register_scraper
class HimalayasScraper(CuratedBoardScraper):
    name = "himalayas"
    _API = "https://himalayas.app/jobs/api/search?q={kw}"

    def _parse_item(self, item: dict, kw: str) -> RawJob | None:
        title = (item.get("title") or "").strip()
        url = (item.get("applicationLink") or item.get("guid") or "").strip()
        if not title or not url:
            return None
        loc = item.get("locationRestrictions")
        if isinstance(loc, list) and loc:
            loc = ", ".join(str(x) for x in loc)
        else:
            loc = "Remote"
        min_, max_ = item.get("minSalary"), item.get("maxSalary")
        salary = None
        if min_ or max_:
            cur = str(item.get("currency") or "").strip()
            salary = " ".join(p for p in (cur, str(min_ or ""), str(max_ or "")) if p)
        return RawJob(
            source=self.name,
            title=title,
            company=(item.get("companyName") or "Unknown").strip(),
            url=url,
            location=loc,
            salary=salary,
            posted_date=_unix_to_date(item.get("pubDate")),
            description=(item.get("excerpt") or item.get("description") or "")[:2000],
            job_type=item.get("employmentType") or None,
            tags=[kw],
        )


@register_scraper
class WeWorkRemotelyScraper(BaseScraper):
    """WeWorkRemotely worldwide remote jobs via public RSS feeds (no login, no CAPTCHA)."""
    name = "weworkremotely"
    _FEEDS = [
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    ]

    def is_available(self) -> bool:
        return True

    def login_required(self) -> bool:
        return False

    def fetch(self, keywords: list[str], posted_after: datetime) -> Iterator[RawJob]:
        from email.utils import parsedate_to_datetime

        seen_links: set[str] = set()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        any_success = False
        errors: list[Exception] = []
        for feed_url in self._FEEDS:
            try:
                r = requests.get(feed_url, headers=headers, timeout=15)
                r.raise_for_status()
                any_success = True
                root = ET.fromstring(r.text)
                for item in root.findall(".//item"):
                    link = (item.findtext("link") or "").strip()
                    if not link or link in seen_links:
                        continue
                    seen_links.add(link)
                    raw_title = (item.findtext("title") or "").strip()
                    if ":" in raw_title:
                        company, title = [p.strip() for p in raw_title.split(":", 1)]
                    else:
                        company, title = "Unknown", raw_title
                    region = (item.findtext("region") or "").strip() or "Worldwide"
                    desc = (item.findtext("description") or "").strip()
                    posted_date = None
                    raw_date = item.findtext("pubDate")
                    if raw_date:
                        try:
                            dt = parsedate_to_datetime(raw_date)
                            if dt < posted_after:
                                continue
                            posted_date = dt.date().isoformat()
                        except Exception:
                            pass
                    yield RawJob(
                        source=self.name,
                        title=title,
                        company=company,
                        url=link,
                        location=region,
                        posted_date=posted_date,
                        description=desc[:2000],
                        tags=["remote"],
                        fetched_at=datetime.now(timezone.utc),
                    )
            except Exception as exc:
                errors.append(exc)
                log.info("[weworkremotely] feed error (%s): %s", feed_url, exc)
        if not any_success and errors:
            raise errors[0]


@register_scraper
class JobicyScraper(BaseScraper):
    """Jobicy worldwide remote tech & AI jobs via official v2 public JSON API."""
    name = "jobicy"
    _APIS = [
        "https://jobicy.com/api/v2/remote-jobs?count=100&geo=anywhere",
        "https://jobicy.com/api/v2/remote-jobs?count=100&industry=engineering",
        "https://jobicy.com/api/v2/remote-jobs?count=100&industry=data-science",
    ]

    def is_available(self) -> bool:
        return True

    def login_required(self) -> bool:
        return False

    def fetch(self, keywords: list[str], posted_after: datetime) -> Iterator[RawJob]:
        seen_urls: set[str] = set()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        any_success = False
        errors: list[Exception] = []
        for api_url in self._APIS:
            try:
                r = requests.get(api_url, headers=headers, timeout=15)
                r.raise_for_status()
                any_success = True
                data = r.json()
                jobs = data.get("jobs", []) if isinstance(data, dict) else []
                for it in jobs:
                    url = (it.get("url") or "").strip()
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    title = (it.get("jobTitle") or "").strip()
                    company = (it.get("companyName") or "Unknown").strip()
                    geo = (it.get("jobGeo") or "").strip() or "Worldwide"
                    pub = str(it.get("pubDate") or "")[:10] or None
                    desc = (it.get("jobExcerpt") or it.get("jobDescription") or f"{title} at {company}")
                    jt = it.get("jobType")[0] if isinstance(it.get("jobType"), list) and it.get("jobType") else None

                    yield RawJob(
                        source=self.name,
                        title=title,
                        company=company,
                        url=url,
                        location=geo,
                        posted_date=pub,
                        description=desc[:2000],
                        job_type=jt,
                        tags=["remote", "ai"],
                        fetched_at=datetime.now(timezone.utc),
                    )
            except Exception as exc:
                errors.append(exc)
                log.info("[jobicy] fetch failed (%s): %s", api_url, exc)
        if not any_success and errors:
            raise errors[0]


# ── Wellfound (requests + embedded __NEXT_DATA__ apollo state) ───────────────

def _extract_apollo_jobs(payload: dict) -> list[dict]:
    """Pull JobListing dicts from Wellfound's __NEXT_DATA__ apolloState.

    Each listing is enriched with resolved fields: `_company` (Startup name)
    and `_url` (real canonical href, or id-slug fallback). Pure + testable.
    Null-safe: any missing/mis-typed intermediate node yields [].
    """
    page_props = ((payload or {}).get("props") or {}).get("pageProps") or {}
    data = (page_props.get("apolloState") or {}).get("data") or {}
    if not isinstance(data, dict):
        return []
    startups = {
        key: value
        for key, value in data.items()
        if str(key).startswith("Startup:") and isinstance(value, dict)
    }
    jobs: list[dict] = []
    for key, entry in data.items():
        if not (str(key).startswith("JobListing:") and isinstance(entry, dict)):
            continue
        job = dict(entry)
        ref = job.get("startup")
        if isinstance(ref, dict) and ref.get("__ref"):
            startup = startups.get(ref["__ref"], {})
            job["_company"] = (startup.get("name") or "Unknown").strip()
        jobs.append(job)
    return jobs


def _wellfound_href_map(html: str) -> dict[str, str]:
    """JobListing id -> canonical URL from real rendered hrefs (no guessing)."""
    hrefs: dict[str, str] = {}
    for slug_path, job_id in re.findall(r'href="(/jobs/(\d+)-[^"]+)"', html):
        hrefs[job_id] = "https://wellfound.com" + slug_path
    return hrefs


@register_scraper
class WellfoundScraper(CuratedBoardScraper):
    name = "wellfound"
    _URL = "https://wellfound.com/jobs"

    def _get(self, kw: str) -> list[dict]:
        resp = requests.get(
            self._URL, timeout=25,
            headers={"User-Agent": random.choice(USER_AGENTS)},
        )
        resp.raise_for_status()
        html = resp.text
        match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        if not match:
            log.info("[%s] no __NEXT_DATA__ found (kw=%r)", self.name, kw)
            return []
        payload = json.loads(match.group(1))
        jobs = _extract_apollo_jobs(payload)
        hrefs = _wellfound_href_map(html)
        for job in jobs:
            job_id = str(job.get("id") or "")
            job["_url"] = hrefs.get(job_id) or (
                f"https://wellfound.com/jobs/{job_id}-{job.get('slug') or ''}")
        return jobs

    def fetch(self, keywords: list[str], posted_after) -> Iterator[RawJob]:
        # Wellfound ignores the keyword in the HTTP request (one __NEXT_DATA__
        # payload), so the base class would re-download the same page once per
        # keyword. Fetch the page ONCE, then run the per-keyword tag/match loop
        # in memory — keeps per-keyword tags (the AI gate reads them) with 1
        # HTTP hit instead of N.
        seen_urls: set[str] = set()
        items = self._get("")
        for kw in keywords:
            for item in items:
                job = self._parse_item(item, kw)
                if job is None:
                    continue
                if job.url in seen_urls:
                    continue
                seen_urls.add(job.url)
                yield job

    def _parse_item(self, item: dict, kw: str) -> RawJob | None:
        title = (item.get("title") or "").strip()
        url = (item.get("_url") or "").strip()
        if not title or not url:
            return None
        is_remote = bool(item.get("remote"))
        accepted = item.get("acceptedRemoteLocationNames")
        listed = item.get("locationNames") or []
        if isinstance(accepted, list) and accepted:
            loc = ", ".join(str(x) for x in accepted)
        elif is_remote:
            loc = "Remote"
        else:
            loc = ", ".join(str(x) for x in listed) if listed else "On-site"
        role = None
        primary = item.get("primaryRole")
        if isinstance(primary, dict):
            role = primary.get("name") or primary.get("slug")
        desc = "Wellfound listing"
        listed = item.get("locationNames")
        if isinstance(listed, list) and listed:
            desc += f" Locations: {', '.join(str(x) for x in listed)}."
        if role and str(role) != title:
            desc += f" Role: {role}."
        return RawJob(
            source=self.name,
            title=title,
            company=(item.get("_company") or "Unknown").strip(),
            url=url,
            location=loc,
            salary=str(item.get("compensation") or "").strip() or None,
            posted_date=_unix_to_date(item.get("liveStartAt")),
            description=desc[:2000],
            job_type="Remote" if item.get("remote") else None,
            tags=[kw],
        )


# ── JustRemote (Playwright render of the homepage) ───────────────────────────

_JUSTREMOTE_CARD_SELECTOR = "a[class*='new-job-item__JobMeta']"


def _justremote_tag(keywords: list[str]) -> str:
    """Single string tag for justremote jobs (never a nested list)."""
    return keywords[0] if keywords else "AI"


def _justremote_card_to_raw(card: dict, tag: str) -> RawJob | None:
    """Pure mapper for a rendered job card (href/title/company dict) -> RawJob."""
    href = (card.get("href") or "").strip()
    title = (card.get("title") or "").strip()
    if not href or not title:
        return None
    if not re.search(r"remote-[a-z0-9-]+-jobs/", href):
        return None
    return RawJob(
        source="justremote",
        title=title,
        company=(card.get("company") or "Unknown").strip(),
        url=href,
        location="Remote",
        tags=[tag] if tag else [],
    )


@register_scraper
class JustRemoteScraper(BaseScraper):
    name = "justremote"
    _URL = "https://justremote.co/"

    def is_available(self) -> bool:
        return True

    def fetch(self, keywords: list[str], posted_after) -> Iterator[RawJob]:
        yield from asyncio.run(self._gather(keywords))

    async def _gather(self, keywords: list[str]) -> list[RawJob]:
        log.info("[%s] fetching via browser render", self.name)
        async with launch_browser(self.name) as ctx:
            page = await ctx.new_page()
            await page.goto(self._URL, timeout=30000, wait_until="domcontentloaded")
            await asyncio.sleep(4)
            cards = await page.evaluate(
                """(sel) => Array.from(document.querySelectorAll(sel)).map(a => ({
                    href: a.href,
                    title: (a.querySelector('[class*="JobTitle"],h3') || {}).innerText || a.innerText.split('\\n')[0] || '',
                    company: (a.querySelector('[class*="JobItemCompany"]') || {}).innerText || ''
                  })).filter(c => c.href && c.title.trim())""",
                _JUSTREMOTE_CARD_SELECTOR,
            )
        seen: set[str] = set()
        tag = _justremote_tag(keywords)
        jobs: list[RawJob] = []
        for card in cards:
            job = _justremote_card_to_raw(card, tag)
            if job is None or job.url in seen:
                continue
            seen.add(job.url)
            jobs.append(job)
        return jobs


# ── NoDesk (public RSS feed) ──────────────────────────────────────────────────

@register_scraper
class NoDeskScraper(BaseScraper):
    """NoDesk remote jobs via official public RSS feed (no login, no CAPTCHA)."""
    name = "nodesk"
    _FEED_URL = "https://nodesk.co/remote-jobs/index.xml"

    def is_available(self) -> bool:
        return True

    def login_required(self) -> bool:
        return False

    def fetch(self, keywords: list[str], posted_after: datetime) -> Iterator[RawJob]:
        import html
        from email.utils import parsedate_to_datetime

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        r = requests.get(self._FEED_URL, headers=headers, timeout=15)
        r.raise_for_status()
        clean_xml = re.sub(r'&(?!(?:amp|lt|gt|apos|quot|#\d+|#x[0-9a-fA-F]+);)', '&amp;', r.text)
        root = ET.fromstring(clean_xml)
        seen: set[str] = set()
        for item in root.findall(".//item"):
            link = (item.findtext("link") or "").strip()
            if not link or link in seen:
                continue
            seen.add(link)
            raw_title = html.unescape((item.findtext("title") or "").strip())
            if " at " in raw_title:
                title, company = [p.strip() for p in raw_title.rsplit(" at ", 1)]
            else:
                title, company = raw_title, "Unknown"
            desc = html.unescape((item.findtext("description") or "").strip())
            posted_date = None
            raw_date = item.findtext("pubDate")
            if raw_date:
                try:
                    dt = parsedate_to_datetime(raw_date)
                    if dt < posted_after:
                        continue
                    posted_date = dt.date().isoformat()
                except Exception:
                    pass
            yield RawJob(
                source=self.name,
                title=title,
                company=company,
                url=link,
                location="Worldwide",
                posted_date=posted_date,
                description=desc[:2000],
                tags=["remote"],
                fetched_at=datetime.now(timezone.utc),
            )


# ── Arbeitnow (Open JSON API — 250+ tech jobs) ───────────────────────────────

@register_scraper
class ArbeitnowScraper(BaseScraper):
    """Arbeitnow remote jobs via official public JSON API (250+ listings per sweep)."""
    name = "arbeitnow"
    _API = "https://www.arbeitnow.com/api/job-board-api"

    def is_available(self) -> bool:
        return True

    def login_required(self) -> bool:
        return False

    def fetch(self, keywords: list[str], posted_after: datetime) -> Iterator[RawJob]:
        import html
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        seen_urls: set[str] = set()
        r = requests.get(self._API, headers=headers, timeout=20)
        r.raise_for_status()
        data = r.json()
        jobs = data.get("data", []) if isinstance(data, dict) else []
        for it in jobs:
            if not isinstance(it, dict):
                continue
            # Only remote jobs
            if not it.get("remote"):
                continue
            url = (it.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            title = html.unescape((it.get("title") or "").strip())
            company = html.unescape((it.get("company_name") or "Unknown").strip())
            raw_loc = (it.get("location") or "").strip()
            raw_tags = it.get("tags") or []
            tags = [str(t).lower() for t in raw_tags if t]
            if "hybrid" in tags or "hybrid work" in tags or not it.get("remote"):
                loc = raw_loc or "Hybrid"
            else:
                loc = raw_loc or "Worldwide"
            desc = html.unescape((it.get("description") or "").strip())
            created_at = it.get("created_at")
            posted_date = None
            if created_at:
                try:
                    posted_date = datetime.fromtimestamp(created_at, timezone.utc).date().isoformat()
                except Exception:
                    pass
            jtypes = it.get("job_types")
            jt = jtypes[0] if isinstance(jtypes, list) and jtypes else "full-time"
            yield RawJob(
                source=self.name,
                title=title,
                company=company,
                url=url,
                location=loc,
                posted_date=posted_date,
                description=desc[:2000],
                tags=tags or ["remote"],
                job_type=jt,
                fetched_at=datetime.now(timezone.utc),
            )


# ── Python.org (Official PSF RSS feed) ───────────────────────────────────────

@register_scraper
class PythonOrgScraper(BaseScraper):
    """Python Software Foundation official remote tech/AI jobs feed."""
    name = "python_org"
    _FEED = "https://www.python.org/jobs/feed/rss/"

    def is_available(self) -> bool:
        return True

    def login_required(self) -> bool:
        return False

    def fetch(self, keywords: list[str], posted_after: datetime) -> Iterator[RawJob]:
        import html
        from email.utils import parsedate_to_datetime

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        seen_urls: set[str] = set()
        r = requests.get(self._FEED, headers=headers, timeout=15)
        r.raise_for_status()
        clean_xml = re.sub(r'&(?!(?:amp|lt|gt|apos|quot|#\d+|#x[0-9a-fA-F]+);)', '&amp;', r.text)
        root = ET.fromstring(clean_xml)
        for item in root.findall(".//item"):
            link = (item.findtext("link") or "").strip()
            if not link or link in seen_urls:
                continue
            seen_urls.add(link)
            raw_title = html.unescape((item.findtext("title") or "").strip())
            if "," in raw_title:
                title, company = [p.strip() for p in raw_title.rsplit(",", 1)]
            else:
                title, company = raw_title, "Unknown"
            raw_desc = html.unescape((item.findtext("description") or "").strip())
            loc = "Worldwide"
            clean_desc = raw_desc
            if "\n" in raw_desc:
                first_line, rest = raw_desc.split("\n", 1)
                first_line_clean = re.sub(r"<[^>]+>", "", first_line).strip()
                if first_line_clean and len(first_line_clean) < 150:
                    loc = first_line_clean
                    clean_desc = re.sub(r"<[^>]+>", " ", rest).strip()
            else:
                clean_desc = re.sub(r"<[^>]+>", " ", raw_desc).strip()
            posted_date = None
            raw_date = item.findtext("pubDate")
            if raw_date:
                try:
                    dt = parsedate_to_datetime(raw_date)
                    if dt < posted_after:
                        continue
                    posted_date = dt.date().isoformat()
                except Exception:
                    pass
            yield RawJob(
                source=self.name,
                title=title,
                company=company,
                url=link,
                location=loc,
                posted_date=posted_date,
                description=clean_desc[:2000],
                tags=["python", "remote"],
                fetched_at=datetime.now(timezone.utc),
            )