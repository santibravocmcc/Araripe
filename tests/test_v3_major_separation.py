"""Fail-closed boundaries between the v2 (audit-only) and v3 families."""

from pathlib import Path
import json

import pytest

from src.detection.contracts_v2 import (
    ContractV2ValidationError,
    validate_v2_document,
)
from src.detection.contracts_v3 import (
    ContractV3ValidationError,
    validate_v3_document,
)
from src.detection.identity_v2 import (
    AcquisitionV2,
    IdentityMajorError as IdentityMajorErrorV2,
    create_acquisition_v2,
    require_v2_id,
)
from src.detection.identity_v3 import (
    AcquisitionV3,
    IdentityMajorError as IdentityMajorErrorV3,
    create_acquisition_v3,
    require_v3_id,
)
from src.detection.ledger_v2 import ProcessingLedgerV2
from src.detection.ledger_v3 import ProcessingLedgerV3
from src.detection.persistence_v2 import validate_persistence_state_v2
from src.detection.persistence_v3 import validate_persistence_state_v3


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "docs" / "contracts" / "phase2a" / "examples"
EXTENT_ID = "araripe-implementation-rectangle-v1"
METHOD_ID = "coverage-ranked-first-valid-v1"
GRID_ID = "araripe-sentinel2-20m-grid-v1"
CONTRACT_NAMES = (
    "acquisition",
    "observation",
    "event",
    "lineage",
    "persistence-contribution",
    "persistence-state",
    "processing-ledger",
)


def _example(name: str, major: str) -> dict:
    return json.loads(
        (EXAMPLES / f"{name}-{major}.example.json").read_text(encoding="utf-8")
    )


def _acquisition_v3(platform="S2C"):
    return create_acquisition_v3(
        run_manifest_id="run-v3-" + "a" * 64,
        run_manifest_sha256="b" * 64,
        collection_id="COPERNICUS/S2_SR_HARMONIZED",
        platform=platform,
        datatake_id="GS2C_20260512T130251_008788_N05.12"
        if platform == "S2C"
        else "GS2A_20260512T130251_008788_N05.12",
        acquisition_timestamp_utc="2026-05-12T13:02:51Z",
        scene_ids=["scene-1"],
        monitoring_extent_id=EXTENT_ID,
        composite_method_id=METHOD_ID,
        grid_id=GRID_ID,
    )


class TestPlatformMatrix:
    @pytest.mark.parametrize("platform", ["S2A", "S2B", "S2C"])
    def test_v3_accepts_the_reviewed_constellation_units(self, platform):
        datatake_id = f"GS2{platform[-1]}_20260512T130251_008788_N05.12"
        acquisition = create_acquisition_v3(
            run_manifest_id="run-v3-" + "a" * 64,
            run_manifest_sha256="b" * 64,
            collection_id="COPERNICUS/S2_SR_HARMONIZED",
            platform=platform,
            datatake_id=datatake_id,
            acquisition_timestamp_utc="2026-05-12T13:02:51Z",
            scene_ids=["scene-1"],
            monitoring_extent_id=EXTENT_ID,
            composite_method_id=METHOD_ID,
            grid_id=GRID_ID,
        )
        assert acquisition.platform == platform
        assert acquisition.acquisition_id.startswith("acq-v3-")

    @pytest.mark.parametrize("platform", ["S2D", "S2E", "sentinel-2c", ""])
    def test_v3_fails_closed_for_unreviewed_or_raw_labels(self, platform):
        with pytest.raises(ValueError):
            create_acquisition_v3(
                run_manifest_id="run-v3-" + "a" * 64,
                run_manifest_sha256="b" * 64,
                collection_id="COPERNICUS/S2_SR_HARMONIZED",
                platform=platform,
                datatake_id="dt-1",
                acquisition_timestamp_utc="2026-05-12T13:02:51Z",
                scene_ids=["scene-1"],
                monitoring_extent_id=EXTENT_ID,
                composite_method_id=METHOD_ID,
                grid_id=GRID_ID,
            )

    def test_v2_platform_guard_is_unchanged(self):
        with pytest.raises(ValueError, match="S2A or S2B"):
            create_acquisition_v2(
                run_manifest_id="run-v2-" + "a" * 64,
                run_manifest_sha256="b" * 64,
                collection_id="COPERNICUS/S2_SR_HARMONIZED",
                platform="S2C",
                datatake_id="GS2C_20260512T130251_008788_N05.12",
                acquisition_timestamp_utc="2026-05-12T13:02:51Z",
                scene_ids=["scene-1"],
                monitoring_extent_id=EXTENT_ID,
                composite_method_id=METHOD_ID,
                grid_id=GRID_ID,
            )

    def test_identities_use_disjoint_domains_for_identical_physical_inputs(self):
        shared = dict(
            run_manifest_sha256="b" * 64,
            collection_id="COPERNICUS/S2_SR_HARMONIZED",
            platform="S2A",
            datatake_id="GS2A_20260512T130251_008788_N05.12",
            acquisition_timestamp_utc="2026-05-12T13:02:51Z",
            scene_ids=["scene-1"],
            monitoring_extent_id=EXTENT_ID,
            composite_method_id=METHOD_ID,
            grid_id=GRID_ID,
        )
        v2 = create_acquisition_v2(
            run_manifest_id="run-v2-" + "a" * 64, **shared
        )
        v3 = create_acquisition_v3(
            run_manifest_id="run-v3-" + "a" * 64, **shared
        )
        assert v2.identity_inputs_sha256 != v3.identity_inputs_sha256


class TestIdentityBoundaries:
    def test_prefix_guards_reject_the_other_major(self):
        with pytest.raises(IdentityMajorErrorV2):
            require_v2_id(
                "acq-v3-" + "0" * 64, prefix="acq-v2-", label="acquisition_id"
            )
        with pytest.raises(IdentityMajorErrorV3):
            require_v3_id(
                "acq-v2-" + "0" * 64, prefix="acq-v3-", label="acquisition_id"
            )

    def test_from_dict_rejects_the_other_major(self):
        with pytest.raises(IdentityMajorErrorV2):
            AcquisitionV2.from_dict(_example("acquisition", "v3"))
        with pytest.raises(IdentityMajorErrorV3):
            AcquisitionV3.from_dict(_example("acquisition", "v2"))

    @pytest.mark.parametrize("name", CONTRACT_NAMES)
    def test_contract_boundaries_reject_the_other_major(self, name):
        with pytest.raises(ContractV2ValidationError):
            validate_v2_document(f"{name}-v2", _example(name, "v3"))
        with pytest.raises(ContractV3ValidationError):
            validate_v3_document(f"{name}-v3", _example(name, "v2"))

    def test_examples_carry_no_foreign_major_identities(self):
        for name in CONTRACT_NAMES:
            v3_bytes = json.dumps(_example(name, "v3"))
            assert "-v2-" not in v3_bytes and "-v1-" not in v3_bytes
            v2_bytes = json.dumps(_example(name, "v2"))
            assert "-v3-" not in v2_bytes


class TestLedgerAndStateBoundaries:
    def test_v2_ledger_rejects_v3_acquisitions(self):
        acquisition = _acquisition_v3()
        with pytest.raises(IdentityMajorErrorV2):
            ProcessingLedgerV2(
                run_manifest_id="run-v3-" + "a" * 64,
                run_manifest_sha256="b" * 64,
                acquisitions=(acquisition,),
                monitoring_extent_id=EXTENT_ID,
                algorithm_version="2.0.0",
                created_at="2026-05-13T00:00:00Z",
            )
        with pytest.raises(ValueError, match="manifest binding"):
            ProcessingLedgerV2(
                run_manifest_id="run-v2-" + "a" * 64,
                run_manifest_sha256="b" * 64,
                acquisitions=(acquisition,),
                monitoring_extent_id=EXTENT_ID,
                algorithm_version="2.0.0",
                created_at="2026-05-13T00:00:00Z",
            )

    def test_v3_ledger_rejects_v2_acquisitions(self):
        acquisition = create_acquisition_v2(
            run_manifest_id="run-v2-" + "a" * 64,
            run_manifest_sha256="b" * 64,
            collection_id="COPERNICUS/S2_SR_HARMONIZED",
            platform="S2A",
            datatake_id="GS2A_20260512T130251_008788_N05.12",
            acquisition_timestamp_utc="2026-05-12T13:02:51Z",
            scene_ids=["scene-1"],
            monitoring_extent_id=EXTENT_ID,
            composite_method_id=METHOD_ID,
            grid_id=GRID_ID,
        )
        with pytest.raises(IdentityMajorErrorV3):
            ProcessingLedgerV3(
                run_manifest_id="run-v2-" + "a" * 64,
                run_manifest_sha256="b" * 64,
                acquisitions=(acquisition,),
                monitoring_extent_id=EXTENT_ID,
                algorithm_version="2.0.0",
                created_at="2026-05-13T00:00:00Z",
            )
        with pytest.raises(ValueError, match="manifest binding"):
            ProcessingLedgerV3(
                run_manifest_id="run-v3-" + "a" * 64,
                run_manifest_sha256="b" * 64,
                acquisitions=(acquisition,),
                monitoring_extent_id=EXTENT_ID,
                algorithm_version="2.0.0",
                created_at="2026-05-13T00:00:00Z",
            )

    def test_state_validators_reject_the_other_major(self):
        with pytest.raises(ContractV2ValidationError):
            validate_persistence_state_v2(_example("persistence-state", "v3"))
        with pytest.raises(ContractV3ValidationError):
            validate_persistence_state_v3(_example("persistence-state", "v2"))
