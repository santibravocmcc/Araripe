#!/usr/bin/env python3
"""Deterministically regenerate the seven v3 contract examples.

The v3 examples cannot be text-ported from the v2 examples because every
identity, checksum, and digest changes with the v3 identity domains.  This
script therefore drives the v3 runtime itself through the same fixture
scenario the v2 family documents — two same-day physical datatakes where the
second datatake's two observations split the origin event — with one
deliberate difference: the second datatake is **Sentinel-2C**, exercising
exactly the capability the 2026-09-01 amendment authorizes.

Run locally from the backend repository:

    /opt/anaconda3/envs/araripe/bin/python \
        docs/contracts/phase2a/generate_v3_examples.py

The pytest gate re-derives the documents through :func:`build_documents` and
requires the committed example bytes to match, so the fixtures cannot drift
from the runtime.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = ROOT.parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from shapely.geometry import Polygon

from src.detection.contracts_v3 import validate_v3_document
from src.detection.identity import identity_sha256
from src.detection.identity_v3 import (
    create_acquisition_v3,
    create_observation_v3,
    origin_event_id_v3,
)
from src.detection.ledger_v3 import ProcessingLedgerV3
from src.detection.persistence_v3 import (
    apply_terminal_date_v3,
    contribution_key_v3,
    empty_persistence_state_v3,
)

EXAMPLES = ROOT / "examples"
MANIFEST_ID = "run-v3-" + "a" * 64
MANIFEST_SHA256 = "b" * 64
COLLECTION_ID = "COPERNICUS/S2_SR_HARMONIZED"
EXTENT_ID = "araripe-implementation-rectangle-v1"
METHOD_ID = "coverage-ranked-first-valid-v1"
GRID_ID = "araripe-sentinel2-20m-grid-v1"
ALGORITHM_VERSION = "2.0.0"
BASELINE_VERSION = "2.0.0"
OBSERVED_ON = "2026-04-07"
GENERATION_ID = "gen-v3-" + identity_sha256("phase2a6b1-v3-example-generation")


def _square(west: float, east: float) -> Polygon:
    return Polygon(
        [(west, -7.1), (east, -7.1), (east, -7.0), (west, -7.0), (west, -7.1)]
    )


def build_documents() -> dict[str, dict[str, Any]]:
    acquisition_s2a = create_acquisition_v3(
        run_manifest_id=MANIFEST_ID,
        run_manifest_sha256=MANIFEST_SHA256,
        collection_id=COLLECTION_ID,
        platform="S2A",
        datatake_id="GS2A_20260407T131241_055725_N05.11",
        acquisition_timestamp_utc="2026-04-07T13:12:41Z",
        scene_ids=[
            f"{COLLECTION_ID}/20260407T131241_20260407T131238_T24LWK",
            f"{COLLECTION_ID}/20260407T131241_20260407T131238_T24LWL",
        ],
        monitoring_extent_id=EXTENT_ID,
        composite_method_id=METHOD_ID,
        grid_id=GRID_ID,
    )
    acquisition_s2c = create_acquisition_v3(
        run_manifest_id=MANIFEST_ID,
        run_manifest_sha256=MANIFEST_SHA256,
        collection_id=COLLECTION_ID,
        platform="S2C",
        datatake_id="GS2C_20260407T132251_008788_N05.11",
        acquisition_timestamp_utc="2026-04-07T13:22:51Z",
        scene_ids=[
            f"{COLLECTION_ID}/20260407T132251_20260407T132248_T24LWK",
            f"{COLLECTION_ID}/20260407T132251_20260407T132248_T24LWL",
        ],
        monitoring_extent_id=EXTENT_ID,
        composite_method_id=METHOD_ID,
        grid_id=GRID_ID,
    )

    origin_observation = create_observation_v3(
        acquisition=acquisition_s2a,
        geometry=_square(-40.0, -39.9),
        algorithm_version=ALGORITHM_VERSION,
        baseline_version=BASELINE_VERSION,
        area_ha=123.5,
        created_at="2026-04-07T13:30:00Z",
    )
    split_west = create_observation_v3(
        acquisition=acquisition_s2c,
        geometry=_square(-40.0, -39.95),
        algorithm_version=ALGORITHM_VERSION,
        baseline_version=BASELINE_VERSION,
        area_ha=61.75,
        created_at="2026-04-07T13:35:00Z",
    )
    split_east = create_observation_v3(
        acquisition=acquisition_s2c,
        geometry=_square(-39.95, -39.9),
        algorithm_version=ALGORITHM_VERSION,
        baseline_version=BASELINE_VERSION,
        area_ha=61.75,
        created_at="2026-04-07T13:35:00Z",
    )

    ledger = ProcessingLedgerV3(
        run_manifest_id=MANIFEST_ID,
        run_manifest_sha256=MANIFEST_SHA256,
        acquisitions=(acquisition_s2a, acquisition_s2c),
        monitoring_extent_id=EXTENT_ID,
        algorithm_version=ALGORITHM_VERSION,
        created_at="2026-04-07T14:00:00Z",
    )
    ledger.record_terminal(
        acquisition_id=acquisition_s2a.acquisition_id,
        status="complete_with_alerts",
        observation_ids=[origin_observation.observation_id],
        terminal_at="2026-04-07T13:50:00Z",
        artifact_sha256="c" * 64,
    )
    ledger.record_terminal(
        acquisition_id=acquisition_s2c.acquisition_id,
        status="complete_with_alerts",
        observation_ids=[
            split_west.observation_id,
            split_east.observation_id,
        ],
        terminal_at="2026-04-07T13:50:00Z",
        artifact_sha256="d" * 64,
    )

    empty_state = empty_persistence_state_v3(
        generation_id=GENERATION_ID,
        ledger=ledger,
        baseline_version=BASELINE_VERSION,
        generated_at="2026-04-07T13:00:00Z",
    )
    transition = apply_terminal_date_v3(
        state=empty_state,
        ledger=ledger,
        observed_on=OBSERVED_ON,
        observations=[origin_observation, split_west, split_east],
        transitioned_at="2026-04-07T14:00:00Z",
    )
    state = transition.state

    origin_event_id = origin_event_id_v3(origin_observation.observation_id)
    origin_event = next(
        item for item in state["events"] if item["event_id"] == origin_event_id
    )
    split_edge = next(
        item for item in state["lineage"] if item["relation"] == "split"
    )
    origin_contribution_key = contribution_key_v3(origin_event_id, OBSERVED_ON)
    origin_contribution = next(
        item
        for item in state["contributions"]
        if item["contribution_key"] == origin_contribution_key
    )

    documents = {
        "acquisition-v3": acquisition_s2a.to_dict(),
        "observation-v3": origin_observation.to_dict(),
        "event-v3": origin_event,
        "lineage-v3": split_edge,
        "persistence-contribution-v3": origin_contribution,
        "persistence-state-v3": state,
        "processing-ledger-v3": ledger.to_dict(),
    }
    for name, document in documents.items():
        validate_v3_document(name, document)
    return documents


def main() -> None:
    documents = build_documents()
    for name, document in documents.items():
        path = EXAMPLES / f"{name}.example.json"
        path.write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {path.relative_to(REPOSITORY_ROOT)}")


if __name__ == "__main__":
    main()
