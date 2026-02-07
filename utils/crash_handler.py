"""RF Tactical Monitor - Crash handler for unhandled exceptions."""

import logging
import os
import sys
import traceback


def install_crash_handler(logger: logging.Logger) -> None:
    """Install a global exception hook that logs and restarts the app."""

    def _handle_exception(exc_type, exc, tb):
        logger.error("Unhandled exception", exc_info=(exc_type, exc, tb))
        # Avoid auto-restart loops while diagnosing startup failures.
        # Print the actual exception details to stdout.
        traceback.print_exception(exc_type, exc, tb)

    sys.excepthook = _handle_exception