"""The version set the 2026 replay is frozen against.

Phase 3, scope item 2 — the roadmap bullet *"Freeze the wider monitoring
extent, algorithm, baseline, cloud/mosaic, drought, MapBiomas, label, schema,
environment, and release versions"*.

A freeze that is not verifiable by test is not a freeze
------------------------------------------------------
The obvious way to satisfy that bullet is a document listing ten version
strings.  It would be wrong within a week: nothing connects the prose to the
constants, so a threshold change would leave the document quietly describing a
system that no longer exists, and the replay would be reconciled against a
freeze nobody had broken because nobody could.

So :func:`build_freeze` reads every value **from the module that owns it** and
:func:`validate_freeze` re-reads them and fails closed on any disagreement.
The checked-in document, ``config/phase3_replay_freeze_v1.json``, is therefore
a *measurement*, and changing a frozen constant breaks
``tests/test_replay_freeze.py`` with the field named.

What is deliberately **not** frozen here
----------------------------------------
* **The cutoff date.** It is a rule resolved at Phase 4 query time
  (:mod:`src.replay.cutoff`), and none of the ten version groups depends on
  it, which is exactly why the freeze can stand while the date is still open.
* **Which baseline generation the replay uses.** The freeze records both
  registered generations with their identities and marks the choice as the
  owner's, open.  Recording a default here would decide a scientific question
  by omission — and it is the most consequential decision of this phase,
  because the whole year is compared against whatever wins.
* **Anything the producer does not promise.** The detection export's grid, for
  instance, is recorded as *requested* (``crs`` + ``scale``, no pinned
  transform) rather than as the baseline grid, because nothing guarantees the
  two align.

Determinism
-----------
No clock, no network, no object store, no credential.  The document's bytes
are a function of the repository's constants and of the paths handed in, so
the same tree always produces the same freeze, and its ``freeze_sha256``
identifies it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from config import settings
from src.detection.baseline_manifest import (
    MONITORING_EXTENT_BOUNDS,
    MONITORING_EXTENT_BOUNDS_SHA256,
    MONITORING_EXTENT_GEOMETRY_SHA256,
    MONITORING_EXTENT_ID,
)
from src.detection.baseline_selection import (
    BASELINE_GENERATIONS,
    SUPERSEDED_GENERATIONS,
)
from src.detection.identity import canonical_sha256
from src.detection.identity_v3 import SCHEMA_VERSION as IDENTITY_SCHEMA_VERSION
from src.detection.ledger_v3 import TERMINAL_STATUSES
from src.detection.persistence import CONFIRMED_MIN, DEFAULT_MIN_OVERLAP_FRAC, GRACE_DAYS
from src.processing.composition_v2 import (
    COMPOSITION_METHOD_ID,
    COMPOSITION_SCOPE_VERSION,
    PIXEL_SELECTION_POLICY,
    SCENE_ORDER_POLICY,
)
from src.processing.scl_mask_v2 import (
    CLOUD_SHADOW_DILATION_M,
    DARK_NIR_PROXIMITY_MASK,
    REVIEWED_PROCESSING_BASELINE_REGISTRY_ID,
    REVIEWED_PROCESSING_BASELINES,
    SCL_ACCEPTED_CLASSES,
    SCL_MASK_METHOD_ID,
    SCL_REJECTED_CLASSES,
)
from src.publication.green_release import POINTER_KEY, POINTER_SCHEMA, RELEASE_SCHEMA
from src.publication.site_artifact import INDEX_SCHEMA, STATS_POLICY_VERSION
from src.timeseries.schema import TIMESERIES_SCHEMA_VERSION

#: Version token of the freeze document itself.
REPLAY_FREEZE_VERSION = "phase3-replay-freeze-v1"

#: Where the checked-in freeze lives.
FREEZE_PATH = Path(settings.ROOT_DIR) / "config" / "phase3_replay_freeze_v1.json"

#: The ten groups the roadmap bullet names, in its order.  Present as a
#: constant so a group cannot be dropped from the document without the test
#: noticing — a missing key is easy to overlook, a missing name is not.
FROZEN_GROUPS = (
    "monitoring_extent",
    "algorithm",
    "baseline",
    "cloud_and_mosaic",
    "drought",
    "mapbiomas",
    "label",
    "schema",
    "environment",
    "release",
)


class FreezeError(ValueError):
    """The freeze document disagrees with what the producers declare."""


def _sha256_of(path: Path) -> str | None:
    import hashlib

    path = Path(path)
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _decimal(value: float) -> str:
    """A float as its shortest round-tripping decimal string.

    Same reason as in ``scripts/build_detection_gee.py``: the freeze's digest
    is over canonical JSON, and a float in the body makes the bytes depend on
    which canonicalizer wrote them.  Every number here is an ``int`` or one of
    these strings.
    """

    return repr(float(value))


def _monitoring_extent() -> dict[str, Any]:
    return {
        "extent_id": MONITORING_EXTENT_ID,
        "settings_extent_id": settings.MONITORING_EXTENT_ID,
        "bounds_epsg4326": [_decimal(bound) for bound in MONITORING_EXTENT_BOUNDS],
        "bounds_sha256": MONITORING_EXTENT_BOUNDS_SHA256,
        "geometry_sha256": MONITORING_EXTENT_GEOMETRY_SHA256,
        "scope": "APA and surroundings",
    }


def _algorithm() -> dict[str, Any]:
    return {
        "detection_algorithm_version": settings.DETECTION_ALGORITHM_VERSION,
        "indices": ["ndmi", "nbr", "evi2"],
        "confidence_levels": {"0": "none", "1": "low", "2": "medium", "3": "high"},
        "z_thresholds": {
            "high": _decimal(settings.Z_THRESHOLD_HIGH),
            "medium": _decimal(settings.Z_THRESHOLD_MEDIUM),
            "low": _decimal(settings.Z_THRESHOLD_LOW),
        },
        "delta_thresholds": {
            "high": _decimal(settings.DELTA_THRESHOLD_HIGH),
            "medium": _decimal(settings.DELTA_THRESHOLD_MEDIUM),
            "low": _decimal(settings.DELTA_THRESHOLD_LOW),
        },
        "alert_area_ha": {
            "minimum": _decimal(settings.MIN_ALERT_AREA_HA),
            "maximum": _decimal(settings.MAX_ALERT_AREA_HA),
        },
        "scene_anomaly_reject_fraction": _decimal(
            settings.SCENE_ANOMALY_REJECT_FRAC
        ),
        "reflectance_scaling": settings.REFLECTANCE_SCALING,
        "persistence": {
            "confirmed_minimum_sightings": CONFIRMED_MIN,
            "grace_days": GRACE_DAYS,
            "minimum_overlap_fraction": _decimal(DEFAULT_MIN_OVERLAP_FRAC),
        },
        # The incremental window matters to the replay because the operational
        # path reprocesses each date several times and the replay processes it
        # once.  Recorded because a stale value corrupted a cost estimate: two
        # docstrings still said 16 when the constant had been 5 since 2A.1.
        "incremental_search_days_back": settings.SEARCH_DAYS_BACK,
    }


def _baseline() -> dict[str, Any]:
    generations = {}
    for version, generation in sorted(BASELINE_GENERATIONS.items()):
        manifest = generation.load_manifest()
        generations[version] = {
            "manifest_path": Path(generation.manifest_path)
            .relative_to(settings.ROOT_DIR)
            .as_posix(),
            "manifest_sha256": _sha256_of(generation.manifest_path),
            "key_prefix": generation.key_prefix,
            "object_count": manifest["aggregate"]["object_count"],
            "total_bytes": manifest["aggregate"]["total_bytes"],
            "inventory_sha256": manifest["aggregate"]["inventory_sha256"],
            "status": manifest["status"],
        }
    return {
        "registered_generations": generations,
        "superseded_generations": dict(sorted(SUPERSEDED_GENERATIONS.items())),
        "runtime_default": settings.BASELINE_VERSION,
        "replay_generation": {
            "decided": False,
            "decided_by": "project_owner",
            "reason": (
                "the whole year is compared against this generation; the two "
                "registered generations share no raster, so the choice is "
                "scientific and is recorded, not defaulted"
            ),
        },
        "source_years": list(settings.BASELINE_SOURCE_YEARS),
    }


def _cloud_and_mosaic() -> dict[str, Any]:
    return {
        "scl_mask": {
            "method_id": SCL_MASK_METHOD_ID,
            "accepted_classes": list(SCL_ACCEPTED_CLASSES),
            "rejected_classes": list(SCL_REJECTED_CLASSES),
            "cloud_shadow_dilation_m": CLOUD_SHADOW_DILATION_M,
            "dark_nir_proximity_mask": DARK_NIR_PROXIMITY_MASK,
            "reviewed_processing_baseline_registry_id": (
                REVIEWED_PROCESSING_BASELINE_REGISTRY_ID
            ),
            "reviewed_processing_baselines": list(REVIEWED_PROCESSING_BASELINES),
        },
        "datatake_composition": {
            "method_id": COMPOSITION_METHOD_ID,
            "scope_version": COMPOSITION_SCOPE_VERSION,
            "scene_order_policy": list(SCENE_ORDER_POLICY),
            "pixel_selection": PIXEL_SELECTION_POLICY,
        },
        "detection_export": {
            "collection_id": settings.GEE_COLLECTION_ID,
            "composite_method_id": settings.GEE_COMPOSITE_METHOD_ID,
            "streaming_composite_method_id": (
                settings.STREAMING_COMPOSITE_METHOD_ID
            ),
            "scl_clear_classes": list(settings.BASELINE_SCL_CLEAR_CLASSES),
            "grid_request": {
                "crs": settings.TARGET_CRS,
                "scale_m": settings.BASELINE_RESOLUTION,
                "crs_transform_pinned": False,
            },
            # Measured, not assumed: CompositionRunV3 binds the composite
            # method to the datatake-scoped one while the export mosaics a
            # whole date. Phase 4 has to resolve which unit it composes.
            "open_question_for_phase_4": (
                "the export composes one mosaic per UTC date under "
                "daily_mosaic-v1; CompositionRunV3 mints identities under "
                "coverage-ranked-first-valid-v1, which is datatake-scoped"
            ),
        },
    }


def _drought() -> dict[str, Any]:
    return {
        "spi_drought_threshold": _decimal(settings.SPI_DROUGHT_THRESHOLD),
        "drought_z_adjustment": _decimal(settings.DROUGHT_Z_ADJUSTMENT),
        "chirps_base_url": settings.CHIRPS_BASE_URL,
        # The constants exist and the adjustment is NOT applied: both
        # detection entry points log the fact and pass spi_3month=None. A
        # freeze that recorded only the thresholds would imply otherwise.
        "operationally_applied": False,
        "operational_evidence": (
            "scripts/run_detection_from_gee.py and scripts/run_detection.py "
            "always pass spi_3month=None; no qualified drought method is "
            "accepted"
        ),
    }


def _mapbiomas() -> dict[str, Any]:
    rasters = {}
    for name, path in sorted(settings.LANDCOVER_RASTERS.items()):
        path = Path(path)
        rasters[name] = {
            "path": path.relative_to(settings.ROOT_DIR).as_posix(),
            "present_locally": path.exists(),
            "bytes": path.stat().st_size if path.exists() else None,
        }
    manifest_path = (
        Path(settings.ROOT_DIR)
        / "config"
        / "collection10_1_export_manifest_v1.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        "default_collection": settings.DEFAULT_LANDCOVER_COLLECTION,
        "natural_vegetation_minimum_fraction": _decimal(
            settings.NATURAL_VEG_MIN_FRAC
        ),
        "rasters": rasters,
        "collection10_1_export": {
            "manifest_path": manifest_path.relative_to(
                settings.ROOT_DIR
            ).as_posix(),
            "manifest_sha256": _sha256_of(manifest_path),
            "manifest_id": manifest["manifest_id"],
            "asset_id": manifest["asset_id"],
            "monitoring_extent_id": manifest["monitoring_extent_id"],
        },
    }


def _label() -> dict[str, Any]:
    return {
        "confidence_labels": ["low", "medium", "high"],
        "clearing_types": ["none", "fire", "mechanical", "uncertain"],
        "persistence_tiers": ["first_observation", "candidate", "confirmed"],
        "terminal_ledger_statuses": list(TERMINAL_STATUSES),
        "site_strong_confidence_label": "high",
        # The qualified validation label set belongs to Phase 5, which does
        # not start without the owner's review. Recording it as frozen here
        # would freeze a taxonomy nobody has accepted yet.
        "qualified_validation_labels": {
            "frozen": False,
            "owner": "Phase 5, behind the owner's review gate",
        },
    }


def _schema() -> dict[str, Any]:
    return {
        "identity_and_ledger_v3": IDENTITY_SCHEMA_VERSION,
        "timeseries": TIMESERIES_SCHEMA_VERSION,
        "green_release": RELEASE_SCHEMA,
        "green_pointer": POINTER_SCHEMA,
        "green_pointer_key": POINTER_KEY,
        "site_alert_index": INDEX_SCHEMA,
        "site_stats_policy_version": STATS_POLICY_VERSION,
    }


def _environment() -> dict[str, Any]:
    environment_path = Path(settings.ROOT_DIR) / "environment.yml"
    text = environment_path.read_text(encoding="utf-8")
    pinned = sorted(
        line.strip().lstrip("- ").strip()
        for line in text.splitlines()
        if line.strip().startswith("- ")
        and any(
            line.strip().lstrip("- ").startswith(package)
            for package in ("python=", "boto3", "botocore", "rasterio", "geopandas")
        )
    )
    return {
        "environment_yml_sha256": _sha256_of(environment_path),
        "conda_environment_name": "araripe",
        "interpreter": "/opt/anaconda3/envs/araripe/bin/python",
        "pinned_of_record": pinned,
        # boto3/botocore are of record because the pin's window matters to the
        # publication path: 1.35.x carries If-None-Match but not If-Match, so
        # the conditional compare-and-swap is not expressible through
        # botocore's own parameters at this pin.
        "conditional_write_note": (
            "the 1.35.x pin exposes IfNoneMatch but not IfMatch; the "
            "compare-and-swap is issued outside botocore's typed parameters"
        ),
    }


def _release(timeseries_release: Mapping[str, Any] | None) -> dict[str, Any]:
    release_path = Path(settings.TIMESERIES_DIR) / "RELEASE.json"
    document = (
        dict(timeseries_release)
        if timeseries_release is not None
        else json.loads(release_path.read_text(encoding="utf-8"))
    )
    return {
        "timeseries_release_path": release_path.relative_to(
            settings.ROOT_DIR
        ).as_posix(),
        "timeseries_release_sha256": _sha256_of(release_path),
        "schema": document["schema"],
        "latest_observation": document["latest_observation"],
        "published_utc": document["published_utc"],
        "run_id": document["run_id"],
        "timeseries_db_sha256": document["timeseries"]["sha256"],
        "timeseries_db_bytes": document["timeseries"]["bytes"],
        # This is a photograph of the live blue release at freeze time, not a
        # pin on it: the blue lane keeps publishing through Phases 2B-5 by
        # design, so the live file WILL advance past these values. Drift is
        # reported by the snapshot tool, never by a test — a test that broke
        # on every successful production run would be noise.
        "is_a_photograph_not_a_pin": True,
    }


def build_freeze(
    *,
    timeseries_release: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Read the frozen version set from its producers and seal it."""

    body = {
        "replay_freeze_version": REPLAY_FREEZE_VERSION,
        "monitoring_extent": _monitoring_extent(),
        "algorithm": _algorithm(),
        "baseline": _baseline(),
        "cloud_and_mosaic": _cloud_and_mosaic(),
        "drought": _drought(),
        "mapbiomas": _mapbiomas(),
        "label": _label(),
        "schema": _schema(),
        "environment": _environment(),
        "release": _release(timeseries_release),
    }
    missing = [group for group in FROZEN_GROUPS if group not in body]
    if missing:
        raise FreezeError(
            "the freeze omits the roadmap group(s): " + ", ".join(missing)
        )
    document = dict(body)
    document["freeze_sha256"] = canonical_sha256(body)
    return document


def validate_freeze(document: Mapping[str, Any]) -> None:
    """Re-read every producer and fail closed on any disagreement.

    Compares the whole document rather than field by field, so a group added
    to :func:`build_freeze` is covered the moment it exists — a per-field
    comparison would silently ignore anything nobody remembered to list.
    """

    if not isinstance(document, Mapping):
        raise FreezeError("the freeze document must be a mapping")
    if document.get("replay_freeze_version") != REPLAY_FREEZE_VERSION:
        raise FreezeError(
            f"freeze version is {document.get('replay_freeze_version')!r}, "
            f"expected {REPLAY_FREEZE_VERSION!r}"
        )
    sealed = document.get("freeze_sha256")
    body = {key: value for key, value in document.items() if key != "freeze_sha256"}
    if canonical_sha256(body) != sealed:
        raise FreezeError("freeze_sha256 does not match the document body")

    # `release` is a photograph of a live file, so it is compared against the
    # document's own recorded values rather than against today's blue release.
    current = build_freeze(timeseries_release=None)
    drifted = [
        group
        for group in FROZEN_GROUPS
        if group != "release" and current[group] != body.get(group)
    ]
    if drifted:
        raise FreezeError(
            "the repository no longer matches the freeze in: "
            + ", ".join(sorted(drifted))
        )


def load_freeze(path: Path | None = None) -> dict[str, Any]:
    """Load and fully validate the checked-in freeze."""

    path = Path(FREEZE_PATH if path is None else path)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FreezeError(f"cannot read the replay freeze {path}: {exc}") from exc
    validate_freeze(document)
    return document


def write_freeze(document: Mapping[str, Any], path: Path | None = None) -> Path:
    """Write a validated freeze document."""

    validate_freeze(document)
    path = Path(FREEZE_PATH if path is None else path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
