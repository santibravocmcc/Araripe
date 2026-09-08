"""Package 2A.6D per-case MapBiomas and signature evidence (v2).

Regenerates the 60-case contextual evidence under the accepted 2026-08-11
decisions, superseding the v1 evidence for future candidate work while the v1
artifact stays byte-unchanged as audit material:

- MapBiomas context uses the ``mapbiomas-context-groups-v2`` mappings, the
  pixel-centre polygon rule (the v1 evidence used ``all_touched``), the
  explicit 0/27/255 exclusion states, and the fresh Collection 10.1 GEE
  export as the secondary collection;
- the strong subset is the selected ``natural-vegetation-share-0.50-v2``
  with the 0.75 alternative recorded as sensitivity only;
- the non-causal contextual signature is computed on the ACCEPTED v2 mask and
  datatake-scoped composition, rebuilt per case from the retained Phase 2A.4
  source windows through the closed 2A.6B science — never on the obsolete
  Phase 2A.4 candidate strata — and dNBR references the rebuilt baseline
  2.1.0, because comparing a v2-mask composite against the v1-mask baseline
  is exactly the incompatibility the rebuild removed;
- every raw detection's geometry, identity and order are preserved bit for
  bit, and nothing here can delete, relabel or filter one.

Same-day physics is respected: scenes are grouped into physical datatakes and
each datatake is its own observation stratum. A scene whose metadata fails the
closed v2 gates (an unreviewed processing baseline, say) makes its stratum
fail closed with the typed reason; it is recorded, never coerced.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.warp import transform_geom
from rasterio.windows import Window

from src.processing.composition_v2 import (
    compose_datatake,
    create_scene_input_v2,
    group_scenes_by_datatake,
)
from src.processing.scl_mask_v2 import (
    REVIEWED_PROCESSING_BASELINES,
    SclMaskUnavailableError,
)
from src.validation.phase2a5_context_v2 import (
    COL3_KEY_V2,
    COL10_1_KEY_V2,
    Phase2A5ContextV2Error,
    REGIONAL_MANIFEST_V2_PATH,
    REGISTRY_V2_PATH,
    aggregate_dominant_share_v2,
    align_secondary_nearest,
    calculate_agreement_disagreement_v2,
    classify_contextual_signature_pixels,
    classify_mapbiomas_codes_v2,
    load_context_registry_v2,
    strong_subset_membership_v2,
    summarize_polygon_context_v2,
)

EVIDENCE_V2_VERSION = "phase2a5-context-evidence-v2"
CASE_FILENAME = "case-evidence-v2.json"
CHECKSUM_FILENAME = "CHECKSUMS.sha256"
# The six retained reflectance windows, keyed by provider band.
WINDOW_BANDS = {
    "blue": "blue",
    "B4": "red",
    "B8": "nir",
    "B8A": "nir08",
    "B11": "swir16",
    "B12": "swir22",
}
BASELINE_V2_MANIFEST = Path("config/baseline_manifest_v2_1.json")
BASELINE_V2_DIR = Path("data/baselines_v2/2.1.0")


class Phase2A5EvidenceV2Error(ValueError):
    """Raised when an input or output violates the v2 evidence contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Phase2A5EvidenceV2Error(message)


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


def _load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


@dataclass(frozen=True)
class EvidenceV2Config:
    output_dir: Path
    phase2a3_dir: Path
    phase2a4_dir: Path
    generated_at: str
    repository_root: Path


# ─── per-case MapBiomas context under the v2 rules ───────────────────────────


def _polygon_values(
    raster_path: Path, geometry: Mapping[str, Any]
) -> tuple[np.ndarray, Any]:
    """Values of the pixels whose CENTRES fall inside the polygon.

    ``all_touched=False`` is rasterio's centre-containment rule — the accepted
    v2 polygon rule. The v1 evidence used ``all_touched=True``; the change is
    deliberate and recorded, not incidental.
    """

    with rasterio.open(raster_path) as dataset:
        native = transform_geom("EPSG:4326", dataset.crs, geometry, precision=-1)
        from shapely.geometry import shape as _shape
        from rasterio.windows import from_bounds

        bounds = _shape(native).bounds
        raw = from_bounds(*bounds, transform=dataset.transform)
        col0 = max(0, int(np.floor(raw.col_off)))
        row0 = max(0, int(np.floor(raw.row_off)))
        col1 = min(dataset.width, int(np.ceil(raw.col_off + raw.width)))
        row1 = min(dataset.height, int(np.ceil(raw.row_off + raw.height)))
        _require(
            col1 > col0 and row1 > row0,
            "case geometry does not intersect the regional raster",
        )
        window = Window(col0, row0, col1 - col0, row1 - row0)
        values = dataset.read(1, window=window)
        window_transform = dataset.window_transform(window)
        selected = geometry_mask(
            [native],
            out_shape=values.shape,
            transform=window_transform,
            invert=True,
            all_touched=False,
        )
        return values[selected], window_transform


def _mapbiomas_context_v2(
    geometry: Mapping[str, Any],
    registry: Mapping[str, Any],
    regional: Mapping[str, Any],
) -> dict[str, Any]:
    col3_path = Path(regional["regional_sources"][COL3_KEY_V2]["path"])
    col10_1_path = Path(regional["regional_sources"][COL10_1_KEY_V2]["path"])

    primary_values, _ = _polygon_values(col3_path, geometry)
    primary = summarize_polygon_context_v2(primary_values, COL3_KEY_V2, registry)
    subset = strong_subset_membership_v2(
        primary["category_counts"]["natural_vegetation"],
        primary["valid_mapped_pixel_count"],
        registry,
    )

    # Cross-collection: align the fresh 10.1 export to the SAME primary
    # pixels. The primary polygon pixels are re-read here as a full window so
    # the aligned secondary shares their lattice positions exactly.
    with rasterio.open(col3_path) as primary_ds:
        native = transform_geom(
            "EPSG:4326", primary_ds.crs, geometry, precision=-1
        )
        from shapely.geometry import shape as _shape
        from rasterio.windows import from_bounds

        bounds = _shape(native).bounds
        raw = from_bounds(*bounds, transform=primary_ds.transform)
        col0 = max(0, int(np.floor(raw.col_off)))
        row0 = max(0, int(np.floor(raw.row_off)))
        col1 = min(primary_ds.width, int(np.ceil(raw.col_off + raw.width)))
        row1 = min(primary_ds.height, int(np.ceil(raw.row_off + raw.height)))
        window = Window(col0, row0, col1 - col0, row1 - row0)
        window_values = primary_ds.read(1, window=window)
        window_transform = primary_ds.window_transform(window)
        selected = geometry_mask(
            [native],
            out_shape=window_values.shape,
            transform=window_transform,
            invert=True,
            all_touched=False,
        )
    with rasterio.open(col10_1_path) as secondary_ds:
        secondary_full = secondary_ds.read(1)
        secondary_transform = list(secondary_ds.transform)[:6]
    aligned = align_secondary_nearest(
        primary_transform=list(window_transform)[:6],
        primary_shape=window_values.shape,
        secondary_values=secondary_full,
        secondary_transform=secondary_transform,
    )
    comparison = calculate_agreement_disagreement_v2(
        window_values[selected], aligned[selected], registry
    )
    secondary = summarize_polygon_context_v2(
        aligned[selected], COL10_1_KEY_V2, registry
    )

    if not primary["valid_mapped_pixel_count"]:
        status, reason = "unreviewable", "no valid mapped Collection 3 pixels"
    elif primary["valid_mapped_pixel_count"] < primary["total_pixel_count"]:
        status = "partial"
        reason = (
            f"{primary['valid_mapped_pixel_count']} of "
            f"{primary['total_pixel_count']} polygon pixels are valid and mapped"
        )
    else:
        status, reason = "available", None
    return {
        "status": status,
        "reason": reason,
        "polygon_pixel_rule": "pixel_centre_within_polygon",
        "mapping_version": registry["class_mappings"]["mapping_version"],
        "collections": {COL3_KEY_V2: primary, COL10_1_KEY_V2: secondary},
        "strong_subset_v2": subset,
        "cross_collection_v2": comparison,
    }


# ─── per-case signature under the ACCEPTED v2 mask and composition ───────────


def _scene_inputs(case_dir: Path) -> list[Any]:
    scenes = []
    source_dir = case_dir / "source-scenes"
    if not source_dir.exists():
        return scenes
    for record_path in sorted(source_dir.glob("*.json")):
        stac = _load_json(record_path)
        window_dir = case_dir / "source-windows" / record_path.stem
        scl = np.load(window_dir / "scl.npy").astype(np.int16)
        scl_valid = np.load(window_dir / "scl-valid.npy").astype(bool)
        scl = np.where(scl_valid, scl, 0)  # SCL 0 is provider no-data
        bands: dict[str, np.ndarray] = {}
        for band_name, window_name in WINDOW_BANDS.items():
            values = np.load(window_dir / f"{window_name}.npy").astype(np.float64)
            valid = np.load(window_dir / f"{window_name}-valid.npy").astype(bool)
            bands[band_name] = np.where(valid, values, np.nan)
        properties = stac["properties"]
        scenes.append(
            create_scene_input_v2(
                scene_id=stac["id"],
                platform=properties["platform"],
                datatake_id=properties["s2:datatake_id"],
                properties=properties,
                scl=scl,
                bands=bands,
            )
        )
    return scenes


def _signature_context_v2(
    *,
    case_dir: Path,
    case_record: Mapping[str, Any],
    geometry: Mapping[str, Any],
    registry: Mapping[str, Any],
    baseline_nbr_by_month: Mapping[int, Any],
    output_case_dir: Path,
) -> dict[str, Any]:
    context = case_record["grid"]["context_window"]
    transform = [float(v) for v in context["transform"]]
    crs = case_record["grid"]["reference_grid"].get("crs", "EPSG:32724")
    shape = (int(context["height"]), int(context["width"]))

    native = transform_geom("EPSG:4326", crs, geometry, precision=-1)
    from rasterio.transform import Affine

    polygon = geometry_mask(
        [native],
        out_shape=shape,
        transform=Affine(*transform),
        invert=True,
        all_touched=False,
    )
    rows, cols = np.nonzero(polygon)
    month = int(str(case_record["target_date"])[5:7])
    baseline_reader = baseline_nbr_by_month[month]
    window = Window(
        int(context["column_offset"]),
        int(context["row_offset"]),
        shape[1],
        shape[0],
    )
    baseline_nbr = baseline_reader.read(1, window=window).astype(np.float64)

    scenes = _scene_inputs(case_dir)
    groups = group_scenes_by_datatake(scenes) if scenes else []
    observations: list[dict[str, Any]] = []
    if not scenes:
        # An acquisition the pilot could not retain is an explicit absent
        # state, exactly as the v1 evidence recorded it — never a zero.
        observations.append(
            {
                "status": "unreviewable",
                "reason": "no retained source scene for the target date",
                "mask_method": "scl-explicit-allowlist-v2",
                "composition_method": "coverage-ranked-first-valid-v1",
                "baseline_version": "2.1.0",
                "baseline_month": month,
                "aggregate": {
                    "aggregator": "dominant-assessed-share-0.60-v1",
                    "label": "not_assessed",
                    "assessed_pixel_count": 0,
                    "reason": "no retained source scene",
                    "internal_candidate_only": True,
                    "causal_inference": False,
                    "public_label_enabled": False,
                },
            }
        )
    for group in groups:
        entry: dict[str, Any] = {
            "platform": group.platform,
            "datatake_id": group.datatake_id,
            "scene_ids": [scene.scene_id for scene in group.scenes],
            "mask_method": "scl-explicit-allowlist-v2",
            "composition_method": "coverage-ranked-first-valid-v1",
            "baseline_version": "2.1.0",
            "baseline_month": month,
        }
        try:
            composite = compose_datatake(
                group, reviewed_baselines=REVIEWED_PROCESSING_BASELINES
            )
        except (SclMaskUnavailableError, ValueError) as exc:
            entry.update(
                {
                    "status": "unreviewable",
                    "reason": f"fail-closed composition: {exc}",
                    "aggregate": {
                        "aggregator": "dominant-assessed-share-0.60-v1",
                        "label": "not_assessed",
                        "assessed_pixel_count": 0,
                        "reason": "composition failed closed",
                        "internal_candidate_only": True,
                        "causal_inference": False,
                        "public_label_enabled": False,
                    },
                }
            )
            observations.append(entry)
            continue
        band = {
            name: np.asarray(composite.composed_bands[name], dtype=np.float64)
            for name in WINDOW_BANDS
        }
        with np.errstate(divide="ignore", invalid="ignore"):
            post_nbr = (band["B8A"] - band["B12"]) / (band["B8A"] + band["B12"])
            bsi = ((band["B11"] + band["B4"]) - (band["B8"] + band["blue"])) / (
                band["B11"] + band["B4"] + band["B8"] + band["blue"]
            )
        dnbr = baseline_nbr - post_nbr
        post_sel = post_nbr[rows, cols].astype(np.float32)
        bsi_sel = bsi[rows, cols].astype(np.float32)
        dnbr_sel = dnbr[rows, cols].astype(np.float32)
        valid = (
            np.isfinite(post_sel) & np.isfinite(bsi_sel) & np.isfinite(dnbr_sel)
        )
        labels = classify_contextual_signature_pixels(dnbr_sel, post_sel, bsi_sel)
        labels = np.asarray(labels).astype("<U32")
        labels[~valid] = "not_assessed"
        aggregate = aggregate_dominant_share_v2(labels, registry)

        stratum_dir = (
            output_case_dir / "signature-v2" / group.datatake_id.replace("/", "_")
        )
        stratum_dir.mkdir(parents=True, exist_ok=True)
        arrays = {
            "dnbr": dnbr_sel,
            "post_nbr": post_sel,
            "bsi": bsi_sel,
            "valid": valid.astype(np.uint8),
        }
        digests = {}
        for name, array in arrays.items():
            path = stratum_dir / f"{name}.npy"
            np.save(path, array)
            digests[name] = _sha256_file(path)
        valid_count = int(valid.sum())
        entry.update(
            {
                "status": (
                    "unreviewable"
                    if not valid_count
                    else "partial"
                    if valid_count < int(polygon.sum())
                    else "available"
                ),
                "reason": (
                    "no finite within-polygon measurements"
                    if not valid_count
                    else None
                    if valid_count == int(polygon.sum())
                    else f"{valid_count} of {int(polygon.sum())} polygon "
                    "pixels have finite v2-composite measurements"
                ),
                "observed_processing_baselines": list(
                    composite.observed_processing_baselines
                ),
                "composed_pixel_count": int(composite.composed_pixel_count),
                "polygon_pixel_count": int(polygon.sum()),
                "finite_polygon_pixel_count": valid_count,
                "array_sha256": digests,
                "aggregate": aggregate,
            }
        )
        observations.append(entry)

    polygon_indices = np.stack([rows, cols], axis=1).astype(np.int32)
    indices_path = output_case_dir / "signature-v2" / "polygon-pixel-indices.npy"
    indices_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(indices_path, polygon_indices)
    return {
        "aggregation_scope": "selected_v2_mask_and_composition_only",
        "same_day_datatakes_kept_separate": True,
        "observation_count": len(observations),
        "polygon_pixel_indices_sha256": _sha256_file(indices_path),
        "observations": observations,
    }


# ─── build and validate ──────────────────────────────────────────────────────


def _checksum_inventory(root: Path) -> list[dict[str, Any]]:
    entries = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in {"manifest.json", CHECKSUM_FILENAME}:
            continue
        entries.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return entries


def _write_checksums(root: Path, inventory: list[dict[str, Any]]) -> None:
    lines = [f"{entry['sha256']}  {entry['path']}" for entry in inventory]
    manifest_sha = _sha256_file(root / "manifest.json")
    lines.append(f"{manifest_sha}  manifest.json")
    (root / CHECKSUM_FILENAME).write_text("\n".join(lines) + "\n", "utf-8")


def build_phase2a5_evidence_v2(config: EvidenceV2Config) -> dict[str, Any]:
    target = Path(config.output_dir).absolute()
    _require(
        not os.path.lexists(target),
        f"output already exists; refusing to replace evidence: {target}",
    )
    registry = load_context_registry_v2(root=config.repository_root)
    regional = _load_json(config.repository_root / REGIONAL_MANIFEST_V2_PATH)
    baseline_manifest = _load_json(config.repository_root / BASELINE_V2_MANIFEST)
    _require(
        baseline_manifest["baseline_version"] == "2.1.0",
        "the rebuilt baseline manifest is not version 2.1.0",
    )
    nbr_objects = {
        obj["month"]: obj
        for obj in baseline_manifest["objects"]
        if obj["index"] == "nbr" and obj["filename_statistic"] == "mean"
    }

    sample = _load_json(config.phase2a3_dir / "sampling/sample.geojson")
    features = sample["features"]
    _require(len(features) == 60, f"expected 60 cases, found {len(features)}")
    crosswalk = {
        entry["sample_id"]: entry
        for entry in _load_json(
            config.phase2a3_dir / "coordinator/crosswalk.json"
        )["mappings"]
    }

    staging = target.parent / f".{target.name}.staging-{os.getpid()}"
    _require(not staging.exists(), f"stale staging directory: {staging}")
    staging.mkdir(parents=True)
    baseline_readers: dict[int, Any] = {}
    try:
        # Open (and hash-verify) each monthly baseline NBR raster once.
        months_needed = sorted(
            {int(str(f["properties"]["observed_on"])[5:7]) for f in features}
        )
        baseline_bindings = {}
        for month in months_needed:
            obj = nbr_objects[month]
            path = config.repository_root / BASELINE_V2_DIR / obj["filename"]
            _require(
                _sha256_file(path) == obj["sha256"],
                f"baseline raster {obj['filename']} does not match the 2.1.0 "
                "manifest",
            )
            baseline_readers[month] = rasterio.open(path)
            baseline_bindings[str(month)] = {
                "filename": obj["filename"],
                "sha256": obj["sha256"],
            }

        descriptors = []
        subset_totals = {"included": 0, "excluded": 0, "not_assessed": 0}
        comparison_states = {"agreement": 0, "disagreement": 0, "not_assessed": 0}
        aggregate_labels: dict[str, int] = {}
        geometry_hashes = []
        for order_index, feature in enumerate(features):
            properties = feature["properties"]
            sample_id = properties["sample_id"]
            geometry = feature["geometry"]
            geometry_sha = _canonical_sha256(geometry)
            geometry_hashes.append(geometry_sha)
            p2a3_case = _load_json(
                config.phase2a3_dir / "coordinator/cases" / f"{sample_id}.json"
            )
            _require(
                p2a3_case["source"]["geometry_sha256"] == geometry_sha,
                f"Phase 2A.3 geometry checksum mismatch for {sample_id}",
            )
            case_dir = config.phase2a4_dir / "cases" / sample_id
            case_record = _load_json(case_dir / "case-evidence.json")
            _require(
                case_record["target_geometry_sha256"] == geometry_sha,
                f"Phase 2A.4 geometry checksum mismatch for {sample_id}",
            )
            _require(
                properties["observed_on"] == case_record["target_date"],
                f"target-date mismatch for {sample_id}",
            )
            output_case_dir = staging / "cases" / sample_id
            mapbiomas = _mapbiomas_context_v2(geometry, registry, regional)
            signature = _signature_context_v2(
                case_dir=case_dir,
                case_record=case_record,
                geometry=geometry,
                registry=registry,
                baseline_nbr_by_month=baseline_readers,
                output_case_dir=output_case_dir,
            )
            subset_totals[
                mapbiomas["strong_subset_v2"]["selected"]["membership"]
            ] += 1
            comparison_states[mapbiomas["cross_collection_v2"]["state"]] += 1
            for observation in signature["observations"]:
                label = observation["aggregate"]["label"]
                aggregate_labels[label] = aggregate_labels.get(label, 0) + 1
            record = {
                "schema_version": "1.0.0",
                "evidence_version": EVIDENCE_V2_VERSION,
                "sample_id": sample_id,
                "blind_case_id": crosswalk[sample_id]["blind_case_id"],
                "source_order_index": order_index,
                "target_date": properties["observed_on"],
                "raw_detection": {
                    "geometry": geometry,
                    "geometry_sha256": geometry_sha,
                    "source_record_id": p2a3_case["source"]["source_record_id"],
                    "source_feature_index": p2a3_case["source"][
                        "source_feature_index"
                    ],
                    "geometry_preserved": True,
                    "identity_preserved": True,
                    "order_preserved": True,
                    "filtered_or_relabelled": False,
                },
                "mapbiomas_v2": mapbiomas,
                "contextual_signature_v2": signature,
                "claims": {
                    "scientific_accuracy": False,
                    "causal_labels": False,
                    "public_labels": False,
                    "population_totals": False,
                },
            }
            _write_json(output_case_dir / CASE_FILENAME, record)
            descriptors.append(
                {
                    "sample_id": sample_id,
                    "blind_case_id": record["blind_case_id"],
                    "subset_membership": mapbiomas["strong_subset_v2"][
                        "selected"
                    ]["membership"],
                    "cross_collection_state": mapbiomas["cross_collection_v2"][
                        "state"
                    ],
                }
            )
    finally:
        for reader in baseline_readers.values():
            reader.close()

    manifest = {
        "schema_version": "1.0.0",
        "evidence_version": EVIDENCE_V2_VERSION,
        "generated_at": config.generated_at,
        "decision_binding": registry["decision_binding"],
        "bindings": {
            "context_registry_v2": {
                "path": str(REGISTRY_V2_PATH),
                "sha256": _sha256_file(
                    config.repository_root / REGISTRY_V2_PATH
                ),
            },
            "regional_context_manifest_v2": {
                "path": str(REGIONAL_MANIFEST_V2_PATH),
                "sha256": _sha256_file(
                    config.repository_root / REGIONAL_MANIFEST_V2_PATH
                ),
            },
            "baseline_manifest_v2_1": {
                "path": str(BASELINE_V2_MANIFEST),
                "sha256": _sha256_file(
                    config.repository_root / BASELINE_V2_MANIFEST
                ),
                "baseline_version": baseline_manifest["baseline_version"],
                "monthly_nbr_mean": baseline_bindings,
            },
            "phase2a3_manifest_sha256": _sha256_file(
                config.phase2a3_dir / "manifest.json"
            ),
            "phase2a4_manifest_sha256": _sha256_file(
                config.phase2a4_dir / "manifest.json"
            ),
            "superseded_v1_evidence": {
                "role": "audit_only",
                "runtime_use_permitted": False,
                "qualified_review_use_permitted": False,
            },
        },
        "polygon_pixel_rule": "pixel_centre_within_polygon",
        "case_count": len(descriptors),
        "raw_detection_count": len(descriptors),
        "original_geometry_order_sha256": _canonical_sha256(geometry_hashes),
        "strong_subset_v2_totals": subset_totals,
        "cross_collection_v2_states": comparison_states,
        "signature_v2_aggregate_labels": dict(sorted(aggregate_labels.items())),
        "cases": descriptors,
        "claims": {
            "scientific_accuracy": False,
            "causal_labels": False,
            "public_labels": False,
            "population_totals": False,
            "raw_detection_removal": False,
        },
    }
    manifest["evidence_id"] = "p2a5-context-evidence-v2-" + _canonical_sha256(
        {key: manifest[key] for key in sorted(manifest) if key != "evidence_id"}
    )
    _write_json(staging / "manifest.json", manifest)
    inventory = _checksum_inventory(staging)
    manifest["artifact_inventory_sha256"] = _canonical_sha256(inventory)
    _write_json(staging / "manifest.json", manifest)
    _write_checksums(staging, inventory)

    validate_phase2a5_evidence_v2(staging, repository_root=config.repository_root)
    os.rename(staging, target)
    return manifest


def validate_phase2a5_evidence_v2(
    root: Path, *, repository_root: Path
) -> dict[str, Any]:
    """Re-verify the artifact from its own bytes, failing closed."""

    root = Path(root)
    manifest = _load_json(root / "manifest.json")
    _require(
        manifest["evidence_version"] == EVIDENCE_V2_VERSION,
        "unexpected evidence version",
    )
    inventory = _checksum_inventory(root)
    _require(
        manifest["artifact_inventory_sha256"] == _canonical_sha256(inventory),
        "artifact inventory checksum mismatch",
    )
    checksums = (root / CHECKSUM_FILENAME).read_text("utf-8").splitlines()
    recorded = {
        line.split("  ", 1)[1]: line.split("  ", 1)[0] for line in checksums
    }
    for entry in inventory:
        _require(
            recorded.get(entry["path"]) == entry["sha256"],
            f"checksum file disagrees for {entry['path']}",
        )
    _require(
        recorded.get("manifest.json") == _sha256_file(root / "manifest.json"),
        "checksum file disagrees for manifest.json",
    )
    for name, binding in manifest["bindings"].items():
        if isinstance(binding, Mapping) and "path" in binding:
            _require(
                _sha256_file(repository_root / binding["path"])
                == binding["sha256"],
                f"binding {name} no longer matches its recorded checksum",
            )
    _require(manifest["case_count"] == 60, "case count must be 60")
    _require(
        manifest["raw_detection_count"] == manifest["case_count"],
        "raw detections must equal cases",
    )
    cases_dir = root / "cases"
    case_ids = sorted(path.name for path in cases_dir.iterdir())
    _require(len(case_ids) == 60, "case directory count must be 60")
    totals = {"included": 0, "excluded": 0, "not_assessed": 0}
    for descriptor in manifest["cases"]:
        record = _load_json(
            cases_dir / descriptor["sample_id"] / CASE_FILENAME
        )
        _require(
            record["raw_detection"]["geometry_sha256"]
            == _canonical_sha256(record["raw_detection"]["geometry"]),
            f"geometry checksum broken for {descriptor['sample_id']}",
        )
        _require(
            record["mapbiomas_v2"]["strong_subset_v2"]["selected"]["membership"]
            == descriptor["subset_membership"],
            f"manifest/case subset mismatch for {descriptor['sample_id']}",
        )
        totals[descriptor["subset_membership"]] += 1
        for observation in record["contextual_signature_v2"]["observations"]:
            for name, digest in observation.get("array_sha256", {}).items():
                path = (
                    cases_dir
                    / descriptor["sample_id"]
                    / "signature-v2"
                    / observation["datatake_id"].replace("/", "_")
                    / f"{name}.npy"
                )
                _require(
                    _sha256_file(path) == digest,
                    f"signature array checksum broken: {path}",
                )
    _require(
        totals == manifest["strong_subset_v2_totals"],
        "subset totals do not reconcile with the cases",
    )
    return manifest
