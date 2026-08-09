"""Operational guards for the unaccepted drought adjustment."""

from __future__ import annotations

import inspect
from pathlib import Path

from click.testing import CliRunner

import scripts.run_detection as streaming
import scripts.run_detection_from_gee as from_gee
import scripts.run_detection_gee as gee


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_OPTIONS = {
    "--spi",
    "--no-spi",
    "--audit-only-unaccepted-legacy-spi",
    "--no-audit-only-unaccepted-legacy-spi",
}


def test_operational_entrypoints_expose_no_drought_adjustment_switch() -> None:
    for command in (streaming.main, from_gee.main, gee.main):
        option_names = {
            name
            for parameter in command.params
            for name in (*parameter.opts, *parameter.secondary_opts)
        }
        assert option_names.isdisjoint(FORBIDDEN_OPTIONS)
        assert not any("spi" in parameter.name for parameter in command.params)
        help_result = CliRunner().invoke(command, ["--help"])
        assert help_result.exit_code == 0
        assert "legacy SPI" not in help_result.output

    parameters = inspect.signature(from_gee.run_detection_on_dir).parameters
    assert not any("spi" in name for name in parameters)


def test_operational_detection_hard_codes_drought_input_to_none() -> None:
    streaming_source = (REPOSITORY_ROOT / "scripts/run_detection.py").read_text(
        encoding="utf-8"
    )
    gee_source = (
        REPOSITORY_ROOT / "scripts/run_detection_from_gee.py"
    ).read_text(encoding="utf-8")
    for source in (streaming_source, gee_source):
        assert "get_current_spi" not in source
        assert "spi_value" not in source
        assert "spi_3month=None" in source
        assert "operational detection always passes spi_3month=None" in source


def test_scheduled_workflows_have_no_legacy_spi_route() -> None:
    for relative, command in (
        (".github/workflows/detect_gee.yml", "python scripts/run_detection_gee.py"),
        (".github/workflows/update_data.yml", "python scripts/run_detection.py"),
    ):
        source = (REPOSITORY_ROOT / relative).read_text(encoding="utf-8")
        assert command in source
        assert all(option not in source for option in FORBIDDEN_OPTIONS)

    for relative in (
        "scripts/run_detection.py",
        "scripts/run_detection_from_gee.py",
        "scripts/run_detection_gee.py",
    ):
        source = (REPOSITORY_ROOT / relative).read_text(encoding="utf-8")
        assert all(option not in source for option in FORBIDDEN_OPTIONS)
