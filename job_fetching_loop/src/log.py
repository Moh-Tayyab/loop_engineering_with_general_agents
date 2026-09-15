"""Structured logging setup for the job fetching loop.

Replaces bare print() with timestamped, leveled, module-named records so
cron logs are greppable and errors are distinguishable from routine info.
All records go to stderr so stdout stays reserved for CLI/scripting output.
"""
from __future__ import annotations

import logging
import sys

_FMT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_DATEFMT = "%Y-%m-%dT%H:%M:%S"

_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    """Idempotent root-logger configuration (call once at startup)."""
    global _configured
    if _configured:
        return
    logging.basicConfig(
        level=level,
        format=_FMT,
        datefmt=_DATEFMT,
        stream=sys.stderr,
        force=True,
    )
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)