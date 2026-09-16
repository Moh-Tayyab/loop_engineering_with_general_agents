"""Google Sheets & BD Spreadsheet exporter.

Formats discovered jobs into professional BD columns:
- Job ID (dedup identifier)
- Date Posted
- Company Name
- Job Title
- Apply Link / URL
- Source Platform
- Location / Eligibility
- Salary Range
- Job Type
- Tech Stack / Tags
- BD Outreach Status (New / In Review / Reached Out / Interview / Closed)
- BD Notes

Two sync targets:
1. Local/Cloud CSV Export: `output/jobs_YYYY-MM-DD.csv` (UTF-8 with BOM for Excel/Sheets)
2. Live Google Sheets Webhook: if `GOOGLE_SHEET_WEBHOOK_URL` is set in .env,
   automatically appends new rows into the BD Google Sheet via HTTP POST.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from src.models import NormalizedJob, utc_now
from src.state import atomic_write_text

log = logging.getLogger(__name__)

BD_HEADERS = [
    "Job ID",
    "Posted Date",
    "Company",
    "Job Title",
    "CV Match %",
    "Job URL",
    "Source",
    "Location",
    "Location Type",
    "Salary",
    "Job Type",
    "Tags",
    "BD Status",
    "BD Notes",
]


def job_to_bd_row(job: NormalizedJob) -> dict[str, str]:
    """Convert a NormalizedJob into a clean BD row dict."""
    sal = "N/A"
    if job.salary_min:
        cur = job.salary_currency or "$"
        sal = f"{cur}{job.salary_min // 1000}k"
        if job.salary_max:
            sal += f"-{job.salary_max // 1000}k"

    posted = str(job.posted_date or job.fetched_at.date())
    if job.cv_match_label:
        match_str = job.cv_match_label
    elif job.cv_match_score:
        match_str = f"{job.cv_match_score}%"
    else:
        match_str = "unscored"

    return {
        "Job ID": job.id,
        "Posted Date": posted,
        "Company": job.company,
        "Job Title": job.title,
        "CV Match %": match_str,
        "Job URL": job.url,
        "Source": job.source,
        "Location": job.location or "Remote",
        "Location Type": job.location_type,
        "Salary": sal,
        "Job Type": job.job_type,
        "Tags": ", ".join(job.tags) if job.tags else "AI/ML",
        "BD Status": "New",
        "BD Notes": "",
    }


def export_jobs_to_csv(jobs: list[NormalizedJob], output_dir: Path) -> Path:
    """Save jobs into jobs_YYYY-MM-DD.csv atomically with Excel/Sheets UTF-8 BOM."""
    output_dir.mkdir(parents=True, exist_ok=True)
    today = utc_now().date().isoformat()
    csv_path = output_dir / f"jobs_{today}.csv"

    # Merge with existing rows for today
    existing_rows: dict[str, dict[str, str]] = {}
    if csv_path.exists():
        try:
            with open(csv_path, mode="r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    jid = r.get("Job ID")
                    if jid:
                        existing_rows[jid] = r
        except Exception as exc:
            log.warning("[sheets] could not read existing csv (%s): %s", csv_path, exc)

    # Append new jobs
    for j in jobs:
        if j.id not in existing_rows:
            existing_rows[j.id] = job_to_bd_row(j)

    # Write atomically
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=BD_HEADERS)
    writer.writeheader()
    for row in existing_rows.values():
        writer.writerow(row)

    atomic_write_text(csv_path, buf.getvalue(), encoding="utf-8-sig")
    log.info("[sheets] exported %d jobs -> %s", len(existing_rows), csv_path)
    return csv_path


def sync_to_google_sheet(jobs: list[NormalizedJob], action: str = "append") -> bool:
    """Push new jobs to a Google Sheet Webhook endpoint if configured.

    Uses zero-dependency Google Apps Script Webhook (no GCP credentials required).
    `action`: 'append' (default) or 'replace' (resets and repopulates).
    """
    webhook_url = os.environ.get("GOOGLE_SHEET_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return False

    rows = [job_to_bd_row(j) for j in jobs]
    if not rows:
        return False

    try:
        r = requests.post(
            webhook_url,
            json={
                "action": action,
                "jobs": rows,
                "count": len(rows),
                "synced_at": utc_now().isoformat(),
            },
            timeout=50,
            headers={"Content-Type": "application/json"},
        )
        if r.status_code in (200, 201, 302):
            log.info("[sheets] successfully synced %d jobs to Google Sheet", len(rows))
            return True
        else:
            log.warning("[sheets] Google Sheet webhook returned %s: %s", r.status_code, r.text[:200])
            return False
    except Exception as exc:
        log.warning("[sheets] Google Sheet sync failed: %s", exc)
        return False
