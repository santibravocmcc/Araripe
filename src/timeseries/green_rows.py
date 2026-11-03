"""The green time series: one run's rows, and the clean database built from them (D4).

Why this exists
---------------
The only producer of ``regional_stats`` rows is the blue
``run_detection_from_gee.py`` (``store_regional_stats``), stopped since C1.
The green deposit lane computes every index of every pulled datatake to detect
and keeps none of it: ``runs/<id>/`` holds the ledger, the alerts and the
state, not the composites.  So the series has to be measured **in the detect
job**, from the composites on the runner's disk, or not at all.

What it writes, and why that schema
-----------------------------------
Package 2A.2 quarantined ``data/timeseries/timeseries.db`` as a whole — *"build
the corrected 2026 series from empty chronology in a new generation"*
(``src/timeseries/audit.py``) — and defined the clean schema for it
(``src/timeseries/schema.py``: ``processing_generations``, ``acquisitions``,
``regional_stats_v1``).  Nothing has written that schema until now.  This
module writes it and nothing else: it never opens the legacy table, so a green
row and a blue row cannot meet in one table unmarked.

The unit
--------
The blue series is one row per UTC date of a ``daily_mosaic-v1`` composite;
the green one is one row per acquisition of a ``datatake_mosaic-v1`` composite
(``config``-free copy of the method id below).  The clean schema allows one
acquisition per generation and date, so a date with two composites keeps one
and names the other in the document (``superseded``): accepted before
quality-rejected, then the most valid pixels, then the acquisition id.  In the
2026 replay no date had two pulled composites (measured on 2026-11-03: of 17
dates with two datatakes, the second was screened out on coverage every time).

The statistics are ``store_regional_stats_values``'s, on the same valid pixels
``_load_composite`` keeps (``> -9990``): mean, median, population std, min,
max — computed on the float32 band, as the blue path does.

What the ledger decides
-----------------------
The ledger, not the directory, says which composites exist: a row is written
for every acquisition the ledger calls ``complete_*`` (``accepted``) or
``rejected_quality`` (kept, with its reason, because the blue series carried
those dates too and the consumer must decide).  ``rejected_low_coverage``
pulled nothing.  ``failed_*`` is listed as absent, never invented.  An
accepted acquisition's composite must hash to the ``artifact_sha256`` its
terminal row sealed, or the run is refused: that hash is what binds a series
row to the pixels the detection used.

It imports nothing from ``config``: ``config.settings`` loads the production
``.env`` at import (``tests/test_assemble_green_run.py`` guards the scripts).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.timeseries import schema

ROWS_SCHEMA = "araripe.green.timeseries_rows/1"

#: The export band order of ``scripts/build_detection_gee.py`` and
#: ``scripts/replay_2026.py`` (``BANDS``); the test reads both.
BAND_ORDER = ("ndmi", "nbr", "evi2", "bsi")
SERIES_INDICES = ("ndmi", "nbr", "evi2")
REGION = "full_aoi"

#: ``_load_composite`` restores the -9999 export fill with ``da > -9990``.
FILL_THRESHOLD = -9990.0

#: The datatake composite basename, ``build_detection_gee.composite_name``.
COMPOSITE_NAME = "araripe_detect_{observed_on}_{datatake_id}.tif"

#: ``src.detection.baseline_manifest.MONITORING_EXTENT_BOUNDS_SHA256``, copied
#: because that module is not on the ``config``-free side; the test compares.
MONITORING_EXTENT_BOUNDS_SHA256 = (
    "93f254373d6b203bca33aa5c356bd03fec3bff7f43c9c15b368cc2bdb7029f28"
)
#: ``query.reflectance_scale_divisor`` of every run manifest.
REFLECTANCE_SCALING = True

ACCEPTED = ("complete_with_alerts", "complete_zero_alerts")
IN_SERIES = ACCEPTED + ("rejected_quality",)


class RowsRejected(ValueError):
    """The run's outputs cannot support a series row."""


def _canonical(document: Any) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def generation_identity(
    *,
    algorithm_version: str,
    baseline_version: str,
    monitoring_extent_id: str,
    source_collection_id: str,
    composition_method_id: str,
) -> dict[str, Any]:
    """The generation a run's rows belong to, and its id.

    A function of the processing configuration only — no run, date or clock —
    so every run of one chain lands in one generation, and a new algorithm or
    baseline version opens a new one instead of mixing into the old.
    """

    inputs = {
        "algorithm_version": algorithm_version,
        "baseline_version": baseline_version,
        "monitoring_extent_id": monitoring_extent_id,
        "monitoring_extent_sha256": MONITORING_EXTENT_BOUNDS_SHA256,
        "source_collection_id": source_collection_id,
        "composition_method_id": composition_method_id,
        "reflectance_scaling": REFLECTANCE_SCALING,
    }
    digest = hashlib.sha256(_canonical(inputs)).hexdigest()
    return {"generation_id": "gen-g1-" + digest, **inputs}


def band_statistics(values) -> dict[str, Any]:
    """``store_regional_stats_values`` on one band, plus the pixel counts."""

    import numpy as np

    flat = np.asarray(values).ravel()
    total = int(flat.size)
    valid = flat[np.isfinite(flat) & (flat > FILL_THRESHOLD)]
    count = int(valid.size)
    if count == 0:
        return {"valid_pixels": 0, "total_pixels": total, "mean": None,
                "median": None, "std": None, "min": None, "max": None}
    return {
        "valid_pixels": count,
        "total_pixels": total,
        "mean": float(np.mean(valid)),
        "median": float(np.median(valid)),
        "std": float(np.std(valid)),
        "min": float(np.min(valid)),
        "max": float(np.max(valid)),
    }


def composite_statistics(path: Path) -> dict[str, dict[str, Any]]:
    """Each series index of one composite, read band by band."""

    import rasterio

    with rasterio.open(path) as source:
        if source.count < len(SERIES_INDICES):
            raise RowsRejected(f"{path.name} has {source.count} band(s)")
        return {
            name: band_statistics(source.read(BAND_ORDER.index(name) + 1))
            for name in SERIES_INDICES
        }


def _qa(row: Mapping[str, Any]) -> tuple[str, str | None]:
    if row["status"] in ACCEPTED:
        return "accepted", None
    reason = row.get("reason") or {}
    return "rejected_quality", str(reason.get("code") or "rejected_quality")


def _preference(entry: Mapping[str, Any]) -> tuple:
    return (entry["qa_status"] != "accepted", -entry["valid_pixels"],
            entry["acquisition_id"])


def run_rows(
    ledger: Mapping[str, Any],
    composites_dir: Path,
    *,
    baseline_version: str,
    algorithm_version: str,
    measure=composite_statistics,
) -> dict[str, Any]:
    """The rows document of one run, from its sealed ledger and its composites."""

    expected = {item["acquisition_id"]: item for item in ledger["expected_acquisitions"]}
    methods = {item["composite_method_id"] for item in expected.values()}
    collections = {item["collection_id"] for item in expected.values()}
    if len(methods) != 1 or len(collections) != 1:
        raise RowsRejected(f"one run, one method and collection: {methods} {collections}")
    generation = generation_identity(
        algorithm_version=algorithm_version,
        baseline_version=baseline_version,
        monitoring_extent_id=ledger["monitoring_extent_id"],
        source_collection_id=collections.pop(),
        composition_method_id=methods.pop(),
    )

    candidates: dict[str, list[dict[str, Any]]] = {}
    absent: list[dict[str, str]] = []
    for row in ledger["terminal_rows"]:
        if row["status"] not in IN_SERIES:
            if row["status"].startswith("failed_"):
                absent.append({"acquisition_id": row["acquisition_id"],
                               "observed_on": row["observed_on"],
                               "status": row["status"]})
            continue
        item = expected.get(row["acquisition_id"])
        if item is None:
            raise RowsRejected(f"{row['acquisition_id']} is not an expected acquisition")
        path = Path(composites_dir) / COMPOSITE_NAME.format(
            observed_on=row["observed_on"], datatake_id=item["datatake_id"])
        if not path.is_file():
            raise RowsRejected(f"{row['status']} {row['acquisition_id']}: no composite {path.name}")
        digest = sha256_file(path)
        sealed = (row.get("output") or {}).get("artifact_sha256")
        if row["status"] in ACCEPTED and sealed != digest:
            raise RowsRejected(
                f"{path.name} hashes to {digest}, the ledger sealed {sealed}")
        qa_status, qa_reason = _qa(row)
        stats = measure(path)
        pixels = {(s["valid_pixels"], s["total_pixels"]) for s in stats.values()}
        candidates.setdefault(row["observed_on"], []).append({
            "acquisition_id": row["acquisition_id"],
            "observed_on": row["observed_on"],
            "datatake_id": item["datatake_id"],
            "scene_ids": sorted(item["scene_ids"]),
            "source_metadata_sha256": item["identity_inputs_sha256"],
            "ledger_status": row["status"],
            "qa_status": qa_status,
            "qa_reason": qa_reason,
            "composite_sha256": digest,
            # the acquisition's coverage is its most complete band's; the
            # bands share one mask in _prep, and the test pins that they agree
            "valid_pixels": max(v for v, _ in pixels),
            "total_pixels": max(t for _, t in pixels),
            "indices": stats,
        })

    acquisitions, superseded = [], []
    for observed_on in sorted(candidates):
        ranked = sorted(candidates[observed_on], key=_preference)
        acquisitions.append(ranked[0])
        superseded += [{"observed_on": observed_on, "acquisition_id": other["acquisition_id"],
                        "kept": ranked[0]["acquisition_id"]} for other in ranked[1:]]

    return {
        "schema": ROWS_SCHEMA,
        "ledger_id": ledger["ledger_id"],
        "run_manifest_id": ledger["run_manifest_id"],
        "region": REGION,
        "generation": generation,
        "acquisitions": acquisitions,
        "superseded": superseded,
        "absent": absent,
    }


def apply_rows(db_path: Path, documents: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Write rows documents into a clean-schema database, idempotently.

    A date's rows are deleted and rewritten in one transaction, children
    first: ``INSERT OR REPLACE`` on ``acquisitions`` would delete a parent its
    ``regional_stats_v1`` rows still reference, and the schema enforces the
    foreign key.  So a repeated run rewrites its rows instead of adding to
    them.  Never touches the legacy tables.
    """

    db_path = Path(db_path)
    schema.init_clean_database(db_path)
    counts = {"acquisitions": 0, "regional_stats_v1": 0}
    connection = schema.connect_database(db_path)
    try:
        for document in documents:
            if document.get("schema") != ROWS_SCHEMA:
                raise RowsRejected(f"not a {ROWS_SCHEMA} document")
            g = document["generation"]
            connection.execute(
                """INSERT OR IGNORE INTO processing_generations (
                    generation_id, schema_version, algorithm_version,
                    baseline_version, monitoring_extent_id,
                    monitoring_extent_sha256, source_collection_id,
                    composition_method_id, reflectance_scaling, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'candidate')""",
                (g["generation_id"], schema.TIMESERIES_SCHEMA_VERSION,
                 g["algorithm_version"], g["baseline_version"],
                 g["monitoring_extent_id"], g["monitoring_extent_sha256"],
                 g["source_collection_id"], g["composition_method_id"],
                 int(g["reflectance_scaling"])))
            for a in document["acquisitions"]:
                scenes = json.dumps(a["scene_ids"])
                coverage = a["valid_pixels"] / a["total_pixels"]
                key = (g["generation_id"], a["observed_on"])
                connection.execute("DELETE FROM regional_stats_v1 WHERE "
                                   "generation_id = ? AND observed_on = ?", key)
                connection.execute("DELETE FROM acquisitions WHERE "
                                   "generation_id = ? AND observed_on = ?", key)
                connection.execute(
                    """INSERT INTO acquisitions (
                        generation_id, observed_on, acquisition_id,
                        source_collection_id, scene_ids_json,
                        source_metadata_sha256, valid_pixels, total_pixels,
                        coverage_fraction, qa_status, qa_reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (g["generation_id"], a["observed_on"], a["acquisition_id"],
                     g["source_collection_id"], scenes,
                     a["source_metadata_sha256"], a["valid_pixels"],
                     a["total_pixels"], coverage, a["qa_status"], a["qa_reason"]))
                counts["acquisitions"] += 1
                for name, s in sorted(a["indices"].items()):
                    connection.execute(
                        """INSERT INTO regional_stats_v1 (
                            generation_id, acquisition_id, observed_on,
                            index_name, region, source_collection_id,
                            scene_ids_json, baseline_version, algorithm_version,
                            monitoring_extent_id, mean, median, std, min, max,
                            valid_pixels, total_pixels, coverage_fraction,
                            qa_status, qa_reason)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                                ?, ?, ?, ?, ?)""",
                        (g["generation_id"], a["acquisition_id"], a["observed_on"],
                         name, document["region"], g["source_collection_id"],
                         scenes, g["baseline_version"], g["algorithm_version"],
                         g["monitoring_extent_id"], s["mean"], s["median"],
                         s["std"], s["min"], s["max"], s["valid_pixels"],
                         s["total_pixels"], s["valid_pixels"] / s["total_pixels"],
                         a["qa_status"], a["qa_reason"]))
                    counts["regional_stats_v1"] += 1
        connection.commit()
    finally:
        connection.close()
    return counts
