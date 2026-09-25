"""Single-writer + cloud-safe source guards."""
from __future__ import annotations

import src.config as cfg


def test_job_loop_disabled(monkeypatch):
    monkeypatch.setenv("JOB_LOOP_ENABLED", "0")
    monkeypatch.delenv("JOB_LOOP_CLOUD", raising=False)
    assert cfg.job_loop_should_run() is False


def test_primary_github_skips_local(monkeypatch):
    monkeypatch.setenv("JOB_LOOP_ENABLED", "1")
    monkeypatch.setenv("JOB_LOOP_PRIMARY", "github")
    monkeypatch.delenv("JOB_LOOP_CLOUD", raising=False)
    assert cfg.job_loop_should_run() is False


def test_primary_github_runs_on_cloud(monkeypatch):
    monkeypatch.setenv("JOB_LOOP_ENABLED", "1")
    monkeypatch.setenv("JOB_LOOP_PRIMARY", "github")
    monkeypatch.setenv("JOB_LOOP_CLOUD", "1")
    assert cfg.job_loop_should_run() is True


def test_primary_local_skips_cloud(monkeypatch):
    monkeypatch.setenv("JOB_LOOP_PRIMARY", "local")
    monkeypatch.setenv("JOB_LOOP_CLOUD", "1")
    assert cfg.job_loop_should_run() is False


def test_cloud_disables_browser_sources(monkeypatch):
    monkeypatch.setenv("JOB_LOOP_CLOUD", "1")
    monkeypatch.delenv("CLOUD_ALLOW_BROWSER", raising=False)
    monkeypatch.delenv("SOURCE_INDEED", raising=False)
    monkeypatch.delenv("SOURCE_GLASSDOOR", raising=False)
    assert cfg.allow_browser_scrapers() is False
    assert cfg.source_enabled("indeed") is False
    assert cfg.source_enabled("glassdoor") is False
    assert cfg.source_enabled("linkedin") is True


def test_cloud_can_opt_in_browser(monkeypatch):
    monkeypatch.setenv("JOB_LOOP_CLOUD", "1")
    monkeypatch.setenv("CLOUD_ALLOW_BROWSER", "1")
    monkeypatch.delenv("SOURCE_INDEED", raising=False)
    assert cfg.allow_browser_scrapers() is True
    assert cfg.source_enabled("indeed") is True


def test_pytest_actions_without_cloud_flag_keeps_browser_sources(monkeypatch):
    """test-gate.yml sets GITHUB_ACTIONS but must not hide indeed/glassdoor."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("JOB_LOOP_CLOUD", raising=False)
    monkeypatch.delenv("SOURCE_INDEED", raising=False)
    assert cfg.allow_browser_scrapers() is True
    assert cfg.source_enabled("indeed") is True


def test_captcha_timeout_zero_on_cloud_by_default(monkeypatch):
    monkeypatch.setenv("JOB_LOOP_CLOUD", "1")
    monkeypatch.delenv("CAPTCHA_SOLVE_TIMEOUT", raising=False)
    assert cfg.captcha_solve_timeout() == 0.0


def test_linkedin_default_enabled(monkeypatch):
    monkeypatch.delenv("SOURCE_LINKEDIN", raising=False)
    assert cfg.source_enabled("linkedin") is True


def test_main_skips_when_github_is_primary(monkeypatch, tmp_slc):
    monkeypatch.setenv("JOB_LOOP_PRIMARY", "github")
    monkeypatch.delenv("JOB_LOOP_CLOUD", raising=False)
    import src.main as main
    assert main.main(["--window", "daily"]) == 0
