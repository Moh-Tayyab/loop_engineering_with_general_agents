"""Unit tests for BD Google Sheets & CSV exporter."""
from datetime import datetime, timezone
from pathlib import Path
from src.models import NormalizedJob
from src.sheets import job_to_bd_row, export_jobs_to_csv, sync_to_google_sheet


def _sample_job(jid="job-1"):
    return NormalizedJob(
        id=jid,
        title="Senior AI Engineer",
        title_normalized="senior ai engineer",
        company="Devsinc",
        company_normalized="devsinc",
        url="https://linkedin.com/jobs/view/123",
        source="linkedin",
        location="Islamabad, Pakistan (Remote)",
        location_type="remote",
        salary_min=120000,
        salary_max=160000,
        salary_currency="$",
        job_type="full-time",
        posted_date=None,
        fetched_at=datetime.now(timezone.utc),
        tags=["AI", "Python"],
        description_snippet="Build LLMs",
    )


def test_job_to_bd_row_formatting():
    job = _sample_job()
    row = job_to_bd_row(job)
    assert row["Job ID"] == "job-1"
    assert row["Company"] == "Devsinc"
    assert row["Job Title"] == "Senior AI Engineer"
    assert row["Salary"] == "$120k-160k"
    assert row["BD Status"] == "New"
    assert "AI" in row["Tags"]
    assert row["CV Match %"] == "unscored"


def test_job_to_bd_row_uses_real_cv_score():
    job = _sample_job()
    job.cv_match_score = 92
    job.cv_match_label = "AI Engineer (92%)"
    row = job_to_bd_row(job)
    assert row["CV Match %"] == "AI Engineer (92%)"


def test_export_jobs_to_csv(tmp_path):
    jobs = [_sample_job("j1"), _sample_job("j2")]
    csv_path = export_jobs_to_csv(jobs, tmp_path)
    assert csv_path.exists()
    content = csv_path.read_text(encoding="utf-8-sig")
    assert "Job ID,Posted Date,Company" in content
    assert "Devsinc" in content
    assert "j1" in content
    assert "j2" in content


def test_sync_to_google_sheet_no_url(monkeypatch):
    monkeypatch.delenv("GOOGLE_SHEET_WEBHOOK_URL", raising=False)
    assert not sync_to_google_sheet([_sample_job()])


def test_sync_to_google_sheet_success(monkeypatch):
    from unittest.mock import MagicMock
    import requests

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    monkeypatch.setattr(requests, "post", lambda *a, **k: mock_resp)
    monkeypatch.setenv("GOOGLE_SHEET_WEBHOOK_URL", "https://script.google.com/macros/s/test/exec")

    assert sync_to_google_sheet([_sample_job()])


def test_sync_to_google_sheet_retry_recovers(monkeypatch):
    from unittest.mock import MagicMock
    import requests

    attempts = 0

    def mock_post(*a, **k):
        nonlocal attempts
        attempts += 1
        resp = MagicMock()
        if attempts == 1:
            resp.status_code = 500
            resp.text = "Internal Server Error"
        else:
            resp.status_code = 200
        return resp

    monkeypatch.setattr(requests, "post", mock_post)
    monkeypatch.setenv("GOOGLE_SHEET_WEBHOOK_URL", "https://script.google.com/macros/s/test/exec")

    assert sync_to_google_sheet([_sample_job()], retries=2, backoff_s=0.01)
    assert attempts == 2


def test_sync_to_google_sheet_failure_records_in_dlq(tmp_slc, monkeypatch):
    from unittest.mock import MagicMock
    import requests
    from src.state import DeadLetterQueue

    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mock_resp.text = "Service Unavailable"
    monkeypatch.setattr(requests, "post", lambda *a, **k: mock_resp)
    monkeypatch.setenv("GOOGLE_SHEET_WEBHOOK_URL", "https://script.google.com/macros/s/test/exec")

    success = sync_to_google_sheet([_sample_job("job-dlq-test")], retries=2, backoff_s=0.01)
    assert not success

    dlq = DeadLetterQueue()
    assert len(dlq.items) == 1
    assert dlq.items[0]["source"] == "google_sheets"
    assert "job-dlq-test" in dlq.items[0]["job_ids"]
    assert "RetriesExhausted" in dlq.items[0]["error"]

