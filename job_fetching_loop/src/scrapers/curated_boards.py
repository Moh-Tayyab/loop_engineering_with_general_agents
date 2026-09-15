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