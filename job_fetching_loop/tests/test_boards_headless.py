"""Headed-by-default CAPTCHA boards (Indeed/Glassdoor).

The human-in-the-loop CAPTCHA strategy requires a visible browser unless the
operator explicitly opts out. Regression guards: the two boards must not
silently flip to `headless=cfg.scrape_headless()` (default headless) and must
not reintroduce a hardcoded `headless=False` that ignores config entirely.
"""
from __future__ import annotations

import pathlib

import src.config as cfg


def test_board_headless_defaults_headed(monkeypatch):
    monkeypatch.delenv("BOARD_HEADLESS", raising=False)
    assert cfg.board_headless() is False


def test_board_headless_optin(monkeypatch):
    monkeypatch.setenv("BOARD_HEADLESS", "1")
    assert cfg.board_headless() is True


def test_captcha_boards_respect_board_headless():
    scrapers_root = pathlib.Path(__file__).resolve().parent.parent / "src" / "scrapers"
    for fname in ("indeed.py", "glassdoor.py"):
        text = (scrapers_root / fname).read_text(encoding="utf-8")
        assert "headless=cfg.board_headless()" in text, (
            f"{fname} must launch with cfg.board_headless() (headed by default)")


def test_board_headless_ignores_scrape_headless(monkeypatch):
    """SCRAPE_HEADLESS=1 (global) must NOT silently headless the CAPTCHA boards."""
    monkeypatch.setenv("SCRAPE_HEADLESS", "1")
    monkeypatch.delenv("BOARD_HEADLESS", raising=False)
    assert cfg.board_headless() is False