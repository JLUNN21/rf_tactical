"""RF Tactical Monitor - Logging utilities."""

import logging
import os
import sys


def setup_logger(name: str = "rf_tactical", debug: bool = False) -> logging.Logger:
    """Configure and return a logger.

    Logs to app.log without rotation (to avoid Windows file locking issues).
    When debug is True, also logs to stdout.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG if debug else logging.INFO)

    if os.name == "nt":
        base_dir = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        log_dir = os.path.join(base_dir, "rf_tactical", "logs")
    else:
        log_dir = "/var/log/rf_tactical"

    log_file = os.path.join(log_dir, "app.log")
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError:
        log_dir = os.path.join(os.path.expanduser("~"), ".rf_tactical_logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "app.log")

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Use simple FileHandler without rotation to avoid Windows file locking issues
    # The log file will grow indefinitely, but this prevents the PermissionError
    file_handler = logging.FileHandler(log_file, mode='a', delay=True)
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
