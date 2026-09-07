"""The exact Package 2A.6 ledger contract this repository consumes.

Package 2B.2 owns publication integration, not a second ledger definition
(canonical roadmap, Package 2B.2, first bullet).  So this module holds no
copy of the contract's rules.  It holds a *pin*: which contract family, at
which version, from which producer commit, with the exact bytes of every
artifact the gate depends on.  Everything the gate needs to know about the
ledger's shape — the ``schema_version`` constant, the terminal status
vocabulary, the identity prefixes — is read back out of the pinned schema, so
the schema stays the single source of truth and its checksum protects all of
it at once.

The family is **v3.0.0**.  The rationale, and why the roadmap bullet says v2,
are in ``docs/contracts/phase2b/LEDGER_CONTRACT_BINDING_V1.md``.

What "fails closed on a silent producer change" means here, precisely
---------------------------------------------------------------------
Three separate properties, because they catch different things and only one
of them can run everywhere:

1. **Pinned-byte integrity** — ``verify_pinned_artifacts`` recomputes the
   SHA-256 of every pinned file and refuses to build a validator if any
   differs.  Always available.  This is what makes editing the vendored
   schema without a reviewed re-pin impossible: the gate stops working.
   It is also what catches a later Package 2A.6 merge that changes the
   ledger contract, because the artifacts are pinned *at the producer's own
   paths* — a merge either leaves the bytes identical or breaks this check.
2. **Document binding** — the gate refuses any ledger whose
   ``schema_version`` is not the pinned constant.  Always available, and it
   is the property that actually holds at run time: a producer that moves to
   a v4 major emits v4 documents, and those are refused rather than
   half-understood.
3. **Producer-blob agreement** — ``verify_producer_blobs`` re-reads each
   artifact from the pinned producer *commit* through ``git cat-file`` and
   requires byte equality.  This is a repository check, not a run-time one:
   it needs the producer commit to be present in the clone.  When the object
   is absent the result says ``unverifiable`` and says so out loud; it never
   reports success it did not establish.  Its purpose is narrow and worth
   stating, given that a commit message on 2026-09-07 carried a 40-character
   SHA whose last 33 characters were invented: it proves the pin was taken
   from the real producer rather than typed.

``check_ref_drift`` adds the fourth, deliberately noisy case: if the
producer's branch has moved and its ledger artifacts no longer match the pin,
the repository gate fails until a human re-reviews the binding.  That is the
point of a pin, and it fires only for changes to these four artifacts.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
PIN_PATH = REPO_ROOT / "docs" / "contracts" / "phase2b" / "ledger_contract_pin.json"


class ContractBindingError(RuntimeError):
    """The consumed contract cannot be established, so nothing may proceed."""


@dataclass(frozen=True)
class ArtifactCheck:
    path: str
    role: str
    expected_sha256: str
    actual_sha256: str | None
    expected_bytes: int
    actual_bytes: int | None
    status: str  # "match" | "mismatch" | "missing" | "unverifiable"
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "match"


@lru_cache(maxsize=1)
def load_pin() -> dict[str, Any]:
    """Read and shape-check the pin.  A malformed pin is a hard failure."""

    try:
        pin = json.loads(PIN_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractBindingError(f"cannot read the ledger contract pin at {PIN_PATH}") from exc
    if not isinstance(pin, dict):
        raise ContractBindingError("the ledger contract pin must be a JSON object")
    for key in (
        "consumed_contract",
        "contract_major",
        "declared_contract_version",
        "producer",
        "identity_primitives",
        "artifacts",
    ):
        if key not in pin:
            raise ContractBindingError(f"the ledger contract pin is missing {key!r}")
    producer = pin["producer"]
    if not isinstance(producer, dict) or "commit" not in producer or "ref" not in producer:
        raise ContractBindingError("the pin's producer must record a ref and a commit")
    commit = producer["commit"]
    if not isinstance(commit, str) or len(commit) != 40 or any(
        character not in "0123456789abcdef" for character in commit
    ):
        raise ContractBindingError(
            "the pinned producer commit must be a full 40-character SHA-1"
        )
    artifacts = pin["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise ContractBindingError("the pin must list at least one artifact")
    for entry in artifacts:
        if not isinstance(entry, dict):
            raise ContractBindingError("each pinned artifact must be an object")
        for key in ("path", "role", "sha256", "bytes"):
            if key not in entry:
                raise ContractBindingError(f"a pinned artifact is missing {key!r}")
        digest = entry["sha256"]
        if not isinstance(digest, str) or len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise ContractBindingError(
                f"pinned artifact {entry['path']} has no lowercase SHA-256 digest"
            )
    return pin


def pinned_artifacts() -> tuple[dict[str, Any], ...]:
    return tuple(load_pin()["artifacts"])


def _artifact(role: str) -> dict[str, Any]:
    matches = [entry for entry in pinned_artifacts() if entry["role"] == role]
    if len(matches) != 1:
        raise ContractBindingError(
            f"the pin must name exactly one {role!r} artifact, found {len(matches)}"
        )
    return matches[0]


def schema_path() -> Path:
    return REPO_ROOT / _artifact("consumed_schema")["path"]


def acceptance_fixture_path() -> Path:
    return REPO_ROOT / _artifact("producer_acceptance_fixture")["path"]


def verify_pinned_artifacts() -> tuple[ArtifactCheck, ...]:
    """Recompute every pinned checksum against the working tree."""

    results = []
    for entry in pinned_artifacts():
        path = REPO_ROOT / entry["path"]
        try:
            raw = path.read_bytes()
        except OSError as exc:
            results.append(
                ArtifactCheck(
                    path=entry["path"],
                    role=entry["role"],
                    expected_sha256=entry["sha256"],
                    actual_sha256=None,
                    expected_bytes=entry["bytes"],
                    actual_bytes=None,
                    status="missing",
                    detail=str(exc),
                )
            )
            continue
        digest = hashlib.sha256(raw).hexdigest()
        matched = digest == entry["sha256"] and len(raw) == entry["bytes"]
        results.append(
            ArtifactCheck(
                path=entry["path"],
                role=entry["role"],
                expected_sha256=entry["sha256"],
                actual_sha256=digest,
                expected_bytes=entry["bytes"],
                actual_bytes=len(raw),
                status="match" if matched else "mismatch",
            )
        )
    return tuple(results)


def require_pinned_artifacts() -> None:
    """Fail closed unless every pinned artifact is byte-exact."""

    broken = [check for check in verify_pinned_artifacts() if not check.ok]
    if broken:
        details = "; ".join(
            f"{check.path}: {check.status} "
            f"(expected {check.expected_sha256[:12]}…/{check.expected_bytes}B, "
            f"found {(check.actual_sha256 or 'nothing')[:12]}…/"
            f"{check.actual_bytes if check.actual_bytes is not None else 0}B)"
            for check in broken
        )
        raise ContractBindingError(
            "the consumed Package 2A.6 ledger contract no longer matches its pin, "
            "so no ledger may be accepted until the binding is re-reviewed "
            f"(docs/contracts/phase2b/LEDGER_CONTRACT_BINDING_V1.md): {details}"
        )


def _git_blob(revision: str, path: str) -> bytes | None:
    """Return a blob from this clone, or None when the object is absent."""

    try:
        completed = subprocess.run(
            ["git", "cat-file", "blob", f"{revision}:{path}"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def verify_producer_blobs(revision: str | None = None) -> tuple[ArtifactCheck, ...]:
    """Compare each pinned artifact with the producer revision's own bytes.

    ``revision`` defaults to the pinned producer commit, which is immutable —
    so a match proves the pin was taken from the producer, not typed from
    memory.  Pass the producer *ref* to ask the different question of whether
    the producer has since moved.
    """

    pin = load_pin()
    revision = revision or pin["producer"]["commit"]
    results = []
    for entry in pinned_artifacts():
        blob = _git_blob(revision, entry["path"])
        if blob is None:
            results.append(
                ArtifactCheck(
                    path=entry["path"],
                    role=entry["role"],
                    expected_sha256=entry["sha256"],
                    actual_sha256=None,
                    expected_bytes=entry["bytes"],
                    actual_bytes=None,
                    status="unverifiable",
                    detail=(
                        f"{revision} is not present in this clone, so producer "
                        "agreement was not established either way"
                    ),
                )
            )
            continue
        digest = hashlib.sha256(blob).hexdigest()
        results.append(
            ArtifactCheck(
                path=entry["path"],
                role=entry["role"],
                expected_sha256=entry["sha256"],
                actual_sha256=digest,
                expected_bytes=entry["bytes"],
                actual_bytes=len(blob),
                status="match" if digest == entry["sha256"] else "mismatch",
            )
        )
    return tuple(results)


def check_ref_drift() -> tuple[ArtifactCheck, ...]:
    """Has the producer branch moved away from what this repository consumes?"""

    return verify_producer_blobs(load_pin()["producer"]["ref"])


@lru_cache(maxsize=1)
def pinned_schema() -> dict[str, Any]:
    """The pinned schema document, only after its bytes are verified."""

    require_pinned_artifacts()
    try:
        schema = json.loads(schema_path().read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractBindingError("the pinned ledger schema is not readable JSON") from exc
    declared = load_pin()["declared_contract_version"]
    constant = schema.get("properties", {}).get("schema_version", {}).get("const")
    if constant != declared:
        raise ContractBindingError(
            "the pin records contract version "
            f"{declared!r} but the pinned schema fixes schema_version to "
            f"{constant!r}; the recorded decision and the pinned bytes disagree"
        )
    return schema


@lru_cache(maxsize=1)
def pinned_validator():
    """A Draft 2020-12 validator over the pinned schema.

    ``jsonschema`` is imported here rather than at module scope so that an
    environment without it fails closed *at the gate* with a message naming
    the missing capability, instead of breaking every import in this package.
    """

    schema = pinned_schema()
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError as exc:  # pragma: no cover - exercised by env, not tests
        raise ContractBindingError(
            "jsonschema is required to validate a ledger against its pinned "
            "schema and is not importable; it is declared in environment.yml"
        ) from exc
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def pinned_contract_version() -> str:
    return str(pinned_schema()["properties"]["schema_version"]["const"])


def pinned_terminal_statuses() -> tuple[str, ...]:
    """The terminal vocabulary, read out of the pinned schema."""

    try:
        statuses = pinned_schema()["$defs"]["terminal_status"]["enum"]
    except (KeyError, TypeError) as exc:
        raise ContractBindingError(
            "the pinned schema does not declare a terminal status vocabulary"
        ) from exc
    if not isinstance(statuses, list) or not statuses:
        raise ContractBindingError("the pinned terminal status vocabulary is empty")
    return tuple(str(status) for status in statuses)


def pinned_id_pattern(name: str) -> str:
    try:
        return str(pinned_schema()["$defs"][name]["pattern"])
    except (KeyError, TypeError) as exc:
        raise ContractBindingError(
            f"the pinned schema does not declare a {name!r} pattern"
        ) from exc


def identity_primitives() -> dict[str, Any]:
    return dict(load_pin()["identity_primitives"])
