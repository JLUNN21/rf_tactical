"""RF Tactical Monitor - Logging utilities."""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler


def setup_logger(name: str = "rf_tactical", debug: bool = False) -> logging.Logger:
    """Configure and return a logger.

    Logs to /var/log/rf_tactical/app.log with rotation.
    When debug is True, also logs to stdout.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG if debug else logging.INFO)

    log_dir = "/var/log/rf_tactical"
    log_file = os.path.join(log_dir, "app.log")
    os.makedirs(log_dir, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3)
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)

    if debug:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(logging.DEBUG)
        logger.addHandler(stream_handler)

    logger.propagate = False
    return logger