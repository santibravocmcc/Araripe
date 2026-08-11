"""Package 2A.5 must not decide or mutate the frozen Phase 2A.4 methods."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PHASE2A4_REGISTRY = REPOSITORY_ROOT / "config/phase2a4_candidates_v1.json"
PHASE2A5_REGISTRY = REPOSITORY_ROOT / "config/phase2a5_context_candidates_v1.json"
FROZEN_PHASE2A4_REGISTRY_SHA256 = (
    "3c79ebcd1dd5921d2b9e7a983c25ddd6604ff915d1cd63ab6926aeeeb3cafcc7"
)
ACCEPTED_EXTENT_SOURCE_SHA256 = (
    "2bff31afa6cb74630a437b4fffb96ad88f7f873a3aa1461f337c66f61c209881"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_phase2a4_registry_remains_byte_identical() -> None:
    assert _sha256(PHASE2A4_REGISTRY) == FROZEN_PHASE2A4_REGISTRY_SHA256


def test_phase2a5_registry_keeps_every_scientific_decision_open() -> None:
    registry = json.loads(PHASE2A5_REGISTRY.read_text(encoding="utf-8"))

    assert registry["package_scope"]["phase2a4_candidates_unchanged"] is True
    assert registry["package_scope"]["raw_valid_detections_preserved"] is True
    assert registry["package_scope"]["primary_change_assessment_precedes_context_comparison"] is True
    assert registry["monitoring_extent"]["source_aoi_sha256"] == ACCEPTED_EXTENT_SOURCE_SHA256

    assert all(value is False for value in registry["decision_state"].values())
    assert all(
        candidate["selected_or_activated"] is False
        for candidate in registry["strong_subset"]["candidates"]
    )
    assert all(
        candidate["selected_or_activated"] is False
        for candidate in registry["contextual_signature"]["candidates"]
    )
    assert registry["strong_subset"]["threshold_tuning_to_detection_totals"] is False
    assert registry["strong_subset"]["raw_detection_removal_or_relabeling"] is False
    assert registry["contextual_signature"]["causal_inference_permitted"] is False
    assert registry["contextual_signature"]["phase2a4_method_selection_or_mutation"] is False


def test_phase2a5_source_and_generated_artifact_paths_stay_outside_git() -> None:
    ignored_lines = {
        line.strip()
        for line in (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "data/landcover/updated/" in ignored_lines
    assert "data/landcover/*.tif" in ignored_lines
    assert "data/validation/" in ignored_lines
