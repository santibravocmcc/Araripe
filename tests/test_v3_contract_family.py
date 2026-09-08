"""Keep the Package 2A.6B.1 v3 schema family and amendment in the pytest gate."""

from pathlib import Path
import importlib.util
import hashlib
import json
import runpy

from src.detection.contracts_v3 import CONTRACT_NAMES_V3, validate_v3_document


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "docs" / "contracts" / "phase2a" / "validate_v3_contracts.py"
GENERATOR = ROOT / "docs" / "contracts" / "phase2a" / "generate_v3_examples.py"
EXAMPLES = VALIDATOR.parent / "examples"
AMENDMENT = ROOT / "config" / "phase2a_sentinel2c_contract_amendment_v3.json"
PARENT_DECISIONS = (
    ROOT / "config" / "phase2a_candidate_generation_decisions_v2.json"
)


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_v3_examples", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v3_schema_examples_and_semantic_contracts(capsys):
    runpy.run_path(str(VALIDATOR), run_name="__main__")

    assert (
        capsys.readouterr().out
        == "Phase 2A.6B.1 v3 contracts: 7 schemas and 7 examples valid; "
        "semantic, v1, and v2 isolation checks passed.\n"
    )


def test_every_v3_example_crosses_the_runtime_semantic_boundary():
    for contract_name in CONTRACT_NAMES_V3:
        payload = json.loads(
            (EXAMPLES / f"{contract_name}.example.json").read_text(
                encoding="utf-8"
            )
        )
        validate_v3_document(contract_name, payload)


def test_committed_examples_equal_the_deterministic_generator_output():
    documents = _load_generator().build_documents()
    assert set(documents) == set(CONTRACT_NAMES_V3)
    for contract_name, document in documents.items():
        committed = (EXAMPLES / f"{contract_name}.example.json").read_text(
            encoding="utf-8"
        )
        assert committed == json.dumps(
            document, indent=2, ensure_ascii=False
        ) + "\n", f"{contract_name} example drifted from the v3 runtime"


def test_v3_example_family_exercises_sentinel_2c():
    ledger = json.loads(
        (EXAMPLES / "processing-ledger-v3.example.json").read_text(
            encoding="utf-8"
        )
    )
    platforms = {
        item["platform"] for item in ledger["expected_acquisitions"]
    }
    assert platforms == {"S2A", "S2C"}
    datatakes = {item["datatake_id"] for item in ledger["expected_acquisitions"]}
    assert any(item.startswith("GS2C_") for item in datatakes)


def test_amendment_record_binds_authorization_and_parent_decisions():
    amendment = json.loads(AMENDMENT.read_text(encoding="utf-8"))
    authorization = amendment["authorization"]
    assert authorization["silent_v2_contract_mutation_permitted"] is False
    assert authorization["s2c_to_s2a_fallback_permitted"] is False
    assert authorization["production_mutation_permitted"] is False
    assert (
        authorization["phase2a6c_start_before_local_gates_pass_permitted"]
        is False
    )

    platform = amendment["platform_representation"]
    assert platform["v2_platform_enum"] == ["S2A", "S2B"]
    assert platform["v3_platform_enum"] == ["S2A", "S2B", "S2C"]
    assert platform["relabeling_permitted"] is False
    assert platform["unlisted_platform_policy"] == "unavailable_fail_closed"
    assert platform["s2d_and_later_units_reviewed"] is False

    parent = amendment["parent_bindings"][
        "phase2a_candidate_generation_decisions_v2"
    ]
    digest = hashlib.sha256(PARENT_DECISIONS.read_bytes()).hexdigest()
    assert parent["sha256"] == digest
    assert parent["science_decisions_superseded"] is False

    family = amendment["identity"]["contract_family"]
    assert family["selected_major"] == 3
    assert family["required_contracts"] == list(CONTRACT_NAMES_V3)
    assert family["v1_runtime_serialization_permitted"] is False
    assert family["v2_runtime_serialization_permitted"] is False
    assert family["v2_artifacts_preserved_for_audit"] is True

    science = amendment["science_bindings_unchanged"]
    assert science["cloud_mask"] == "scl-explicit-allowlist-v2"
    assert science["composition"] == "coverage-ranked-first-valid-v1"
    assert science["mask_or_composition_reimplementation_permitted"] is False
    assert science["unreviewed_scl_or_baseline_policy"] == (
        "unavailable_fail_closed"
    )


def test_v3_transition_policy_declares_both_legacy_majors_forbidden():
    state = json.loads(
        (EXAMPLES / "persistence-state-v3.example.json").read_text(
            encoding="utf-8"
        )
    )
    policy = state["transition_policy"]
    assert policy["legacy_serialization"] == "v1_v2_forbidden_audit_only"
    assert "v1_serialization" not in policy
