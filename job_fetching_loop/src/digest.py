"""Weekly digest generator — summary of the week's discovered jobs.

The digest now triggers on Monday morning (the 3-day backfill run). Friday is
the LinkedIn hiring-feed scrape day and no longer generates the weekly summary.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import src.config as cfg
from src.log import get_logger
from src.models import NormalizedJob, utc_now
from src.state import atomic_write_text

log = get_logger(__name__)


def week_key(dt: date | None = None) -> str:
    """ISO week key: '2026-W37'.

    Defaults to the UTC date — job files are named with UTC dates, so a local
    date here could roll the week key a day early/late and mislabel the digest."""
    dt = dt or utc_now().date()
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def collect_weekly_jobs(output_dir: Path | None = None) -> list[NormalizedJob]:
    """Read all job files from the past 7 days and merge.

    Iterates UTC dates to stay aligned with save_jobs() (which names files by
    UTC date); a local-date loop in a UTC+ timezone would silently drop the
    oldest day's file at the window edge."""
    output_dir = output_dir or cfg.OUTPUT_DIR
    today = utc_now().date()
    all_jobs: list[NormalizedJob] = []
    seen_ids: set[str] = set()

    for delta in range(7):
        day = today - timedelta(days=delta)
        day_file = output_dir / f"jobs_{day.isoformat()}.json"
        if not day_file.exists():
            continue
        try:
            raw = json.loads(day_file.read_text(encoding="utf-8"))
            jobs = raw if isinstance(raw, list) else raw.get("jobs", [])
            for d in jobs:
                j = NormalizedJob.from_dict(d)
                if j.id not in seen_ids:
                    seen_ids.add(j.id)
                    all_jobs.append(j)
        except (json.JSONDecodeError, OSError, KeyError) as e:
            log.warning("skipped %s: %s", day_file.name, e)

    return all_jobs


def generate_digest(jobs: list[NormalizedJob]) -> dict[str, Any]:
    """Compute weekly statistics from collected jobs."""
    total = len(jobs)
    by_source: Counter[str] = Counter()
    by_type: Counter[str] = Counter()
    by_location: Counter[str] = Counter()
    companies: Counter[str] = Counter()

    for j in jobs:
        by_source[j.source] += 1
        by_type[j.job_type] += 1
        by_location[j.location_type] += 1
        companies[j.company] += 1

    # top jobs by recency (posted_date first, fetched_at as tiebreak) then by source diversity
    top = sorted(
        jobs,
        key=lambda j: (j.posted_date or j.fetched_at.date(), j.fetched_at),
        reverse=True,
    )[:20]

    return {
        "week_key": week_key(),
        "generated_at": utc_now().isoformat(timespec="seconds"),
        "total": total,
        "by_source": dict(by_source.most_common()),
        "by_type": dict(by_type.most_common()),
        "by_location": dict(by_location.most_common()),
        "top_companies": dict(companies.most_common(10)),
        "top_jobs": [j.to_dict() for j in top],
    }


def write_digest(digest: dict[str, Any], output_dir: Path | None = None) -> tuple[Path, Path]:
    """Write digest JSON + Markdown report. Returns (json_path, md_path)."""
    output_dir = output_dir or cfg.OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    wk = digest["week_key"]

    json_path = output_dir / f"digest_{wk}.json"
    md_path = output_dir / f"digest_{wk}.md"

    # Atomic: a crash mid-write must never tear the digest (state/seende files
    # are already atomic; the digest had a bare write_text straggler).
    atomic_write_text(json_path, json.dumps(digest, indent=2, ensure_ascii=False))

    md_lines = [
        f"# Weekly Digest — {wk}",
        f"Generated: {digest['generated_at']}",
        "",
        "## Summary",
        f"- **Total jobs:** {digest['total']}",
        "",
        "## By Source",
    ]
    for name, count in digest.get("by_source", {}).items():
        md_lines.append(f"- {name}: {count}")

    md_lines.append("")
    md_lines.append("## By Type")
    for jtype, count in digest.get("by_type", {}).items():
        md_lines.append(f"- {jtype}: {count}")

    md_lines.append("")
    md_lines.append("## Top Companies")
    for company, count in digest.get("top_companies", {}).items():
        md_lines.append(f"- {company}: {count} openings")

    md_lines.append("")
    md_lines.append("## Top 20 Jobs")
    for i, j in enumerate(digest.get("top_jobs", [])[:20], 1):
        salary = ""
        if j.get("salary_min"):
            salary = f" ({j.get('salary_currency', '')}{j['salary_min']//1000}k)"
        md_lines.append(f"{i}. **{j['title']}** @ {j['company']}{salary}")
        md_lines.append(f"   - Source: {j['source']} | Type: {j.get('job_type', 'unknown')}")
        md_lines.append(f"   - <{j['url']}>")

    atomic_write_text(md_path, "\n".join(md_lines))
    return json_path, md_path