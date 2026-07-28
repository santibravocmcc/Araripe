"""Deterministic scientific identities for Phase 2A.1.

The formulas and canonicalization rules in this module implement the accepted
Phase 1 data contract in ``docs/contracts/phase1/DATA_CONTRACTS_V1.md``.
Identity inputs are intentionally independent of release paths, presentation
order, MapBiomas annotations, and persistence tiers.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry


UNIT_SEPARATOR = "\x1f"
LINE_FEED = "\n"


def _encode_string(value: str) -> str:
    """Encode a string using the JSON/JCS escaping rules."""
    out = ['"']
    escapes = {
        '"': '\\"',
        "\\": "\\\\",
        "\b": "\\b",
        "\t": "\\t",
        "\n": "\\n",
        "\f": "\\f",
        "\r": "\\r",
    }
    for char in value:
        code = ord(char)
        if 0xD800 <= code <= 0xDFFF:
            raise ValueError("JCS strings cannot contain lone surrogate code points")
        if char in escapes:
            out.append(escapes[char])
        elif code < 0x20:
            out.append(f"\\u{code:04x}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _encode_float(value: float) -> str:
    """Return the ECMAScript-compatible finite-number form required by JCS.

    Python and ECMAScript both use a shortest round-trippable decimal for IEEE
    754 doubles. Their remaining differences are notation thresholds and
    exponent formatting, normalized here according to RFC 8785 section 3.2.2.3.
    """
    if not math.isfinite(value):
        raise ValueError("JCS numbers must be finite")
    if value == 0:
        return "0"

    negative = value < 0
    absolute = -value if negative else value
    shortest = repr(absolute).lower()

    if "e" in shortest:
        mantissa, exponent_text = shortest.split("e", 1)
        exponent = int(exponent_text)
        digits = mantissa.replace(".", "")
        decimal_position = 1 + exponent
    else:
        digits = shortest.replace(".", "")
        decimal_position = (
            shortest.index(".") if "." in shortest else len(shortest)
        )

    leading_zeros = len(digits) - len(digits.lstrip("0"))
    digits = digits.lstrip("0") or "0"
    decimal_position -= leading_zeros
    sign = "-" if negative else ""

    if 1e-6 <= absolute < 1e21:
        if decimal_position <= 0:
            body = "0." + ("0" * -decimal_position) + digits
        elif decimal_position >= len(digits):
            body = digits + ("0" * (decimal_position - len(digits)))
        else:
            body = digits[:decimal_position] + "." + digits[decimal_position:]
        if "." in body:
            body = body.rstrip("0").rstrip(".")
        return sign + body

    exponent = decimal_position - 1
    mantissa = digits[0]
    remainder = digits[1:].rstrip("0")
    if remainder:
        mantissa += "." + remainder
    exponent_sign = "+" if exponent >= 0 else "-"
    return f"{sign}{mantissa}e{exponent_sign}{abs(exponent)}"


def jcs_dumps(value: Any) -> str:
    """Serialize JSON-compatible data with RFC 8785 canonical ordering."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _encode_string(value)
    if isinstance(value, int):
        # JCS interoperable integers are constrained to the exact IEEE-754
        # range. Scientific identities use coordinates (floats) and small ints.
        if abs(value) > 9_007_199_254_740_991:
            raise ValueError("integer exceeds the JCS interoperable range")
        return str(value)
    if isinstance(value, float):
        return _encode_float(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(jcs_dumps(item) for item in value) + "]"
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("JCS object keys must be strings")
        keys = sorted(
            value,
            key=lambda item: item.encode("utf-16be", errors="surrogatepass"),
        )
        return (
            "{"
            + ",".join(
                f"{_encode_string(key)}:{jcs_dumps(value[key])}" for key in keys
            )
            + "}"
        )
    raise TypeError(f"unsupported JCS value type: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    return jcs_dumps(value).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def identity_sha256(*components: str) -> str:
    if not all(isinstance(component, str) for component in components):
        raise TypeError("identity components must be strings")
    return hashlib.sha256(
        UNIT_SEPARATOR.join(components).encode("utf-8")
    ).hexdigest()


def _sorted_unique(values: Iterable[str], *, label: str) -> list[str]:
    items = list(values)
    if not items or any(not isinstance(item, str) or not item for item in items):
        raise ValueError(f"{label} must contain one or more non-empty strings")
    if len(items) != len(set(items)):
        raise ValueError(f"{label} contains duplicates")
    return sorted(items, key=lambda item: item.encode("utf-8"))


def _signed_area(ring: Sequence[Sequence[float]]) -> float:
    return sum(
        float(ring[index][0]) * float(ring[index + 1][1])
        - float(ring[index + 1][0]) * float(ring[index][1])
        for index in range(len(ring) - 1)
    ) / 2.0


def _canonical_position(position: Sequence[float]) -> list[float]:
    if len(position) < 2:
        raise ValueError("geometry positions require longitude and latitude")
    longitude = float(position[0])
    latitude = float(position[1])
    if not math.isfinite(longitude) or not math.isfinite(latitude):
        raise ValueError("geometry coordinates must be finite")
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        raise ValueError("geometry must use EPSG:4326 longitude/latitude")
    return [
        0.0 if longitude == 0 else longitude,
        0.0 if latitude == 0 else latitude,
    ]


def _canonical_ring(
    coordinates: Sequence[Sequence[float]], *, exterior: bool
) -> list[list[float]]:
    ring = [_canonical_position(position) for position in coordinates]
    if len(ring) < 3:
        raise ValueError("polygon rings require at least three distinct positions")
    if ring[0] == ring[-1]:
        ring = ring[:-1]
    if len(ring) < 3:
        raise ValueError("polygon rings require at least three distinct positions")

    closed = ring + [ring[0]]
    is_counter_clockwise = _signed_area(closed) > 0
    if is_counter_clockwise != exterior:
        ring.reverse()

    candidates = [
        ring[index:] + ring[:index]
        for index, point in enumerate(ring)
        if point == min(ring)
    ]
    rotated = min(candidates, key=canonical_json_bytes)
    return rotated + [rotated[0]]


def _canonical_polygon_coordinates(
    coordinates: Sequence[Sequence[Sequence[float]]],
) -> list[list[list[float]]]:
    if not coordinates:
        raise ValueError("polygon requires an exterior ring")
    exterior = _canonical_ring(coordinates[0], exterior=True)
    holes = [
        _canonical_ring(ring, exterior=False) for ring in coordinates[1:]
    ]
    holes.sort(key=canonical_json_bytes)
    return [exterior, *holes]


def canonical_geometry(geometry: BaseGeometry | dict[str, Any]) -> dict[str, Any]:
    """Return the accepted canonical EPSG:4326 Polygon/MultiPolygon object."""
    geom = shape(geometry) if isinstance(geometry, dict) else geometry
    if geom is None or geom.is_empty:
        raise ValueError("observation geometry must be non-empty")
    if not geom.is_valid:
        raise ValueError("observation geometry must be valid")

    raw = mapping(geom)
    if isinstance(geom, Polygon):
        return {
            "type": "Polygon",
            "coordinates": _canonical_polygon_coordinates(raw["coordinates"]),
        }
    if isinstance(geom, MultiPolygon):
        polygons = [
            _canonical_polygon_coordinates(coordinates)
            for coordinates in raw["coordinates"]
        ]
        polygons.sort(key=canonical_json_bytes)
        return {"type": "MultiPolygon", "coordinates": polygons}
    raise TypeError("observation geometry must be Polygon or MultiPolygon")


def canonical_geometry_sha256(
    geometry: BaseGeometry | dict[str, Any],
) -> tuple[dict[str, Any], str]:
    canonical = canonical_geometry(geometry)
    return canonical, canonical_sha256(canonical)


@dataclass(frozen=True)
class AcquisitionIdentity:
    """One canonical daily acquisition and its deterministic identity."""

    acquisition_id: str
    identity_inputs_sha256: str
    collection_id: str
    observed_on: str
    scene_ids: tuple[str, ...]
    monitoring_extent_id: str
    composite_method_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "acquisition_id": self.acquisition_id,
            "identity_inputs_sha256": self.identity_inputs_sha256,
            "collection_id": self.collection_id,
            "observed_on": self.observed_on,
            "scene_ids": list(self.scene_ids),
            "monitoring_extent_id": self.monitoring_extent_id,
            "composite_method_id": self.composite_method_id,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AcquisitionIdentity":
        created = create_acquisition_identity(
            collection_id=value["collection_id"],
            observed_on=value["observed_on"],
            scene_ids=value["scene_ids"],
            monitoring_extent_id=value["monitoring_extent_id"],
            composite_method_id=value["composite_method_id"],
        )
        if value.get("acquisition_id") != created.acquisition_id:
            raise ValueError("acquisition metadata ID does not match its inputs")
        if value.get("identity_inputs_sha256") != created.identity_inputs_sha256:
            raise ValueError("acquisition metadata checksum does not match its inputs")
        return created


def create_acquisition_identity(
    *,
    collection_id: str,
    observed_on: str,
    scene_ids: Iterable[str],
    monitoring_extent_id: str,
    composite_method_id: str,
) -> AcquisitionIdentity:
    scenes = _sorted_unique(scene_ids, label="scene_ids")
    digest = identity_sha256(
        "acquisition-v1",
        collection_id,
        observed_on,
        LINE_FEED.join(scenes),
        monitoring_extent_id,
        composite_method_id,
    )
    return AcquisitionIdentity(
        acquisition_id=f"acq-v1-{digest}",
        identity_inputs_sha256=digest,
        collection_id=collection_id,
        observed_on=observed_on,
        scene_ids=tuple(scenes),
        monitoring_extent_id=monitoring_extent_id,
        composite_method_id=composite_method_id,
    )


def observation_id(
    acquisition_id: str,
    geometry_sha256: str,
    algorithm_version: str,
    baseline_version: str,
) -> str:
    digest = identity_sha256(
        "observation-v1",
        acquisition_id,
        geometry_sha256,
        algorithm_version,
        baseline_version,
    )
    return f"obs-v1-{digest}"


def origin_event_id(first_observation_id: str) -> str:
    return "evt-v1-" + identity_sha256(
        "event-v1", "origin", first_observation_id
    )


def child_event_id(
    operation: str,
    parent_event_ids: Iterable[str],
    trigger_observation_ids: Iterable[str],
) -> str:
    if operation not in {"split", "merge"}:
        raise ValueError("child event operation must be split or merge")
    parents = _sorted_unique(parent_event_ids, label="parent_event_ids")
    triggers = _sorted_unique(
        trigger_observation_ids, label="trigger_observation_ids"
    )
    return "evt-v1-" + identity_sha256(
        "event-v1",
        operation,
        LINE_FEED.join(parents),
        LINE_FEED.join(triggers),
    )


def lineage_id(
    *,
    relation: str,
    parent_event_ids: Iterable[str],
    child_event_ids: Iterable[str],
    acquisition_id: str,
    observed_on: str,
    trigger_observation_ids: Iterable[str],
    algorithm_version: str,
) -> str:
    if relation not in {"continuation", "split", "merge"}:
        raise ValueError("invalid lineage relation")
    parents = _sorted_unique(parent_event_ids, label="parent_event_ids")
    children = _sorted_unique(child_event_ids, label="child_event_ids")
    triggers = _sorted_unique(
        trigger_observation_ids, label="trigger_observation_ids"
    )
    return "lin-v1-" + identity_sha256(
        "lineage-v1",
        relation,
        LINE_FEED.join(parents),
        LINE_FEED.join(children),
        acquisition_id,
        observed_on,
        LINE_FEED.join(triggers),
        algorithm_version,
    )


def contribution_key(event_id: str, acquisition_id: str) -> str:
    return "pc-v1-" + identity_sha256(
        "persistence-contribution-v1", event_id, acquisition_id
    )


def write_acquisition_metadata(
    path: Path, acquisition: AcquisitionIdentity
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            acquisition.to_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def load_acquisition_metadata(path: Path) -> AcquisitionIdentity:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("acquisition metadata must be a JSON object")
    return AcquisitionIdentity.from_dict(value)


def load_composite_acquisition(
    composite_path: Path,
) -> AcquisitionIdentity:
    """Load a headless sidecar or the manual GEE directory manifest."""
    sidecar = composite_path.with_suffix(".acquisition.json")
    if sidecar.exists():
        return load_acquisition_metadata(sidecar)

    for name in (
        "araripe_detection_acquisitions.json",
        "acquisition_manifest.json",
    ):
        manifest_path = composite_path.parent / name
        if not manifest_path.exists():
            continue
        with manifest_path.open("r", encoding="utf-8") as stream:
            manifest = json.load(stream)
        date_text = composite_path.stem.rsplit("_", 1)[-1]
        record = manifest.get(date_text)
        if not isinstance(record, dict):
            raise ValueError(
                f"{manifest_path.name} has no acquisition for {date_text}"
            )
        return AcquisitionIdentity.from_dict(record)
    raise FileNotFoundError(
        f"missing deterministic acquisition metadata for {composite_path.name}; "
        "expected its .acquisition.json sidecar or the manual GEE manifest"
    )
