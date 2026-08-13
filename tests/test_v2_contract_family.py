"""Keep the complete Package 2A.6A schema family in the pytest gate."""

from pathlib import Path
import json
import runpy

from src.detection.contracts_v2 import CONTRACT_NAMES_V2, validate_v2_document


VALIDATOR = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "contracts"
    / "phase2a"
    / "validate_v2_contracts.py"
)
EXAMPLES = VALIDATOR.parent / "examples"


def test_v2_schema_examples_and_semantic_contracts(capsys):
    runpy.run_path(str(VALIDATOR), run_name="__main__")

    assert (
        capsys.readouterr().out
        == "Phase 2A.6A contracts: 7 schemas and 7 examples valid; "
        "semantic and v1 isolation checks passed.\n"
    )


def test_every_v2_example_crosses_the_runtime_semantic_boundary():
    for contract_name in CONTRACT_NAMES_V2:
        payload = json.loads(
            (EXAMPLES / f"{contract_name}.example.json").read_text(
                encoding="utf-8"
            )
        )
        validate_v2_document(contract_name, payload)
