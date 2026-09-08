"""The baseline-year diagnostic must remain executable on Python 3.11."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from click.testing import CliRunner


def _module():
    path = Path(__file__).resolve().parents[1] / "scripts/select_baseline_years.py"
    spec = importlib.util.spec_from_file_location("select_baseline_years", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_snapshot_parses_all_adopted_years():
    module = _module()
    parsed = module.parse_oni(module._ONI_SNAPSHOT)
    assert {2017, 2019, 2021, 2022, 2025}.issubset(parsed)
    assert len(parsed[2025]) == 12


def test_cli_runs_on_python_311_and_marks_ranking_diagnostic(tmp_path):
    module = _module()
    result = CliRunner().invoke(
        module.main,
        ["--min-year", "2025", "--max-year", "2025", "--n", "1"],
    )
    assert result.exit_code == 0, result.output
    assert "diagnostic" in result.output.lower()
    assert "2025" in result.output
