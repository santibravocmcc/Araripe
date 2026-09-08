"""The standalone watch config must not drift from the accepted regime contract.

`scripts/check_esa_reprocessing.py` runs from the repository default branch,
where the Phase 2A rebuild machinery does not exist, so its query parameters
live in a small standalone JSON. That file is a copy, and a copy that nobody
checks is how two sources of truth quietly disagree.

These tests re-derive every value from the live contract, so the copy fails the
gate the moment the regime, the extent, the source years or the collection
changes without it.
"""

from __future__ import annotations

import json
from pathlib import Path

from config.settings import BASELINE_SOURCE_YEARS, GEE_COLLECTION_ID
from src.detection.baseline_manifest import (
    MONITORING_EXTENT_BOUNDS,
    MONITORING_EXTENT_ID,
)
from src.processing.baseline_rebuild_v2 import (
    AMENDMENT_REGIME_V1_PATH,
    AMENDMENT_REGIME_V1_SHA256,
    load_source_regimes,
)

CONFIG = Path("config/esa_reprocessing_watch_query_v1.json")


def _config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def _wet_regime():
    return next(
        regime
        for regime in load_source_regimes()
        if regime.provenance_state == "mixed_lineage_pending_esa_reprocessing"
    )


def test_watch_query_matches_the_pending_regime():
    config = _config()
    wet = _wet_regime()
    query = config["query"]
    assert query["months"] == list(wet.months)
    assert query["scene_cloud_filter_percent"] == wet.scene_cloud_filter_percent
    assert config["derived_from"]["regime_id"] == wet.regime_id
    assert config["derived_from"]["provenance_state"] == wet.provenance_state


def test_watch_query_matches_the_accepted_source_selection():
    query = _config()["query"]
    assert query["collection_id"] == GEE_COLLECTION_ID
    assert query["source_years"] == list(BASELINE_SOURCE_YEARS)
    assert query["monitoring_extent_id"] == MONITORING_EXTENT_ID
    assert query["monitoring_extent_bounds"] == list(MONITORING_EXTENT_BOUNDS)


def test_watch_query_binds_the_amendment_it_came_from():
    binding = _config()["derived_from"]["seasonal_source_regime_amendment"]
    assert binding["path"] == AMENDMENT_REGIME_V1_PATH
    assert binding["sha256"] == AMENDMENT_REGIME_V1_SHA256


def test_watch_script_imports_nothing_from_the_repository():
    """It has to run where src/ and config/settings.py do not exist."""
    source = Path("scripts/check_esa_reprocessing.py").read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        assert not stripped.startswith(("from src.", "from config.")), stripped
        assert not stripped.startswith(("import src", "import config")), stripped


def test_collection1_floor_is_the_criterion_the_owner_reviewed():
    # The 2026-09-05 review admitted a value if and only if its processing
    # baseline is 05.00 or later.
    assert _config()["collection1_processing_baseline_floor"] == "05."
