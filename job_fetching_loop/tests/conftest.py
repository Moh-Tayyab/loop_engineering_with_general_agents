"""pytest fixtures for the job fetching loop tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# ensure job_fetching_loop/src is importable
JOB_LOOP = Path(__file__).resolve().parent.parent
if str(JOB_LOOP) not in sys.path:
    sys.path.insert(0, str(JOB_LOOP))


@pytest.fixture(autouse=True)
def _isolate_runner_env(monkeypatch):
    """Keep pytest hermetic vs a production .env (JOB_LOOP_PRIMARY=github)."""
    monkeypatch.setenv("JOB_LOOP_PRIMARY", "local")
    monkeypatch.setenv("JOB_LOOP_ENABLED", "1")
    monkeypatch.delenv("JOB_LOOP_CLOUD", raising=False)
    monkeypatch.delenv("CLOUD_ALLOW_BROWSER", raising=False)
    monkeypatch.setattr("src.main.send_ops_alert", lambda *_a, **_k: False, raising=False)


@pytest.fixture
def tmp_slc(tmp_path: Path):
    """Provide a temporary .slc dir with clean state + seen files."""
    import src.config as cfg

    slc = tmp_path / ".slc"
    slc.mkdir()

    state_path = slc / "state.json"
    state_path.write_text(json.dumps({
        "schema_version": 1,
        "last_run": None,
        "last_fetch_window": None,
        "sources": {},
        "jobs_this_week": 0,
        "notifications_sent_today": {},
        "digest_generated_for": None,
    }), encoding="utf-8")

    seen_path = slc / "seen.json"
    seen_path.write_text(json.dumps({"seen_hashes": [], "recent_jobs": []}), encoding="utf-8")

    dead_path = slc / "dead_letter.json"
    dead_path.write_text(json.dumps({"items": []}), encoding="utf-8")

    # monkey-patch config paths
    cfg.STATE_PATH = state_path
    cfg.SEEN_PATH = seen_path
    cfg.DEAD_LETTER_PATH = dead_path
    cfg.SLC_DIR = slc

    return tmp_path


@pytest.fixture
def sample_raw_job():
    from src.models import RawJob
    return RawJob(
        source="indeed",
        title="Machine Learning Engineer",
        company="OpenAI",
        url="https://indeed.com/viewjob?jk=abc123",
        location="Remote",
        salary="$180k-$220k",
        description="Build LLMs at scale. Python, PyTorch required.",
        job_type="full-time",
        tags=["python", "pytorch", "llm"],
    )