#!/usr/bin/env python3
"""Publish and promote one immutable green release (Package 2B.2B).

Roadmap Package 2B.2: publish every artifact under an immutable
release/staging identity, validate before promoting the green staging
pointer, use conditional writes so an older or racing job cannot replace a
newer release, keep the last complete release live when a run is partial, and
represent zero-alert dates and stale objects explicitly.

    # no credential, no object access, no network:
    python scripts/publish_green_release.py plan \
        --ledger data/ledger.json \
        --state-sha256 <sha> --state-bytes <n> \
        --object alerts/2026-04-07/a.geojson=out/a.geojson

    # writes objects, verifies them, then moves the pointer:
    python scripts/publish_green_release.py apply --ledger … --object …

    # the same three steps, from a run prefix in the staging bucket rather
    # than from local files — the operational path, with no git in it:
    python scripts/publish_green_release.py publish --run <run-id>

    # deliberate backwards move, to a release that is still complete:
    python scripts/publish_green_release.py rollback --to rel-g1-…

    # read the live pointer:
    python scripts/publish_green_release.py status

``plan`` is the whole validation chain and touches no object store, so it is
the mode that runs anywhere — including in the promotion lane on a branch,
where no credential exists.

Boundaries this script does not cross
-------------------------------------
* it writes only to ``araripe-v2-staging`` at the approved account endpoint,
  and refuses ``araripe-cogs`` by name before a credential is read
  (``conditional_store.assert_staging_target``);
* it never deletes and never writes without a precondition;
* it does not touch ``data/timeseries/RELEASE.json``.  That signal is blue and
  the site validates it (``site/scripts/check_backend_release.py`` accepts
  only ``araripe.timeseries.release/1``); the green release is built beside it
  and the two meet at the Phase 6 cutover, not before.

``publish`` is the Package 2B.2C entry point: it reads one green run from
``runs/<run-id>/`` in the staging bucket — the immutable per-run prefix lane 2
writes — and runs the same publish → verify → promote sequence ``apply``
runs from local files.  Nothing on that path touches git, which is the
roadmap bullet it exists for (*keep operational data publication automatic
without PRs or manual merges*).  Whether a run prefix is publishable at all is
answered first, with the smaller lane-2 identity, by
``scripts/stage_green_run.py``.

``apply``, ``publish``, ``rollback`` and ``status`` need the **promotion** identity, which
is deliberately not the green candidate identity and is not provisioned yet.
Without it they stop and name the missing capability instead of substituting a
broader credential.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.publication import atomic_publish as ap  # noqa: E402
from src.publication import conditional_store as cs  # noqa: E402
from src.publication.findings import Rejected  # noqa: E402
from src.publication.green_release import (  # noqa: E402
    POINTER_KEY,
    ProductObject,
    ReleaseBuildError,
    build_release,
    check_green_release,
    object_key,
)
from src.publication.ledger_binding import ContractBindingError  # noqa: E402
from src.publication.ledger_gate import check_processing_ledger  # noqa: E402
from src.publication import run_inputs as ri  # noqa: E402

#: The promotion identity is separate from the candidate identity by design
#: (``docs/operations/GREEN_CONCURRENCY_LANES.md`` lane 3).
ACCESS_KEY_VAR = "R2_PROMOTION_ACCESS_KEY_ID"
SECRET_KEY_VAR = "R2_PROMOTION_SECRET_ACCESS_KEY"
BUCKET_VAR = "R2_STAGING_BUCKET"
ENDPOINT_VAR = "R2_ENDPOINT_URL"


def _annotate(message: str) -> str:
    return f"::error::{message}" if os.environ.get("GITHUB_ACTIONS") else f"erro: {message}"


def parse_object(spec: str) -> tuple[str, Path]:
    logical, sep, local = spec.partition("=")
    if not sep or not logical or not local:
        raise SystemExit(
            _annotate(f"--object expects logical/path=local/file, got {spec!r}")
        )
    return logical, Path(local)


def load_inputs(args) -> tuple[dict, dict, list[ProductObject]]:
    ledger_document = json.loads(args.ledger.read_text(encoding="utf-8"))
    acceptance = check_processing_ledger(ledger_document)
    sealed = _sealed_artifacts(ledger_document)

    objects: list[ProductObject] = []
    for spec in args.artifact or []:
        logical, local = parse_object(spec)
        body = local.read_bytes()
        observed_on = args.date or _date_from(logical, acceptance)
        objects.append(
            ProductObject(
                path=logical,
                body=body,
                content_type=args.content_type or "application/geo+json",
                observed_on=observed_on,
                acquisition_id=_sealed_acquisition(body, observed_on, local, sealed),
            )
        )
    for spec in args.product or []:
        logical, local = parse_object(spec)
        objects.append(
            ProductObject(
                path=logical,
                body=local.read_bytes(),
                content_type=args.content_type or "application/json",
                observed_on=args.date or _date_from(logical, acceptance),
            )
        )

    if args.require_sealed_artifacts:
        published = {
            item.acquisition_id for item in objects if item.acquisition_id is not None
        }
        unpublished = sorted(set(sealed.values()) - published)
        if unpublished:
            raise SystemExit(
                _annotate(
                    f"{len(unpublished)} acquisition(s) seal an artifact checksum "
                    "that no --artifact publishes: " + ", ".join(unpublished)
                )
            )

    release = build_release(
        acceptance,
        ledger_document,
        objects,
        persistence_state_sha256=args.state_sha256,
        persistence_state_bytes=args.state_bytes,
    )
    check_green_release(release, ledger_document)
    return release, ledger_document, objects


def _sealed_artifacts(ledger_document: dict) -> dict[tuple[str, str], str]:
    """``{(observed_on, artifact_sha256): acquisition_id}`` for sealed rows only.

    Built from the two statuses the contract says seal a checksum.  The five
    rejection and failure statuses leave ``artifact_sha256`` unconstrained
    (``LEDGER_CONTRACT_BINDING_V1.md`` §5, non-requirement 2), so their value
    is never read — not even to compare against.
    """

    from src.publication import ledger_binding

    sealing = ledger_binding.pinned_status_semantics()["artifact_sealing"]
    return {
        (row["observed_on"], row["output"]["artifact_sha256"]): row["acquisition_id"]
        for row in ledger_document["terminal_rows"]
        if row["status"] in sealing
    }


def _date_from(logical: str, acceptance) -> str:
    """Infer the UTC date from the logical path, or refuse to guess."""

    candidates = [date for date in acceptance.observed_dates if date in logical]
    if len(candidates) == 1:
        return candidates[0]
    raise SystemExit(
        _annotate(
            f"cannot tell which UTC date {logical!r} belongs to; pass --date "
            f"(the ledger reconciles {', '.join(acceptance.observed_dates)})"
        )
    )


def _sealed_acquisition(
    body: bytes, observed_on: str, local: Path, sealed: dict[tuple[str, str], str]
) -> str:
    """The acquisition whose sealed checksum these bytes are, or a refusal.

    The join is the checksum, because a checksum is what the ledger actually
    seals — a filename is not evidence of anything.  A mismatch is fatal
    rather than a quiet downgrade to ``date_product``: the operator stated
    that this file *is* the sealed artifact, and if it is not, either the file
    is wrong or the ledger is, and neither is resolved by relabelling it.
    """

    import hashlib

    digest = hashlib.sha256(body).hexdigest()
    acquisition_id = sealed.get((observed_on, digest))
    if acquisition_id is None:
        raise SystemExit(
            _annotate(
                f"{local} hashes to {digest[:12]}… which no acquisition on "
                f"{observed_on} seals. Publish it with --product if it is a "
                "derived date product; otherwise the artifact or the ledger is "
                "wrong."
            )
        )
    return acquisition_id


def print_plan(release: dict, ledger_document: dict, objects: list[ProductObject]) -> None:
    print(f"release          : {release['release_id']}")
    print(f"prefix           : {release['release_prefix']}")
    print(f"ledger           : {release['ledger']['ledger_id']}")
    print(f"run manifest     : {release['ledger']['run_manifest_id']}")
    print(f"contract         : {release['ledger']['contract_version']}")
    print(
        "coverage         : "
        f"{release['coverage']['first_observed_on']} … "
        f"{release['coverage']['last_observed_on']} "
        f"({len(release['coverage']['observed_dates'])} UTC date(s))"
    )
    print(
        "state watermark  : finalized through "
        f"{release['state_watermark']['finalized_through']}, persistence state "
        f"{release['state_watermark']['persistence_state_sha256'][:12]}… "
        f"({release['state_watermark']['persistence_state_bytes']} bytes)"
    )
    print("\ndates:")
    for entry in release["dates"]:
        print(
            f"  {entry['observed_on']}  {entry['alert_state']:<18} "
            f"coverage={entry['coverage']:<8} "
            f"usable={entry['usable_acquisition_count']}/"
            f"{entry['expected_acquisition_count']} "
            f"observations={entry['observation_count']} "
            f"objects={len(entry['paths'])}"
        )
    print("\nobjects (write-once, If-None-Match: *):")
    for item in release["objects"]:
        print(
            f"  {object_key(release['release_id'], item['path'])}  "
            f"{item['bytes']} bytes  {item['sha256'][:12]}…  "
            f"{item['provenance']['kind']}"
        )
    print(f"  {object_key(release['release_id'], 'ledger.json')}  "
          f"{release['ledger']['bytes']} bytes  "
          f"{release['ledger']['file_sha256'][:12]}…  ledger")
    sealed = _sealed_artifacts(ledger_document)
    published = sum(
        1 for item in release["objects"]
        if item["provenance"]["kind"] == "acquisition_artifact"
    )
    print(
        f"\nsealed artifacts : {published} of {len(sealed)} published"
        + ("" if published == len(sealed) else "  (see --require-sealed-artifacts)")
    )
    print(f"pointer          : {POINTER_KEY} (If-Match compare-and-swap)")


def build_store():
    bucket = os.environ.get(BUCKET_VAR, cs.STAGING_BUCKET)
    endpoint = os.environ.get(ENDPOINT_VAR)
    client = cs.build_client(
        bucket,
        endpoint,
        {
            "access_key_id": os.environ.get(ACCESS_KEY_VAR, ""),
            "secret_access_key": os.environ.get(SECRET_KEY_VAR, ""),
            "region": os.environ.get("AWS_REGION", "auto"),
        },
    )
    return cs.ConditionalStore(client, bucket)


def provenance() -> dict:
    env = os.environ
    run_id = env.get("GITHUB_RUN_ID")
    repo = env.get("GITHUB_REPOSITORY")
    server = env.get("GITHUB_SERVER_URL", "https://github.com")
    return {
        "workflow": env.get("GITHUB_WORKFLOW"),
        "run_id": run_id,
        "run_url": f"{server}/{repo}/actions/runs/{run_id}" if run_id and repo else None,
        "actor": env.get("GITHUB_ACTOR"),
    }


def cmd_plan(args) -> int:
    release, ledger_document, objects = load_inputs(args)
    if args.json:
        print(json.dumps(release, indent=2, sort_keys=True))
    else:
        print_plan(release, ledger_document, objects)
        print("\nplan only — no object store was contacted")
    return 0


def cmd_apply(args) -> int:
    release, ledger_document, objects = load_inputs(args)
    print_plan(release, ledger_document, objects)
    return _publish_verify_promote(
        release,
        ledger_document,
        {item.path: item.body for item in objects},
        build_store(),
    )


def _publish_verify_promote(release, ledger_document, bodies, store) -> int:
    """The three steps, in the one order that makes publication atomic.

    Objects and ledger first under the immutable prefix, the manifest last,
    every declared object re-read, and only then one compare-and-swap on the
    pointer.  A run that dies at any earlier step leaves the previous release
    live and complete.
    """

    report = ap.publish_release(store, release, ledger_document, bodies)
    print(
        f"\npublished: {len(report.created)} created, "
        f"{len(report.unchanged)} already identical"
    )
    ap.verify_release(store, release)
    print("verified : every declared object re-read and matched")
    result = ap.promote(
        store, release, ledger_document, now=datetime.now(timezone.utc),
        promoted_by=provenance(),
    )
    print(
        f"pointer  : {result.action} -> {result.release_id} at sequence "
        f"{result.sequence}, {result.tombstone_count} tombstone(s)"
    )
    return 0


def cmd_publish(args) -> int:
    """Publish one green run from its immutable prefix in the staging bucket.

    The run prefix is read with the same store that publishes, so the bytes
    validated are the bytes written.  ``load_run`` has already run the ledger
    gate and ``check_green_release`` before this returns, so nothing is
    written on the strength of an unvalidated input.
    """

    store = build_store()
    staged = ri.load_run(store, args.run)
    print(ri.describe(staged))
    return _publish_verify_promote(
        staged.release, staged.ledger_document, staged.bodies, store
    )


def cmd_rollback(args) -> int:
    store = build_store()
    result = ap.rollback(
        store, args.to, now=datetime.now(timezone.utc), promoted_by=provenance()
    )
    print(
        f"pointer  : {result.action} -> {result.release_id} at sequence "
        f"{result.sequence}, {result.tombstone_count} tombstone(s)"
    )
    return 0


def cmd_status(args) -> int:
    store = build_store()
    pointer, etag = ap.read_pointer(store)
    if pointer is None:
        print(f"{POINTER_KEY}: absent — no green release has been promoted")
        return 0
    print(json.dumps(pointer, indent=2, sort_keys=True))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def add_build_arguments(target):
        target.add_argument("--ledger", type=Path, required=True,
                            help="processing-ledger-v3 document to publish from")
        target.add_argument("--artifact", action="append", metavar="LOGICAL=LOCAL",
                            help="an object whose checksum the ledger seals for one "
                                 "acquisition; a mismatch is fatal. Repeatable.")
        target.add_argument("--product", action="append", metavar="LOGICAL=LOCAL",
                            help="a date-level product the ledger makes no claim "
                                 "about. Repeatable.")
        target.add_argument("--date", help="UTC date for every object, when the "
                                          "logical path does not name one")
        target.add_argument("--content-type", default=None,
                            help="override the per-kind default content type")
        target.add_argument("--require-sealed-artifacts", action="store_true",
                            help="refuse unless every acquisition that seals an "
                                 "artifact checksum has one published. Not the "
                                 "default: a release of date-level products only "
                                 "is a shape the contract permits.")
        target.add_argument("--state-sha256", required=True,
                            help="sha256 of the persistence state this run wrote")
        target.add_argument("--state-bytes", type=int, required=True)

    plan = sub.add_parser("plan", help="validate and print the plan; no object access")
    add_build_arguments(plan)
    plan.add_argument("--json", action="store_true", help="print the manifest instead")
    plan.set_defaults(handler=cmd_plan)

    apply_ = sub.add_parser("apply", help="publish, verify, then promote the pointer")
    add_build_arguments(apply_)
    apply_.set_defaults(handler=cmd_apply, json=False)

    published = sub.add_parser(
        "publish",
        help="publish, verify and promote one run from runs/<run-id>/ in the "
             "staging bucket — the operational path, with no git in it",
    )
    published.add_argument("--run", required=True, help="the run id to publish")
    published.set_defaults(handler=cmd_publish)

    back = sub.add_parser("rollback", help="point at an already published release")
    back.add_argument("--to", required=True, help="release id to point at")
    back.set_defaults(handler=cmd_rollback)

    status = sub.add_parser("status", help="print the live green pointer")
    status.set_defaults(handler=cmd_status)

    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (Rejected, ReleaseBuildError, ContractBindingError, cs.ObjectStoreError) as exc:
        return _fail(exc)
    except OSError as exc:
        return _fail(exc)


def _fail(exc: Exception) -> int:
    print(_annotate(f"{type(exc).__name__}: {exc}"), file=sys.stderr)
    findings = getattr(exc, "findings", ())
    for finding in findings:
        print(f"  {finding}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
