"""The overlap fraction the replay binds event lineage with, read from the decision.

Phase 4, second escalation.  The frozen ``0.05`` made ``update_tracks`` refuse
event lineage on 34 of 107 expected acquisitions
(``docs/implementation/PHASE_4B_2026-09-09.md`` §4), because the accepted
Package 2A.1 contract fails closed on an ambiguous many-to-many split/merge
component and the reviewed correction it presupposes was never built.  The
owner decided the rule, and the decision lives in
``config/phase4_persistence_overlap_decision_v1.json``.

Why the reader refuses anything at or below one half
----------------------------------------------------
This is the whole reason the module exists, and it is not a style choice.

The owner's requirement is that **nothing needing human review remains in the
final production system**.  A threshold that merely *happened* not to raise on
the dates we looked at does not satisfy that: it is unreviewed luck.  A
threshold strictly greater than ``0.5`` satisfies it structurally.

Two *distinct* parents can each cover a fraction ``f`` of the same current
polygon only if their intersections with it are disjoint subsets of it, so
``2f <= 1`` and ``f <= 0.5``.  For a threshold strictly above ``0.5`` a current
polygon therefore has **at most one** parent, and both branches of the guard
require some polygon to have more than one.  The refusal becomes unreachable
by construction.

So a decision naming ``0.30`` — which did clear the refusal on the date that
was measured — is **refused here**, because it buys observation where the owner
asked for a guarantee.  Refusing it is the difference between enforcing the
requirement and documenting it.

The premise, and why the guard is not deleted
---------------------------------------------
The argument needs the parents' intersections with the current polygon to be
disjoint, which holds when active track geometries do not overlap each other in
area.  Measured on the replay's own state: 5049 active tracks, 281 intersecting
distinct pairs, and an overlap area of ``0.000000`` at every percentile
including the maximum — they touch at boundaries and never overlap.

But **no producer promises** that active tracks stay area-disjoint.  So this is
a measured premise, not a guaranteed one, and ``AmbiguousLineageError`` is
deliberately left in place: if the premise ever fails, the refusal is the
evidence.  Removing the guard because a threshold makes it unreachable would
throw away exactly the signal that the threshold stopped working.

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

#: The recorded decision this module reads.
DECISION_PATH = (
    Path(settings.ROOT_DIR)
    / "config"
    / "phase4_persistence_overlap_decision_v1.json"
)

#: Identifier of the decision document.
DECISION_ID = "araripe-phase4-persistence-overlap-decision-v1"

#: The bound below which the guard is reachable.  A current polygon can have
#: two distinct parents only when each covers at most half of it, so a
#: threshold at or below one half leaves the many-to-many component possible.
STRUCTURAL_BOUND = 0.5


class OverlapDecisionError(RuntimeError):
    """The recorded overlap decision cannot be used as read."""


@dataclass(frozen=True)
class OverlapDecision:
    """The decided overlap fraction and the record it came from."""

    min_overlap_fraction: float
    rule_in_words: str
    decided_by: str
    decision_date: str
    decision_sha256: str
    supersedes: str

    @property
    def guard_is_structurally_unreachable(self) -> bool:
        """True when no current polygon can acquire two distinct parents."""

        return self.min_overlap_fraction > STRUCTURAL_BOUND

    def as_dict(self) -> dict[str, Any]:
        return {
            "min_overlap_fraction": repr(self.min_overlap_fraction),
            "rule_in_words": self.rule_in_words,
            "decided_by": self.decided_by,
            "decision_date": self.decision_date,
            "decision_sha256": self.decision_sha256,
            "supersedes": self.supersedes,
            "guard_is_structurally_unreachable": (
                self.guard_is_structurally_unreachable
            ),
        }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise OverlapDecisionError(message)


def _fraction(raw: Any) -> float:
    """Parse the recorded fraction, refusing a float in the document.

    The decision documents record fractions as strings because ``json.dumps``
    and the RFC 8785 form disagree on a float of integral value and on
    exponents, and a document that may later be canonicalised must not carry
    one.
    """

    _require(
        isinstance(raw, str),
        "min_overlap_fraction must be recorded as a string, not a JSON "
        f"number; got {type(raw).__name__}",
    )
    try:
        value = float(raw)
    except ValueError as exc:
        raise OverlapDecisionError(
            f"min_overlap_fraction {raw!r} is not a number"
        ) from exc
    _require(
        0.0 < value < 1.0,
        f"min_overlap_fraction {raw!r} is a fraction of the new detection's "
        "area and must be strictly between 0 and 1",
    )
    return value


def load_decision(path: Path | str = DECISION_PATH) -> OverlapDecision:
    """Read the recorded decision, or refuse to run.

    Fails closed on a missing or wrong document, on an unauthorised decision,
    and — the point of the module — on a value that leaves the ambiguous
    lineage refusal reachable.
    """

    target = Path(path)
    try:
        body = target.read_bytes()
        document: Mapping[str, Any] = json.loads(body)
    except FileNotFoundError as exc:
        raise OverlapDecisionError(
            f"the overlap decision {target} does not exist; the replay does "
            "not default a scientific rule"
        ) from exc
    except json.JSONDecodeError as exc:
        raise OverlapDecisionError(
            f"the overlap decision {target} is not readable JSON: {exc}"
        ) from exc

    _require(
        document.get("decision_id") == DECISION_ID,
        f"{target} declares decision_id {document.get('decision_id')!r}, not "
        f"{DECISION_ID!r}; a different document is a different decision",
    )

    authorization = document.get("authorization") or {}
    _require(
        authorization.get("decided_by") == "project_owner",
        "this rule changes what counts as the same deforestation event across "
        "two dates, which is scientific; the decision must be the owner's and "
        f"is recorded as {authorization.get('decided_by')!r}",
    )
    _require(
        authorization.get("blue_default_change_permitted") is False,
        "the decision must not grant itself permission to move the blue "
        "default; production is frozen",
    )
    _require(
        authorization.get("production_mutation_permitted") is False,
        "the decision must not grant itself production mutation",
    )

    decided = document.get("decided") or {}
    value = _fraction(decided.get("min_overlap_fraction"))

    # The requirement, enforced rather than documented.
    _require(
        value > STRUCTURAL_BOUND,
        f"min_overlap_fraction {value!r} is not strictly greater than "
        f"{STRUCTURAL_BOUND}, so a current polygon can still acquire two "
        "distinct parents and the ambiguous-lineage refusal stays reachable. "
        "The owner's requirement is that nothing needing human review remain "
        "in the final system, and a value that merely was not observed to "
        "raise does not meet it.",
    )

    rule = decided.get("rule_in_words")
    _require(
        isinstance(rule, str) and bool(rule.strip()),
        "the decision must state the rule in words, so a reader can repeat it "
        "without recomputing it",
    )

    from src.detection.persistence import DEFAULT_MIN_OVERLAP_FRAC

    _require(
        value != DEFAULT_MIN_OVERLAP_FRAC,
        f"the decided fraction equals the blue default "
        f"{DEFAULT_MIN_OVERLAP_FRAC!r}; a decision that changes nothing is a "
        "document that says it changed something",
    )

    return OverlapDecision(
        min_overlap_fraction=value,
        rule_in_words=rule.strip(),
        decided_by=authorization["decided_by"],
        decision_date=str(document.get("decision_date")),
        decision_sha256=hashlib.sha256(body).hexdigest(),
        supersedes=str(decided.get("supersedes_for_the_replay")),
    )
