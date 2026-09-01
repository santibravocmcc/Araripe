"""Runtime JSON-Schema boundary for the Package 2A.6B.1 v3 contract family."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from src.detection.identity import canonical_json_bytes


CONTRACT_NAMES_V3 = (
    "acquisition-v3",
    "observation-v3",
    "event-v3",
    "lineage-v3",
    "persistence-contribution-v3",
    "persistence-state-v3",
    "processing-ledger-v3",
)
_SCHEMA_ROOT = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "contracts"
    / "phase2a"
    / "schemas"
)


class ContractV3ValidationError(ValueError):
    """A payload cannot cross the executable v3 contract boundary."""


@lru_cache(maxsize=len(CONTRACT_NAMES_V3))
def _validator(contract_name: str) -> Draft202012Validator:
    if contract_name not in CONTRACT_NAMES_V3:
        raise ContractV3ValidationError(
            "serializer accepts only the explicit Package 2A.6B.1 v3 contracts"
        )
    path = _SCHEMA_ROOT / f"{contract_name}.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_v3_schema(contract_name: str, payload: Any) -> None:
    """Validate against the exact advertised v3 schema, without coercion."""

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
        raise ContractV3ValidationError(
            f"{contract_name} schema validation failed: {details}"
        )


def validate_v3_document(contract_name: str, payload: Any) -> None:
    """Apply JSON Schema plus the contract's executable semantic checks."""

    validate_v3_schema(contract_name, payload)
    try:
        if contract_name == "acquisition-v3":
            from src.detection.identity_v3 import AcquisitionV3

            AcquisitionV3.from_dict(payload)
        elif contract_name == "observation-v3":
            from src.detection.identity_v3 import validate_observation_v3

            validate_observation_v3(payload)
        elif contract_name == "processing-ledger-v3":
            from src.detection.ledger_v3 import validate_processing_ledger_v3

            validate_processing_ledger_v3(payload)
        elif contract_name == "event-v3":
            from src.detection.persistence_v3 import validate_event_v3

            validate_event_v3(payload)
        elif contract_name == "lineage-v3":
            from src.detection.persistence_v3 import validate_lineage_v3

            validate_lineage_v3(payload)
        elif contract_name == "persistence-contribution-v3":
            from src.detection.persistence_v3 import (
                validate_persistence_contribution_v3,
            )

            validate_persistence_contribution_v3(payload)
        elif contract_name == "persistence-state-v3":
            from src.detection.persistence_v3 import validate_persistence_state_v3

            validate_persistence_state_v3(payload)
    except ContractV3ValidationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractV3ValidationError(
            f"{contract_name} semantic validation failed"
        ) from exc


def serialize_v3_document(contract_name: str, payload: Any) -> bytes:
    validate_v3_document(contract_name, payload)
    return canonical_json_bytes(payload) + b"\n"


def load_v3_document(path: Path, contract_name: str) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractV3ValidationError(
            f"cannot read valid JSON for {contract_name}"
        ) from exc
    if not isinstance(payload, dict):
        raise ContractV3ValidationError(f"{contract_name} must be a JSON object")
    validate_v3_document(contract_name, payload)
    return payload
