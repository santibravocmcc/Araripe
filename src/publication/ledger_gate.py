"""Publication-side completeness gate over a Package 2A.6 v3 processing ledger.

Roadmap Topic 31 and Package 2B.2, bullet 2: *require one terminal ledger row
per manifest-bound expected acquisition and a derived daily summary that
reconciles all same-day rows.*  This module is that requirement, on the
consumer side of the boundary.

What this is not
----------------
It is not a second ledger.  It defines no acquisition unit, no status
vocabulary and no reconciliation rule of its own: the unit and the statuses
come out of the pinned producer schema
(``src/publication/ledger_binding.py``), and every rule below is a property
the producer already promises, cited to the line of
``src/detection/ledger_v3.py`` that promises it.  The gate re-derives; it does
not re-decide.

Why re-derive at all, when the producer refuses to serialize an incomplete
ledger
------------------------------------------------------------------------------
``ProcessingLedgerV3._document_unvalidated`` raises unless every expected
acquisition is terminal and every date reconciles, so a document that came
from that producer, unmodified, always passes this gate.  That is the point.
The gate exists for the documents that did *not*: a truncated or partially
written object, a hand-assembled or replayed ledger, one produced by a later
or earlier producer, or one from a different run manifest.  Topic 31's
requirement — "incomplete runs never replace the last complete release" — is
only enforceable if the publication side can tell those apart from a complete
one, without trusting the claim in the document's own ``integrity`` block.

Every rejection is collected, never raised on the first one
----------------------------------------------------------
Package 2B.1's state validator failed on the first bad feature and the log
could not distinguish one odd row from a hundred thousand
(``docs/implementation/PHASE_2B1_2026-09-06.md`` §1).  This gate evaluates
every rule and reports all rejections at once, each with a stable code and the
JSON path it applies to.

Where the schema stops and this gate starts
-------------------------------------------
The pinned schema owns *shape*: field presence, types, the terminal status
enum, the per-status output/reason combinations, and the ``terminal`` /
``persistence_finalization_allowed`` / ``integrity`` constants.  This gate
owns only what JSON Schema cannot express — comparing one array against
another, recomputing a digest, checking chronological order, relating counts
to array lengths, and relating terminal rows to the manifest-bound expected
set.  Both layers read the *same* pinned schema file, so re-checking a rule
the schema already states would not be defence in depth; it would be an
unreachable branch that looks like protection.  Rules were removed from this
module for exactly that reason, and the division is deliberate.

Only producer-promised properties are asserted
----------------------------------------------
On 2026-09-07 a validator required ``first_seen <= last_seen``, which
``update_tracks`` never promised, and stopped the production pipeline over
0.10% of rows.  Three properties this gate deliberately does **not** require,
because the producer does not promise them, are recorded in
``docs/contracts/phase2b/LEDGER_CONTRACT_BINDING_V1.md`` §5.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from src.publication.canonical_json import (
    CanonicalJsonError,
    canonical_sha256,
    identity_sha256,
)
from src.publication import ledger_binding

LINE_FEED = "\n"

@dataclass(frozen=True)
class LedgerRejection:
    """One reason a ledger may not be published from."""

    code: str
    detail: str
    path: str = "<root>"

    def __str__(self) -> str:
        return f"{self.path}: [{self.code}] {self.detail}"


class LedgerRejected(ValueError):
    """The ledger is not an acceptable publication input."""

    def __init__(self, rejections: Iterable[LedgerRejection]) -> None:
        self.rejections = tuple(rejections)
        counts = Counter(rejection.code for rejection in self.rejections)
        headline = ", ".join(
            f"{code}×{count}" if count > 1 else code
            for code, count in sorted(counts.items())
        )
        shown = "; ".join(str(rejection) for rejection in self.rejections[:8])
        more = len(self.rejections) - 8
        if more > 0:
            shown += f"; (+{more} more)"
        super().__init__(
            f"processing ledger rejected — {len(self.rejections)} finding(s) "
            f"[{headline}]: {shown}"
        )

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(rejection.code for rejection in self.rejections)


@dataclass(frozen=True)
class DateAcceptance:
    """One UTC date whose every manifest-bound acquisition is terminal."""

    observed_on: str
    expected_acquisition_ids: tuple[str, ...]
    observation_ids: tuple[str, ...]
    status_counts: dict[str, int]
    max_terminal_at: str
    daily_summary_sha256: str


@dataclass(frozen=True)
class LedgerAcceptance:
    """What a ledger that passed the gate authorizes downstream."""

    ledger_id: str
    run_manifest_id: str
    run_manifest_sha256: str
    monitoring_extent_id: str
    algorithm_version: str
    contract_version: str
    document_sha256: str
    expected_acquisition_count: int
    dates: tuple[DateAcceptance, ...] = field(default_factory=tuple)

    @property
    def observed_dates(self) -> tuple[str, ...]:
        return tuple(item.observed_on for item in self.dates)

    @property
    def observation_ids(self) -> tuple[str, ...]:
        seen: set[str] = set()
        for item in self.dates:
            seen.update(item.observation_ids)
        return tuple(sorted(seen, key=lambda value: value.encode("utf-8")))


def _utf8_sorted(values: Iterable[str]) -> list[str]:
    return sorted(values, key=lambda value: value.encode("utf-8"))


def _instant(timestamp: str) -> datetime:
    """Parse a normalized contract timestamp.

    ``acquisition_order_key`` parses rather than compares strings on purpose:
    ``.`` sorts before ``Z``, so a fractional-second timestamp would sort
    ahead of a whole-second one from the same second under lexical order
    (``src/detection/identity_v3.py``, ``acquisition_order_key`` docstring).
    """

    return datetime.fromisoformat(timestamp[:-1] + "+00:00")


def _digest(value: Any) -> str | None:
    """canonical_sha256, or None when the value is not canonicalizable."""

    try:
        return canonical_sha256(value)
    except CanonicalJsonError:
        return None


def _without(mapping: dict[str, Any], key: str) -> dict[str, Any]:
    return {name: value for name, value in mapping.items() if name != key}


def check_processing_ledger(document: Any) -> LedgerAcceptance:
    """Accept a v3 processing ledger as a publication input, or reject it.

    Raises ``LedgerRejected`` carrying every finding, or
    ``ledger_binding.ContractBindingError`` when the consumed contract itself
    cannot be established — a missing or edited pinned artifact, a pin that
    disagrees with its own schema, or no ``jsonschema``.
    """

    ledger_binding.require_pinned_artifacts()
    contract_version = ledger_binding.pinned_contract_version()
    statuses = ledger_binding.pinned_terminal_statuses()
    primitives = ledger_binding.identity_primitives()

    rejections: list[LedgerRejection] = []

    if not isinstance(document, dict):
        raise LedgerRejected(
            [
                LedgerRejection(
                    "not_a_ledger_document",
                    f"a processing ledger must be a JSON object, got "
                    f"{type(document).__name__}",
                )
            ]
        )

    # 1. Contract binding, before anything is interpreted.
    declared = document.get("schema_version")
    if declared != contract_version:
        raise LedgerRejected(
            [
                LedgerRejection(
                    "contract_binding_mismatch",
                    f"this repository consumes processing-ledger at "
                    f"{contract_version!r}; the document declares {declared!r}. "
                    "A different major is refused, not coerced.",
                    "schema_version",
                )
            ]
        )

    # 2. The pinned schema.  Semantic checks below index into the document, so
    #    a structurally invalid document stops here rather than crashing later.
    schema_errors = sorted(
        ledger_binding.pinned_validator().iter_errors(document),
        key=lambda error: list(error.absolute_path),
    )
    if schema_errors:
        raise LedgerRejected(
            LedgerRejection(
                "schema_invalid",
                error.message,
                "/".join(str(part) for part in error.absolute_path) or "<root>",
            )
            for error in schema_errors
        )

    expected = list(document["expected_acquisitions"])
    rows = list(document["terminal_rows"])
    summaries = list(document["daily_summaries"])
    run_manifest_id = document["run_manifest_id"]
    run_manifest_sha256 = document["run_manifest_sha256"]
    monitoring_extent_id = document["monitoring_extent_id"]

    # 3. Manifest binding of the expected set.
    #    ProcessingLedgerV3.__init__ promises: identical manifest binding and
    #    monitoring extent on every expected acquisition, unique acquisition
    #    IDs, unique physical datatake keys, and (timestamp, id) order.
    for index, item in enumerate(expected):
        where = f"expected_acquisitions/{index}"
        if (
            item["run_manifest_id"] != run_manifest_id
            or item["run_manifest_sha256"] != run_manifest_sha256
        ):
            rejections.append(
                LedgerRejection(
                    "manifest_binding_mismatch",
                    f"{item['acquisition_id']} binds a different run manifest "
                    "than the ledger it is embedded in",
                    where,
                )
            )
        if item["monitoring_extent_id"] != monitoring_extent_id:
            rejections.append(
                LedgerRejection(
                    "manifest_binding_mismatch",
                    f"{item['acquisition_id']} declares monitoring extent "
                    f"{item['monitoring_extent_id']!r}, the ledger declares "
                    f"{monitoring_extent_id!r}",
                    where,
                )
            )
        if item["observed_on"] != item["acquisition_timestamp_utc"][:10]:
            rejections.append(
                LedgerRejection(
                    "acquisition_identity_mismatch",
                    f"{item['acquisition_id']} has observed_on "
                    f"{item['observed_on']!r}, which is not the UTC date of "
                    f"{item['acquisition_timestamp_utc']!r}",
                    where,
                )
            )
        scenes = list(item["scene_ids"])
        if scenes != _utf8_sorted(scenes):
            rejections.append(
                LedgerRejection(
                    "acquisition_identity_mismatch",
                    f"{item['acquisition_id']} lists scene_ids out of UTF-8 "
                    "ascending order, so its identity cannot be recomputed",
                    where,
                )
            )
        digest = identity_sha256(
            primitives["acquisition_identity_domain"],
            item["collection_id"],
            item["platform"],
            item["datatake_id"],
            item["acquisition_timestamp_utc"],
            LINE_FEED.join(scenes),
            item["monitoring_extent_id"],
            item["composite_method_id"],
            item["grid_id"],
        )
        prefix = primitives["acquisition_id_prefix"]
        if item["acquisition_id"] != prefix + digest or item[
            "identity_inputs_sha256"
        ] != digest:
            rejections.append(
                LedgerRejection(
                    "acquisition_identity_mismatch",
                    f"{item['acquisition_id']} does not recompute from its own "
                    f"identity inputs (expected {prefix}{digest})",
                    where,
                )
            )

    expected_ids = [item["acquisition_id"] for item in expected]
    if len(set(expected_ids)) != len(expected_ids):
        duplicated = sorted(
            identifier
            for identifier, count in Counter(expected_ids).items()
            if count > 1
        )
        rejections.append(
            LedgerRejection(
                "duplicate_expected_acquisition",
                f"the manifest-bound expected set repeats {len(duplicated)} "
                f"acquisition ID(s): {', '.join(duplicated[:4])}",
                "expected_acquisitions",
            )
        )
    physical_keys = [
        (item["platform"], item["datatake_id"], item["acquisition_timestamp_utc"])
        for item in expected
    ]
    if len(set(physical_keys)) != len(physical_keys):
        rejections.append(
            LedgerRejection(
                "duplicate_physical_datatake",
                "two expected acquisitions share one physical "
                "platform/datatake/timestamp key",
                "expected_acquisitions",
            )
        )
    order_keys = [
        (_instant(item["acquisition_timestamp_utc"]), item["acquisition_id"])
        for item in expected
    ]
    if order_keys != sorted(order_keys):
        rejections.append(
            LedgerRejection(
                "expected_acquisitions_out_of_order",
                "the expected set is not in (acquisition_timestamp_utc, "
                "acquisition_id) chronological order",
                "expected_acquisitions",
            )
        )

    by_id = {item["acquisition_id"]: item for item in expected}

    # 4. One terminal row per manifest-bound expected acquisition.
    row_ids = [row["acquisition_id"] for row in rows]
    row_counts = Counter(row_ids)
    for index, row in enumerate(rows):
        where = f"terminal_rows/{index}"
        acquisition_id = row["acquisition_id"]
        acquisition = by_id.get(acquisition_id)
        if acquisition is None:
            # record_terminal raises UnexpectedAcquisitionError for this.
            rejections.append(
                LedgerRejection(
                    "acquisition_outside_manifest",
                    f"{acquisition_id} has a terminal row but is absent from "
                    "the bound run manifest; a late acquisition requires a new "
                    "chronological generation, not an extra row",
                    where,
                )
            )
            continue
        if (
            row["acquisition_timestamp_utc"]
            != acquisition["acquisition_timestamp_utc"]
            or row["observed_on"] != acquisition["observed_on"]
        ):
            rejections.append(
                LedgerRejection(
                    "terminal_row_acquisition_mismatch",
                    f"{acquisition_id}'s row restates a timestamp/date that "
                    "differs from the expected acquisition it accounts for",
                    where,
                )
            )
        else:
            if _instant(row["terminal_at"]) < _instant(
                acquisition["acquisition_timestamp_utc"]
            ):
                rejections.append(
                    LedgerRejection(
                        "terminal_before_acquisition",
                        f"terminal_at {row['terminal_at']} precedes the "
                        f"acquisition instant "
                        f"{acquisition['acquisition_timestamp_utc']}",
                        where,
                    )
                )
        output = row["output"]
        observation_ids = list(output["observation_ids"])
        if output["observation_count"] != len(observation_ids):
            rejections.append(
                LedgerRejection(
                    "terminal_row_output_incoherent",
                    f"observation_count {output['observation_count']} does not "
                    f"match the {len(observation_ids)} observation ID(s) listed",
                    where,
                )
            )
        if observation_ids != _utf8_sorted(set(observation_ids)):
            rejections.append(
                LedgerRejection(
                    "terminal_row_output_incoherent",
                    "observation_ids must be unique and UTF-8 ascending",
                    where,
                )
            )
        recomputed = _digest(_without(row, "terminal_record_sha256"))
        if recomputed != row["terminal_record_sha256"]:
            rejections.append(
                LedgerRejection(
                    "terminal_record_digest_mismatch",
                    "terminal_record_sha256 does not recompute from the row's "
                    f"own bytes (found {row['terminal_record_sha256'][:12]}…, "
                    f"recomputed {(recomputed or 'unhashable')[:12]}…)",
                    where,
                )
            )
        if row_counts[acquisition_id] > 1:
            rejections.append(
                LedgerRejection(
                    "duplicate_terminal_row",
                    f"{acquisition_id} has {row_counts[acquisition_id]} terminal "
                    "rows; a replayed row is a no-op only when it is the same "
                    "row, and one acquisition may hold only one",
                    where,
                )
            )

    missing = [
        identifier for identifier in expected_ids if row_counts.get(identifier, 0) == 0
    ]
    if missing:
        rejections.append(
            LedgerRejection(
                "missing_terminal_row",
                f"{len(missing)} of {len(expected_ids)} manifest-bound expected "
                "acquisition(s) have no terminal row, so this ledger accounts "
                f"for an incomplete run: {', '.join(missing[:4])}",
                "terminal_rows",
            )
        )
    row_order = [
        (_instant(row["acquisition_timestamp_utc"]), row["acquisition_id"])
        for row in rows
    ]
    if row_order != sorted(row_order):
        rejections.append(
            LedgerRejection(
                "terminal_rows_out_of_order",
                "terminal rows are not in (acquisition_timestamp_utc, "
                "acquisition_id) order",
                "terminal_rows",
            )
        )

    # 5. One daily summary per UTC date, reconciling every same-day row.
    rows_by_id = {row["acquisition_id"]: row for row in rows}
    expected_dates = sorted({item["observed_on"] for item in expected})
    summary_dates = [summary["observed_on"] for summary in summaries]
    accepted_dates: list[DateAcceptance] = []

    if summary_dates != sorted(summary_dates):
        rejections.append(
            LedgerRejection(
                "daily_summaries_out_of_order",
                "daily summaries are not in ascending UTC-date order",
                "daily_summaries",
            )
        )
    absent = [date for date in expected_dates if date not in set(summary_dates)]
    if absent:
        rejections.append(
            LedgerRejection(
                "daily_summary_missing",
                f"{len(absent)} UTC date(s) in the expected set have no daily "
                f"summary: {', '.join(absent[:4])}",
                "daily_summaries",
            )
        )
    for date, count in sorted(Counter(summary_dates).items()):
        if count > 1:
            rejections.append(
                LedgerRejection(
                    "daily_summary_missing",
                    f"{date} has {count} daily summaries; exactly one exists "
                    "per UTC date",
                    "daily_summaries",
                )
            )

    for index, summary in enumerate(summaries):
        where = f"daily_summaries/{index}"
        date = summary["observed_on"]
        date_expected = [item for item in expected if item["observed_on"] == date]
        if not date_expected:
            rejections.append(
                LedgerRejection(
                    "daily_summary_unexpected_date",
                    f"{date} has a daily summary but no manifest-bound expected "
                    "acquisition",
                    where,
                )
            )
            continue
        date_expected_ids = _utf8_sorted(
            item["acquisition_id"] for item in date_expected
        )
        date_rows = [
            rows_by_id[item["acquisition_id"]]
            for item in date_expected
            if item["acquisition_id"] in rows_by_id
        ]
        problems: list[str] = []
        if list(summary["expected_acquisition_ids"]) != date_expected_ids:
            problems.append(
                "expected_acquisition_ids are not the manifest's expected set "
                f"for {date}"
            )
        if len(date_rows) != len(date_expected):
            problems.append(
                f"{len(date_expected) - len(date_rows)} of "
                f"{len(date_expected)} expected acquisition(s) on {date} are "
                "not terminal, so no summary for this date may claim to be"
            )
        if list(summary["terminal_acquisition_ids"]) != _utf8_sorted(
            row["acquisition_id"] for row in date_rows
        ):
            problems.append(
                "terminal_acquisition_ids do not match the rows actually "
                "present for this date"
            )
        union = _utf8_sorted(
            {
                observation_id
                for row in date_rows
                for observation_id in row["output"]["observation_ids"]
            }
        )
        if list(summary["observation_ids"]) != union:
            problems.append(
                f"observation_ids are not the {len(union)}-member union of this "
                "date's terminal rows"
            )
        recount = Counter(row["status"] for row in date_rows)
        if summary["status_counts"] != {
            status: recount.get(status, 0)
            for status in statuses
        }:
            problems.append("status_counts do not recount this date's rows")
        rows_digest = _digest(date_rows)
        if rows_digest != summary["terminal_rows_sha256"]:
            problems.append(
                "terminal_rows_sha256 does not recompute from this date's rows "
                "in chronological order"
            )
        if problems:
            rejections.append(
                LedgerRejection(
                    "daily_summary_does_not_reconcile",
                    f"{date}: " + "; ".join(problems),
                    where,
                )
            )
        summary_digest = _digest(_without(summary, "daily_summary_sha256"))
        if summary_digest != summary["daily_summary_sha256"]:
            rejections.append(
                LedgerRejection(
                    "daily_summary_digest_mismatch",
                    f"{date}: daily_summary_sha256 does not recompute from the "
                    "summary's own bytes",
                    where,
                )
            )
        if not problems and date_rows:
            accepted_dates.append(
                DateAcceptance(
                    observed_on=date,
                    expected_acquisition_ids=tuple(date_expected_ids),
                    observation_ids=tuple(union),
                    status_counts=dict(summary["status_counts"]),
                    max_terminal_at=max(
                        (row["terminal_at"] for row in date_rows),
                        key=_instant,
                    ),
                    daily_summary_sha256=summary["daily_summary_sha256"],
                )
            )

    # 6. The ledger's own totals, integrity block and identity.
    totals = document["summary"]
    declared_totals = {
        "expected_acquisition_count": len(expected),
        "terminal_acquisition_count": len(rows),
        "utc_date_count": len(expected_dates),
        "terminal_utc_date_count": len(summaries),
        "status_counts": {
            status: Counter(row["status"] for row in rows).get(status, 0)
            for status in statuses
        },
    }
    if totals != declared_totals:
        differing = sorted(
            key for key in declared_totals if totals.get(key) != declared_totals[key]
        )
        rejections.append(
            LedgerRejection(
                "ledger_summary_does_not_reconcile",
                "the ledger's own totals do not recount its collections: "
                + ", ".join(
                    f"{key} says {totals.get(key)!r}, recount is "
                    f"{declared_totals[key]!r}"
                    for key in differing
                ),
                "summary",
            )
        )

    integrity = document["integrity"]
    expected_digests = {
        "expected_acquisitions_sha256": _digest(expected),
        "terminal_rows_sha256": _digest(rows),
        "daily_summaries_sha256": _digest(summaries),
    }
    for key, value in expected_digests.items():
        if integrity[key] != value:
            rejections.append(
                LedgerRejection(
                    "integrity_digest_mismatch",
                    f"{key} does not recompute from the collection it covers",
                    f"integrity/{key}",
                )
            )
    body = _without(document, "integrity")
    body["integrity"] = _without(integrity, "document_sha256")
    document_digest = _digest(body)
    if integrity["document_sha256"] != document_digest:
        rejections.append(
            LedgerRejection(
                "integrity_digest_mismatch",
                "document_sha256 does not recompute from the document body",
                "integrity/document_sha256",
            )
        )

    identity_digest = identity_sha256(
        primitives["ledger_identity_domain"],
        run_manifest_id,
        run_manifest_sha256,
        monitoring_extent_id,
        document["algorithm_version"],
        integrity["expected_acquisitions_sha256"],
    )
    ledger_prefix = primitives["ledger_id_prefix"]
    if (
        document["ledger_id"] != ledger_prefix + identity_digest
        or document["identity_inputs_sha256"] != identity_digest
    ):
        rejections.append(
            LedgerRejection(
                "ledger_identity_mismatch",
                "ledger_id does not recompute from its manifest, monitoring "
                "extent, algorithm version and expected-acquisition digest "
                f"(expected {ledger_prefix}{identity_digest})",
                "ledger_id",
            )
        )

    if rejections:
        raise LedgerRejected(rejections)

    return LedgerAcceptance(
        ledger_id=document["ledger_id"],
        run_manifest_id=run_manifest_id,
        run_manifest_sha256=run_manifest_sha256,
        monitoring_extent_id=monitoring_extent_id,
        algorithm_version=document["algorithm_version"],
        contract_version=contract_version,
        document_sha256=integrity["document_sha256"],
        expected_acquisition_count=len(expected),
        dates=tuple(accepted_dates),
    )
