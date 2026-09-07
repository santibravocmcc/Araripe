"""The exact Package 2A.6 ledger contract this repository consumes (2B.2A).

Three things are proven here, and they are different things:

1. the pin is *real* — every pinned digest reproduces from the producer's own
   commit, so none of it was typed from memory.  On 2026-09-07 a commit
   message asserted a "verified base" whose 40-character SHA had 33 invented
   characters, which review did not catch precisely because a plausible
   identifier reads like a checked one;
2. the pin *binds* — editing a pinned artifact, or letting the producer branch
   move away from it, stops the publication gate instead of quietly changing
   what "the contract" means; and
3. the consumer's canonicalization *agrees with the producer's* — every digest
   the producer embedded in its own ledger fixture recomputes here, byte for
   byte, so recomputing a checksum is evidence rather than a second opinion.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest

from src.publication import ledger_binding
from src.publication.canonical_json import (
    CanonicalJsonError,
    canonical_json_bytes,
    canonical_json_text,
    canonical_sha256,
    identity_sha256,
)
from src.publication.ledger_gate import LedgerRejected, check_processing_ledger


REPO_ROOT = Path(__file__).resolve().parents[1]
_CACHED = (
    ledger_binding.load_pin,
    ledger_binding.pinned_schema,
    ledger_binding.pinned_validator,
)


@pytest.fixture
def ledger() -> dict:
    """The producer's own v3 ledger, exactly as Package 2A.6 committed it."""
    return json.loads(
        ledger_binding.acceptance_fixture_path().read_text(encoding="utf-8")
    )


@pytest.fixture
def clear_caches():
    """Binding lookups are cached; a test that edits a pinned file must reset."""
    for cached in _CACHED:
        cached.cache_clear()
    yield
    for cached in _CACHED:
        cached.cache_clear()


def _stage_pinned_tree(root: Path) -> Path:
    """Copy every pinned artifact and the pin itself into a scratch tree."""
    root.mkdir(parents=True, exist_ok=True)
    for entry in ledger_binding.pinned_artifacts():
        target = root / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((REPO_ROOT / entry["path"]).read_bytes())
    relative = ledger_binding.PIN_PATH.relative_to(REPO_ROOT)
    (root / relative).parent.mkdir(parents=True, exist_ok=True)
    (root / relative).write_bytes(ledger_binding.PIN_PATH.read_bytes())
    return root / relative


# --------------------------------------------------------------------------
# 1. The pin is real
# --------------------------------------------------------------------------


def test_the_pin_records_the_v3_family_and_agrees_with_its_own_schema():
    pin = ledger_binding.load_pin()
    assert pin["consumed_contract"] == "processing-ledger-v3"
    assert pin["contract_major"] == "v3"
    assert pin["declared_contract_version"] == "3.0.0"
    # The version is not trusted from the pin: it must equal the constant the
    # pinned schema itself fixes, or the binding refuses to build.
    assert ledger_binding.pinned_contract_version() == "3.0.0"


def test_every_pinned_artifact_reproduces_from_the_producer_commit():
    """No pinned digest may be unverifiable, and none may merely be plausible."""
    checks = ledger_binding.verify_producer_blobs()
    assert checks, "the pin must name at least one artifact"
    unverifiable = [check.path for check in checks if check.status == "unverifiable"]
    assert not unverifiable, (
        "the pinned producer commit is missing from this clone, so the pin "
        f"could not be proven real: {unverifiable}. Run `git fetch origin "
        f"{ledger_binding.load_pin()['producer']['ref']}`."
    )
    assert [check.status for check in checks] == ["match"] * len(checks)


def test_the_pinned_producer_commit_exists_in_full_form():
    """A pin by commit, not by branch name, is what makes it immutable."""
    commit = ledger_binding.load_pin()["producer"]["commit"]
    resolved = subprocess.run(
        ["git", "rev-parse", "--verify", f"{commit}^{{commit}}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert resolved.returncode == 0, (
        f"the pinned producer commit {commit} does not exist in this clone"
    )
    assert resolved.stdout.strip() == commit


def test_pinned_bytes_in_the_working_tree_match_the_pin():
    checks = ledger_binding.verify_pinned_artifacts()
    assert [check.status for check in checks] == ["match"] * len(checks)
    for check in checks:
        raw = (REPO_ROOT / check.path).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == check.expected_sha256
        assert len(raw) == check.expected_bytes


def test_the_producer_branch_has_not_drifted_away_from_the_pin():
    """A silent producer change must stop the gate until the pin is re-reviewed."""
    checks = ledger_binding.check_ref_drift()
    drifted = [check.path for check in checks if check.status == "mismatch"]
    assert not drifted, (
        "the producer branch has changed these consumed contract artifacts: "
        f"{drifted}. Re-review docs/contracts/phase2b/"
        "LEDGER_CONTRACT_BINDING_V1.md and re-pin deliberately; do not just "
        "refresh the checksums."
    )


def test_the_ledger_schema_is_vendored_only_at_the_producers_own_path():
    """One copy, at the producer's path, so a 2A.6 merge cannot fork it."""
    found = sorted(
        str(path.relative_to(REPO_ROOT))
        for path in REPO_ROOT.rglob("processing-ledger-v3.schema.json")
        if ".git" not in path.parts
    )
    assert found == [
        "docs/contracts/phase2a/schemas/processing-ledger-v3.schema.json"
    ]


# --------------------------------------------------------------------------
# 2. The pin binds
# --------------------------------------------------------------------------


def test_editing_a_pinned_artifact_stops_the_gate(
    tmp_path, monkeypatch, clear_caches, ledger
):
    """Fail closed: an unpinned contract may not be used, not even once."""
    pin_path = _stage_pinned_tree(tmp_path / "repo")
    schema = tmp_path / "repo" / ledger_binding._artifact("consumed_schema")["path"]
    document = json.loads(schema.read_text(encoding="utf-8"))
    document["$defs"]["terminal_status"]["enum"].append("in_progress")
    schema.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    monkeypatch.setattr(ledger_binding, "REPO_ROOT", tmp_path / "repo")
    monkeypatch.setattr(ledger_binding, "PIN_PATH", pin_path)
    for cached in _CACHED:
        cached.cache_clear()

    with pytest.raises(ledger_binding.ContractBindingError) as raised:
        check_processing_ledger(ledger)
    assert "no longer matches its pin" in str(raised.value)


def test_a_pin_that_disagrees_with_its_schema_is_refused(
    tmp_path, monkeypatch, clear_caches
):
    """The recorded decision and the pinned bytes must say the same version."""
    pin_path = _stage_pinned_tree(tmp_path / "repo")
    pin = json.loads(pin_path.read_text(encoding="utf-8"))
    pin["declared_contract_version"] = "2.0.0"
    pin_path.write_text(json.dumps(pin), encoding="utf-8")

    monkeypatch.setattr(ledger_binding, "REPO_ROOT", tmp_path / "repo")
    monkeypatch.setattr(ledger_binding, "PIN_PATH", pin_path)
    for cached in _CACHED:
        cached.cache_clear()

    with pytest.raises(ledger_binding.ContractBindingError) as raised:
        ledger_binding.pinned_schema()
    assert "disagree" in str(raised.value)


def test_a_pin_with_an_abbreviated_producer_sha_is_refused(
    tmp_path, monkeypatch, clear_caches
):
    """A short SHA is exactly the identifier that gets completed from memory."""
    pin = ledger_binding.load_pin()
    pin["producer"] = dict(pin["producer"])
    pin["producer"]["commit"] = pin["producer"]["commit"][:7]
    pin_path = tmp_path / "pin.json"
    pin_path.write_text(json.dumps(pin), encoding="utf-8")
    monkeypatch.setattr(ledger_binding, "PIN_PATH", pin_path)
    for cached in _CACHED:
        cached.cache_clear()

    with pytest.raises(ledger_binding.ContractBindingError) as raised:
        ledger_binding.load_pin()
    assert "40-character" in str(raised.value)


@pytest.mark.parametrize(
    "missing",
    ["consumed_contract", "declared_contract_version", "producer", "artifacts"],
)
def test_an_incomplete_pin_is_refused(missing, tmp_path, monkeypatch, clear_caches):
    pin = ledger_binding.load_pin()
    pin = {key: value for key, value in pin.items() if key != missing}
    pin_path = tmp_path / "pin.json"
    pin_path.write_text(json.dumps(pin), encoding="utf-8")
    monkeypatch.setattr(ledger_binding, "PIN_PATH", pin_path)
    for cached in _CACHED:
        cached.cache_clear()

    with pytest.raises(ledger_binding.ContractBindingError):
        ledger_binding.load_pin()


def test_the_gate_reads_its_vocabulary_out_of_the_pinned_schema():
    """No second copy of the contract: the schema is the only source."""
    schema = json.loads(ledger_binding.schema_path().read_text(encoding="utf-8"))
    assert ledger_binding.pinned_terminal_statuses() == tuple(
        schema["$defs"]["terminal_status"]["enum"]
    )
    assert len(ledger_binding.pinned_terminal_statuses()) == 7
    for name in ("acquisition_id", "observation_id", "run_manifest_id", "ledger_id"):
        pattern = ledger_binding.pinned_id_pattern(name)
        assert pattern == schema["$defs"][name]["pattern"]
        assert "-v3-" in pattern, "the consumed major must be v3 throughout"


def test_a_v2_ledger_is_refused_rather_than_coerced(ledger):
    """Enum changes are major; consumers never silently coerce an old major."""
    ledger["schema_version"] = "2.0.0"
    with pytest.raises(LedgerRejected) as raised:
        check_processing_ledger(ledger)
    assert raised.value.codes == ("contract_binding_mismatch",)
    assert "refused, not coerced" in str(raised.value)


def test_a_sentinel_2c_acquisition_is_representable(ledger):
    """The whole reason the v3 major exists: 20 of 70 pilot scenes are S2C."""
    platforms = ledger_binding.pinned_schema()["$defs"]["expected_acquisition"][
        "properties"
    ]["platform"]["enum"]
    assert platforms == ["S2A", "S2B", "S2C"]
    present = {item["platform"] for item in ledger["expected_acquisitions"]}
    assert "S2C" in present, (
        "the pinned acceptance fixture must exercise the platform value that "
        "the v2 family could not represent"
    )
    check_processing_ledger(ledger)


# --------------------------------------------------------------------------
# 3. The consumer's canonicalization agrees with the producer's
# --------------------------------------------------------------------------


def test_every_digest_the_producer_embedded_recomputes_here(ledger):
    """The equivalence claim, executed against real producer output.

    If ``canonical_json.py`` ever drifts from the producer's ``jcs_dumps``,
    this fails before any gate result can be believed.
    """
    integrity = ledger["integrity"]
    assert canonical_sha256(ledger["expected_acquisitions"]) == (
        integrity["expected_acquisitions_sha256"]
    )
    assert canonical_sha256(ledger["terminal_rows"]) == (
        integrity["terminal_rows_sha256"]
    )
    assert canonical_sha256(ledger["daily_summaries"]) == (
        integrity["daily_summaries_sha256"]
    )

    body = {key: value for key, value in ledger.items() if key != "integrity"}
    body["integrity"] = {
        key: value for key, value in integrity.items() if key != "document_sha256"
    }
    assert canonical_sha256(body) == integrity["document_sha256"]

    checked = 0
    for row in ledger["terminal_rows"]:
        rest = {
            key: value for key, value in row.items() if key != "terminal_record_sha256"
        }
        assert canonical_sha256(rest) == row["terminal_record_sha256"]
        checked += 1
    for summary in ledger["daily_summaries"]:
        rest = {
            key: value
            for key, value in summary.items()
            if key != "daily_summary_sha256"
        }
        assert canonical_sha256(rest) == summary["daily_summary_sha256"]
        checked += 1
    assert checked >= 3, "the fixture must anchor more than one digest"


def test_the_producers_identity_formulas_recompute_here(ledger):
    """``SHA256_US`` over the contract's documented identity inputs."""
    primitives = ledger_binding.identity_primitives()
    for item in ledger["expected_acquisitions"]:
        digest = identity_sha256(
            primitives["acquisition_identity_domain"],
            item["collection_id"],
            item["platform"],
            item["datatake_id"],
            item["acquisition_timestamp_utc"],
            "\n".join(item["scene_ids"]),
            item["monitoring_extent_id"],
            item["composite_method_id"],
            item["grid_id"],
        )
        assert item["acquisition_id"] == (
            primitives["acquisition_id_prefix"] + digest
        )
        assert item["identity_inputs_sha256"] == digest

    digest = identity_sha256(
        primitives["ledger_identity_domain"],
        ledger["run_manifest_id"],
        ledger["run_manifest_sha256"],
        ledger["monitoring_extent_id"],
        ledger["algorithm_version"],
        ledger["integrity"]["expected_acquisitions_sha256"],
    )
    assert ledger["ledger_id"] == primitives["ledger_id_prefix"] + digest
    assert ledger["identity_inputs_sha256"] == digest


def test_canonical_form_matches_the_producers_documented_rules():
    assert canonical_json_text({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    assert canonical_json_text([True, False, None]) == "[true,false,null]"
    assert canonical_json_text("\x1f") == '"\\u001f"'
    assert canonical_json_text('a\nb"c\\d') == '"a\\nb\\"c\\\\d"'
    # Non-ASCII stays literal (UTF-8 output), as in the producer.
    assert canonical_json_text("Araripé") == '"Araripé"'


def test_keys_are_ordered_by_utf16_code_unit_not_code_point():
    """The one case where RFC 8785 and Python's ``sort_keys`` disagree.

    U+FFFD is one UTF-16 unit; U+10000 is a surrogate pair whose first unit
    (0xD800) sorts *below* 0xFFFD, so code-point order would invert these two.
    """
    text = canonical_json_text({"\ufffd": 1, "\U00010000": 2})
    assert text.index('"\U00010000"') < text.index('"\ufffd"')
    assert text != json.dumps(
        {"\ufffd": 1, "\U00010000": 2}, sort_keys=True, separators=(",", ":")
    )


@pytest.mark.parametrize(
    "value",
    [
        0.5,
        {"area_ha": 1.0},
        [1, 2.5],
        {1: "int key"},
        2**53,
        "\ud800",
    ],
)
def test_the_canonicalizer_refuses_what_it_cannot_reproduce(value):
    """It either agrees with the producer or refuses; it never guesses."""
    with pytest.raises(CanonicalJsonError):
        canonical_json_text(value)


def test_the_gate_verifies_digests_rather_than_file_bytes(ledger):
    """A pinned negative result: producer example files are not canonical bytes.

    ``generate_v3_examples.py`` writes ``json.dumps(..., indent=2)``, while the
    runtime ``serialize_v3_document`` writes canonical bytes plus a newline.
    The two differ, so a gate that required canonical *file* bytes would
    reject the producer's own committed fixture.  That is the shape of the
    2026-09-07 outage — a validator requiring what the producer never
    promised — caught here before it could fail closed on real data.
    """
    raw = ledger_binding.acceptance_fixture_path().read_bytes()
    assert raw != canonical_json_bytes(ledger) + b"\n"
    check_processing_ledger(ledger)


def test_the_binding_doc_records_the_v3_decision_and_its_basis():
    """The decision lives in a contract document, not only in a commit body."""
    text = (
        REPO_ROOT / "docs" / "contracts" / "phase2b" / "LEDGER_CONTRACT_BINDING_V1.md"
    ).read_text(encoding="utf-8")
    for needle in (
        "3.0.0",
        "config/phase2a_sentinel2c_contract_amendment_v3.json",
        "2026-09-01",
        "64fd781f1551a45914a7db32960b923c05056955",
        "S2C",
    ):
        assert needle in text, f"the binding document must record {needle!r}"
    # The pin's own digests must appear, so the document and the machine
    # readable pin cannot silently disagree.
    for entry in ledger_binding.pinned_artifacts():
        assert entry["sha256"] in text, f"{entry['path']} digest is not recorded"
    assert re.search(r"roadmap", text, re.IGNORECASE), (
        "the document must explain why the roadmap bullet says v2"
    )
