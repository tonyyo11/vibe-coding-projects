"""
Logging helpers for Jamf Health Tool.
"""

from __future__ import annotations

import logging
from typing import Optional


def setup_logging(verbose: bool = False, quiet: bool = False, logger_name: Optional[str] = None) -> logging.Logger:
    """
    Configure root logger or a named logger based on verbosity flags.

    Parameters
    ----------
    verbose: bool
        When True, set level to DEBUG.
    quiet: bool
        When True, set level to WARNING.
    logger_name: Optional[str]
        Name of a specific logger; defaults to root.
    """
    if verbose and quiet:
        level = logging.INFO
    elif verbose:
        level = logging.DEBUG
    elif quiet:
        level = logging.WARNING
    else:
        level = logging.INFO

    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    return logger
