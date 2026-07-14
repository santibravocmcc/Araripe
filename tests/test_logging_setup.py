"""configure_run_logging must persist a full-detail log file under logs/."""

import sys
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.utils.logging_setup import configure_run_logging  # noqa: E402


def _flush_and_restore():
    logger.remove()          # joins the enqueue thread -> flushes the file sink
    logger.add(sys.stderr)   # restore a default sink for the rest of the session


def test_creates_logfile_capturing_debug(tmp_path):
    log_file = configure_run_logging("unittest_run", logs_dir=tmp_path, console_level="INFO")
    logger.info("an info line here")
    logger.debug("a debug line xyz")
    _flush_and_restore()

    assert log_file.exists()
    text = log_file.read_text()
    assert "an info line here" in text
    # File sink is DEBUG even when the console is INFO, so detail is never lost.
    assert "a debug line xyz" in text


def test_logfile_naming_and_dir_created(tmp_path):
    d = tmp_path / "nested" / "logs"
    log_file = configure_run_logging("myscript", logs_dir=d)
    _flush_and_restore()

    assert d.is_dir()
    assert log_file.parent == d
    assert log_file.name.startswith("myscript_")
    assert log_file.suffix == ".log"
