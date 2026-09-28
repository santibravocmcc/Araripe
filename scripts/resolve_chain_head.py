#!/usr/bin/env python3
"""Find the head of the green state chain and the window that continues it.

    python scripts/resolve_chain_head.py --today "$(date -u +%F)"

prints the head and the window and, inside Actions, emits ``from_run``,
``start``, ``end`` and ``nothing_to_do`` — or refuses and exits 1.  It reads
run documents and never the ~1 GB state: ``scripts/fetch_green_state.py`` does
that afterwards, with the same checks it applies to a hand-named ``from_run``.

``docs/implementation/PHASE_6H_2026-09-28.md`` is the decision:

* **the head is derived** (§1): the one leaf of the tree the ``predecessor``
  fields draw from ``state_chain.CHAIN_ROOT``; a fork, an invalid ``run.json``
  or a link that does not match its parent's declared state refuses;
* **the window** (§3): from the day after the head's last covered date to
  ``today - SETTLE_DAYS``, exclusive, at most ``WINDOW_MAX_DAYS``.  A head that
  already covers everything the settle rule allows is *nothing to do* — exit 0,
  no window — not a failure.

``--today`` is an argument, not the clock, so the rule is testable; the lane
passes the runner's UTC date.

The identity, and what it can do from here
------------------------------------------
``R2_STAGING_*``, opened through ``ReadOnlyStore`` and **without** the local
profile fallback, exactly as ``fetch_green_state.py``: a lane step, not a new
local caller of the key.  It never imports ``config``.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.publication import conditional_store as cs  # noqa: E402
from src.publication import state_chain as sc  # noqa: E402
from src.publication.findings import Rejected  # noqa: E402
from src.publication.ledger_binding import ContractBindingError  # noqa: E402
from src.publication.run_inputs import ReadOnlyStore  # noqa: E402

ACCESS_KEY_VAR = "R2_STAGING_ACCESS_KEY_ID"
SECRET_KEY_VAR = "R2_STAGING_SECRET_ACCESS_KEY"
BUCKET_VAR = "R2_STAGING_BUCKET"
ENDPOINT_VAR = "R2_ENDPOINT_URL"


def _annotate(message: str) -> str:
    return f"::error::{message}" if os.environ.get("GITHUB_ACTIONS") else f"erro: {message}"


def build_reader() -> ReadOnlyStore:
    """The candidate identity, unable to write through this object."""

    bucket = os.environ.get(BUCKET_VAR, cs.STAGING_BUCKET)
    client = cs.build_client(
        bucket,
        os.environ.get(ENDPOINT_VAR),
        {
            "access_key_id": os.environ.get(ACCESS_KEY_VAR, ""),
            "secret_access_key": os.environ.get(SECRET_KEY_VAR, ""),
            "region": os.environ.get("AWS_REGION", "auto"),
        },
    )
    return ReadOnlyStore(client, bucket)


def emit(outputs: dict[str, str]) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            for name, value in outputs.items():
                handle.write(f"{name}={value}\n")


def resolve(store, today: str) -> tuple[sc.ChainHead, sc.Predecessor, sc.Window | None]:
    head = sc.resolve_head(store)
    predecessor = sc.read_predecessor(store, head.run_id)
    return head, predecessor, sc.automatic_window(predecessor, today)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--today", required=True, help="the UTC date of the run, YYYY-MM-DD")
    args = parser.parse_args(argv)

    try:
        head, predecessor, window = resolve(build_reader(), args.today)
    except (Rejected, ContractBindingError, cs.ObjectStoreError, RuntimeError, ValueError) as exc:
        print(_annotate(f"{type(exc).__name__}: {exc}"), file=sys.stderr)
        for finding in getattr(exc, "findings", ()):
            print(f"  {finding}", file=sys.stderr)
        return 1

    print(f"chain       : {' -> '.join(head.path)}")
    print(f"head        : {head.run_id}, covers to {predecessor.last_observed_on}")
    print(f"not on it   : {len(head.outside)} run(s); without run.json: "
          f"{len(head.incomplete)} prefix(es)")
    if window is None:
        print(f"window      : none — today is {args.today} and the head already covers "
              f"everything before {args.today} minus {sc.SETTLE_DAYS} day(s)")
        emit({"nothing_to_do": "true", "from_run": head.run_id, "start": "", "end": ""})
    else:
        print(f"window      : {window.start} .. {window.end} (exclusive), {window.days} "
              f"day(s){', at the ceiling' if window.full else ''}")
        emit({"nothing_to_do": "false", "from_run": head.run_id,
              "start": window.start, "end": window.end})
    print("read-only — nothing was written to the bucket and no pointer was read")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
