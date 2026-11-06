"""Atomic publication of PTE cache files."""

import logging
import os
from pathlib import Path
import time as clock


_LOGGER = logging.getLogger(__name__)
_FILE_REPLACE_DELAYS = (0.025, 0.050, 0.100, 0.200) if os.name == "nt" else ()


def replace_published_file(source: Path, target: Path) -> None:
    """Retry short Windows access conflicts while retaining atomic replacement."""
    for attempt in range(len(_FILE_REPLACE_DELAYS) + 1):
        try:
            os.replace(source, target)
        except OSError as error:
            winerror = getattr(error, "winerror", None)
            if winerror not in (5, 32) or attempt == len(_FILE_REPLACE_DELAYS):
                if attempt:
                    _LOGGER.error("File replacement failed after %d attempts: %s -> %s (winerror=%s)",
                                  attempt + 1, source, target, winerror)
                raise
            clock.sleep(_FILE_REPLACE_DELAYS[attempt])
        else:
            if attempt:
                _LOGGER.warning("File replacement recovered after %d retries: %s -> %s", attempt, source, target)
            return
