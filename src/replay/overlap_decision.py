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
Because the recorded rule is a **majority** rule — *a new detection joins an
existing event only when the majority of the new detection's area lies inside
that event* — and a value at or below one half is not a majority of anything.
The floor keeps the document and the number saying the same thing.

**A correction, recorded because the first version of this module claimed
more.**  It argued that a threshold above ``0.5`` makes the refusal unreachable
*by construction*: two distinct parents can each cover a fraction ``f`` of the
same current polygon only if their intersections with it are disjoint, so
``2f <= 1``.  That argument needs active track geometries to be area-disjoint,
which was measured — 5049 active tracks, 281 intersecting pairs, overlap area
``0.000000`` at every percentile including the maximum.

**The premise was measured on the wrong state and the claim was false.**  That
state came from the run in which almost nothing chained.  Once chaining works,
``update_tracks`` performs split and merge operations, and the tracks it leaves
behind *do* overlap in area:

===========================  ======  ==========================
state                        tracks  pairs with real area overlap
===========================  ======  ==========================
after 2026-02-11 (no chain)   17704   0   (max overlap 0.000000)
after 2026-03-13              24174   1308 (max overlap 1.000000)
after 2026-04-04              30810   5655
===========================  ======  ==========================

Of the first 400 overlapping pairs, 299 have **both** tracks ``active``.  So
two genuinely distinct parents can each hold a majority of the same new
detection, ``len(parents) > 1`` stays possible, and the refusal stays
**reachable**.  Measured end to end: the owner's value cuts the refusals sharply
but does not eliminate them.

The mistake is worth naming, because it is the same one this line of work had
just written down about cost projections: **a sample chosen along an axis that
correlates with the property being measured misleads at any sample size.**  The
disjointness measurement was taken from the only state in which nothing had
chained — that is, the state selected precisely by the condition that makes
tracks disjoint.

So the floor at one half is a **policy** consistent with the recorded rule, not
a proof, and ``AmbiguousLineageError`` stays in place because it is still
reachable and is the evidence when it fires.

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

#: A majority of the new detection's area.  The recorded rule is a majority
#: rule, so a value at or below this is not the rule the document states.
#:
#: This is NOT a guarantee that the ambiguous-lineage refusal cannot fire —
#: the module docstring records the measurement that disproved that claim.
MAJORITY_BOUND = 0.5


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
    def is_majority_rule(self) -> bool:
        """True when the threshold requires a majority of the new detection.

        Deliberately **not** called ``guard_is_structurally_unreachable``,
        which is what this property was first named.  That name asserted an
        impossibility the module docstring now records as false: once lineage
        operations run, active tracks overlap in area and a current polygon can
        still acquire two distinct parents.
        """

        return self.min_overlap_fraction > MAJORITY_BOUND

    def as_dict(self) -> dict[str, Any]:
        return {
            "min_overlap_fraction": repr(self.min_overlap_fraction),
            "rule_in_words": self.rule_in_words,
            "decided_by": self.decided_by,
            "decision_date": self.decision_date,
            "decision_sha256": self.decision_sha256,
            "supersedes": self.supersedes,
            "is_majority_rule": self.is_majority_rule,
            "refusal_remains_reachable": (
                "measured: active tracks overlap in area once lineage "
                "operations run, so this threshold reduces the ambiguous-"
                "lineage refusal but does not make it impossible"
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

    # The recorded rule is a majority rule; keep the number and the words
    # saying the same thing.
    _require(
        value > MAJORITY_BOUND,
        f"min_overlap_fraction {value!r} is not strictly greater than "
        f"{MAJORITY_BOUND}, so it is not the majority rule the decision "
        "states in words. Raising the floor is a policy consistent with that "
        "rule and NOT a guarantee that the ambiguous-lineage refusal cannot "
        "fire; see this module's docstring for the measurement that "
        "disproved the guarantee.",
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
