"""Build an offline, reviewer/coordinator-separated Phase 2A.3 package."""

from __future__ import annotations

import copy
import gzip
import hashlib
import html
import json
import math
import platform
import shutil
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import fiona
import numpy
import PIL
import pyproj
import rasterio
import scipy
import shapely

from src.detection.baseline_manifest import sha256_file
from src.detection.identity import canonical_json_bytes, canonical_sha256, identity_sha256
from src.validation.sampling import (
    BALANCE_LEVELS,
    MONITORING_EXTENT_BOUNDS,
    MONITORING_EXTENT_ID,
    PILOT_SCHEMA_VERSION,
    SAMPLING_DESIGN_VERSION,
)


PACKAGE_TYPE = "provisional_method_selection_pilot"
METHOD_FAMILIES = (
    "cloud_mask",
    "daily_composition",
    "drought_adjustment",
    "mapbiomas",
    "contextual_signature",
)
REQUIRED_EVIDENCE_ROLES = (
    "before_imagery",
    "after_imagery",
    "wider_spatial_context",
    "provenance_valid_time_series",
    "independent_source_comparison",
    "mapbiomas_context_comparison",
)


class ValidationPackageError(ValueError):
    """Raised when package construction cannot preserve the pilot contract."""


def write_canonical_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def write_canonical_jsonl(path: Path, values: Iterable[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        for value in values:
            handle.write(canonical_json_bytes(value))
            handle.write(b"\n")


def write_canonical_jsonl_gzip(path: Path, values: Iterable[Any]) -> None:
    """Write deterministic gzip JSONL (fixed mtime and no embedded filename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as handle:
            for value in values:
                handle.write(canonical_json_bytes(value))
                handle.write(b"\n")


def _artifact(path: Path, root: Path) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    return {
        "path": relative,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _copy_asset(
    evidence: dict[str, Any],
    *,
    reviewer_root: Path,
    blind_case_id: str,
    role: str,
) -> dict[str, Any]:
    output = copy.deepcopy(evidence)
    source = output.pop("_source_path", None)
    if source is None:
        return output
    source_path = Path(source)
    if not source_path.is_file():
        raise ValidationPackageError(f"evidence asset does not exist: {source_path}")
    suffix = source_path.suffix.lower() or ".bin"
    relative = Path("evidence") / blind_case_id / f"{role}{suffix}"
    destination = reviewer_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, destination)
    output["local_path"] = relative.as_posix()
    output["local_bytes"] = destination.stat().st_size
    output["local_sha256"] = sha256_file(destination)
    return output


def _missing_evidence(role: str) -> dict[str, Any]:
    reasons = {
        "before_imagery": "No provenance-bound pre-date image was retrieved.",
        "after_imagery": "No provenance-bound post-date image was retrieved.",
        "wider_spatial_context": "No provenance-bound wider-context image was retrieved.",
        "provenance_valid_time_series": (
            "The tracked regional SQLite series is quarantined mixed-generation "
            "audit material and has no location/acquisition provenance; it was not used."
        ),
        "independent_source_comparison": (
            "No independent-sensor comparison was retrieved. Same-sensor imagery "
            "must not be relabeled as independent evidence."
        ),
        "mapbiomas_context_comparison": (
            "No case-level 2024 MapBiomas comparison was generated. Legacy alert "
            "land-cover fields remain hidden provisional strata only."
        ),
    }
    status = "unavailable" if role == "provenance_valid_time_series" else "missing"
    return {
        "role": role,
        "status": status,
        "reason": reasons[role],
        "independence_class": (
            "independent_sensor"
            if role == "independent_source_comparison"
            else "contextual_classification"
            if role == "mapbiomas_context_comparison"
            else "operational_source_same_sensor"
        ),
        "local_path": None,
        "local_bytes": None,
        "local_sha256": None,
        "source": None,
    }


def _method_record() -> dict[str, Any]:
    return {
        family: {
            "availability": "not_generated_in_2a3",
            "option_a": None,
            "option_b": None,
            "display_order": [],
            "preference": None,
            "reviewer_confidence": None,
            "evidence_reason": None,
            "selected_or_activated": False,
        }
        for family in METHOD_FAMILIES
    }


def blank_review(blind_case_id: str) -> dict[str, Any]:
    """Return a schema-valid blank record; no human label is fabricated."""
    return {
        "schema_version": PILOT_SCHEMA_VERSION,
        "blind_case_id": blind_case_id,
        "review_status": "unreviewed",
        "reviewer": {
            "pseudonymous_id": None,
            "qualification_attested": None,
            "independence_attested": None,
        },
        "change_assessment": {
            "change_label": None,
            "reason": None,
            "evidence_sufficiency": None,
            "artifact_flags": [],
        },
        "temporal_assessment": {
            "confidence": None,
            "reason": None,
        },
        "land_cover_assessment": {
            "context": None,
            "confidence": None,
            "reason": None,
        },
        "contextual_signature": {
            "label": None,
            "reason": None,
        },
        "method_comparisons": _method_record(),
        "usability": {
            "review_duration_seconds": None,
            "missing_or_confusing_evidence": [],
            "tool_issue": None,
        },
        "notes": None,
    }


def _agreement_subset(selected: list[dict[str, Any]], seed: str) -> set[str]:
    target = max(1, math.ceil(len(selected) * 0.20))
    ordered = sorted(
        selected,
        key=lambda unit: (
            identity_sha256("phase2a3-agreement-v1", seed, unit["sample_id"]),
            unit["sample_id"],
        ),
    )
    return {unit["sample_id"] for unit in ordered[:target]}


def _review_order(
    mappings: Iterable[dict[str, Any]], *, seed: str, reviewer_slot: str
) -> list[str]:
    return [
        item["blind_case_id"]
        for item in sorted(
            mappings,
            key=lambda item: (
                identity_sha256(
                    "phase2a3-review-order-v1",
                    seed,
                    reviewer_slot,
                    item["blind_case_id"],
                ),
                item["blind_case_id"],
            ),
        )
    ]


def _frame_record(unit: Mapping[str, Any]) -> dict[str, Any]:
    # Geometry is retained by checksum/centroid for the complete 369k-row frame;
    # exact selected geometry is in sample.geojson and coordinator case records.
    return {
        key: value
        for key, value in unit.items()
        if key not in {"canonical_geometry", "population_snapshot_id"}
    }


def _sample_geojson(selected: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "name": "phase2a3_provisional_validation_sample",
        "pilot_semantics": (
            "Sampled legacy location-date features; not accepted observations or events."
        ),
        "features": [
            {
                "type": "Feature",
                "geometry": unit["canonical_geometry"],
                "properties": {
                    "sample_id": unit["sample_id"],
                    "source_record_id": unit["source_record_id"],
                    "observed_on": unit["observed_on"],
                    "area_ha_reported": unit["area_ha_reported"],
                    "strata": unit["strata"],
                    "selection_probability": unit["selection_probability"],
                    "canonical_observation_id": None,
                    "canonical_event_id": None,
                },
            }
            for unit in selected
        ],
    }


def _reviewer_case(
    unit: dict[str, Any],
    blind_case_id: str,
    evidence: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": PILOT_SCHEMA_VERSION,
        "blind_case_id": blind_case_id,
        "scientific_status": PACKAGE_TYPE,
        "target_date": unit["observed_on"],
        "target_geometry": unit["canonical_geometry"],
        "evidence": evidence,
        "review_fields": blank_review(blind_case_id),
        "instructions": {
            "primary_assessment_first": True,
            "system_confidence_hidden": True,
            "system_persistence_hidden": True,
            "system_land_cover_hidden": True,
            "missing_required_before_or_after_default": "unreviewable",
            "uncertain_definition": (
                "Required evidence is present but ambiguity or conflict prevents a "
                "real-change/no-change decision."
            ),
            "unreviewable_definition": (
                "Required evidence is absent, obscured, corrupt, or otherwise "
                "insufficient for interpretation."
            ),
        },
    }


def _coordinator_case(
    unit: dict[str, Any],
    mapping: dict[str, Any],
    reviewer_case: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": PILOT_SCHEMA_VERSION,
        "sample_id": unit["sample_id"],
        "blind_case_id": mapping["blind_case_id"],
        "population_snapshot_id": unit["population_snapshot_id"],
        "scientific_status": PACKAGE_TYPE,
        "identity_disposition": {
            "canonical_observation_id": None,
            "canonical_event_id": None,
            "reason": (
                "Legacy feature lacks provider scene list and accepted acquisition "
                "identity inputs."
            ),
        },
        "source": {
            "source_record_id": unit["source_record_id"],
            "source_artifact_key": unit["source_artifact_key"],
            "source_artifact_sha256": unit["source_artifact_sha256"],
            "source_feature_index": unit["source_feature_index"],
            "geometry_sha256": unit["geometry_sha256"],
        },
        "provisional_strata": unit["strata"],
        "provisional_attributes": {
            "area_ha_reported": unit["area_ha_reported"],
            "persistence_count": unit["persistence_count"],
            "first_seen": unit["first_seen"],
            "last_seen": unit["last_seen"],
            "land_cover_source_value": unit["land_cover_source_value"],
            "persistence_source_value": unit["persistence_source_value"],
            "contextual_signature": unit["provisional_contextual_signature"],
        },
        "sampling": {
            "joint_stratum_id": unit["joint_stratum_id"],
            "joint_stratum_population": unit["joint_stratum_population"],
            "selection_probability": unit["selection_probability"],
            "random_rank": unit["random_rank"],
        },
        "double_review": mapping["double_review"],
        "reviewer_case": reviewer_case,
    }


def _legacy_html_document(
    *,
    reviewer_slot: str,
    cases: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
) -> str:
    payload = json.dumps(
        {"reviewer_slot": reviewer_slot, "cases": cases, "reviews": reviews},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).replace("<", "\\u003c")
    title = html.escape(f"Araripe Phase 2A.3 — {reviewer_slot}")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
body{{font:15px system-ui,sans-serif;margin:0;background:#f4f1e8;color:#18201b}}header{{position:sticky;top:0;background:#143d2b;color:white;padding:12px 18px;z-index:2}}main{{max-width:1200px;margin:auto;padding:18px}}.nav{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}button,select,textarea,input{{font:inherit}}button{{padding:7px 12px}}.case{{background:white;border-radius:10px;padding:16px;box-shadow:0 2px 8px #0002}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}}figure{{margin:0;border:1px solid #ccd4cc;padding:8px;border-radius:8px}}img{{width:100%;height:auto;background:#eee}}.missing{{min-height:120px;display:grid;place-items:center;background:#eee;padding:12px}}label{{display:block;margin:10px 0 4px}}textarea{{width:100%;min-height:70px}}.warning{{background:#fff4ce;padding:10px;border-left:4px solid #a66a00}}.meta{{color:#526158}}.method{{border-top:1px solid #ddd;margin-top:12px;padding-top:8px}}@media(max-width:600px){{main{{padding:8px}}}}
</style></head><body>
<header><div><strong>{title}</strong></div><div class="nav"><button id="prev">Previous</button><span id="counter"></span><button id="next">Next</button><button id="export">Export review JSON</button></div></header>
<main><p class="warning">This is a provisional method-selection/usability pilot. Assess the imagery first. It is not a final accuracy study, and no system label shown here is a qualified human label.</p><div id="app"></div></main>
<script id="payload" type="application/json">{payload}</script>
<script>
const data=JSON.parse(document.getElementById('payload').textContent);let i=0;const byId=Object.fromEntries(data.reviews.map(r=>[r.blind_case_id,r]));
const esc=s=>String(s??'').replace(/[&<>\"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]));
function options(values,current){{return '<option value=""></option>'+values.map(v=>`<option ${{current===v?'selected':''}}>${{esc(v)}}</option>`).join('')}}
function evidenceCard(e){{if(e.local_path)return `<figure><figcaption><strong>${{esc(e.role)}}</strong> — ${{esc(e.source?.item_id||e.source?.dataset||'provenance recorded')}}</figcaption><img src="${{esc(e.local_path)}}"><div class="meta">${{esc(e.source?.observed_at||e.reason||'')}}</div></figure>`;return `<figure><figcaption><strong>${{esc(e.role)}}</strong></figcaption><div class="missing">${{esc(e.status)}}: ${{esc(e.reason)}}</div></figure>`}}
function render(){{const c=data.cases[i],r=byId[c.blind_case_id];document.getElementById('counter').textContent=`${{i+1}} / ${{data.cases.length}} — ${{c.blind_case_id}}`;const cards=Object.values(c.evidence).map(evidenceCard).join('');document.getElementById('app').innerHTML=`<section class="case"><h2>${{esc(c.blind_case_id)}}</h2><p>Target date: ${{esc(c.target_date)}}</p><div class="grid">${{cards}}</div><h3>Primary assessment</h3><label>Change label</label><select id="change">${{options(['real_change','no_change','uncertain','unreviewable'],r.change_assessment.change_label)}}</select><label>Reason</label><textarea id="reason">${{esc(r.change_assessment.reason)}}</textarea><label>Temporal confidence</label><select id="temporal">${{options(['high','medium','low','not_assessable'],r.temporal_assessment.confidence)}}</select><label>Land-cover context</label><select id="landcover">${{options(['natural_vegetation','anthropic_agriculture_pasture','built_or_extractive','water_or_wetland','bare_or_other_natural','mixed','unknown','not_assessable'],r.land_cover_assessment.context)}}</select><label>Contextual signature</label><select id="signature">${{options(['fire_like','exposed_soil_or_clearing_like','mixed_or_uncertain','not_assessed'],r.contextual_signature.label)}}</select><label>Notes / usability issues</label><textarea id="notes">${{esc(r.notes)}}</textarea><p class="meta">Method A/B fields remain unavailable until blinded candidate panels are supplied. No option is selected or activated by this package.</p></section>`;}}
function save(){{const c=data.cases[i],r=byId[c.blind_case_id];r.change_assessment.change_label=document.getElementById('change').value||null;r.change_assessment.reason=document.getElementById('reason').value||null;r.temporal_assessment.confidence=document.getElementById('temporal').value||null;r.land_cover_assessment.context=document.getElementById('landcover').value||null;r.contextual_signature.label=document.getElementById('signature').value||null;r.notes=document.getElementById('notes').value||null;r.review_status=r.change_assessment.change_label?'in_progress':'unreviewed';}}
document.getElementById('prev').onclick=()=>{{save();i=(i-1+data.cases.length)%data.cases.length;render()}};document.getElementById('next').onclick=()=>{{save();i=(i+1)%data.cases.length;render()}};document.getElementById('export').onclick=()=>{{save();const blob=new Blob([JSON.stringify({{schema_version:'1.0.0',reviewer_slot:data.reviewer_slot,reviews:data.reviews}},null,2)],{{type:'application/json'}});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`phase2a3-${{data.reviewer_slot}}-reviews.json`;a.click();URL.revokeObjectURL(a.href)}};render();
</script></body></html>"""


def _html_document(
    *,
    reviewer_slot: str,
    cases: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    method_evidence: Mapping[str, Any] | None = None,
    package_phase: str = "phase2a3",
    package_binding: Mapping[str, Any] | None = None,
) -> str:
    """Build a self-contained-data shell backed by the audited local app."""
    payload = json.dumps(
        {
            "package_phase": package_phase,
            "reviewer_slot": reviewer_slot,
            "cases": cases,
            "reviews": reviews,
            "method_evidence": dict(method_evidence or {}),
            "package_binding": dict(package_binding or {}),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).replace("<", "\\u003c")
    phase_title = "2A.4" if package_phase == "phase2a4" else "2A.3"
    title = html.escape(f"Araripe Phase {phase_title} — {reviewer_slot}")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><link rel="stylesheet" href="reviewer.css"></head>
<body><header><strong>{title}</strong><div id="profile"></div><nav>
<button id="prev" type="button">Previous</button><span id="counter"></span>
<button id="next" type="button">Next</button><button id="export" type="button">Export review JSON</button>
<label class="import">Import/resume JSON <input id="import" type="file" accept="application/json"></label>
</nav></header><main><p class="warning">Provisional method-selection and usability pilot only. This is not a final accuracy study and no system label is a qualified human label.</p>
<p id="progress"></p><div id="app"></div></main>
<script id="payload" type="application/json">{payload}</script><script src="reviewer.js"></script></body></html>"""


def _runtime_versions() -> dict[str, str]:
    def package_version(name: str) -> str:
        try:
            return version(name)
        except PackageNotFoundError:
            return "not-installed"

    return {
        "python": platform.python_version(),
        "fiona": fiona.__version__,
        "numpy": numpy.__version__,
        "pillow": PIL.__version__,
        "pyproj": pyproj.__version__,
        "proj": pyproj.__proj_version__,
        "rasterio": rasterio.__version__,
        "gdal": rasterio.__gdal_version__,
        "scipy": scipy.__version__,
        "shapely": shapely.__version__,
        "highs": package_version("highspy"),
        "jsonschema": package_version("jsonschema"),
        "planetary-computer": package_version("planetary-computer"),
        "pystac": package_version("pystac"),
        "pystac-client": package_version("pystac-client"),
    }


def _generator_source_inventory(repository_root: Path) -> list[dict[str, Any]]:
    candidates = [
        repository_root / "src" / "detection" / "baseline_manifest.py",
        repository_root / "src" / "detection" / "identity.py",
        *sorted((repository_root / "src" / "validation").glob("*.py")),
        repository_root / "scripts" / "build_validation_pilot.py",
        repository_root / "scripts" / "validate_validation_package.py",
        repository_root / "scripts" / "validate_validation_reviews.py",
    ]
    output = []
    for path in candidates:
        if not path.is_file():
            continue
        output.append(
            {
                "path": path.relative_to(repository_root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return output


def build_validation_package(
    frame: Mapping[str, Any],
    *,
    output_dir: Path,
    repository_root: Path,
    generated_at: str,
    source_retrieved_at: str,
    evidence_by_sample: Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None,
    evidence_generation: Mapping[str, Any] | None = None,
    generation_command: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Build the complete local/private coordinator and reviewer package."""
    output_dir = Path(output_dir)
    repository_root = Path(repository_root)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValidationPackageError(f"output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    selected = [copy.deepcopy(unit) for unit in frame["selected_units"]]
    seed = str(frame["random_seed"])
    agreement = _agreement_subset(selected, seed)
    evidence_by_sample = evidence_by_sample or {}
    evidence_generation_record = dict(
        evidence_generation
        or {
            "mode": "not_retrieved",
            "reason": "Package built without read-only evidence retrieval.",
        }
    )

    schema_source = repository_root / "docs" / "contracts" / "phase2a" / "schemas"
    protocol_source = (
        repository_root / "docs" / "contracts" / "phase2a" / "VALIDATION_REVIEWER_PROTOCOL_V1.md"
    )
    schema_names = (
        "validation-pilot-manifest-v1.schema.json",
        "validation-case-v1.schema.json",
        "validation-review-v1.schema.json",
    )
    for name in schema_names:
        source = schema_source / name
        if not source.is_file():
            raise ValidationPackageError(f"missing package schema: {source}")
        destination = output_dir / "schemas" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    if not protocol_source.is_file():
        raise ValidationPackageError(f"missing reviewer protocol: {protocol_source}")
    shutil.copyfile(protocol_source, output_dir / "PROTOCOL.md")

    baseline_manifest_path = repository_root / "config" / "baseline_manifest_v1.json"
    legacy_db_path = repository_root / "data" / "timeseries" / "timeseries.db"
    timeseries_audit_path = (
        repository_root
        / "docs"
        / "implementation"
        / "PHASE_2A2_TIMESERIES_AUDIT_2026-07-28.json"
    )
    baseline_manifest = json.loads(baseline_manifest_path.read_text(encoding="utf-8"))
    sources = {
        "schema_version": PILOT_SCHEMA_VERSION,
        "population_snapshot_id": frame["population_snapshot_id"],
        "source_retrieved_at": source_retrieved_at,
        "source_population": {
            "status": "provisional_current_alert_audit_input",
            "canonical_release": False,
            "feature_count": frame["source_feature_count"],
            "eligible_count": frame["eligible_count"],
            "excluded_count": frame["excluded_count"],
            "exclusion_counts": frame["exclusion_counts"],
            "artifact_inventory_sha256": frame["source_artifact_inventory_sha256"],
            "artifacts": frame["source_artifacts"],
        },
        "accepted_baseline_reference": {
            "baseline_version": baseline_manifest["baseline_version"],
            "manifest_path_label": "config/baseline_manifest_v1.json",
            "manifest_bytes": baseline_manifest_path.stat().st_size,
            "manifest_sha256": sha256_file(baseline_manifest_path),
            "object_inventory_sha256": baseline_manifest["aggregate"]["inventory_sha256"],
            "status": baseline_manifest["status"],
            "rebuild_performed": False,
            "provenance_status": baseline_manifest["source"]["provenance_completeness"]["status"],
            "provenance_missing": baseline_manifest["source"]["provenance_completeness"]["missing"],
        },
        "legacy_time_series_reference": {
            "path_label": "data/timeseries/timeseries.db",
            "bytes": legacy_db_path.stat().st_size,
            "sha256": sha256_file(legacy_db_path),
            "audit_path_label": "docs/implementation/PHASE_2A2_TIMESERIES_AUDIT_2026-07-28.json",
            "audit_sha256": sha256_file(timeseries_audit_path),
            "classification": "quarantined_mixed_generation_audit",
            "used_as_location_time_series": False,
        },
        "monitoring_extent": {
            "extent_id": MONITORING_EXTENT_ID,
            "bounds": list(MONITORING_EXTENT_BOUNDS),
            "scope": "APA and surroundings",
        },
        "limitations": list(frame["limitations"]),
    }
    write_canonical_json(output_dir / "sources.json", sources)

    write_canonical_jsonl_gzip(
        output_dir / "sampling" / "frame.jsonl.gz",
        (_frame_record(unit) for unit in frame["units"]),
    )
    write_canonical_jsonl_gzip(
        output_dir / "sampling" / "exclusions.jsonl.gz",
        (_frame_record(unit) for unit in frame["units"] if not unit["eligible"]),
    )
    write_canonical_json(
        output_dir / "sampling" / "strata.json",
        {
            "schema_version": PILOT_SCHEMA_VERSION,
            "sampling_design_version": frame["sampling_design_version"],
            "balance_status": frame["balance_status"],
            "balance_levels": frame["balance_levels"],
            "exclusion_counts": frame["exclusion_counts"],
            "margin_targets": frame["margin_targets"],
            "population_margins": frame["population_margins"],
            "sample_margins": frame["sample_margins"],
            "fine_strata": frame["fine_strata"],
            "probability_interpretation": (
                "Selected joint cells have cell probability 1; other cells have "
                "probability 0. Within a selected cell the seeded hash draw has "
                "conditional probability 1/N_h. These probabilities do not support "
                "a population accuracy estimate."
            ),
        },
    )
    write_canonical_json(output_dir / "sampling" / "sample.geojson", _sample_geojson(selected))

    mappings = []
    for unit in selected:
        blind_case_id = "p2a3-blind-v1-" + identity_sha256(
            "phase2a3-blind-case-v1", seed, unit["sample_id"]
        )[:24]
        mappings.append(
            {
                "sample_id": unit["sample_id"],
                "blind_case_id": blind_case_id,
                "double_review": unit["sample_id"] in agreement,
            }
        )
    mapping_by_sample = {item["sample_id"]: item for item in mappings}

    reviewer_cases_a: dict[str, dict[str, Any]] = {}
    reviewer_cases_b: dict[str, dict[str, Any]] = {}
    coordinator_cases = []

    def build_reviewer_case(
        unit: dict[str, Any],
        mapping: dict[str, Any],
        reviewer_root: Path,
    ) -> dict[str, Any]:
        supplied = evidence_by_sample.get(unit["sample_id"], {})
        evidence = {}
        for role in REQUIRED_EVIDENCE_ROLES:
            item = copy.deepcopy(supplied.get(role) or _missing_evidence(role))
            supplied_role = item.get("role")
            if supplied_role not in {None, role}:
                raise ValidationPackageError(
                    f"evidence role mismatch for {unit['sample_id']}: "
                    f"expected {role}, found {supplied_role}"
                )
            item["role"] = role
            evidence[role] = _copy_asset(
                item,
                reviewer_root=reviewer_root,
                blind_case_id=mapping["blind_case_id"],
                role=role,
            )
        return _reviewer_case(unit, mapping["blind_case_id"], evidence)

    for unit in selected:
        mapping = mapping_by_sample[unit["sample_id"]]
        reviewer_case_a = build_reviewer_case(
            unit, mapping, output_dir / "reviewer-a"
        )
        coordinator_case = _coordinator_case(unit, mapping, reviewer_case_a)
        reviewer_cases_a[mapping["blind_case_id"]] = reviewer_case_a
        coordinator_cases.append(coordinator_case)
        write_canonical_json(
            output_dir / "reviewer-a" / "cases" / f"{mapping['blind_case_id']}.json",
            reviewer_case_a,
        )
        if mapping["double_review"]:
            reviewer_case_b = build_reviewer_case(
                unit, mapping, output_dir / "reviewer-b"
            )
            reviewer_cases_b[mapping["blind_case_id"]] = reviewer_case_b
            write_canonical_json(
                output_dir
                / "reviewer-b"
                / "cases"
                / f"{mapping['blind_case_id']}.json",
                reviewer_case_b,
            )
        write_canonical_json(
            output_dir / "coordinator" / "cases" / f"{unit['sample_id']}.json",
            coordinator_case,
        )

    order_a = _review_order(mappings, seed=seed, reviewer_slot="reviewer-a")
    mapping_b = [item for item in mappings if item["double_review"]]
    order_b = _review_order(mapping_b, seed=seed, reviewer_slot="reviewer-b")
    assignment_a = {
        "schema_version": PILOT_SCHEMA_VERSION,
        "reviewer_slot": "reviewer-a",
        "blind_case_ids": order_a,
        "prior_labels_visible": False,
        "double_review_status_visible": False,
    }
    assignment_b = {
        "schema_version": PILOT_SCHEMA_VERSION,
        "reviewer_slot": "reviewer-b",
        "blind_case_ids": order_b,
        "prior_labels_visible": False,
        "double_review_status_visible": False,
    }
    write_canonical_json(output_dir / "reviewer-a" / "assignment.json", assignment_a)
    write_canonical_json(output_dir / "reviewer-b" / "assignment.json", assignment_b)
    reviews_a = [blank_review(case_id) for case_id in order_a]
    reviews_b = [blank_review(case_id) for case_id in order_b]
    write_canonical_json(
        output_dir / "reviewer-a" / "review-template.json",
        {"schema_version": PILOT_SCHEMA_VERSION, "reviewer_slot": "reviewer-a", "reviews": reviews_a},
    )
    write_canonical_json(
        output_dir / "reviewer-b" / "review-template.json",
        {"schema_version": PILOT_SCHEMA_VERSION, "reviewer_slot": "reviewer-b", "reviews": reviews_b},
    )
    shutil.copyfile(protocol_source, output_dir / "reviewer-a" / "PROTOCOL.md")
    shutil.copyfile(protocol_source, output_dir / "reviewer-b" / "PROTOCOL.md")
    for asset_name in ("reviewer.js", "reviewer.css"):
        asset_source = protocol_source.parent / asset_name
        if not asset_source.is_file():
            raise ValidationPackageError(f"missing reviewer application asset: {asset_source}")
        shutil.copyfile(asset_source, output_dir / "reviewer-a" / asset_name)
        shutil.copyfile(asset_source, output_dir / "reviewer-b" / asset_name)
    (output_dir / "reviewer-a" / "index.html").write_text(
        _html_document(
            reviewer_slot="reviewer-a",
            cases=[reviewer_cases_a[case_id] for case_id in order_a],
            reviews=reviews_a,
        ),
        encoding="utf-8",
        newline="\n",
    )
    (output_dir / "reviewer-b" / "index.html").write_text(
        _html_document(
            reviewer_slot="reviewer-b",
            cases=[reviewer_cases_b[case_id] for case_id in order_b],
            reviews=reviews_b,
        ),
        encoding="utf-8",
        newline="\n",
    )

    write_canonical_json(
        output_dir / "coordinator" / "crosswalk.json",
        {
            "schema_version": PILOT_SCHEMA_VERSION,
            "population_snapshot_id": frame["population_snapshot_id"],
            "mappings": sorted(mappings, key=lambda item: item["sample_id"]),
        },
    )
    write_canonical_json(
        output_dir / "coordinator" / "method-key.json",
        {
            "schema_version": PILOT_SCHEMA_VERSION,
            "method_decision_status": "none",
            "families": {
                family: {
                    "status": "not_generated_in_2a3",
                    "option_a": None,
                    "option_b": None,
                    "selected_or_activated": False,
                }
                for family in METHOD_FAMILIES
            },
            "warning": (
                "Phase 2A.4/2A.5 own method evidence and selection. This key "
                "does not activate or canonize an alternative."
            ),
        },
    )

    # The manifest inventories every immutable file except itself and the
    # checksum list.  CHECKSUMS.sha256 then also binds the manifest, avoiding a
    # circular self-checksum.
    inventory_paths = sorted(
        path
        for path in output_dir.rglob("*")
        if path.is_file() and path.name not in {"manifest.json", "CHECKSUMS.sha256"}
    )
    inventory = [_artifact(path, output_dir) for path in inventory_paths]
    generator_source_inventory = _generator_source_inventory(repository_root)
    generation_command_record = list(generation_command or [])
    runtime_versions_record = _runtime_versions()
    generation_identity = {
        "generated_at": generated_at,
        "generation_command": generation_command_record,
        "runtime_versions": runtime_versions_record,
    }
    package_id = "p2a3-pilot-package-v1-" + identity_sha256(
        "phase2a3-pilot-package-v1",
        frame["population_snapshot_id"],
        frame["sampling_design_version"],
        seed,
        str(frame["target_size"]),
        canonical_sha256(inventory),
        canonical_sha256(generator_source_inventory),
        canonical_sha256(evidence_generation_record),
        canonical_sha256(generation_identity),
    )
    evidence_status_counts: dict[str, dict[str, int]] = {}
    for role in REQUIRED_EVIDENCE_ROLES:
        counts: dict[str, int] = {}
        for case in reviewer_cases_a.values():
            status = case["evidence"][role]["status"]
            counts[status] = counts.get(status, 0) + 1
        evidence_status_counts[role] = dict(sorted(counts.items()))

    manifest = {
        "schema_version": PILOT_SCHEMA_VERSION,
        "package_id": package_id,
        "package_type": PACKAGE_TYPE,
        "scientific_status": "provisional_audit_inputs_only",
        "method_decision_status": "none",
        "generated_at": generated_at,
        "generation_command": generation_command_record,
        "runtime_versions": runtime_versions_record,
        "generator_source_inventory": generator_source_inventory,
        "evidence_generation": evidence_generation_record,
        "population_snapshot_id": frame["population_snapshot_id"],
        "source_artifact_inventory_sha256": frame["source_artifact_inventory_sha256"],
        "sampling": {
            "design_version": frame["sampling_design_version"],
            "random_seed": seed,
            "source_feature_count": frame["source_feature_count"],
            "eligible_count": frame["eligible_count"],
            "excluded_count": frame["excluded_count"],
            "target_size": frame["target_size"],
            "actual_size": len(selected),
            "balance_status": frame["balance_status"],
            "sample_margins": frame["sample_margins"],
            "probability_scope": "conditional_within_purposively_selected_joint_cells",
        },
        "review": {
            "primary_case_count": len(order_a),
            "double_review_case_count": len(order_b),
            "double_review_fraction": len(order_b) / len(order_a),
            "blinded_order": True,
            "human_labels_present": False,
            "evidence_status_counts": evidence_status_counts,
        },
        "claims": {
            "tool_validation_and_usability_only": True,
            "scientific_accuracy_claim": False,
            "precision_estimate": False,
            "recall_estimate": False,
            "omission_estimate": False,
            "qualified_human_labels_present": False,
            "method_promoted_or_activated": False,
            "raw_detection_modified": False,
        },
        "generation_limitations": list(frame["limitations"])
        + [
            "Rendered evidence files, where present, are validation derivatives; their checksums do not prove upstream provider bytes.",
            "Missing evidence remains in the frozen sample and is never silently replaced.",
            "The local/private package is not a public release artifact and must not be uploaded or published without a separate provenance/licensing review.",
            "Reviewer agreement later measures interpretation reliability, not scientific accuracy.",
        ],
        "artifact_inventory_rule": (
            "artifact_inventory contains every immutable package file except "
            "manifest.json and CHECKSUMS.sha256; CHECKSUMS.sha256 includes the "
            "manifest and every inventoried file, and excludes only itself."
        ),
        "artifact_inventory": inventory,
        "checksum_file": "CHECKSUMS.sha256",
    }
    write_canonical_json(output_dir / "manifest.json", manifest)
    checksum_paths = sorted(
        path
        for path in output_dir.rglob("*")
        if path.is_file() and path.name != "CHECKSUMS.sha256"
    )
    checksum_lines = [
        f"{sha256_file(path)}  {path.relative_to(output_dir).as_posix()}"
        for path in checksum_paths
    ]
    (output_dir / "CHECKSUMS.sha256").write_text(
        "\n".join(checksum_lines) + "\n", encoding="utf-8", newline="\n"
    )
    return manifest
