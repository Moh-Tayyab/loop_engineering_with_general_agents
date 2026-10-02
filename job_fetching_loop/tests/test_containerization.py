"""Tests for Phase 4 (A4) Containerization — Dockerfile, docker-compose, .dockerignore."""
from __future__ import annotations

from pathlib import Path
import re


def test_dockerfile_exists_and_matches_playwright_pin():
    root = Path(__file__).resolve().parent.parent
    dockerfile = root / "Dockerfile"
    req_file = root / "requirements.txt"
    assert dockerfile.is_file(), "Dockerfile must exist at root of job_fetching_loop"
    assert req_file.is_file(), "requirements.txt must exist"

    df_content = dockerfile.read_text(encoding="utf-8")
    req_content = req_file.read_text(encoding="utf-8")

    # Match playwright pin in requirements.txt (e.g. playwright==1.62.0)
    req_match = re.search(r"^playwright==([0-9.]+)", req_content, re.MULTILINE)
    assert req_match, "playwright pin not found in requirements.txt"
    pw_version = req_match.group(1)

    # Base image must strictly match the playwright pin and noble release (A4 requirement)
    expected_base = f"mcr.microsoft.com/playwright/python:v{pw_version}-noble"
    assert f"FROM {expected_base}" in df_content, f"Dockerfile must use base image {expected_base}"

    # Must run as non-root pwuser
    assert re.search(r"^\s*USER\s+pwuser\b", df_content, re.MULTILINE), "Dockerfile must switch to non-root pwuser"

    # Must create .slc, .runtime, output
    assert ".slc" in df_content and ".runtime" in df_content and "output" in df_content


def test_docker_compose_valid_structure():
    root = Path(__file__).resolve().parent.parent
    compose_file = root / "docker-compose.yml"
    assert compose_file.is_file(), "docker-compose.yml must exist"

    content = compose_file.read_text(encoding="utf-8")
    # Basic structural validations
    assert "services:" in content
    assert "job-loop:" in content
    assert "volumes:" in content
    assert ".slc:/app/.slc" in content
    assert ".runtime:/app/.runtime" in content
    assert "output:/app/output" in content


def test_dockerignore_covers_secrets_and_runtime_state():
    root = Path(__file__).resolve().parent.parent
    ignore_file = root / ".dockerignore"
    assert ignore_file.is_file(), ".dockerignore must exist"

    content = ignore_file.read_text(encoding="utf-8").splitlines()
    entries = {line.strip() for line in content if line.strip() and not line.startswith("#")}

    assert ".env" in entries, ".env secrets must be excluded from docker build"
    assert ".git" in entries, ".git must be ignored"
    assert ".slc" in entries, ".slc runtime state must be ignored"
    assert "output" in entries, "output dir must be ignored"
