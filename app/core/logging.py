"""
core/logging.py
──────────────────────────────────────────────────────────────────────────────
Structured logging setup for the Metis Intelligence backend.

• Log level is driven by the LOG_LEVEL env var (default INFO).
• JSON-friendly format: timestamp | level | logger | message
• Extra dict keys (method, path, status_code …) are appended automatically
  by the stdlib logging machinery when passed via the `extra` kwarg.
──────────────────────────────────────────────────────────────────────────────
"""

import logging
import sys


def setup_logging() -> None:
    """
    Configure root logger once at application startup.
    Subsequent calls are no-ops thanks to `force=True`.
    """
    # Import here to avoid circular imports during module load
    from app.core.config import get_settings

    settings = get_settings()
    level = getattr(logging, settings.log_level, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Call after setup_logging() has run."""
    return logging.getLogger(name)
