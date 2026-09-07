"""Collect every reason something is unpublishable, then report them at once.

Package 2B.1's state validator died on the first bad feature and the log could
not distinguish one odd row from a hundred thousand
(``docs/implementation/PHASE_2B1_2026-09-06.md`` §1).  Package 2B.2A answered
that in ``ledger_gate.LedgerRejected``: a stable code per finding, the JSON
path it applies to, and a count plus a code histogram *before* the
enumeration, so an operator learns the scale from the first line.

Package 2B.2B needs the same behaviour for release documents and for pointer
promotion, so the mechanism moves here and ``ledger_gate`` keeps its names as
aliases.  One implementation rather than three copies: the formatting is the
part an operator reads under pressure, and three drifting versions of it is
how "2 findings" and "20000 findings" end up looking alike again.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

#: How many findings are enumerated before the message says "+N more".  The
#: headline count and histogram always describe *all* of them.
SHOWN = 8


@dataclass(frozen=True)
class Finding:
    """One reason a document may not be published from."""

    code: str
    detail: str
    path: str = "<root>"

    def __str__(self) -> str:
        return f"{self.path}: [{self.code}] {self.detail}"


class Rejected(ValueError):
    """A document is not an acceptable publication input.

    Subclasses set ``subject`` to name what was rejected.  The message leads
    with the total and a per-code histogram; ``codes`` and ``findings`` carry
    the machine-readable form.
    """

    subject = "document"

    def __init__(self, findings: Iterable[Finding]) -> None:
        self.findings = tuple(findings)
        counts = Counter(finding.code for finding in self.findings)
        headline = ", ".join(
            f"{code}×{count}" if count > 1 else code
            for code, count in sorted(counts.items())
        )
        shown = "; ".join(str(finding) for finding in self.findings[:SHOWN])
        more = len(self.findings) - SHOWN
        if more > 0:
            shown += f"; (+{more} more)"
        super().__init__(
            f"{self.subject} rejected — {len(self.findings)} finding(s) "
            f"[{headline}]: {shown}"
        )

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(finding.code for finding in self.findings)
