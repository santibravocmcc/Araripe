"""Package 2A.6D MapBiomas context under the accepted v2 decisions.

The Package 2A.5 machinery (:mod:`src.validation.phase2a5_context`) stays
byte-unchanged as the executable audit record of the v1 artifacts. This module
is the v2 implementation the 2026-08-11 decision record requires:

- the ``mapbiomas-context-groups-v2`` mappings, re-derived from the decision
  record itself so this module cannot drift from what was accepted;
- the class-0 / class-27 / value-255 policy, with ``not_observed`` and
  ``unknown_unclassified`` as first-class states excluded from every valid
  mapped denominator;
- the checksum-bound national legend fixture, verified in bytes and in
  content (every mapped code must exist in the legend);
- the selected ``natural-vegetation-share-0.50-v2`` subset with the 0.75
  sensitivity alternative recorded but never activated;
- cross-collection agreement/disagreement against the fresh Collection 10.1
  GEE export, nearest-aligned to the Collection 3 grid, as context and never
  truth;
- the invalidation of the mislabeled Collection 10 crop for runtime and
  qualified-review use, its audit bytes untouched.

The non-causal contextual-signature pixel rule is unchanged science and is
consumed from the v1 module, never reimplemented.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

import numpy as np

from src.detection.baseline_manifest import (
    MONITORING_EXTENT_BOUNDS,
    MONITORING_EXTENT_BOUNDS_SHA256,
    MONITORING_EXTENT_GEOMETRY_SHA256,
    MONITORING_EXTENT_ID,
)
from src.processing.baseline_rebuild_v2 import (
    DECISIONS_V2_PATH,
    DECISIONS_V2_SHA256,
)
from src.validation.phase2a5_context import (
    classify_contextual_signature_pixels,
    contextual_signature_proportions,
)

__all__ = [
    "classify_contextual_signature_pixels",
    "contextual_signature_proportions",
]

REGISTRY_V2_PATH = Path("config/phase2a5_context_registry_v2.json")
REGISTRY_V2_ID = "araripe-phase2a5-context-registry-v2"
EXPORT_MANIFEST_PATH = Path("config/collection10_1_export_manifest_v1.json")
REGIONAL_MANIFEST_V2_PATH = Path(
    "config/phase2a5_regional_context_manifest_v2.json"
)

COL3_KEY_V2 = "collection3_beta_10m_2024"
COL10_1_KEY_V2 = "collection10_1_gee_export_30m_2024"
COL10_AUDIT_KEY = "collection10_direct_30m_2024"
COLLECTION_KEYS_V2 = (COL3_KEY_V2, COL10_1_KEY_V2)

MAPPED_CATEGORIES = (
    "natural_vegetation",
    "other_natural_cover",
    "anthropic_cover",
    "uncertain_or_mixed",
)
# The v2 accounting separates every excluded state instead of folding them
# into "unmapped": a pixel the provider marked not-observed (27) is a
# different fact from one carrying an unknown code, and both are different
# from NoData. All of them stay out of the valid mapped denominator.
EXCLUDED_STATES = (
    "nodata",
    "unknown_unclassified",
    "not_observed",
    "unmapped",
)
CATEGORIES_V2 = (*MAPPED_CATEGORIES, *EXCLUDED_STATES)

NOT_OBSERVED_CODE = 27
EXPORT_MASK_VALUE = 255

# Transcribed from the checksum-bound legend fixture
# (data/landcover/updated/Legenda-Colecao-10-Legend-Code.pdf, sha256
# 77fb06eb…). Level-1 group headers are present in the legend and remain
# deliberately unmapped when they appear as pixel values.
LEGEND_FIXTURE_CODE_TABLE: Mapping[int, str] = MappingProxyType(
    {
        1: "Forest",
        3: "Forest Formation",
        4: "Savanna Formation",
        5: "Mangrove",
        6: "Floodable Forest",
        49: "Wooded Sandbank Vegetation",
        10: "Herbaceous and Shrubby Vegetation",
        11: "Wetland",
        12: "Grassland",
        32: "Hypersaline Tidal Flat",
        29: "Rocky Outcrop",
        50: "Herbaceous Sandbank Vegetation",
        14: "Farming",
        15: "Pasture",
        18: "Agriculture",
        19: "Temporary Crop",
        39: "Soybean",
        20: "Sugar cane",
        40: "Rice",
        62: "Cotton (beta)",
        41: "Other Temporary Crops",
        36: "Perennial Crop",
        46: "Coffee",
        47: "Citrus",
        35: "Palm Oil",
        48: "Other Perennial Crops",
        9: "Forest Plantation",
        21: "Mosaic of Uses",
        22: "Non vegetated area",
        23: "Beach, Dune and Sand Spot",
        24: "Urban Area",
        30: "Mining",
        75: "Photovoltaic Power Plant (beta)",
        25: "Other non Vegetated Areas",
        26: "Water",
        33: "River, Lake and Ocean",
        31: "Aquaculture",
        27: "Not Observed",
    }
)


class Phase2A5ContextV2Error(ValueError):
    """Raised when an input violates the accepted v2 context contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Phase2A5ContextV2Error(message)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def load_accepted_decisions(root: Path | str = ".") -> dict[str, Any]:
    """Load the decision record only if its bytes match the accepted pin."""

    path = Path(root) / DECISIONS_V2_PATH
    raw = path.read_bytes()
    _require(
        hashlib.sha256(raw).hexdigest() == DECISIONS_V2_SHA256,
        "the decision record bytes do not match the accepted checksum",
    )
    return json.loads(raw)


def verify_legend_fixture(root: Path | str = ".") -> dict[str, Any]:
    """Verify the national legend fixture in bytes and in content."""

    decisions = load_accepted_decisions(root)
    fixture = decisions["phase2a5"]["legend_fixture"]
    path = Path(root) / fixture["path"]
    raw = path.read_bytes()
    _require(
        len(raw) == int(fixture["bytes"]),
        f"legend fixture is {len(raw)} bytes, expected {fixture['bytes']}",
    )
    _require(
        hashlib.sha256(raw).hexdigest() == fixture["sha256"],
        "legend fixture bytes do not match the accepted checksum",
    )
    mappings = decisions["phase2a5"]["class_mappings"]
    mapped_codes = sorted(
        {
            int(code)
            for collection in (
                "collection3_beta_10m_2024",
                "collection10_family_30m_2024",
            )
            for codes in mappings[collection].values()
            for code in codes
        }
    )
    missing = [
        code for code in mapped_codes if code not in LEGEND_FIXTURE_CODE_TABLE
    ]
    _require(
        not missing,
        f"mapped codes {missing} do not exist in the legend fixture",
    )
    _require(
        NOT_OBSERVED_CODE in LEGEND_FIXTURE_CODE_TABLE
        and LEGEND_FIXTURE_CODE_TABLE[NOT_OBSERVED_CODE] == "Not Observed",
        "the legend fixture must carry code 27 as Not Observed",
    )
    return {
        "path": fixture["path"],
        "bytes": int(fixture["bytes"]),
        "sha256": fixture["sha256"],
        "mapped_codes_verified_in_legend": mapped_codes,
        "code_table_size": len(LEGEND_FIXTURE_CODE_TABLE),
    }


def generate_context_registry_v2(root: Path | str = ".") -> dict[str, Any]:
    """Derive the v2 registry from the accepted decision record.

    Everything scientific in the registry is a verbatim copy of the decision
    record; the registry adds only concrete file bindings (hashes of the
    fixture, the sources, and the fresh Collection 10.1 export manifest) and
    the invalidation record. ``load_context_registry_v2`` re-derives this
    document and requires byte equality, so the stored file cannot drift.
    """

    base = Path(root)
    decisions = load_accepted_decisions(base)
    phase = decisions["phase2a5"]
    fixture = verify_legend_fixture(base)

    export_manifest_path = base / EXPORT_MANIFEST_PATH
    _require(
        export_manifest_path.exists(),
        "the Collection 10.1 export manifest does not exist yet; run "
        "scripts/export_collection10_1_gee.py first",
    )
    export_manifest = json.loads(export_manifest_path.read_text("utf-8"))
    _require(
        export_manifest["task_state"]
        == phase["collection10_1_required_source"]["required_task_state"],
        "the Collection 10.1 export task did not complete",
    )
    _require(
        export_manifest["asset_id"]
        == phase["collection10_1_required_source"]["gee_asset"]
        and export_manifest["selected_band"]
        == phase["collection10_1_required_source"]["band"],
        "the export manifest does not bind the accepted asset and band",
    )

    audit = phase["collection10_direct_download"]
    registry = {
        "schema_version": "1.0.0",
        "registry_id": REGISTRY_V2_ID,
        "registry_version": "2.0.0",
        "status": "accepted_for_implementation",
        "decision_binding": {
            "path": DECISIONS_V2_PATH,
            "sha256": DECISIONS_V2_SHA256,
        },
        "legend_fixture": {
            **fixture,
            "code_table": {
                str(code): label
                for code, label in sorted(LEGEND_FIXTURE_CODE_TABLE.items())
            },
        },
        "monitoring_extent": {
            "extent_id": MONITORING_EXTENT_ID,
            "bounds": list(MONITORING_EXTENT_BOUNDS),
            "bounds_sha256": MONITORING_EXTENT_BOUNDS_SHA256,
            "geometry_sha256": MONITORING_EXTENT_GEOMETRY_SHA256,
        },
        "class_mappings": phase["class_mappings"],
        "class0_and_nodata_policy": phase["class0_and_nodata_policy"],
        "categories": list(CATEGORIES_V2),
        "excluded_from_valid_mapped_denominator": list(EXCLUDED_STATES),
        "sources": {
            COL3_KEY_V2: {
                "role": phase["collection3"]["role"],
                "source_id": phase["collection3"]["source_id"],
                "national_path": "data/landcover/updated/brazil_lulc_10m_2024.tif",
                "national_bytes": 6766932375,
                "national_sha256": (
                    "2ba20d400976020b4e7472a37de04fe1755c6f23631008b39da388001a034f59"
                ),
                "regional_crop_path": (
                    "data/landcover/mapbiomas_col3_beta_10m_2024.tif"
                ),
                "regional_crop_bytes": 10628726,
                "regional_crop_sha256": (
                    "11dc3ecd9595f2ba97dd1866ee2253088bd3014b44ffd9c24ca1381c9e5f2b10"
                ),
                "crop_reuse_policy": (
                    "unchanged_collection3_bytes_may_be_reused_after_hash_"
                    "verification"
                ),
            },
            COL10_1_KEY_V2: {
                "role": phase["collection10_1_required_source"]["role"],
                "source_id": phase["collection10_1_required_source"]["source_id"],
                "gee_asset": phase["collection10_1_required_source"]["gee_asset"],
                "band": phase["collection10_1_required_source"]["band"],
                "export_contract": phase["collection10_1_required_source"][
                    "export_contract"
                ],
                "export_manifest_path": str(EXPORT_MANIFEST_PATH),
                "export_manifest_sha256": _sha256_file(export_manifest_path),
                "regional_path": export_manifest["output_path"],
                "regional_bytes": export_manifest["output_bytes"],
                "regional_sha256": export_manifest["output_sha256"],
            },
        },
        "mislabeled_collection10_invalidation": {
            "path": "data/landcover/mapbiomas_col10_1_30m_2024.tif",
            "bytes": 2795066,
            "sha256": (
                "fdab3fd186fdfc44da9e798761c7edf6327ea12e5939e3d1198a258df9a88e9e"
            ),
            "actual_collection": "10",
            "labeled_collection": "10.1",
            "origin_url": audit["origin_url"],
            "national_source_sha256": audit["local_sha256"],
            "runtime_use_permitted": False,
            "qualified_review_use_permitted": False,
            "audit_bytes_deleted": False,
            "replacement_source": COL10_1_KEY_V2,
        },
        "strong_subset": phase["strong_subset"],
        "contextual_signature": phase["contextual_signature"],
        "cross_collection_comparison": phase["cross_collection_comparison"],
        "licence_and_attribution": {
            "provider_terms": "CC-BY with required attribution",
            "national_source_redistribution_approved": False,
            "required_for_derivatives": [
                "collection-specific attribution",
                "corresponding ATBD",
                "source URL",
                "access date",
                "legend version",
                "recorded limitations",
            ],
        },
        "decision_state": {
            "candidate_generation_policy_gate": "closed",
            "scientific_validation_gate": "open_phase5",
            "public_labels_enabled": False,
            "raw_detection_removal_permitted": False,
        },
    }
    return registry


def load_context_registry_v2(
    path: Path | str = REGISTRY_V2_PATH, *, root: Path | str = "."
) -> dict[str, Any]:
    """Load the stored v2 registry and require it to re-derive exactly."""

    stored = json.loads(Path(path).read_text("utf-8"))
    derived = generate_context_registry_v2(root)
    _require(
        stored == derived,
        "the stored v2 context registry does not re-derive from the accepted "
        "decision record and current bindings; it may have drifted",
    )
    return stored


# ─── v2 classification and denominators ──────────────────────────────────────


def _mapping_lookup_v2(
    registry: Mapping[str, Any], collection_key: str
) -> dict[int, str]:
    _require(
        collection_key in COLLECTION_KEYS_V2,
        f"unknown collection key: {collection_key}",
    )
    mapping_key = (
        "collection3_beta_10m_2024"
        if collection_key == COL3_KEY_V2
        else "collection10_family_30m_2024"
    )
    mapping = registry["class_mappings"][mapping_key]
    lookup: dict[int, str] = {}
    for category in MAPPED_CATEGORIES:
        for raw in mapping.get(category, []):
            code = int(raw)
            previous = lookup.setdefault(code, category)
            _require(
                previous == category,
                f"class {code} appears in both {previous} and {category}",
            )
    return lookup


def classify_mapbiomas_codes_v2(
    codes: np.ndarray | Iterable[int],
    collection_key: str,
    registry: Mapping[str, Any],
) -> np.ndarray:
    """Classify codes under the v2 policy without coercing any unknown value.

    Per-collection special states, applied before the category mapping:
    Collection 3 treats 0 as NoData (its header says so); the Collection 10
    family treats 0 as unknown/unclassified; the fresh 10.1 export adds 255
    as the exported source mask. Code 27 is ``not_observed`` everywhere.
    """

    lookup = _mapping_lookup_v2(registry, collection_key)
    values = np.asarray(codes)
    labels = np.full(values.shape, "unmapped", dtype="<U24")
    for code, category in lookup.items():
        labels[values == code] = category
    labels[values == NOT_OBSERVED_CODE] = "not_observed"
    if collection_key == COL3_KEY_V2:
        labels[values == 0] = "nodata"
    else:
        labels[values == 0] = "unknown_unclassified"
        labels[values == EXPORT_MASK_VALUE] = "nodata"
    return labels


def summarize_polygon_context_v2(
    values: np.ndarray,
    collection_key: str,
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    """Explicit per-state accounting with the v2 denominator policy."""

    array = np.asarray(values).reshape(-1)
    labels = classify_mapbiomas_codes_v2(array, collection_key, registry)
    histogram = {
        str(int(code)): int(count)
        for code, count in zip(*np.unique(array, return_counts=True))
    }
    counts = {
        category: int(np.count_nonzero(labels == category))
        for category in CATEGORIES_V2
    }
    total = int(array.size)
    excluded = sum(counts[state] for state in EXCLUDED_STATES)
    mapped_valid = total - excluded
    _require(
        mapped_valid == sum(counts[c] for c in MAPPED_CATEGORIES),
        "v2 denominator accounting is inconsistent",
    )
    natural_fraction = (
        counts["natural_vegetation"] / mapped_valid if mapped_valid else None
    )
    return {
        "collection_key": collection_key,
        "total_pixel_count": total,
        "valid_mapped_pixel_count": mapped_valid,
        "excluded_pixel_counts": {
            state: counts[state] for state in EXCLUDED_STATES
        },
        "category_counts": {c: counts[c] for c in MAPPED_CATEGORIES},
        "category_proportions": {
            category: (counts[category] / mapped_valid if mapped_valid else None)
            for category in MAPPED_CATEGORIES
        },
        "natural_fraction": natural_fraction,
        "class_histogram": histogram,
    }


def strong_subset_membership_v2(
    natural_pixel_count: int,
    valid_mapped_pixel_count: int,
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate the selected 0.50 subset and the 0.75 sensitivity alternative.

    A zero denominator is ``not_assessed`` — never excluded — and no outcome
    can remove, relabel, or reorder a raw detection.
    """

    subset = registry["strong_subset"]
    _require(
        subset["selected_method"] == "natural-vegetation-share-0.50-v2",
        "the selected strong-subset method is not the accepted v2 method",
    )
    _require(
        0 <= natural_pixel_count <= valid_mapped_pixel_count
        if valid_mapped_pixel_count
        else natural_pixel_count == 0,
        "natural pixel count exceeds the valid mapped denominator",
    )
    fraction = (
        natural_pixel_count / valid_mapped_pixel_count
        if valid_mapped_pixel_count
        else None
    )

    def _one(method: str, threshold: float, *, selected: bool) -> dict[str, Any]:
        if fraction is None:
            membership = subset["zero_denominator_state"]
            reason = "no valid mapped Collection 3 pixels"
        else:
            membership = "included" if fraction >= threshold else "excluded"
            reason = None
        return {
            "method": method,
            "threshold": threshold,
            "natural_pixel_count": int(natural_pixel_count),
            "valid_mapped_pixel_count": int(valid_mapped_pixel_count),
            "natural_fraction": fraction,
            "membership": membership,
            "reason": reason,
            "selected": selected,
            "activated": False,
            "raw_detection_retained": True,
            "public_name": subset["public_name"] if selected else None,
        }

    return {
        "selected": _one(
            subset["selected_method"], float(subset["threshold"]), selected=True
        ),
        "sensitivity_only": _one(
            subset["sensitivity_alternative"]["method"], 0.75, selected=False
        ),
    }


# ─── cross-collection comparison against the fresh 10.1 export ───────────────


def align_secondary_nearest(
    *,
    primary_transform: Iterable[float],
    primary_shape: tuple[int, int],
    secondary_values: np.ndarray,
    secondary_transform: Iterable[float],
) -> np.ndarray:
    """Sample the secondary grid at each primary pixel centre, nearest-only.

    Both grids are axis-aligned EPSG:4326 lattices, so nearest-neighbour
    alignment is an exact index computation with no interpolation and no
    categorical mixing. Primary centres outside the secondary raster fail
    closed rather than wrapping.
    """

    pt = [float(v) for v in primary_transform]
    st = [float(v) for v in secondary_transform]
    _require(
        pt[1] == 0 and pt[3] == 0 and st[1] == 0 and st[3] == 0,
        "nearest alignment requires axis-aligned grids",
    )
    rows, cols = primary_shape
    xs = pt[2] + (np.arange(cols) + 0.5) * pt[0]
    ys = pt[5] + (np.arange(rows) + 0.5) * pt[4]
    sec_cols = np.floor((xs - st[2]) / st[0]).astype(np.int64)
    sec_rows = np.floor((ys - st[5]) / st[4]).astype(np.int64)
    _require(
        bool(
            (sec_cols >= 0).all()
            and (sec_cols < secondary_values.shape[1]).all()
            and (sec_rows >= 0).all()
            and (sec_rows < secondary_values.shape[0]).all()
        ),
        "a primary pixel centre falls outside the secondary raster",
    )
    return secondary_values[np.ix_(sec_rows, sec_cols)]


def calculate_agreement_disagreement_v2(
    primary_codes: np.ndarray,
    secondary_codes_aligned: np.ndarray,
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    """Category agreement as context only, per the accepted v2 comparison.

    The denominator is the set of primary pixels that are valid and mapped;
    within it, a pixel whose aligned secondary state is excluded becomes
    ``not_assessed``. Nothing here can break a tie, change subset membership,
    or modify a raw detection.
    """

    comparison = registry["cross_collection_comparison"]
    _require(
        comparison["comparison_denominator"]
        == "joint_valid_and_mapped_primary_pixels",
        "unexpected cross-collection denominator policy",
    )
    primary = np.asarray(primary_codes).reshape(-1)
    secondary = np.asarray(secondary_codes_aligned).reshape(-1)
    _require(
        primary.shape == secondary.shape,
        "aligned arrays have different sizes",
    )
    left = classify_mapbiomas_codes_v2(primary, COL3_KEY_V2, registry)
    right = classify_mapbiomas_codes_v2(secondary, COL10_1_KEY_V2, registry)
    primary_mapped = np.isin(left, MAPPED_CATEGORIES)
    secondary_mapped = np.isin(right, MAPPED_CATEGORIES)
    denominator = int(np.count_nonzero(primary_mapped))
    assessed_mask = primary_mapped & secondary_mapped
    assessed = int(np.count_nonzero(assessed_mask))
    agree = int(np.count_nonzero(assessed_mask & (left == right)))
    pair_counts: dict[str, int] = {}
    for a, b in zip(left[assessed_mask], right[assessed_mask]):
        key = f"{a}|{b}"
        pair_counts[key] = pair_counts.get(key, 0) + 1
    return {
        "interpretation": comparison["interpretation"],
        "resampling": comparison["secondary_to_primary_resampling"],
        "primary_valid_mapped_pixel_count": denominator,
        "assessed_pixel_count": assessed,
        "not_assessed_pixel_count": denominator - assessed,
        "agreement_count": agree,
        "disagreement_count": assessed - agree,
        "agreement_fraction": agree / assessed if assessed else None,
        "state": (
            "not_assessed"
            if not assessed
            else "agreement"
            if agree * 2 >= assessed
            else "disagreement"
        ),
        "category_pair_histogram": dict(sorted(pair_counts.items())),
        "tie_breaking_permitted": False,
        "subset_change_permitted": False,
        "raw_detection_change_permitted": False,
    }


# ─── the selected internal signature aggregator ──────────────────────────────


def aggregate_dominant_share_v2(
    labels: np.ndarray,
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply the selected ``dominant-assessed-share-0.60-v1`` aggregator.

    It runs on ONE observation stratum — the accepted v2 mask and composition
    — never across the obsolete Phase 2A.4 candidate strata. A unique top
    assessed class is emitted only at a share of at least 0.60; otherwise
    ``mixed_or_uncertain``; an empty assessed denominator is ``not_assessed``.
    """

    signature = registry["contextual_signature"]
    _require(
        signature["selected_internal_aggregator"]
        == "dominant-assessed-share-0.60-v1",
        "the selected aggregator is not the accepted dominant-share rule",
    )
    proportions = contextual_signature_proportions(np.asarray(labels))
    counts = proportions.get("counts", proportions.get("class_counts"))
    assessed_labels = (
        "fire_like",
        "exposed_soil_or_clearing_like",
        "mixed_or_uncertain",
    )
    assessed_total = sum(int(counts[label]) for label in assessed_labels)
    if not assessed_total:
        return {
            "aggregator": signature["selected_internal_aggregator"],
            "label": "not_assessed",
            "assessed_pixel_count": 0,
            "reason": signature["zero_assessed_pixel_state"],
            "shares": {label: None for label in assessed_labels},
            "internal_candidate_only": True,
            "causal_inference": False,
            "public_label_enabled": False,
        }
    shares = {
        label: int(counts[label]) / assessed_total for label in assessed_labels
    }
    ordered = sorted(shares.items(), key=lambda item: (-item[1], item[0]))
    top_label, top_share = ordered[0]
    unique_top = top_share > ordered[1][1]
    label = (
        top_label
        if unique_top and top_share >= 0.60
        else "mixed_or_uncertain"
    )
    return {
        "aggregator": signature["selected_internal_aggregator"],
        "label": label,
        "assessed_pixel_count": assessed_total,
        "reason": None,
        "shares": shares,
        "internal_candidate_only": True,
        "causal_inference": False,
        "public_label_enabled": False,
    }
