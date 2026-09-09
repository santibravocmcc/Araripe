"""The unit the 2026 replay composes on, read from the recorded decision.

Phase 4, scope item 2 — the question Phase 3 measured and deliberately left
open (``docs/operations/PHASE_3_REPLAY_RUNBOOK.md`` §8).

Why this is a module and not a constant
---------------------------------------
The same reason :mod:`src.replay.freeze` reads the baseline decision from a
file rather than restating it: there is one place the decision lives, and the
runtime **fails closed** if that place disagrees with the code.  A constant
here and a paragraph in a document is how the two drift.

What the decision is, in one line: the replay composes **one physical
datatake at a time**, under ``datatake_mosaic-v1``, because the v3 ledger
cannot honestly represent a composition unit coarser than its accounting unit.
The reasoning, the measurements and the rejected alternatives are in
``config/phase4_composition_unit_decision_v1.json``; this module refuses to
run against a decision that says something else.

Why the method ID is not the baseline's
---------------------------------------
``coverage-ranked-first-valid-v1`` names
:func:`src.processing.composition_v2.compose_datatake`, which ranks scenes by
``valid_pixel_count`` and takes every band from the first valid scene in that
explicit order.  An Earth Engine ``mosaic()`` takes the last unmasked image in
collection order.  They agree wherever one scene covers a pixel and are not
proven to agree elsewhere, so this composition gets its own ID.  Asserting the
baseline's ID would be asserting an invariant no producer promises — the same
defect that made the export refuse to pre-compute ``acquisition_id``.

Determinism
-----------
No clock, no network, no object store, no credential.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from config import settings
from src.detection.identity_v3 import require_versioned_method

#: The recorded decision this module reads.
DECISION_PATH = (
    Path(settings.ROOT_DIR) / "config" / "phase4_composition_unit_decision_v1.json"
)

#: Identifier of the decision document.
DECISION_ID = "araripe-phase4-composition-unit-decision-v1"

#: The unit the decision must name.  A decision naming anything else is a
#: different decision and this runtime refuses it rather than guessing.
DECIDED_UNIT = "physical_datatake"

#: The composite method the replay mints acquisition identities under.
COMPOSITE_METHOD_ID = "datatake_mosaic-v1"

#: The method this replaces for the replay only.  Blue keeps writing it.
SUPERSEDED_METHOD_ID = "daily_mosaic-v1"

#: The method that exists in the library and was deliberately not chosen.
AVAILABLE_NOT_CHOSEN_METHOD_ID = "coverage-ranked-first-valid-v1"

#: The grid decision: the export transform is NOT pinned, because the grids
#: were measured to coincide already.
GRID_DECISION = "do_not_pin_crs_transform"


class CompositionUnitError(RuntimeError):
    """The composition-unit decision is absent, unreadable, or says otherwise."""


@dataclass(frozen=True)
class CompositionUnitDecision:
    """The decided composition unit and the document it was read from."""

    unit: str
    composite_method_id: str
    superseded_method_id: str
    grid_decision: str
    decision_path: str
    decision_sha256: str
    decision_date: str
    expected_acquisitions: int
    expected_dates: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit": self.unit,
            "composite_method_id": self.composite_method_id,
            "superseded_method_id": self.superseded_method_id,
            "grid_decision": self.grid_decision,
            "decision_path": self.decision_path,
            "decision_sha256": self.decision_sha256,
            "decision_date": self.decision_date,
            "expected_acquisitions": self.expected_acquisitions,
            "expected_dates": self.expected_dates,
        }


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _require(document: Mapping[str, Any], path: Path, *keys: str) -> Any:
    node: Any = document
    for key in keys:
        if not isinstance(node, Mapping) or key not in node:
            raise CompositionUnitError(
                f"{path.name} has no {'.'.join(keys)}"
            )
        node = node[key]
    return node


def load_decision(decision_path: Path | None = None) -> CompositionUnitDecision:
    """Read and validate the composition-unit decision, or fail closed.

    Every check here exists because its absence would let the replay run
    against a decision it was not built for: a document for another phase, a
    unit this code cannot execute, a method ID that would collide with blue's,
    or a decision that quietly claims permission to change production.
    """

    path = Path(DECISION_PATH if decision_path is None else decision_path)
    if not path.exists():
        raise CompositionUnitError(
            f"the composition-unit decision {path} is absent; Phase 4 does not "
            "default this — the ledger's accounting unit depends on it"
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompositionUnitError(
            f"cannot read the composition-unit decision {path}: {exc}"
        ) from exc

    if document.get("decision_id") != DECISION_ID:
        raise CompositionUnitError(
            f"{path.name} declares decision_id {document.get('decision_id')!r}, "
            f"expected {DECISION_ID!r}"
        )

    unit = _require(document, path, "composition_unit", "decided")
    if unit != DECIDED_UNIT:
        raise CompositionUnitError(
            f"{path.name} decides the unit {unit!r}; this runtime implements "
            f"{DECIDED_UNIT!r} only. A different unit is a different replay."
        )

    method = _require(document, path, "composition_unit", "composite_method_id")
    require_versioned_method(method, label="composite_method_id")
    # The two named wrong answers are diagnosed BEFORE the generic mismatch.
    # Ordered the other way round they are unreachable, and the reader loses
    # the only part of the message that says why the value is wrong rather
    # than merely different.
    if method == SUPERSEDED_METHOD_ID:
        raise CompositionUnitError(
            f"{path.name} would mint v3 identities under the blue "
            f"{SUPERSEDED_METHOD_ID!r} method; that is the collision this "
            "decision exists to prevent"
        )
    if method == AVAILABLE_NOT_CHOSEN_METHOD_ID:
        raise CompositionUnitError(
            f"{path.name} claims the baseline's composition method for an "
            "Earth Engine mosaic; the two are not proven equal"
        )
    if method != COMPOSITE_METHOD_ID:
        raise CompositionUnitError(
            f"{path.name} names composite method {method!r}, expected "
            f"{COMPOSITE_METHOD_ID!r}"
        )

    superseded = _require(
        document, path, "composition_unit", "supersedes_for_the_replay"
    )
    if superseded != SUPERSEDED_METHOD_ID:
        raise CompositionUnitError(
            f"{path.name} says it supersedes {superseded!r}, expected "
            f"{SUPERSEDED_METHOD_ID!r}"
        )

    grid = _require(document, path, "export_grid", "decided")
    if grid != GRID_DECISION:
        raise CompositionUnitError(
            f"{path.name} decides the grid as {grid!r}; this runtime "
            f"implements {GRID_DECISION!r}. Pinning the transform would change "
            "exported pixels and is not what was measured."
        )

    authorization = document.get("authorization") or {}
    for flag in (
        "blue_default_change_permitted",
        "production_mutation_permitted",
        "quality_gate_change_permitted",
    ):
        if authorization.get(flag) is not False:
            raise CompositionUnitError(
                f"{path.name} must state {flag}: false — production is frozen "
                "through Phase 5 and the quality gate is Phase 5's to change"
            )
    if authorization.get("decided_by") != "executing_agent":
        raise CompositionUnitError(
            f"{path.name} must record who decided; this one is the agent's, "
            "delegated, unlike the baseline decision which is the owner's"
        )

    consequence = document.get("consequence_of_the_decision") or {}
    expected = consequence.get("acquisitions_expected")
    measurement = document.get("measurement") or {}
    dates = measurement.get("distinct_utc_dates")
    for label, value in (("acquisitions_expected", expected), ("distinct_utc_dates", dates)):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise CompositionUnitError(
                f"{path.name} must record {label} as a positive integer; the "
                "decision is a measurement or it is an opinion"
            )
    if expected < dates:
        raise CompositionUnitError(
            f"{path.name} records fewer acquisitions ({expected}) than dates "
            f"({dates}); a date holds at least one acquisition"
        )

    return CompositionUnitDecision(
        unit=unit,
        composite_method_id=method,
        superseded_method_id=superseded,
        grid_decision=grid,
        decision_path=path.relative_to(settings.ROOT_DIR).as_posix(),
        decision_sha256=_sha256_of(path),
        decision_date=str(document.get("decision_date")),
        expected_acquisitions=int(expected),
        expected_dates=int(dates),
    )
