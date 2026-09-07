#!/usr/bin/env python3
"""Refuse to publish from an incomplete Package 2A.6 v3 processing ledger.

Roadmap Topic 31: *record one terminal row per manifest-bound expected
acquisition plus a reconciled daily summary … incomplete runs never replace
the last complete release.*  This is the executable half of that on the
publication side (Package 2B.2A).

It reads a ``processing-ledger-v3`` document, verifies that the contract this
repository consumes is exactly the pinned one, and either prints what the
ledger authorizes or exits non-zero listing every reason it does not.  There
is no partial-credit exit status: a ledger is an acceptable publication input
or it is not.

Usage:
    python scripts/check_processing_ledger.py <ledger.json>
    python scripts/check_processing_ledger.py --binding
    python scripts/check_processing_ledger.py --self-test

``--binding`` prints the pin and the three drift checks without needing a
ledger.  ``--self-test`` runs the gate against the pinned producer fixture,
which is the cheapest end-to-end proof that the binding is intact.

Scope: Package 2B.2A stops at consumption.  This script writes nothing,
promotes no pointer and touches no object store — atomic publication,
immutable release identity, conditional writes, tombstones and zero-alert
dates are Package 2B.2B.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.publication import ledger_binding  # noqa: E402
from src.publication.ledger_gate import (  # noqa: E402
    LedgerRejected,
    check_processing_ledger,
)


def print_binding() -> int:
    pin = ledger_binding.load_pin()
    producer = pin["producer"]
    print(
        f"consumed contract : {pin['consumed_contract']} "
        f"{pin['declared_contract_version']} (family {pin['contract_major']})"
    )
    print(f"producer          : {producer['repository']} {producer['ref']}")
    print(f"producer commit   : {producer['commit']}")
    failures = 0

    print("\npinned bytes in this working tree:")
    for check in ledger_binding.verify_pinned_artifacts():
        failures += 0 if check.ok else 1
        print(f"  {check.status:<13} {check.path}")

    print("\nagreement with the pinned producer commit:")
    for check in ledger_binding.verify_producer_blobs():
        if check.status == "mismatch":
            failures += 1
        print(f"  {check.status:<13} {check.path}")

    print(f"\ndrift against the producer ref {producer['ref']!r}:")
    for check in ledger_binding.check_ref_drift():
        if check.status == "mismatch":
            failures += 1
        print(f"  {check.status:<13} {check.path}")

    if failures:
        print(
            f"\n::error::{failures} binding check(s) failed — re-review "
            "docs/contracts/phase2b/LEDGER_CONTRACT_BINDING_V1.md before "
            "publishing from any ledger"
        )
        return 1
    print("\nbinding intact")
    return 0


def check_path(path: Path) -> int:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"::error::{path} is not readable JSON: {exc}")
        return 1
    try:
        acceptance = check_processing_ledger(document)
    except LedgerRejected as exc:
        print(
            f"::error::{path} is not an acceptable publication input — "
            f"{len(exc.rejections)} finding(s)"
        )
        for rejection in exc.rejections:
            print(f"  {rejection}")
        return 1
    except ledger_binding.ContractBindingError as exc:
        print(f"::error::the consumed contract could not be established: {exc}")
        return 1

    print(f"{path}: accepted as a publication input")
    print(f"  contract        : processing-ledger {acceptance.contract_version}")
    print(f"  ledger          : {acceptance.ledger_id}")
    print(f"  run manifest    : {acceptance.run_manifest_id}")
    print(f"  monitoring      : {acceptance.monitoring_extent_id}")
    print(f"  algorithm       : {acceptance.algorithm_version}")
    print(f"  document sha256 : {acceptance.document_sha256}")
    print(
        f"  accounted for   : {acceptance.expected_acquisition_count} "
        f"expected acquisition(s) over {len(acceptance.dates)} terminal date(s)"
    )
    for date in acceptance.dates:
        present = {
            status: count for status, count in date.status_counts.items() if count
        }
        print(
            f"    {date.observed_on}  "
            f"{len(date.expected_acquisition_ids)} acquisition(s), "
            f"{len(date.observation_ids)} observation(s), "
            f"terminal by {date.max_terminal_at}, "
            f"{present}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "ledger", nargs="?", type=Path, help="path to a processing-ledger-v3 document"
    )
    parser.add_argument(
        "--binding",
        action="store_true",
        help="print the contract pin and its drift checks, then exit",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run the gate against the pinned producer fixture",
    )
    args = parser.parse_args(argv)

    if args.binding:
        return print_binding()
    if args.self_test:
        return check_path(ledger_binding.acceptance_fixture_path())
    if args.ledger is None:
        parser.error("give a ledger path, --binding or --self-test")
    return check_path(args.ledger)


if __name__ == "__main__":
    raise SystemExit(main())
