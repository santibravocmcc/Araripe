"""Package 2A.6D blinded method-comparison derivative (v2).

The v1 derivative's two context families were computed from the v1 mappings
and from Collection 10 bytes under a 10.1 label, so the decision record bars
them from any qualified review. This builder derives a v2 package from the v1
one the same way v1 derived from Phase 2A.4: every unchanged byte is copied
after hash verification, and ONLY the affected surfaces are regenerated —

- the per-case blinded evidence and panels of the ``mapbiomas`` and
  ``contextual_signature`` families, now computed from the v2 evidence
  artifact (v2 mappings, pixel-centre rule, fresh Collection 10.1, the
  accepted mask/composition signature against baseline 2.1.0);
- a fresh keyed 30/30 A/B balance for those two families, held only by the
  coordinator;
- the review-template rows for those two families (reviews stay blank);
- the coordinator's v2 input bindings, manifest and checksums.

The three Phase 2A.4 families, the case material, the 60/12 assignments and
the 12-case overlap are preserved byte for byte. Panels never name a
candidate: reviewers see A/B only.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from src.validation.phase2a5_evidence import (
    _draw_bar,
    _format_percent,
    _panel_canvas,
    _png_bytes,
)
from src.validation.phase2a5_context_v2 import (
    COL3_KEY_V2,
    REGIONAL_MANIFEST_V2_PATH,
    REGISTRY_V2_PATH,
)

PACKAGE_V2_VERSION = "phase2a5-method-comparison-v2"
CONTEXT_FAMILIES = ("mapbiomas", "contextual_signature")
FAMILY_CANDIDATES = {
    "mapbiomas": (
        "natural-vegetation-share-0.50-v2",
        "natural-vegetation-share-0.75-v1",
    ),
    "contextual_signature": (
        "dominant-assessed-share-0.60-v1",
        "plurality-assessed-margin-0.15-v1",
    ),
}
# Paths (relative to the v1 package root) that the v2 derivative REPLACES.
REPLACED_PREFIXES = (
    "reviewer-a/context-evidence/",
    "reviewer-b/context-evidence/",
)
REPLACED_FILES = (
    "manifest.json",
    "CHECKSUMS.sha256",
    "PHASE2A5_CONTEXT_COMPARISON.md",
    "reviewer-a/review-template.json",
    "reviewer-b/review-template.json",
    "coordinator/phase2a5-blinding-map.json",
)
REPLACED_DIR_PREFIXES = (
    "coordinator/phase2a5-inputs/",
    "coordinator/phase2a5-evidence/",
    "coordinator/phase2a5-method-evidence/",
)


class Phase2A5PackageV2Error(ValueError):
    """Raised when the derivative would violate the v2 package contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Phase2A5PackageV2Error(message)


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
class PackageV2Config:
    output_dir: Path
    v1_package_dir: Path
    evidence_v2_dir: Path
    repository_root: Path
    generated_at: str
    blinding_key_hex: str | None = None


def _is_replaced(relative: str) -> bool:
    if relative in REPLACED_FILES:
        return True
    return any(
        relative.startswith(prefix)
        for prefix in (*REPLACED_PREFIXES, *REPLACED_DIR_PREFIXES)
    )


# ─── keyed balanced blinding ─────────────────────────────────────────────────


def derive_balanced_blinding(
    blind_case_ids: list[str], key_hex: str
) -> dict[str, dict[str, str]]:
    """Assign A/B per family with an exact 30/30 keyed balance.

    Cases are ordered by a keyed digest per family; the first half shows the
    selected candidate as option A. The key never leaves the coordinator tree,
    and without it the order is not reconstructible from the reviewer trees.
    """

    _require(
        len(blind_case_ids) == len(set(blind_case_ids)),
        "blind case ids repeat",
    )
    _require(
        len(blind_case_ids) % 2 == 0,
        "keyed balance requires an even case count",
    )
    key = bytes.fromhex(key_hex)
    assignments: dict[str, dict[str, str]] = {case: {} for case in blind_case_ids}
    half = len(blind_case_ids) // 2
    for family in CONTEXT_FAMILIES:
        ordered = sorted(
            blind_case_ids,
            key=lambda case: hashlib.sha256(
                key + family.encode() + case.encode()
            ).hexdigest(),
        )
        for position, case in enumerate(ordered):
            assignments[case][family] = "candidate_0_as_A" if position < half else "candidate_1_as_A"
    return assignments


# ─── v2 panels (blinded: no candidate name, no threshold) ────────────────────


def _map_panel_v2(mapbiomas: Mapping[str, Any], outcome: Mapping[str, Any]) -> bytes:
    image, draw = _panel_canvas(
        "Regional land-cover proportions; corrected v2 context"
    )
    primary = mapbiomas["collections"][COL3_KEY_V2]
    values = primary["category_proportions"]
    rows = (
        ("Natural vegetation", values["natural_vegetation"], (65, 130, 85)),
        ("Other natural cover", values["other_natural_cover"], (85, 145, 175)),
        ("Anthropic cover", values["anthropic_cover"], (205, 145, 65)),
        ("Uncertain / mixed", values["uncertain_or_mixed"], (145, 125, 155)),
    )
    for index, (label, value, color) in enumerate(rows):
        _draw_bar(draw, y=128 + index * 54, label=label, value=value, color=color)
    membership = str(outcome["membership"]).replace("_", " ")
    draw.text((46, 365), f"Strong-subset contextual outcome: {membership}", fill=(25, 35, 45))
    agreement = mapbiomas["cross_collection_v2"]["agreement_fraction"]
    draw.text(
        (46, 397),
        f"Collection agreement context: {_format_percent(agreement)}",
        fill=(65, 73, 82),
    )
    draw.text(
        (46, 429),
        "NoData, unknown, not-observed and unmapped pixels stay explicit.",
        fill=(65, 73, 82),
    )
    draw.text((46, 480), "context only; no cause inferred", fill=(100, 50, 40))
    return _png_bytes(image)


BLIND_SIGNATURE_LABELS = {
    "fire_like": "class A",
    "exposed_soil_or_clearing_like": "class B",
    "mixed_or_uncertain": "class C",
    "not_assessed": "not assessed",
}


def _margin_label(shares: Mapping[str, float]) -> str:
    ordered = sorted(shares.items(), key=lambda item: (-item[1], item[0]))
    (top_label, top), (_, runner) = ordered[0], ordered[1]
    if top > runner and (top - runner) >= 0.15:
        return top_label
    return "mixed_or_uncertain"


def signature_candidate_outcomes(
    observation: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Both fixed aggregators on ONE v2 observation stratum.

    The 0.60 dominant-share outcome ships in the evidence; the 0.15 margin
    alternative recomputes from the same recorded shares, so the two options
    always describe the same pixels.
    """

    aggregate = observation["aggregate"]
    shares = aggregate.get("shares") or {}
    if aggregate["assessed_pixel_count"] == 0 or not shares:
        blank = {
            "label": "not_assessed",
            "assessed_pixel_count": 0,
            "status": "unreviewable",
        }
        return {name: dict(blank) for name in FAMILY_CANDIDATES["contextual_signature"]}
    margin = _margin_label(shares)
    return {
        "dominant-assessed-share-0.60-v1": {
            "label": aggregate["label"],
            "assessed_pixel_count": aggregate["assessed_pixel_count"],
            "status": observation["status"],
        },
        "plurality-assessed-margin-0.15-v1": {
            "label": margin,
            "assessed_pixel_count": aggregate["assessed_pixel_count"],
            "status": observation["status"],
        },
    }


def _signature_panel_v2(
    observations: list[Mapping[str, Any]],
    candidate_id: str,
) -> bytes:
    image, draw = _panel_canvas(
        "Non-causal signature on the accepted v2 mask and composition"
    )
    first_assessed = next(
        (
            observation
            for observation in observations
            if observation["aggregate"]["assessed_pixel_count"]
        ),
        None,
    )
    shares = (first_assessed or observations[0])["aggregate"].get("shares") or {}
    rows = (
        ("Signature class A", shares.get("fire_like"), (185, 85, 55)),
        (
            "Signature class B",
            shares.get("exposed_soil_or_clearing_like"),
            (205, 155, 65),
        ),
        ("Signature class C", shares.get("mixed_or_uncertain"), (125, 115, 150)),
    )
    for index, (label, value, color) in enumerate(rows):
        _draw_bar(draw, y=136 + index * 60, label=label, value=value, color=color)
    lines = []
    for number, observation in enumerate(observations, start=1):
        outcome = signature_candidate_outcomes(observation)[candidate_id]
        lines.append(
            f"observation {number}: {BLIND_SIGNATURE_LABELS[outcome['label']]}"
        )
    draw.text((46, 346), "Contextual signature outcome:", fill=(25, 35, 45))
    for index, line in enumerate(lines[:3]):
        draw.text((66, 374 + index * 26), line, fill=(25, 35, 45))
    draw.text(
        (46, 452),
        "one observation per physical satellite pass; none merged",
        fill=(65, 73, 82),
    )
    draw.text((46, 480), "context only; no cause inferred", fill=(100, 50, 40))
    return _png_bytes(image)


# ─── build ───────────────────────────────────────────────────────────────────


def build_phase2a5_package_v2(config: PackageV2Config) -> dict[str, Any]:
    target = Path(config.output_dir).absolute()
    _require(
        not os.path.lexists(target),
        f"output already exists; refusing to replace a derivative: {target}",
    )
    v1_root = Path(config.v1_package_dir)
    evidence_root = Path(config.evidence_v2_dir)
    evidence_manifest = _load_json(evidence_root / "manifest.json")
    _require(
        evidence_manifest["evidence_version"] == "phase2a5-context-evidence-v2",
        "the evidence artifact is not the v2 evidence",
    )
    v1_manifest_sha = _sha256_file(v1_root / "manifest.json")
    v1_checksums_sha = _sha256_file(v1_root / "CHECKSUMS.sha256")

    # The v1 checksum file is the copy oracle: every copied byte must match it.
    recorded: dict[str, str] = {}
    for line in (v1_root / "CHECKSUMS.sha256").read_text("utf-8").splitlines():
        digest, path = line.split("  ", 1)
        recorded[path] = digest

    staging = target.parent / f".{target.name}.staging-{os.getpid()}"
    _require(not staging.exists(), f"stale staging directory: {staging}")
    staging.mkdir(parents=True)

    copied = 0
    for path in sorted(v1_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(v1_root).as_posix()
        if _is_replaced(relative):
            continue
        expected = recorded.get(relative)
        _require(
            expected is not None,
            f"v1 package file is not in its checksum inventory: {relative}",
        )
        _require(
            _sha256_file(path) == expected,
            f"v1 package file no longer matches its inventory: {relative}",
        )
        destination = staging / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied += 1

    # Fresh coordinator-only keyed balance for the two context families.
    key_hex = config.blinding_key_hex or secrets.token_hex(32)
    crosswalk = {
        descriptor["sample_id"]: descriptor["blind_case_id"]
        for descriptor in evidence_manifest["cases"]
    }
    blind_ids = sorted(crosswalk.values())
    assignments = derive_balanced_blinding(blind_ids, key_hex)

    reviewer_b_cases = set(
        _load_json(v1_root / "reviewer-b/assignment.json")["blind_case_ids"]
    )
    coordinator_cases: list[dict[str, Any]] = []
    balance = {
        family: {"candidate_0_as_A": 0, "candidate_1_as_A": 0}
        for family in CONTEXT_FAMILIES
    }
    template_rows: dict[str, dict[str, Any]] = {}

    for sample_id, blind_id in sorted(crosswalk.items()):
        record = _load_json(
            evidence_root / "cases" / sample_id / "case-evidence-v2.json"
        )
        mapbiomas = record["mapbiomas_v2"]
        observations = record["contextual_signature_v2"]["observations"]
        case_assignment = assignments[blind_id]
        for family in CONTEXT_FAMILIES:
            balance[family][case_assignment[family]] += 1

        subset_outcomes = {
            "natural-vegetation-share-0.50-v2": mapbiomas["strong_subset_v2"][
                "selected"
            ],
            "natural-vegetation-share-0.75-v1": mapbiomas["strong_subset_v2"][
                "sensitivity_only"
            ],
        }
        map_available = subset_outcomes[
            "natural-vegetation-share-0.50-v2"
        ]["membership"] != "not_assessed"
        signature_assessed = any(
            observation["aggregate"]["assessed_pixel_count"]
            for observation in observations
        )

        comparisons: dict[str, Any] = {}
        family_meta: dict[str, Any] = {}
        for family in CONTEXT_FAMILIES:
            candidates = FAMILY_CANDIDATES[family]
            first_is_zero = case_assignment[family] == "candidate_0_as_A"
            option_order = candidates if first_is_zero else candidates[::-1]
            available = map_available if family == "mapbiomas" else signature_assessed
            options: dict[str, Any] = {}
            for side, candidate_id in zip(("option_a", "option_b"), option_order):
                blind_option_id = "p2a5-blind-option-v2-" + _canonical_sha256(
                    [key_hex, blind_id, family, candidate_id]
                )[:40]
                if not available:
                    options[side] = {
                        "blind_option_id": blind_option_id,
                        "artifacts": [],
                        "summary": {},
                    }
                    continue
                letter = "A" if side == "option_a" else "B"
                panel_relative = (
                    f"context-evidence/{blind_id}/{family}/{letter}.png"
                )
                if family == "mapbiomas":
                    payload = _map_panel_v2(
                        mapbiomas, subset_outcomes[candidate_id]
                    )
                else:
                    payload = _signature_panel_v2(observations, candidate_id)
                for reviewer in ("reviewer-a", "reviewer-b"):
                    if reviewer == "reviewer-b" and blind_id not in reviewer_b_cases:
                        continue
                    panel_path = staging / reviewer / panel_relative
                    panel_path.parent.mkdir(parents=True, exist_ok=True)
                    panel_path.write_bytes(payload)
                options[side] = {
                    "blind_option_id": blind_option_id,
                    "artifacts": [
                        {
                            "path": panel_relative,
                            "bytes": len(payload),
                            "sha256": hashlib.sha256(payload).hexdigest(),
                            "media_type": "image/png",
                        }
                    ],
                    "summary": {},
                }
            availability = "available" if available else "unreviewable"
            comparisons[family] = {
                "availability": availability,
                "display_order": ["A", "B"],
                "evidence_reason": None if available else "not assessable under v2 context",
                **options,
            }
            family_meta[family] = {
                "availability": availability,
                "display_order": ["A", "B"],
            }

        blind_record = {
            "schema_version": "1.0.0",
            "package_version": PACKAGE_V2_VERSION,
            "evidence_id": evidence_manifest["evidence_id"],
            "parent_case": blind_id,
            "comparisons": comparisons,
            "scientific_status": "provisional_context_only",
            "claims": {
                "cause_inferred": False,
                "method_selected_or_activated": False,
                "qualified_human_label_present": False,
                "raw_detection_modified": False,
                "scientific_accuracy_claim": False,
            },
        }
        for reviewer in ("reviewer-a", "reviewer-b"):
            if reviewer == "reviewer-b" and blind_id not in reviewer_b_cases:
                continue
            _write_json(
                staging / reviewer / "context-evidence" / f"{blind_id}.json",
                blind_record,
            )
        template_rows[blind_id] = family_meta
        coordinator_cases.append(
            {
                "blind_case_id": blind_id,
                "sample_id": sample_id,
                "families": {
                    family: {
                        "assignment": case_assignment[family],
                        "candidate_as_A": (
                            FAMILY_CANDIDATES[family][0]
                            if case_assignment[family] == "candidate_0_as_A"
                            else FAMILY_CANDIDATES[family][1]
                        ),
                    }
                    for family in CONTEXT_FAMILIES
                },
            }
        )

    for family in CONTEXT_FAMILIES:
        counts = balance[family]
        _require(
            counts["candidate_0_as_A"] == counts["candidate_1_as_A"] == 30,
            f"keyed balance broke for {family}: {counts}",
        )

    # Review templates: v1 rows preserved except the two regenerated families.
    for reviewer in ("reviewer-a", "reviewer-b"):
        template = _load_json(v1_root / reviewer / "review-template.json")
        for row in template["reviews"]:
            blind_id = row["blind_case_id"]
            for family in CONTEXT_FAMILIES:
                meta = template_rows[blind_id][family]
                row["method_comparisons"][family] = {
                    "availability": meta["availability"],
                    "display_order": list(meta["display_order"]),
                    "evidence_reason": None,
                    "preferred_option": None,
                    "confidence": None,
                    "reason": None,
                }
        _write_json(staging / reviewer / "review-template.json", template)

    # Coordinator: the v2 inputs and the only true mapping.
    inputs_dir = staging / "coordinator" / "phase2a5-inputs"
    for source, name in (
        (evidence_root / "manifest.json", "evidence-v2-manifest.json"),
        (evidence_root / "CHECKSUMS.sha256", "evidence-v2-CHECKSUMS.sha256"),
        (config.repository_root / REGISTRY_V2_PATH, "context-registry-v2.json"),
        (
            config.repository_root / REGIONAL_MANIFEST_V2_PATH,
            "regional-context-manifest-v2.json",
        ),
    ):
        inputs_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, inputs_dir / name)
    blinding_map = {
        "schema_version": "1.0.0",
        "mapping_id": "phase2a5-balanced-keyed-blinding-v2",
        "coordinator_only": True,
        "blinding_key_hex": key_hex,
        "family_candidates": {
            family: list(candidates)
            for family, candidates in FAMILY_CANDIDATES.items()
        },
        "exact_balance_per_family": balance,
        "evidence_binding": {
            "evidence_id": evidence_manifest["evidence_id"],
            "manifest_sha256": _sha256_file(evidence_root / "manifest.json"),
        },
        "cases": coordinator_cases,
    }
    _write_json(
        staging / "coordinator" / "phase2a5-blinding-map.json", blinding_map
    )

    (staging / "PHASE2A5_CONTEXT_COMPARISON.md").write_text(
        "# Phase 2A.5 context families — v2 derivative\n\n"
        "The mapbiomas and contextual_signature families in this package were\n"
        "regenerated under the accepted 2026-08-11 decisions: v2 mappings, the\n"
        "pixel-centre polygon rule, the fresh Collection 10.1 GEE export, and\n"
        "the contextual signature computed on the accepted v2 mask and\n"
        "datatake-scoped composition against baseline 2.1.0. The superseded v1\n"
        "package remains audit-only and is not a valid qualified-review input.\n\n"
        "Options are blinded A/B with a fresh keyed 30/30 balance per family;\n"
        "the only true mapping is coordinator/phase2a5-blinding-map.json.\n"
        "Reviews remain blank. Context only; no cause is inferred.\n",
        encoding="utf-8",
    )

    inventory = []
    for path in sorted(staging.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(staging).as_posix()
        if relative in {"manifest.json", "CHECKSUMS.sha256"}:
            continue
        inventory.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    manifest = {
        "schema_version": "1.0.0",
        "package_version": PACKAGE_V2_VERSION,
        "generated_at": config.generated_at,
        "decision_binding": {
            "path": "config/phase2a_candidate_generation_decisions_v2.json",
            "sha256": (
                "ac61fd1e6da376a147013a610652e38a6d3d119dcb8479b01001e156625cf69e"
            ),
        },
        "derived_from_v1_package": {
            "path": str(v1_root),
            "manifest_sha256": v1_manifest_sha,
            "checksums_sha256": v1_checksums_sha,
            "preserved_file_count": copied,
            "role": "audit_only",
        },
        "evidence_v2_binding": blinding_map["evidence_binding"],
        "context_families_regenerated": list(CONTEXT_FAMILIES),
        "phase2a4_families_preserved_byte_identical": True,
        "reviews_blank": True,
        "exact_balance_per_family": balance,
        "artifact_inventory_sha256": _canonical_sha256(inventory),
        "file_count": len(inventory) + 2,
    }
    manifest["package_id"] = "p2a5-derivative-package-v2-" + _canonical_sha256(
        {key: manifest[key] for key in sorted(manifest)}
    )
    _write_json(staging / "manifest.json", manifest)
    lines = [f"{entry['sha256']}  {entry['path']}" for entry in inventory]
    lines.append(f"{_sha256_file(staging / 'manifest.json')}  manifest.json")
    (staging / "CHECKSUMS.sha256").write_text("\n".join(lines) + "\n", "utf-8")

    validate_phase2a5_package_v2(staging, v1_package_dir=v1_root)
    os.rename(staging, target)
    return manifest


def validate_phase2a5_package_v2(
    root: Path, *, v1_package_dir: Path
) -> dict[str, Any]:
    root = Path(root)
    manifest = _load_json(root / "manifest.json")
    _require(
        manifest["package_version"] == PACKAGE_V2_VERSION,
        "unexpected package version",
    )
    recorded: dict[str, str] = {}
    for line in (root / "CHECKSUMS.sha256").read_text("utf-8").splitlines():
        digest, path = line.split("  ", 1)
        recorded[path] = digest
    inventory = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative == "CHECKSUMS.sha256":
            continue
        _require(
            recorded.get(relative) == _sha256_file(path),
            f"checksum mismatch: {relative}",
        )
        if relative != "manifest.json":
            inventory.append(
                {
                    "path": relative,
                    "bytes": path.stat().st_size,
                    "sha256": recorded[relative],
                }
            )
    _require(
        manifest["artifact_inventory_sha256"] == _canonical_sha256(inventory),
        "inventory checksum mismatch",
    )

    blinding = _load_json(root / "coordinator/phase2a5-blinding-map.json")
    balance = {
        family: {"candidate_0_as_A": 0, "candidate_1_as_A": 0}
        for family in CONTEXT_FAMILIES
    }
    for case in blinding["cases"]:
        for family in CONTEXT_FAMILIES:
            balance[family][case["families"][family]["assignment"]] += 1
    _require(
        balance == manifest["exact_balance_per_family"],
        "keyed balance does not reconcile",
    )
    for family in CONTEXT_FAMILIES:
        _require(
            balance[family]["candidate_0_as_A"] == 30
            and balance[family]["candidate_1_as_A"] == 30,
            f"balance is not 30/30 for {family}",
        )

    # No true candidate name may appear anywhere a reviewer can see.
    forbidden = [
        name for pair in FAMILY_CANDIDATES.values() for name in pair
    ] + ["blinding_key_hex", "candidate_as_A"]
    for reviewer in ("reviewer-a", "reviewer-b"):
        for path in sorted((root / reviewer).rglob("*")):
            if not path.is_file() or path.suffix not in {".json", ".md", ".html", ".js", ".css"}:
                continue
            text = path.read_text("utf-8", errors="ignore")
            for name in forbidden:
                _require(
                    name not in text,
                    f"reviewer tree leaks {name!r}: {path}",
                )

    # Reviews must be blank, and the overlap byte-identical across reviewers.
    for reviewer in ("reviewer-a", "reviewer-b"):
        template = _load_json(root / reviewer / "review-template.json")
        for row in template["reviews"]:
            for family in CONTEXT_FAMILIES:
                block = row["method_comparisons"][family]
                _require(
                    block["preferred_option"] is None
                    and block["confidence"] is None,
                    f"a {family} review row is not blank",
                )
    overlap = _load_json(root / "reviewer-b/assignment.json")["blind_case_ids"]
    for blind_id in overlap:
        a = root / "reviewer-a/context-evidence" / f"{blind_id}.json"
        b = root / "reviewer-b/context-evidence" / f"{blind_id}.json"
        _require(
            a.read_bytes() == b.read_bytes(),
            f"overlap context evidence differs between reviewers: {blind_id}",
        )
        for family in CONTEXT_FAMILIES:
            for letter in ("A", "B"):
                pa = root / "reviewer-a/context-evidence" / blind_id / family / f"{letter}.png"
                pb = root / "reviewer-b/context-evidence" / blind_id / family / f"{letter}.png"
                _require(
                    pa.exists() == pb.exists(),
                    f"overlap panel presence differs: {blind_id}/{family}/{letter}",
                )
                if pa.exists():
                    _require(
                        pa.read_bytes() == pb.read_bytes(),
                        f"overlap panel differs: {blind_id}/{family}/{letter}",
                    )

    # Preserved v1 bytes really are preserved.
    v1_recorded: dict[str, str] = {}
    for line in (Path(v1_package_dir) / "CHECKSUMS.sha256").read_text("utf-8").splitlines():
        digest, path = line.split("  ", 1)
        v1_recorded[path] = digest
    checked = 0
    for relative, digest in sorted(v1_recorded.items()):
        if _is_replaced(relative):
            continue
        target_path = root / relative
        _require(target_path.exists(), f"preserved v1 file missing: {relative}")
        _require(
            recorded.get(relative) == digest,
            f"preserved v1 file changed: {relative}",
        )
        checked += 1
    _require(
        checked == manifest["derived_from_v1_package"]["preserved_file_count"],
        "preserved-file count does not reconcile",
    )
    return manifest
