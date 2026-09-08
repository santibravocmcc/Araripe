"""Deterministic sampling for the provisional Phase 2A.3 desktop pilot.

The sampling unit is one *legacy alert feature at one source date*.  It is not
an accepted observation or event: the current alert archive does not retain the
scene/acquisition provenance required by the accepted Phase 1 identity rules.
All identifiers in this module therefore use an explicit ``p2a3`` audit
namespace and must never be promoted into canonical monitoring state.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

import fiona
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from shapely.geometry import box, shape

from src.detection.baseline_manifest import inventory_sha256, sha256_file
from src.detection.identity import canonical_geometry_sha256, identity_sha256


PILOT_SCHEMA_VERSION = "1.0.0"
SAMPLING_DESIGN_VERSION = "phase2a3-balanced-location-date-v1"
DEFAULT_RANDOM_SEED = "20260731"
DEFAULT_TARGET_SIZE = 60

MONITORING_EXTENT_ID = "araripe-implementation-rectangle-v1"
MONITORING_EXTENT_BOUNDS = (
    -40.89236812577142,
    -7.840780758480428,
    -38.95208146319247,
    -6.957104781339829,
)

BALANCE_LEVELS: dict[str, tuple[str, ...]] = {
    "confidence": ("high", "medium", "low"),
    "polygon_size": ("small_1_2ha", "medium_2_5ha", "large_5ha_plus"),
    "season": ("wet_nov_apr", "dry_may_oct"),
    "land_cover": ("natural", "anthropic", "other_or_water"),
    "persistence": ("first", "candidate", "confirmed"),
    "geographic_zone": (
        "north_west",
        "north_central",
        "north_east",
        "south_west",
        "south_central",
        "south_east",
    ),
}

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_FORBIDDEN_CANONICAL_PREFIXES = ("acq-v1-", "obs-v1-", "evt-v1-")


class SamplingDesignError(ValueError):
    """Raised when the provisional frame or requested design is invalid."""


def _hash(*parts: str) -> str:
    return identity_sha256(*parts)


def _plain(value: Any) -> Any:
    """Convert Fiona/numpy scalar values to deterministic JSON primitives."""
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if hasattr(value, "item"):
        return _plain(value.item())
    return str(value)


def _date(value: Any, fallback_name: str) -> str | None:
    candidate = str(value or "")[:10]
    if not candidate:
        match = _DATE_RE.search(fallback_name)
        candidate = match.group(1) if match else ""
    try:
        return dt.date.fromisoformat(candidate).isoformat()
    except ValueError:
        return None


def _confidence(properties: Mapping[str, Any]) -> str:
    label = str(properties.get("confidence_label") or "").strip().lower()
    if label in {"high", "medium", "low"}:
        return label
    try:
        numeric = int(properties.get("confidence"))
    except (TypeError, ValueError):
        return "unknown"
    return {3: "high", 2: "medium", 1: "low"}.get(numeric, "unknown")


def _area(properties: Mapping[str, Any]) -> float | None:
    try:
        value = float(properties.get("area_ha"))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def _polygon_size(area_ha: float | None) -> str:
    if area_ha is None:
        return "unknown"
    if area_ha < 1:
        return "below_nominal_minimum"
    if area_ha < 2:
        return "small_1_2ha"
    if area_ha < 5:
        return "medium_2_5ha"
    return "large_5ha_plus"


def _season(observed_on: str | None) -> tuple[str, str]:
    if observed_on is None:
        return "unknown", "unknown"
    month = int(observed_on[5:7])
    season = "wet_nov_apr" if month in {11, 12, 1, 2, 3, 4} else "dry_may_oct"
    phenology = "leaf_off_aug_oct" if month in {8, 9, 10} else "pre_leaf_off"
    return season, phenology


def _land_cover(properties: Mapping[str, Any]) -> tuple[str, str]:
    raw = str(
        properties.get("lc_group")
        or properties.get("lc_group_10m")
        or ""
    ).strip().lower()
    if raw == "natural":
        return "natural", raw
    if raw in {"farming", "urban", "anthropic", "agriculture", "pasture"}:
        return "anthropic", raw
    if raw in {"other", "water", "other_or_water"}:
        return "other_or_water", raw
    return "unknown", raw or "unknown"


def _persistence(properties: Mapping[str, Any]) -> tuple[str, str]:
    raw = str(properties.get("persistence_status") or "").strip().lower()
    if raw in {"first", "first_observation"}:
        return "first", raw
    if raw == "candidate":
        return "candidate", raw
    if raw == "confirmed":
        return "confirmed", raw
    return "unknown", raw or "unknown"


def _geographic_zone(longitude: float, latitude: float) -> str:
    west, south, east, north = MONITORING_EXTENT_BOUNDS
    column = min(2, max(0, int((longitude - west) / ((east - west) / 3))))
    row = "north" if latitude >= south + (north - south) / 2 else "south"
    return f"{row}_{('west', 'central', 'east')[column]}"


def _marginal_targets(
    target_size: int,
    levels: Sequence[str],
    *,
    seed: str,
    variable: str,
) -> dict[str, int]:
    base, remainder = divmod(target_size, len(levels))
    ordered = sorted(
        levels,
        key=lambda level: _hash(
            "p2a3-marginal-remainder-v1", seed, variable, level
        ),
    )
    extra = set(ordered[:remainder])
    return {level: base + int(level in extra) for level in levels}


def _fine_stratum_id(strata: Mapping[str, str]) -> str:
    components = [strata[name] for name in BALANCE_LEVELS]
    return "p2a3-stratum-v1-" + _hash(
        "phase2a3-stratum-v1", *components
    )


def _balanced_cell_selection(
    cells: Mapping[str, list[dict[str, Any]]],
    *,
    target_size: int,
    seed: str,
) -> tuple[set[str], dict[str, dict[str, int]], str]:
    """Select the lexicographically first exact-balance set by SHA rank.

    A single floating-point hash objective is not a reproducibility guarantee:
    solver tolerances can accept different near-optimal solutions.  Instead,
    this routine orders cells by the full SHA-256 rank and fixes each decision
    through a feasibility problem.  The result is the unique lexicographically
    first feasible membership vector, independent of whichever feasible point
    HiGHS returns internally.
    """
    candidates = []
    for cell_id, units in sorted(cells.items()):
        strata = units[0]["strata"]
        if all(strata[name] in BALANCE_LEVELS[name] for name in BALANCE_LEVELS):
            candidates.append((cell_id, strata))
    if len(candidates) < target_size:
        raise SamplingDesignError(
            f"only {len(candidates)} supported joint strata for target {target_size}"
        )

    margin_targets = {
        name: _marginal_targets(
            target_size, levels, seed=seed, variable=name
        )
        for name, levels in BALANCE_LEVELS.items()
    }
    rows: list[list[float]] = []
    bounds: list[float] = []

    rows.append([1.0] * len(candidates))
    bounds.append(float(target_size))
    for name, levels in BALANCE_LEVELS.items():
        for level in levels:
            rows.append(
                [1.0 if strata[name] == level else 0.0 for _, strata in candidates]
            )
            bounds.append(float(margin_targets[name][level]))

    matrix = np.asarray(rows, dtype=float)
    constraint = LinearConstraint(matrix, bounds, bounds)
    objective = np.zeros(len(candidates), dtype=float)
    lower = np.zeros(len(candidates), dtype=float)
    upper = np.ones(len(candidates), dtype=float)

    def feasible(trial_lower: np.ndarray, trial_upper: np.ndarray):
        return milp(
            c=objective,
            integrality=np.ones(len(candidates), dtype=int),
            bounds=Bounds(trial_lower, trial_upper),
            constraints=constraint,
            options={"presolve": True, "mip_rel_gap": 0.0},
        )

    initial = feasible(lower, upper)
    if not initial.success or initial.x is None:
        raise SamplingDesignError(
            "exact six-dimension balance is infeasible for this frozen frame: "
            f"{initial.message}"
        )

    ordered_indices = sorted(
        range(len(candidates)),
        key=lambda index: (
            _hash("p2a3-cell-rank-v1", seed, candidates[index][0]),
            candidates[index][0],
        ),
    )
    selected_indices: set[int] = set()
    for index in ordered_indices:
        if len(selected_indices) == target_size:
            break
        trial_lower = lower.copy()
        trial_upper = upper.copy()
        trial_lower[index] = 1.0
        trial_upper[index] = 1.0
        result = feasible(trial_lower, trial_upper)
        if result.success and result.x is not None:
            lower[index] = upper[index] = 1.0
            selected_indices.add(index)
        else:
            upper[index] = 0.0

    selected = {candidates[index][0] for index in selected_indices}
    if len(selected) != target_size:
        final = milp(
            c=objective,
            integrality=np.ones(len(candidates), dtype=int),
            bounds=Bounds(lower, upper),
            constraints=constraint,
            options={"presolve": True, "mip_rel_gap": 0.0},
        )
        raise SamplingDesignError(
            "lexicographic feasibility selection did not reach the requested "
            f"size ({len(selected)}/{target_size}); final status={final.message}"
        )
    return selected, margin_targets, "exact"


def sanitize_origin_base_url(origin_base_url: str) -> str:
    """Validate an HTTP(S) source prefix and remove query/fragment material."""

    parsed = urlsplit(origin_base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SamplingDesignError("origin_base_url must be an HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise SamplingDesignError("origin_base_url must not contain credentials")
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "")
    )


def _artifact_record(path: Path, *, origin_base_url: str | None) -> dict[str, Any]:
    digest = sha256_file(path)
    origin = None
    if origin_base_url:
        origin = sanitize_origin_base_url(origin_base_url) + "/" + path.name
    return {
        "key": f"alerts/{path.name}",
        "path_label": path.name,
        "origin_url": origin,
        "bytes": path.stat().st_size,
        "sha256": digest,
        "feature_count": 0,
        "source_role": "provisional_current_alert_audit_input",
        "canonical_release_id": None,
        "r2_etag": None,
        "limitations": [
            "No accepted release manifest binds this object.",
            "Legacy features lack accepted acquisition, observation, and event IDs.",
            "The local SHA-256 binds retrieved bytes; no R2 ETag snapshot was supplied.",
        ],
    }


def build_sampling_frame(
    alert_paths: Iterable[Path],
    *,
    target_size: int = DEFAULT_TARGET_SIZE,
    seed: str = DEFAULT_RANDOM_SEED,
    origin_base_url: str | None = None,
) -> dict[str, Any]:
    """Freeze, stratify, and select the provisional alert-location pilot frame."""
    if target_size <= 0:
        raise SamplingDesignError("target_size must be positive")
    seed = str(seed)
    paths = sorted(
        {Path(path).resolve() for path in alert_paths},
        key=lambda path: (path.name, str(path)),
    )
    if not paths:
        raise SamplingDesignError("no source alert artifacts were supplied")
    if len({path.name for path in paths}) != len(paths):
        raise SamplingDesignError("source alert basenames must be unique")

    extent = box(*MONITORING_EXTENT_BOUNDS)
    source_artifacts: list[dict[str, Any]] = []
    units: list[dict[str, Any]] = []

    for path in paths:
        if not path.is_file():
            raise SamplingDesignError(f"source artifact is not a file: {path}")
        artifact = _artifact_record(path, origin_base_url=origin_base_url)
        source_artifacts.append(artifact)
        artifact_date = _date(None, path.name)
        try:
            collection = fiona.open(path)
        except Exception as exc:  # pragma: no cover - Fiona message is platform-specific
            raise SamplingDesignError(f"cannot read {path.name}: {exc}") from exc
        with collection:
            crs_text = str(collection.crs or "")
            if not any(token in crs_text.upper() for token in ("4326", "CRS84")):
                raise SamplingDesignError(
                    f"{path.name} must use EPSG:4326/CRS84, found {crs_text!r}"
                )
            for feature_index, feature in enumerate(collection):
                artifact["feature_count"] += 1
                properties = {
                    str(key): _plain(value)
                    for key, value in dict(feature["properties"] or {}).items()
                }
                locator = f"{artifact['sha256']}:{feature_index:09d}"
                base: dict[str, Any] = {
                    "source_record_id": None,
                    "source_artifact_key": artifact["key"],
                    "source_artifact_sha256": artifact["sha256"],
                    "source_feature_index": feature_index,
                    "source_locator": locator,
                    "canonical_observation_id": None,
                    "canonical_event_id": None,
                    "geometry_sha256": None,
                    "eligible": False,
                    "exclusion_reason": None,
                    "duplicate_of": None,
                    "selected_joint_stratum": False,
                    "selected": False,
                    "selection_probability": 0.0,
                    "conditional_within_stratum_probability": 0.0,
                    "sample_id": None,
                }
                raw_geometry = feature.get("geometry")
                if not raw_geometry:
                    base["exclusion_reason"] = "missing_geometry"
                    units.append(base)
                    continue
                try:
                    geometry = shape(raw_geometry)
                    canonical, geometry_digest = canonical_geometry_sha256(geometry)
                except (TypeError, ValueError) as exc:
                    base["exclusion_reason"] = "invalid_or_unsupported_geometry"
                    base["exclusion_detail"] = str(exc)
                    units.append(base)
                    continue

                observed_on = _date(properties.get("detection_date"), path.name)
                source_record_id = "p2a3-audit-location-v1-" + _hash(
                    "phase2a3-audit-location-v1",
                    SAMPLING_DESIGN_VERSION,
                    artifact["sha256"],
                    f"{feature_index:09d}",
                    geometry_digest,
                )
                representative = geometry.representative_point()
                area_ha = _area(properties)
                season, phenology_period = _season(observed_on)
                land_cover, land_cover_source_value = _land_cover(properties)
                persistence, persistence_source_value = _persistence(properties)
                strata = {
                    "confidence": _confidence(properties),
                    "polygon_size": _polygon_size(area_ha),
                    "season": season,
                    "land_cover": land_cover,
                    "persistence": persistence,
                    "geographic_zone": _geographic_zone(
                        representative.x, representative.y
                    ),
                }
                base.update(
                    {
                        "source_record_id": source_record_id,
                        "geometry_sha256": geometry_digest,
                        "canonical_geometry": canonical,
                        "observed_on": observed_on,
                        "artifact_date": artifact_date,
                        "area_ha_reported": area_ha,
                        "centroid_longitude": round(float(representative.x), 8),
                        "centroid_latitude": round(float(representative.y), 8),
                        "crosses_extent_boundary": not extent.covers(geometry),
                        "strata": strata,
                        "phenology_period": phenology_period,
                        "land_cover_source_value": land_cover_source_value,
                        "persistence_source_value": persistence_source_value,
                        "persistence_count": _plain(properties.get("persistence_count")),
                        "first_seen": _plain(properties.get("first_seen")),
                        "last_seen": _plain(properties.get("last_seen")),
                        "provisional_contextual_signature": _plain(
                            properties.get("clearing_type")
                        ),
                        "eligible": True,
                    }
                )
                if observed_on is None:
                    base["eligible"] = False
                    base["exclusion_reason"] = "invalid_detection_date"
                elif artifact_date is not None and observed_on != artifact_date:
                    base["eligible"] = False
                    base["exclusion_reason"] = "artifact_feature_date_mismatch"
                elif not geometry.intersects(extent):
                    base["eligible"] = False
                    base["exclusion_reason"] = "wholly_outside_accepted_extent"
                base["joint_stratum_id"] = _fine_stratum_id(strata)
                base["random_rank"] = _hash(
                    "phase2a3-unit-rank-v1", seed, source_record_id
                )
                units.append(base)

    # Exact byte/geometry/date duplicates are an explicit frame exclusion.  The
    # first stable locator is kept; raw source features themselves are untouched.
    duplicate_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for unit in units:
        if unit["eligible"]:
            duplicate_groups[(unit["observed_on"], unit["geometry_sha256"])].append(unit)
    for group in duplicate_groups.values():
        if len(group) < 2:
            continue
        ordered = sorted(group, key=lambda unit: unit["source_locator"])
        keeper = ordered[0]["source_record_id"]
        for duplicate in ordered[1:]:
            duplicate["eligible"] = False
            duplicate["exclusion_reason"] = "duplicate_exact_location_date"
            duplicate["duplicate_of"] = keeper

    cells: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for unit in units:
        if unit["eligible"]:
            cells[unit["joint_stratum_id"]].append(unit)
    if sum(map(len, cells.values())) < target_size:
        raise SamplingDesignError("eligible population is smaller than target sample")

    selected_cells, margin_targets, balance_status = _balanced_cell_selection(
        cells, target_size=target_size, seed=seed
    )
    selected_units: list[dict[str, Any]] = []
    for cell_id, members in cells.items():
        population = len(members)
        selected_cell = cell_id in selected_cells
        probability = (1.0 / population) if selected_cell else 0.0
        ordered = sorted(
            members,
            key=lambda unit: (unit["random_rank"], unit["source_record_id"]),
        )
        for member in members:
            member["joint_stratum_population"] = population
            member["joint_stratum_sample"] = int(selected_cell)
            member["selected_joint_stratum"] = selected_cell
            member["conditional_within_stratum_probability"] = probability
            member["selection_probability"] = probability
        if selected_cell:
            chosen = ordered[0]
            chosen["selected"] = True
            chosen["sample_id"] = "p2a3-sample-v1-" + _hash(
                "phase2a3-sample-v1",
                SAMPLING_DESIGN_VERSION,
                seed,
                chosen["source_record_id"],
            )
            selected_units.append(chosen)

    selected_units.sort(key=lambda unit: unit["sample_id"])
    if len(selected_units) != target_size:
        raise SamplingDesignError(
            f"selected {len(selected_units)} units, expected {target_size}"
        )
    for unit in units:
        if (unit.get("source_record_id") or "").startswith(
            _FORBIDDEN_CANONICAL_PREFIXES
        ):
            raise SamplingDesignError("pilot-local source ID uses a canonical prefix")

    artifact_inventory_digest = inventory_sha256(source_artifacts)
    population_snapshot_id = "p2a3-population-v1-" + _hash(
        "phase2a3-population-v1",
        SAMPLING_DESIGN_VERSION,
        artifact_inventory_digest,
    )
    for selected in selected_units:
        selected["population_snapshot_id"] = population_snapshot_id

    fine_strata = []
    for cell_id, members in sorted(cells.items()):
        first = members[0]
        fine_strata.append(
            {
                "joint_stratum_id": cell_id,
                "strata": first["strata"],
                "population": len(members),
                "sample": int(cell_id in selected_cells),
                "cell_inclusion_probability": int(cell_id in selected_cells),
                "conditional_unit_probability": (
                    1.0 / len(members) if cell_id in selected_cells else 0.0
                ),
            }
        )

    def margins(subset: Iterable[dict[str, Any]]) -> dict[str, dict[str, int]]:
        materialized = list(subset)
        return {
            name: dict(
                sorted(Counter(unit["strata"][name] for unit in materialized).items())
            )
            for name in BALANCE_LEVELS
        }

    exclusion_counts = Counter(
        unit["exclusion_reason"] for unit in units if not unit["eligible"]
    )
    source_feature_count = sum(item["feature_count"] for item in source_artifacts)
    eligible_count = sum(unit["eligible"] for unit in units)
    limitations = [
        "The frame contains provisional legacy alert features, not a clean canonical release.",
        "Sampling units are location-date features and can revisit the same physical place on different dates.",
        "Joint cells are purposively balanced; units in unselected cells have zero inclusion probability.",
        "Only conditional within-selected-cell probabilities support the recorded draw; this pilot is not suitable for population accuracy estimation.",
        "The source archive has no accepted per-date processing ledger, so absent dates are not interpreted as zero-alert dates.",
        "Legacy land-cover, persistence, confidence, and contextual-signature attributes are provisional stratification fields only.",
    ]
    if not any(
        unit.get("eligible") and unit.get("phenology_period") == "leaf_off_aug_oct"
        for unit in units
    ):
        limitations.append(
            "No August-October leaf-off alert date is available in this source snapshot."
        )
    return {
        "schema_version": PILOT_SCHEMA_VERSION,
        "sampling_design_version": SAMPLING_DESIGN_VERSION,
        "random_seed": seed,
        "target_size": target_size,
        "population_snapshot_id": population_snapshot_id,
        "source_artifact_inventory_sha256": artifact_inventory_digest,
        "source_artifacts": source_artifacts,
        "source_feature_count": source_feature_count,
        "eligible_count": eligible_count,
        "excluded_count": source_feature_count - eligible_count,
        "exclusion_counts": dict(sorted(exclusion_counts.items())),
        "balance_status": balance_status,
        "balance_levels": {name: list(levels) for name, levels in BALANCE_LEVELS.items()},
        "margin_targets": margin_targets,
        "population_margins": margins(unit for unit in units if unit["eligible"]),
        "sample_margins": margins(selected_units),
        "fine_strata": fine_strata,
        "units": sorted(
            units,
            key=lambda unit: (
                unit["source_artifact_key"],
                unit["source_feature_index"],
            ),
        ),
        "selected_units": selected_units,
        "limitations": limitations,
    }
