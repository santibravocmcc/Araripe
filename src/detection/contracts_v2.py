"""Runtime JSON-Schema boundary for the Package 2A.6A contract family."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from src.detection.identity import canonical_json_bytes


CONTRACT_NAMES_V2 = (
    "acquisition-v2",
    "observation-v2",
    "event-v2",
    "lineage-v2",
    "persistence-contribution-v2",
    "persistence-state-v2",
    "processing-ledger-v2",
)
_SCHEMA_ROOT = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "contracts"
    / "phase2a"
    / "schemas"
)


class ContractV2ValidationError(ValueError):
    """A payload cannot cross the executable v2 contract boundary."""


@lru_cache(maxsize=len(CONTRACT_NAMES_V2))
def _validator(contract_name: str) -> Draft202012Validator:
    if contract_name not in CONTRACT_NAMES_V2:
        raise ContractV2ValidationError(
            "serializer accepts only the explicit Package 2A.6A v2 contracts"
        )
    path = _SCHEMA_ROOT / f"{contract_name}.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_v2_schema(contract_name: str, payload: Any) -> None:
    """Validate against the exact advertised v2 schema, without coercion."""

    errors = sorted(
        _validator(contract_name).iter_errors(payload),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        details = "; ".join(
            f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: "
            f"{error.message}"
            for error in errors[:8]
        )
        raise ContractV2ValidationError(
            f"{contract_name} schema validation failed: {details}"
        )


def validate_v2_document(contract_name: str, payload: Any) -> None:
    """Apply JSON Schema plus the contract's executable semantic checks."""

    validate_v2_schema(contract_name, payload)
    try:
        if contract_name == "acquisition-v2":
            from src.detection.identity_v2 import AcquisitionV2

            AcquisitionV2.from_dict(payload)
        elif contract_name == "observation-v2":
            from src.detection.identity_v2 import validate_observation_v2

            validate_observation_v2(payload)
        elif contract_name == "processing-ledger-v2":
            from src.detection.ledger_v2 import validate_processing_ledger_v2

            validate_processing_ledger_v2(payload)
        elif contract_name == "event-v2":
            from src.detection.persistence_v2 import validate_event_v2

            validate_event_v2(payload)
        elif contract_name == "lineage-v2":
            from src.detection.persistence_v2 import validate_lineage_v2

            validate_lineage_v2(payload)
        elif contract_name == "persistence-contribution-v2":
            from src.detection.persistence_v2 import (
                validate_persistence_contribution_v2,
            )

            validate_persistence_contribution_v2(payload)
        elif contract_name == "persistence-state-v2":
            from src.detection.persistence_v2 import validate_persistence_state_v2

            validate_persistence_state_v2(payload)
    except ContractV2ValidationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractV2ValidationError(
            f"{contract_name} semantic validation failed"
        ) from exc


def serialize_v2_document(contract_name: str, payload: Any) -> bytes:
    validate_v2_document(contract_name, payload)
    return canonical_json_bytes(payload) + b"\n"


def load_v2_document(path: Path, contract_name: str) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractV2ValidationError(
            f"cannot read valid JSON for {contract_name}"
        ) from exc
    if not isinstance(payload, dict):
        raise ContractV2ValidationError(f"{contract_name} must be a JSON object")
    validate_v2_document(contract_name, payload)
    return payload
