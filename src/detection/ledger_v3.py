"""Manifest-bound processing ledger for the v3 family (Package 2A.6B.1).

The ledger accounts for physical acquisitions, not calendar dates.  Daily
summaries are derived only after every acquisition expected by the bound run
manifest for that UTC date has one terminal row.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from src.detection.contracts_v3 import (
    ContractV3ValidationError,
    serialize_v3_document,
    validate_v3_schema,
)
from src.detection.identity import canonical_sha256, identity_sha256
from src.detection.identity_v3 import (
    SCHEMA_VERSION,
    AcquisitionV3,
    acquisition_order_key,
    normalize_utc_timestamp,
    require_nonempty,
    require_semver,
    require_sha256,
    require_v3_id,
    sorted_v3_ids,
    validate_observation_v3,
    validate_run_manifest_binding,
)


TERMINAL_STATUSES = (
    "complete_with_alerts",
    "complete_zero_alerts",
    "rejected_low_coverage",
    "rejected_quality",
    "failed_download",
    "failed_missing_input",
    "failed_processing",
)
_SUCCESS_STATUSES = {"complete_with_alerts", "complete_zero_alerts"}


class LedgerError(RuntimeError):
    """Base class for a fail-closed ledger operation."""


class UnexpectedAcquisitionError(LedgerError):
    """A terminal row is not part of the manifest-bound expected set."""


class ConflictingTerminalRowError(LedgerError):
    """An acquisition already has different terminal evidence."""


class IncompleteDateError(LedgerError):
    """A daily summary was requested before every expected row was terminal."""


def _reason(status: str, reason: dict[str, str] | None) -> dict[str, str] | None:
    if status in _SUCCESS_STATUSES:
        if reason is not None:
            raise ValueError(f"{status} cannot carry a rejection/failure reason")
        return None
    if not isinstance(reason, dict) or set(reason) != {"code", "message"}:
        raise ValueError(f"{status} requires reason with code and message")
    code = require_nonempty(reason["code"], label="reason.code")
    if code[0] not in "abcdefghijklmnopqrstuvwxyz0123456789" or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789._-"
        for character in code
    ):
        raise ValueError("reason.code must use lowercase contract-token characters")
    return {
        "code": code,
        "message": require_nonempty(reason["message"], label="reason.message"),
    }


def _expected_record(acquisition: AcquisitionV3) -> dict[str, Any]:
    return acquisition.to_dict()


def _stable_observation_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return immutable scientific fields, excluding retry provenance."""

    return {
        key: deepcopy(value)
        for key, value in record.items()
        if key not in {"run_manifest_id", "run_manifest_sha256", "created_at"}
    }


@dataclass(frozen=True)
class TerminalRowResult:
    no_op: bool
    row: dict[str, Any]


class ProcessingLedgerV3:
    """Incrementally collect immutable terminal rows for one run manifest."""

    def __init__(
        self,
        *,
        run_manifest_id: str,
        run_manifest_sha256: str,
        acquisitions: Iterable[AcquisitionV3],
        monitoring_extent_id: str,
        algorithm_version: str,
        created_at: str,
    ) -> None:
        validate_run_manifest_binding(run_manifest_id, run_manifest_sha256)
        ordered = tuple(sorted(tuple(acquisitions), key=acquisition_order_key))
        if not ordered:
            raise ValueError("a run manifest must expect at least one acquisition")
        if len({item.acquisition_id for item in ordered}) != len(ordered):
            raise ValueError("expected acquisitions contain duplicate IDs")
        physical_keys = {
            (
                item.platform,
                item.datatake_id,
                item.acquisition_timestamp_utc,
            )
            for item in ordered
        }
        if len(physical_keys) != len(ordered):
            raise ValueError(
                "expected acquisitions contain a duplicate physical datatake key"
            )
        for item in ordered:
            if (
                item.run_manifest_id != run_manifest_id
                or item.run_manifest_sha256 != run_manifest_sha256
            ):
                raise ValueError(
                    "expected acquisition has a different manifest binding"
                )
            if item.monitoring_extent_id != monitoring_extent_id:
                raise ValueError(
                    "expected acquisition has a different monitoring extent"
                )
        self.run_manifest_id = run_manifest_id
        self.run_manifest_sha256 = run_manifest_sha256
        self.monitoring_extent_id = require_nonempty(
            monitoring_extent_id, label="monitoring_extent_id"
        )
        self.algorithm_version = require_semver(
            algorithm_version, label="algorithm_version"
        )
        self.generated_at = normalize_utc_timestamp(created_at, label="created_at")
        self._acquisitions = ordered
        self._expected = tuple(_expected_record(item) for item in ordered)
        self.expected_acquisitions_sha256 = canonical_sha256(list(self._expected))
        identity_digest = identity_sha256(
            "processing-ledger-v3",
            run_manifest_id,
            run_manifest_sha256,
            self.monitoring_extent_id,
            self.algorithm_version,
            self.expected_acquisitions_sha256,
        )
        self.ledger_id = "pl-v3-" + identity_digest
        self.identity_inputs_sha256 = identity_digest
        self._rows: dict[str, dict[str, Any]] = {}

    @property
    def acquisitions(self) -> tuple[AcquisitionV3, ...]:
        return self._acquisitions

    @property
    def expected_acquisitions(self) -> tuple[dict[str, Any], ...]:
        return deepcopy(self._expected)

    @property
    def terminal_rows(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            deepcopy(self._rows[item.acquisition_id])
            for item in self._acquisitions
            if item.acquisition_id in self._rows
        )

    def expected_for_date(self, observed_on: str) -> tuple[AcquisitionV3, ...]:
        return tuple(
            item
            for item in self._acquisitions
            if item.observed_on == observed_on
        )

    def record_terminal(
        self,
        *,
        acquisition_id: str,
        status: str,
        observation_ids: Iterable[str] = (),
        reason: dict[str, str] | None = None,
        terminal_at: str,
        artifact_sha256: str | None = None,
    ) -> TerminalRowResult:
        require_v3_id(acquisition_id, prefix="acq-v3-", label="acquisition_id")
        expected = {item.acquisition_id: item for item in self._acquisitions}
        if acquisition_id not in expected:
            raise UnexpectedAcquisitionError(
                "acquisition is absent from the bound run manifest; rebuild required"
            )
        if status not in TERMINAL_STATUSES:
            raise ValueError("status is not a processing-ledger-v3 terminal status")
        observations = sorted_v3_ids(
            observation_ids,
            prefix="obs-v3-",
            label="observation_ids",
            allow_empty=True,
        )
        if status == "complete_with_alerts" and not observations:
            raise ValueError("complete_with_alerts requires at least one observation")
        if status != "complete_with_alerts" and observations:
            raise ValueError(f"{status} cannot carry observation IDs")
        normalized_reason = _reason(status, reason)
        if artifact_sha256 is not None:
            artifact_sha256 = require_sha256(artifact_sha256, label="artifact_sha256")
        if status in _SUCCESS_STATUSES and artifact_sha256 is None:
            raise ValueError(f"{status} requires an explicit artifact checksum")
        acquisition = expected[acquisition_id]
        terminal_timestamp = normalize_utc_timestamp(terminal_at, label="terminal_at")
        terminal_instant = datetime.fromisoformat(
            terminal_timestamp[:-1] + "+00:00"
        )
        acquisition_instant = datetime.fromisoformat(
            acquisition.acquisition_timestamp_utc[:-1] + "+00:00"
        )
        if terminal_instant < acquisition_instant:
            raise ValueError("terminal_at cannot precede the acquisition timestamp")
        row_without_digest = {
            "acquisition_id": acquisition_id,
            "acquisition_timestamp_utc": acquisition.acquisition_timestamp_utc,
            "observed_on": acquisition.observed_on,
            "status": status,
            "terminal_at": terminal_timestamp,
            "output": {
                "observation_count": len(observations),
                "observation_ids": list(observations),
                "artifact_sha256": artifact_sha256,
            },
            "reason": normalized_reason,
        }
        row = {
            **row_without_digest,
            "terminal_record_sha256": canonical_sha256(row_without_digest),
        }
        existing = self._rows.get(acquisition_id)
        if existing is not None:
            if existing != row:
                raise ConflictingTerminalRowError(
                    "acquisition already has a different terminal row"
                )
            return TerminalRowResult(no_op=True, row=deepcopy(existing))
        self._rows[acquisition_id] = row
        return TerminalRowResult(no_op=False, row=deepcopy(row))

    def is_date_terminal(self, observed_on: str) -> bool:
        expected = self.expected_for_date(observed_on)
        return bool(expected) and all(
            item.acquisition_id in self._rows for item in expected
        )

    def daily_summary(self, observed_on: str) -> dict[str, Any]:
        expected = self.expected_for_date(observed_on)
        if not expected:
            raise UnexpectedAcquisitionError(
                f"{observed_on} is absent from the bound run manifest"
            )
        missing = [
            item.acquisition_id
            for item in expected
            if item.acquisition_id not in self._rows
        ]
        if missing:
            raise IncompleteDateError(
                f"{observed_on} still has {len(missing)} non-terminal acquisition(s)"
            )
        rows = [self._rows[item.acquisition_id] for item in expected]
        expected_ids = sorted(
            (item.acquisition_id for item in expected),
            key=lambda item: item.encode("utf-8"),
        )
        terminal_ids = sorted(
            (row["acquisition_id"] for row in rows),
            key=lambda item: item.encode("utf-8"),
        )
        observation_ids = sorted(
            {
                observation_id
                for row in rows
                for observation_id in row["output"]["observation_ids"]
            },
            key=lambda item: item.encode("utf-8"),
        )
        status_counter = Counter(row["status"] for row in rows)
        summary_without_digest = {
            "observed_on": observed_on,
            "expected_acquisition_ids": expected_ids,
            "terminal_acquisition_ids": terminal_ids,
            "terminal": True,
            "terminal_rows_sha256": canonical_sha256(rows),
            "observation_ids": observation_ids,
            "status_counts": {
                status: status_counter.get(status, 0) for status in TERMINAL_STATUSES
            },
            "persistence_finalization_allowed": True,
        }
        return {
            **summary_without_digest,
            "daily_summary_sha256": canonical_sha256(summary_without_digest),
        }

    def daily_summaries(self) -> tuple[dict[str, Any], ...]:
        dates = sorted({item.observed_on for item in self._acquisitions})
        return tuple(
            self.daily_summary(observed_on)
            for observed_on in dates
            if self.is_date_terminal(observed_on)
        )

    def _document_unvalidated(self) -> dict[str, Any]:
        status_counter = Counter(row["status"] for row in self._rows.values())
        dates = sorted({item.observed_on for item in self._acquisitions})
        summaries = list(self.daily_summaries())
        if len(self._rows) != len(self._acquisitions) or len(summaries) != len(dates):
            raise IncompleteDateError(
                "only a fully terminal, daily-reconciled ledger may be serialized"
            )
        body = {
            "schema_version": SCHEMA_VERSION,
            "ledger_id": self.ledger_id,
            "identity_inputs_sha256": self.identity_inputs_sha256,
            "run_manifest_id": self.run_manifest_id,
            "run_manifest_sha256": self.run_manifest_sha256,
            "monitoring_extent_id": self.monitoring_extent_id,
            "algorithm_version": self.algorithm_version,
            "generated_at": self.generated_at,
            "order_policy": {
                "primary": "acquisition_timestamp_utc",
                "secondary": "acquisition_id",
            },
            "replay_policy": {
                "duplicate_terminal_row": "no_op",
                "conflicting_terminal_row": "reject_fail_closed",
                "late_same_day_acquisition": (
                    "requires_new_chronological_generation"
                ),
            },
            "expected_acquisitions": list(deepcopy(self._expected)),
            "terminal_rows": list(self.terminal_rows),
            "daily_summaries": summaries,
            "summary": {
                "expected_acquisition_count": len(self._acquisitions),
                "terminal_acquisition_count": len(self._rows),
                "utc_date_count": len(dates),
                "terminal_utc_date_count": len(summaries),
                "status_counts": {
                    status: status_counter.get(status, 0)
                    for status in TERMINAL_STATUSES
                },
            },
        }
        integrity_without_document = {
            "expected_acquisitions_sha256": canonical_sha256(
                body["expected_acquisitions"]
            ),
            "terminal_rows_sha256": canonical_sha256(body["terminal_rows"]),
            "daily_summaries_sha256": canonical_sha256(body["daily_summaries"]),
            "schema_validated": True,
            "manifest_reconciled": True,
            "daily_summaries_reconciled": True,
        }
        body["integrity"] = integrity_without_document
        return {
            **body,
            "integrity": {
                **integrity_without_document,
                "document_sha256": canonical_sha256(body),
            },
        }

    def to_dict(self) -> dict[str, Any]:
        document = self._document_unvalidated()
        validate_processing_ledger_v3(document)
        return document

    def to_bytes(self) -> bytes:
        return serialize_v3_document("processing-ledger-v3", self.to_dict())

    def date_input_digest(
        self, observed_on: str, observation_records: Iterable[dict[str, Any]]
    ) -> str:
        # Full observations were already reconciled by the persistence producer.
        # Keep this parameter explicit so callers cannot accidentally finalize
        # without supplying the assessed observations, while binding only the
        # stable scientific inputs.  Operational attempt timestamps and prose
        # messages must not turn an identical rolling-window retry into a rebuild.
        records = [deepcopy(item) for item in observation_records]
        for item in records:
            validate_observation_v3(item)
        records.sort(key=lambda item: item["observation_id"].encode("utf-8"))
        supplied_ids = sorted(
            (item["observation_id"] for item in records),
            key=lambda item: item.encode("utf-8"),
        )
        if len(supplied_ids) != len(set(supplied_ids)):
            raise ValueError("observation records contain duplicate IDs")
        summary = self.daily_summary(observed_on)
        if supplied_ids != summary["observation_ids"]:
            raise ValueError("observation records do not reconcile with daily summary")
        expected = self.expected_for_date(observed_on)
        rows = [self._rows[item.acquisition_id] for item in expected]
        records_by_acquisition = {
            item.acquisition_id: [
                record
                for record in records
                if record["acquisition_id"] == item.acquisition_id
            ]
            for item in expected
        }
        return canonical_sha256(
            {
                "observed_on": observed_on,
                "expected_acquisition_ids": summary["expected_acquisition_ids"],
                "terminal_inputs": [
                    {
                        "acquisition_id": row["acquisition_id"],
                        "status": row["status"],
                        "observation_ids": row["output"]["observation_ids"],
                        "observation_records_sha256": canonical_sha256(
                            [
                                _stable_observation_record(record)
                                for record in records_by_acquisition[
                                    row["acquisition_id"]
                                ]
                            ]
                        ),
                        "artifact_sha256": row["output"]["artifact_sha256"],
                        "reason_code": (
                            row["reason"]["code"] if row["reason"] else None
                        ),
                    }
                    for row in rows
                ],
            }
        )


def validate_processing_ledger_v3(payload: dict[str, Any]) -> None:
    """Rebuild and compare a ledger to enforce all semantic invariants."""

    validate_v3_schema("processing-ledger-v3", payload)
    try:
        acquisitions = tuple(
            AcquisitionV3.from_dict(item)
            for item in payload["expected_acquisitions"]
        )
        rebuilt = ProcessingLedgerV3(
            run_manifest_id=payload["run_manifest_id"],
            run_manifest_sha256=payload["run_manifest_sha256"],
            acquisitions=acquisitions,
            monitoring_extent_id=payload["monitoring_extent_id"],
            algorithm_version=payload["algorithm_version"],
            created_at=payload["generated_at"],
        )
        for row in payload["terminal_rows"]:
            output = row["output"]
            rebuilt.record_terminal(
                acquisition_id=row["acquisition_id"],
                status=row["status"],
                observation_ids=output["observation_ids"],
                reason=row["reason"],
                terminal_at=row["terminal_at"],
                artifact_sha256=output["artifact_sha256"],
            )
        canonical = rebuilt._document_unvalidated()
    except (KeyError, TypeError, ValueError, LedgerError) as exc:
        raise ContractV3ValidationError(
            "processing-ledger-v3 semantic validation failed"
        ) from exc
    if payload != canonical:
        raise ContractV3ValidationError(
            "processing-ledger-v3 hashes, order, or reconciliation differ "
            "from its canonical manifest-bound reconstruction"
        )
