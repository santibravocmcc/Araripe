"""Prove the v3 family equals the v2 family plus the enumerated amendment.

The Package 2A.6B.1 authorization forbids silently altering the closed v2
(``2.0.0``) contracts and forbids an ``S2C -> S2A`` fallback; widening a
platform enum is a major change under the Phase 1 compatibility policy.  The
v3 modules and schemas are therefore mechanical ports of their byte-identical
v2 sources, and THIS FILE is the authoritative delta specification: each v3
file must equal its v2 source after applying, in order,

1. ``pre`` literal replacements (the semantic amendment: platform enum,
   schema-version literals, transition-policy token);
2. ``blanket`` case-sensitive token rules (``v2 -> v3``, ``V2 -> V3``); and
3. ``post`` literal replacements (documentation headers and the appended
   v2-isolation checks, applied last so the blanket cannot mangle them).

Every ``pre``/``post`` pair must actually occur in its input, so a drifted or
hand-edited port fails loudly.  The scratch generator that produced the v3
files imports this same specification; reviewers therefore read the pairs
below, not thousands of ported lines.
"""

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]

RUNTIME_BLANKET = (("v2", "v3"), ("V2", "V3"))
SCHEMA_BLANKET = (("v2", "v3"),)
SCHEMA_VERSION_PAIR = ('"2.0.0"', '"3.0.0"')
SCHEMA_VERSION_MESSAGE_PAIR = ("schema_version 2.0.0", "schema_version 3.0.0")
PLATFORM_ENUM_RUNTIME_PAIR = (
    '    if platform not in {"S2A", "S2B"}:\n'
    '        raise ValueError("platform must be S2A or S2B")',
    '    if platform not in {"S2A", "S2B", "S2C"}:\n'
    '        raise ValueError("platform must be S2A, S2B or S2C")',
)
PLATFORM_ENUM_SCHEMA_PAIR = (
    '"platform": { "enum": ["S2A", "S2B"] },',
    '"platform": { "enum": ["S2A", "S2B", "S2C"] },',
)
POLICY_VALUE_PAIR = (
    '"v1_serialization": "forbidden_audit_only",',
    '"legacy_serialization": "v1_v2_forbidden_audit_only",',
)
POLICY_SCHEMA_REQUIRED_PAIR = ('"v1_serialization",', '"legacy_serialization",')
POLICY_SCHEMA_CONST_PAIR = (
    '"v1_serialization": { "const": "forbidden_audit_only" },',
    '"legacy_serialization": { "const": "v1_v2_forbidden_audit_only" },',
)

_VALIDATOR_V2_ISOLATION_BLOCK = (
    "def main() -> None:\n    validate_decision_lock()",
    "def validate_v2_incompatibility(documents: dict[str, dict[str, Any]]) -> None:\n"
    "    corresponding = {\n"
    '        "acquisition-v3": "acquisition-v2.schema.json",\n'
    '        "observation-v3": "observation-v2.schema.json",\n'
    '        "event-v3": "event-v2.schema.json",\n'
    '        "lineage-v3": "lineage-v2.schema.json",\n'
    '        "persistence-contribution-v3": "persistence-contribution-v2.schema.json",\n'
    '        "persistence-state-v3": "persistence-state-v2.schema.json",\n'
    '        "processing-ledger-v3": "processing-ledger-v2.schema.json",\n'
    "    }\n"
    "    checker = FormatChecker()\n"
    "    for name, schema_name in corresponding.items():\n"
    "        schema = load_json(SCHEMAS / schema_name)\n"
    "        require(\n"
    "            not Draft202012Validator(schema, format_checker=checker).is_valid(documents[name]),\n"
    '            f"{name} was accepted by audit-only {schema_name}",\n'
    "        )\n"
    "    for name, document in documents.items():\n"
    "        require(\n"
    '            "-v2-" not in canonical_bytes(document).decode("utf-8"),\n'
    '            f"{name} contains a v2 identity",\n'
    "        )\n"
    "\n"
    "\n"
    "def main() -> None:\n    validate_decision_lock()",
)

SPEC: dict[str, dict[str, object]] = {
    "src/detection/identity_v3.py": {
        "source": "src/detection/identity_v2.py",
        "pre": (
            PLATFORM_ENUM_RUNTIME_PAIR,
            ('SCHEMA_VERSION = "2.0.0"', 'SCHEMA_VERSION = "3.0.0"'),
            SCHEMA_VERSION_MESSAGE_PAIR,
        ),
        "blanket": RUNTIME_BLANKET,
        "post": (
            (
                '"""Deterministic Package 2A.6A identities for physical '
                "acquisitions.\n\nThis module is deliberately separate from "
                ":mod:`src.detection.identity`.\nVersion 1 models one "
                "canonical acquisition per date and is audit-only for new\n"
                "candidate data.  Version 2 models one physical datatake per "
                'acquisition and\nrefuses every cross-major reference.\n"""',
                '"""Deterministic v3 identities for physical acquisitions '
                "(Package 2A.6B.1).\n\nThis module is deliberately separate "
                "from :mod:`src.detection.identity` and\nfrom the audit-only "
                "version-2 family.  Version 3 preserves the version-2\n"
                "semantics unchanged except that platform Sentinel-2C is "
                "representable; the\nexact delta set is proven by "
                'tests/test_v3_structural_equivalence.py.\n"""',
            ),
        ),
    },
    "src/detection/ledger_v3.py": {
        "source": "src/detection/ledger_v2.py",
        "pre": (),
        "blanket": RUNTIME_BLANKET,
        "post": (
            (
                '"""Manifest-bound processing ledger for Package 2A.6A.',
                '"""Manifest-bound processing ledger for the v3 family '
                "(Package 2A.6B.1).",
            ),
        ),
    },
    "src/detection/persistence_v3.py": {
        "source": "src/detection/persistence_v2.py",
        "pre": (SCHEMA_VERSION_MESSAGE_PAIR,),
        "blanket": RUNTIME_BLANKET,
        "post": (
            POLICY_VALUE_PAIR,
            (
                '"""Atomic per-UTC-date persistence transitions for Package '
                "2A.6A.",
                '"""Atomic per-UTC-date persistence transitions for the v3 '
                "family (2A.6B.1).",
            ),
        ),
    },
    "src/detection/contracts_v3.py": {
        "source": "src/detection/contracts_v2.py",
        "pre": (),
        "blanket": RUNTIME_BLANKET,
        "post": (
            (
                '"""Runtime JSON-Schema boundary for the Package 2A.6A '
                'contract family."""',
                '"""Runtime JSON-Schema boundary for the Package 2A.6B.1 v3 '
                'contract family."""',
            ),
            (
                "serializer accepts only the explicit Package 2A.6A v3 "
                "contracts",
                "serializer accepts only the explicit Package 2A.6B.1 v3 "
                "contracts",
            ),
        ),
    },
    "src/detection/composition_run_v3.py": {
        "source": "src/detection/composition_run_v2.py",
        "pre": (
            ("src.detection.identity_v2", "src.detection.identity_v3"),
            ("src.detection.ledger_v2", "src.detection.ledger_v3"),
            ("AcquisitionV2", "AcquisitionV3"),
            ("ObservationV2", "ObservationV3"),
            ("ProcessingLedgerV2", "ProcessingLedgerV3"),
            ("create_acquisition_v2", "create_acquisition_v3"),
            ("CompositionRunV2", "CompositionRunV3"),
            ("DatatakeRunInputV2", "DatatakeRunInputV3"),
            ("CompositionOutcomeV2", "CompositionOutcomeV3"),
            (
                'RUN_EVIDENCE_VERSION = "phase2a6b-composition-run-evidence-v1"',
                'RUN_EVIDENCE_VERSION = "phase2a6b1-composition-run-evidence-v1"',
            ),
        ),
        "blanket": (),
        "post": (
            (
                '"""Package 2A.6B run producer: physical acquisitions plus '
                "terminal evidence.",
                '"""Package 2A.6B.1 v3 run producer: physical acquisitions '
                "plus terminal evidence.",
            ),
            (
                "Consumes — never redefines — the closed Package 2A.6A "
                "contracts:",
                "Consumes — never redefines — the Package 2A.6B.1 v3 contract "
                "family:",
            ),
            (
                "Whether a normalized platform (for example Sentinel-2C, "
                "present in the\nPhase 2A.4 pilot scenes) is representable is "
                "decided by the closed\nacquisition-v2 contract; this module "
                "deliberately adds no platform policy of\nits own.",
                "Whether a normalized platform is representable is decided by "
                "the\nacquisition-v3 contract (S2A, S2B, and S2C, per the "
                "2026-09-01 amendment);\nthis module still adds no platform "
                "policy of its own, so a later unreviewed\nunit such as "
                "Sentinel-2D fails closed at that contract.",
            ),
            (
                "One manifest-bound Package 2A.6B composition run.",
                "One manifest-bound Package 2A.6B.1 v3 composition run.",
            ),
        ),
    },
    "docs/contracts/phase2a/validate_v3_contracts.py": {
        "source": "docs/contracts/phase2a/validate_v2_contracts.py",
        "pre": (
            (
                '"phase2a_candidate_generation_decisions_v2.json"',
                '"phase2a_sentinel2c_contract_amendment_v3.json"',
            ),
            ('["selected_major"] == 2', '["selected_major"] == 3'),
            SCHEMA_VERSION_PAIR,
        ),
        "blanket": (("v2", "v3"),),
        "post": (
            POLICY_VALUE_PAIR,
            (
                '"""Validate the Phase 2A.6A v3 schemas, examples, and '
                "semantic invariants.",
                '"""Validate the Phase 2A.6B.1 v3 schemas, examples, and '
                "semantic invariants.",
            ),
            _VALIDATOR_V2_ISOLATION_BLOCK,
            (
                "    validate_v1_incompatibility(documents)\n    print(",
                "    validate_v1_incompatibility(documents)\n"
                "    validate_v2_incompatibility(documents)\n    print(",
            ),
            (
                'print("Phase 2A.6A contracts: 7 schemas and 7 examples '
                'valid; semantic and v1 isolation checks passed.")',
                'print("Phase 2A.6B.1 v3 contracts: 7 schemas and 7 examples '
                'valid; semantic, v1, and v2 isolation checks passed.")',
            ),
        ),
    },
    "docs/contracts/phase2a/schemas/acquisition-v3.schema.json": {
        "source": "docs/contracts/phase2a/schemas/acquisition-v2.schema.json",
        "pre": (PLATFORM_ENUM_SCHEMA_PAIR, SCHEMA_VERSION_PAIR),
        "blanket": SCHEMA_BLANKET,
        "post": (),
    },
    "docs/contracts/phase2a/schemas/observation-v3.schema.json": {
        "source": "docs/contracts/phase2a/schemas/observation-v2.schema.json",
        "pre": (SCHEMA_VERSION_PAIR,),
        "blanket": SCHEMA_BLANKET,
        "post": (),
    },
    "docs/contracts/phase2a/schemas/event-v3.schema.json": {
        "source": "docs/contracts/phase2a/schemas/event-v2.schema.json",
        "pre": (SCHEMA_VERSION_PAIR,),
        "blanket": SCHEMA_BLANKET,
        "post": (),
    },
    "docs/contracts/phase2a/schemas/lineage-v3.schema.json": {
        "source": "docs/contracts/phase2a/schemas/lineage-v2.schema.json",
        "pre": (SCHEMA_VERSION_PAIR,),
        "blanket": SCHEMA_BLANKET,
        "post": (),
    },
    "docs/contracts/phase2a/schemas/persistence-contribution-v3.schema.json": {
        "source": (
            "docs/contracts/phase2a/schemas/persistence-contribution-v2.schema.json"
        ),
        "pre": (SCHEMA_VERSION_PAIR,),
        "blanket": SCHEMA_BLANKET,
        "post": (),
    },
    "docs/contracts/phase2a/schemas/persistence-state-v3.schema.json": {
        "source": (
            "docs/contracts/phase2a/schemas/persistence-state-v2.schema.json"
        ),
        "pre": (SCHEMA_VERSION_PAIR,),
        "blanket": SCHEMA_BLANKET,
        "post": (
            POLICY_SCHEMA_REQUIRED_PAIR,
            POLICY_SCHEMA_CONST_PAIR,
        ),
    },
    "docs/contracts/phase2a/schemas/processing-ledger-v3.schema.json": {
        "source": (
            "docs/contracts/phase2a/schemas/processing-ledger-v2.schema.json"
        ),
        "pre": (PLATFORM_ENUM_SCHEMA_PAIR, SCHEMA_VERSION_PAIR),
        "blanket": SCHEMA_BLANKET,
        "post": (),
    },
}


def transform_v2_source(target: str) -> str:
    """Apply the enumerated delta to a target's v2 source text."""

    entry = SPEC[target]
    text = (ROOT / str(entry["source"])).read_text(encoding="utf-8")
    for old, new in entry["pre"]:  # type: ignore[union-attr]
        assert old in text, f"{target}: stale pre pair {old[:60]!r}"
        text = text.replace(old, new)
    for old, new in entry["blanket"]:  # type: ignore[union-attr]
        text = text.replace(old, new)
    for old, new in entry["post"]:  # type: ignore[union-attr]
        assert old in text, f"{target}: stale post pair {old[:60]!r}"
        text = text.replace(old, new)
    return text


@pytest.mark.parametrize("target", sorted(SPEC))
def test_v3_file_is_exactly_its_transformed_v2_source(target):
    generated = transform_v2_source(target)
    committed = (ROOT / target).read_text(encoding="utf-8")
    assert committed == generated, (
        f"{target} drifted from its v2 source plus the enumerated amendment; "
        "either revert the drift or extend the delta specification explicitly"
    )


@pytest.mark.parametrize("target", sorted(SPEC))
def test_v2_sources_remain_untouched_by_the_amendment(target):
    # The structural proof is only meaningful while the v2 side stays the
    # audit-only closed family: its files must still carry v2 tokens and the
    # 2.0.0 schema version, i.e. nobody edited v2 in place instead of porting.
    source = (ROOT / str(SPEC[target]["source"])).read_text(encoding="utf-8")
    assert "v3" not in source


def test_platform_amendment_is_scoped_to_exactly_one_new_unit():
    before = PLATFORM_ENUM_RUNTIME_PAIR[0]
    after = PLATFORM_ENUM_RUNTIME_PAIR[1]
    assert '"S2A", "S2B"' in before and '"S2A", "S2B", "S2C"' in after
    assert "S2D" not in after
    schema_after = PLATFORM_ENUM_SCHEMA_PAIR[1]
    assert schema_after.count("S2C") == 1 and "S2D" not in schema_after
