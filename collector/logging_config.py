from __future__ import annotations

import logging
import os
from pathlib import Path

from collector.project_paths import LOGS_DIR

LOGGER_NAME = "spending_tracker"


def is_debug() -> bool:
    return os.environ.get("SPENDING_DEBUG", "").strip().lower() in {"1", "true", "yes"}


def setup_logging(debug: bool | None = None) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger

    debug = is_debug() if debug is None else debug
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    formatter = logging.Formatter("[%(levelname)s] %(message)s")

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(stream)

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = Path(LOGS_DIR) / "collector.log"
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    logger.addHandler(file_handler)

    logger.propagate = False
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
