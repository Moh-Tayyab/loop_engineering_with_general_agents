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

SCAFFOLD (registered + DEFAULT-OFF until a live run verifies the collection
  surface): feedcoyote, jobboardsearch, flexjobs, dynamitejobs,
  virtual_vocations, nodesk. Observed blockers (2026-09-15 probe): feedcoyote
  has no public board route (`/jobs/` is a profile-404 bug; Angular shell);
  jobboardsearch is a 1.1 MB meta-search needing bespoke parsing;
  flexjobs times out / is paywalled; dynamitejobs renders only category links
  (job hrefs appear post-login/JS state, not found in 6s render); virtual
  vocations 403s plain requests; nodesk's board exposes no `/jobs/` hrefs
  (jobs are email-led/external).

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
        for kw in keywords:
            for item in self._get(kw):
                job = self._parse_item(item, kw)
                if job is None:
                    continue
                if job.url in seen_urls:
                    continue
                seen_urls.add(job.url)
                yield job

    def _get(self, kw: str) -> list[dict]:
        """Return parsed job objects, or [] on any failure (never raise)."""
        try:
            resp = requests.get(
                self._API.format(kw=quote_plus(kw)),
                timeout=20,
                headers={"User-Agent": random.choice(USER_AGENTS)},
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            log.info("[%s] api fetch failed (kw=%r): %s", self.name, kw, exc)
            return []
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

    def _get(self, kw: str) -> list[dict]:
        """Fetch RemoteOK public JSON API with human User-Agent."""
        try:
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
        except Exception as exc:
            log.info("[%s] api fetch failed (kw=%r): %s", self.name, kw, exc)
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
        import xml.etree.ElementTree as ET
        from email.utils import parsedate_to_datetime

        seen_links: set[str] = set()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        for feed_url in self._FEEDS:
            try:
                r = requests.get(feed_url, headers=headers, timeout=15)
                if r.status_code != 200:
                    continue
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
                log.info("[weworkremotely] feed error (%s): %s", feed_url, exc)


@register_scraper
class JobicyScraper(BaseScraper):
    """Jobicy worldwide remote tech & AI jobs via official v2 public JSON API."""
    name = "jobicy"
    _APIS = [
        "https://jobicy.com/api/v2/remote-jobs?count=50&geo=anywhere",
        "https://jobicy.com/api/v2/remote-jobs?count=50&industry=engineering",
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
        for api_url in self._APIS:
            try:
                r = requests.get(api_url, headers=headers, timeout=15)
                if r.status_code != 200:
                    continue
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
                log.info("[jobicy] fetch failed (%s): %s", api_url, exc)


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
        try:
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
        except (requests.RequestException, ValueError) as exc:
            log.info("[%s] fetch failed (kw=%r): %s", self.name, kw, exc)
            return []
        jobs = _extract_apollo_jobs(payload)
        hrefs = _wellfound_href_map(html)
        for job in jobs:
            job_id = str(job.get("id") or "")
            job["_url"] = hrefs.get(job_id) or (
                f"https://wellfound.com/jobs/{job_id}-{job.get('slug') or ''}")
        return jobs

    def _parse_item(self, item: dict, kw: str) -> RawJob | None:
        title = (item.get("title") or "").strip()
        url = (item.get("_url") or "").strip()
        if not title or not url:
            return None
        accepted = item.get("acceptedRemoteLocationNames")
        if isinstance(accepted, list) and accepted:
            loc = ", ".join(str(x) for x in accepted)
        else:
            loc = "Remote"
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
        try:
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
        except Exception as exc:
            log.info("[%s] render fetch failed: %s", self.name, exc)
            return []
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


# ── Scaffolds: registered + default-OFF until live-verified ──────────────────

_SCAFFOLD_NAMES = (
    "feedcoyote", "jobboardsearch", "flexjobs", "dynamitejobs",
    "virtual_vocations", "nodesk",
)


class _ScaffoldBoard(BaseScraper):
    """Placeholder for a curated board whose live collection isn't verified yet.

    Registered so `--list-sources` shows the full roadmap; hard DEFAULT-OFF in
    `config.source_enabled` so it never runs on a live cron (returning [] would
    masquerade as a healthy 'ok' and could mask a real outage).
    """

    def is_available(self) -> bool:
        return True

    def fetch(self, keywords, posted_after) -> Iterator[RawJob]:
        log.info("[%s] scaffold — collector not wired yet; implement + live-verify, then set SOURCE_%s=1",
                 self.name, self.name.upper())
        return iter(())


def _register_scaffold(name: str) -> None:
    cls = type(name.title().replace("_", "") + "Scraper", (_ScaffoldBoard,),
               {"name": name, "__module__": __name__})
    register_scraper(cls)


for _scaffold_name in _SCAFFOLD_NAMES:
    _register_scaffold(_scaffold_name)