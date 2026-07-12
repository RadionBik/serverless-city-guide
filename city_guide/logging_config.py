"""Centralized logging configuration with optional file rotation."""

import logging
import sys
from logging.handlers import RotatingFileHandler

from city_guide.config import LogConfig, get_log_file, get_log_level

LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"

_configured = False


def setup_logging(*, log_file: str | None = None) -> None:
    """Configure the root logger with stderr and optional file handlers.

    Parameters
    ----------
    log_file:
        Explicit log file path.  When *None* (default), the value is
        read from the ``LOG_FILE`` env var / config default.

    The function is idempotent — calling it a second time is a no-op.
    """
    global _configured
    if _configured:
        return

    root = logging.getLogger()

    level = getattr(logging, get_log_level().upper(), logging.INFO)
    root.setLevel(level)

    formatter = logging.Formatter(LOG_FORMAT)

    # --- stderr handler ---
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    # Third-party request noise off unless debugging; city_guide.* INFO is the status signal.
    if level > logging.DEBUG:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)

    # --- optional rotating file handler ---
    # Empty string (e.g. LOG_FILE="") is treated as no file.
    resolved_file = log_file if log_file is not None else get_log_file()
    if resolved_file:
        file_handler = RotatingFileHandler(
            resolved_file,
            maxBytes=LogConfig.max_bytes,
            backupCount=LogConfig.backup_count,
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    _configured = True
