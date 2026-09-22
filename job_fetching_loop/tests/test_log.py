"""Tests for structured logging setup (src/log.py)."""
from __future__ import annotations

import logging
import sys

import pytest

import src.log as log_mod
from src.log import get_logger, setup_logging


@pytest.fixture(autouse=True)
def _reset_logging_config_flag():
    """Isolate tests: setup_logging is a process-wide singleton."""
    log_mod._configured = False
    yield
    log_mod._configured = False


def test_get_logger_returns_named_logger():
    logger = get_logger("my.module")
    assert logger.name == "my.module"
    assert isinstance(logger, logging.Logger)


def test_get_logger_returns_same_instance():
    a = get_logger("same.name")
    b = get_logger("same.name")
    assert a is b


def test_setup_logging_sets_root_level():
    setup_logging(level=logging.DEBUG)
    root = logging.getLogger()
    assert root.level == logging.DEBUG


def test_setup_logging_idempotent():
    """Second call should not override existing config."""
    setup_logging(level=logging.WARNING)
    root = logging.getLogger()
    assert root.level == logging.WARNING

    setup_logging(level=logging.DEBUG)
    assert root.level == logging.WARNING  # unchanged because _configured=True


def test_setup_logging_writes_to_stderr():
    handler = logging.root.handlers[0]
    assert handler.stream is sys.stderr


def test_setup_logging_format_contains_timestamp():
    handler = logging.root.handlers[0]
    fmt = handler.formatter._fmt
    assert "%(asctime)s" in fmt
    assert "%(levelname)" in fmt
    assert "%(name)s" in fmt
