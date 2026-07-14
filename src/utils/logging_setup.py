"""Console + file logging for the pipeline scripts.

Loguru sends everything to stderr only by default, so a long run's logs vanish
when the terminal scrolls or the process ends — and detection runs emit a lot of
important detail (per-date counts, persistence, rejections). This routes logs to
BOTH a clean console (INFO) and a persistent full-detail file (DEBUG) under
``logs/``, matching the convention already used by build_baseline.py /
download_baseline_data.py.

Call :func:`configure_run_logging` once at the top of a script's ``main()``.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from loguru import logger

_CONSOLE_FMT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | {message}"
)
_FILE_FMT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
    "{name}:{function}:{line} | {message}"
)

# repo root = src/utils/logging_setup.py -> parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]


def configure_run_logging(
    name: str,
    *,
    console_level: str = "INFO",
    file_level: str = "DEBUG",
    logs_dir: Path | str | None = None,
) -> Path:
    """Send logs to a clean console (INFO) and a timestamped DEBUG file.

    Parameters
    ----------
    name : str
        Basename for the log file: ``logs/{name}_{YYYYMMDD_HHMMSS}.log``.
    console_level, file_level : str
        Minimum levels for the console and file sinks. The console is INFO by
        default (the per-store DEBUG chatter goes to the file only); set
        ``console_level="DEBUG"`` to mirror everything on the terminal.
    logs_dir : path, optional
        Override the log directory (defaults to ``<repo>/logs``).

    Returns
    -------
    Path
        The log file path (also logged at startup).
    """
    logs_path = Path(logs_dir) if logs_dir else _REPO_ROOT / "logs"
    logs_path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    log_file = logs_path / f"{name}_{timestamp}.log"

    logger.remove()  # drop loguru's default stderr sink
    logger.add(sys.stderr, level=console_level, format=_CONSOLE_FMT)
    logger.add(
        str(log_file),
        level=file_level,
        format=_FILE_FMT,
        rotation="100 MB",
        enqueue=True,      # safe for long/interrupted runs
        backtrace=True,
    )
    logger.info("Logging to {} (console={}, file={})", log_file, console_level, file_level)
    return log_file
