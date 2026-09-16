"""What the replay does when event lineage is genuinely ambiguous.

The accepted Package 2A.1 contract fails closed on a many-to-many split/merge
component — *"requires reviewed correction"* — and the reviewed correction it
presupposes was never built.  Measured in
``docs/implementation/PHASE_4B_2026-09-09.md``: that refusal discarded the whole
date, 90 dates collapsed to 3, and no value of ``min_overlap_frac`` avoids it
(§15.3, the parameter is self-defeating).

The owner chose the rule on 2026-09-16, from three options measured and
tabulated in §16.4: **a detection whose lineage cannot be determined is
recorded as a new event, and the ambiguity is recorded with it.**

Why the reader refuses anything else
------------------------------------
Because the other two options were rejected with reasons, and a document that
quietly changed the resolution would be re-deciding a scientific question
without the owner.  ``largest_overlap`` in particular is the tempting one — it
preserves more continuity — and it is *less* faithful than the behaviour beside
it: for a detection with several parents and no tangle, ``update_tracks``
already mints a merge child recording **all** parents.  The executing agent
recommended it first, without having read that neighbouring path, and retracted
it.  The reader exists so that retraction cannot be silently undone.

What this module does not do
----------------------------
It does not decide, and it does not carry the rule into the blue runtime.
``update_tracks`` defaults to ``raise``; the replay names ``origin``.  A test
pins that the two stay different, the same way the baseline and the overlap
fraction are pinned.

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
    / "phase4_lineage_ambiguity_decision_v1.json"
)

#: Identifier of the decision document.
DECISION_ID = "araripe-phase4-lineage-ambiguity-decision-v1"

#: The rule the owner chose.  Option (c) of §16.4.
DECIDED_RESOLUTION = "origin"

#: Identifier of the rule, so a run record can cite it rather than describe it.
RULE_ID = "ambiguous-lineage-as-origin-v1"


class LineageDecisionError(RuntimeError):
    """The recorded lineage decision cannot be used as read."""


@dataclass(frozen=True)
class LineageDecision:
    """The decided resolution and the record it came from."""

    resolution: str
    rule_id: str
    rule_in_words: str
    decided_by: str
    decision_date: str
    decision_sha256: str
    supersedes: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "resolution": self.resolution,
            "rule_id": self.rule_id,
            "rule_in_words": self.rule_in_words,
            "decided_by": self.decided_by,
            "decision_date": self.decision_date,
            "decision_sha256": self.decision_sha256,
            "supersedes": self.supersedes,
        }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LineageDecisionError(message)


def load_decision(path: Path | str = DECISION_PATH) -> LineageDecision:
    """Read the recorded decision, or refuse to run."""

    target = Path(path)
    try:
        body = target.read_bytes()
        document: Mapping[str, Any] = json.loads(body)
    except FileNotFoundError as exc:
        raise LineageDecisionError(
            f"the lineage decision {target} does not exist; the replay does "
            "not default a scientific rule"
        ) from exc
    except json.JSONDecodeError as exc:
        raise LineageDecisionError(
            f"the lineage decision {target} is not readable JSON: {exc}"
        ) from exc

    _require(
        document.get("decision_id") == DECISION_ID,
        f"{target} declares decision_id {document.get('decision_id')!r}, not "
        f"{DECISION_ID!r}; a different document is a different decision",
    )

    authorization = document.get("authorization") or {}
    _require(
        authorization.get("decided_by") == "project_owner",
        "this rule states what the system means by 'this detection continues "
        "that event', which is scientific; the decision must be the owner's "
        f"and is recorded as {authorization.get('decided_by')!r}",
    )
    for field in ("blue_default_change_permitted", "production_mutation_permitted"):
        _require(
            authorization.get(field) is False,
            f"the decision must not grant itself {field}; production is frozen",
        )

    decided = document.get("decided") or {}
    resolution = decided.get("resolution")
    _require(
        resolution == DECIDED_RESOLUTION,
        f"the decision names resolution {resolution!r}; this runtime "
        f"implements {DECIDED_RESOLUTION!r}, the option the owner chose. The "
        "other two options were rejected with recorded reasons and changing "
        "the document is not how they get reopened.",
    )
    rule_id = decided.get("rule_id")
    _require(
        rule_id == RULE_ID,
        f"the decision names rule_id {rule_id!r}, not {RULE_ID!r}",
    )
    rule = decided.get("rule_in_words")
    _require(
        isinstance(rule, str) and bool(rule.strip()),
        "the decision must state the rule in words, so a reader can repeat it "
        "without recomputing it",
    )

    from src.detection.persistence import AMBIGUOUS_LINEAGE_RAISE

    _require(
        resolution != AMBIGUOUS_LINEAGE_RAISE,
        "the decided resolution equals the blue default; a decision that "
        "changes nothing is a document that says it changed something",
    )

    return LineageDecision(
        resolution=resolution,
        rule_id=rule_id,
        rule_in_words=rule.strip(),
        decided_by=authorization["decided_by"],
        decision_date=str(document.get("decision_date")),
        decision_sha256=hashlib.sha256(body).hexdigest(),
        supersedes=str(decided.get("supersedes_for_the_replay")),
    )
