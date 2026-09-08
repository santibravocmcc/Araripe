#!/usr/bin/env python3
"""Deposit one green run prefix from a real detection run's outputs — lane 2.

    # nothing is read but local files; no credential, no network, no store:
    python scripts/assemble_green_run.py plan \
        --run <run-id> --ledger data/ledger.json

    # the same assembly, written to runs/<run-id>/ in araripe-v2-staging:
    python scripts/assemble_green_run.py apply \
        --run <run-id> --ledger data/ledger.json

Exit gate P2B.  ``src/publication/run_assembler.py`` (``bf2c2cf``) knows how to
turn a ledger and a date's features into a run prefix, and
``scripts/stage_green_run.py`` and ``scripts/publish_green_release.py`` know how
to read one, publish it and move the pointer.  Between them sat the gap Package
2B.2C named and this file closes: **nothing deposited** ``runs/<run-id>/``.  The
prefix was assembled by hand for the 2026-09-07 proofs, and the assembler was
merged as a library that only its own test imported.

This is the operator's end of that library, and its whole job is to answer one
question the library deliberately leaves open — *where do the features come
from* — by reading the files the detection run actually wrote.

Which lane this belongs to, and what it therefore may not do
------------------------------------------------------------
Lane 2, ``araripe-green-candidate`` (``docs/operations/GREEN_CONCURRENCY_LANES.md``):

    "Writes: immutable per-run prefixes only (`green-isolation-proof/run-<id>/`,
     later `runs/<run-id>/…`); no deletes, no overwrites, no pointers."

So it reads ``R2_STAGING_*`` — the bucket-scoped candidate identity — and never
names the promotion identity, exactly as ``stage_green_run.py`` does in the
other direction.  It writes only under ``runs/<run-id>/``, only with
``put_if_absent``, and no pointer read or write is expressible from it.
``tests/test_assemble_green_run.py`` pins each of those from this file.

It does not produce a ledger
----------------------------
``PACKAGE_2B_GATE_PROMPT.md`` §4: *"O montador da rodada usa o ledger que a
detecção produz; ele não escreve um."*  ``--ledger`` is required and is read as
bytes the producer sealed.  The Package 2A.6 producer that emits it is
``src/detection/ledger_v3.py`` on ``claude/phase2a6d-mapbiomas``; **no producer
on `main` writes one**, which is measured in
``docs/implementation/PHASE_2B_GATE_2026-09-08.md`` §4 and is the one thing this
entry point cannot supply for itself.

Why it must not import ``config.settings``
------------------------------------------
Because that module calls ``load_dotenv(ROOT_DIR / ".env")`` at import time
(``config/settings.py``:13-18), and the repository ``.env`` holds the
**production** R2 credentials.  Importing it to reach ``ALERTS_DIR`` would put
those values into the environment of a green lane whose entire premise is that
it cannot reach production — the same defect measured on the site side, where
``wrangler dev`` injected five credential bindings from the repository ``.env``.
No green script imports it (``stage_green_run.py``, ``publish_green_release.py``,
``check_site_artifact.py``, ``plan_retention.py``), and
``test_no_green_script_imports_the_dotenv_loader`` now keeps it that way.

The paths below are therefore the producer's own, cited and pinned by a test
that reads the producer's source rather than trusting this comment.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.publication import conditional_store as cs  # noqa: E402
from src.publication import run_assembler as ra  # noqa: E402
from src.publication import run_inputs as ri  # noqa: E402
from src.publication.findings import Finding, Rejected  # noqa: E402
from src.publication.green_release import ReleaseBuildError, sha256_bytes  # noqa: E402
from src.publication.ledger_binding import ContractBindingError  # noqa: E402

#: The candidate identity of lane 2.  The promotion identity is deliberately
#: not readable from this file — see the module docstring.
ACCESS_KEY_VAR = "R2_STAGING_ACCESS_KEY_ID"
SECRET_KEY_VAR = "R2_STAGING_SECRET_ACCESS_KEY"
BUCKET_VAR = "R2_STAGING_BUCKET"
ENDPOINT_VAR = "R2_ENDPOINT_URL"

#: Where ``src/detection/alerts.py::save_alerts`` writes one date's alerts,
#: relative to the alerts directory.  Copied from the producer rather than
#: guessed, and ``test_the_alert_filename_is_the_producers_own`` reads the
#: producer's source to keep the two from drifting: a renamed file here would
#: make every date look absent, and an absent date is a *refusal*, so the
#: failure would at least be loud — but it would be loud for the wrong reason.
ALERT_FILENAME = "alerts_{observed_on}.geojson"

#: The alerts directory and the persistence state file, as
#: ``config/settings.py`` and ``scripts/run_detection.py`` compute them:
#: ``ALERTS_DIR = DATA_DIR / "alerts"`` and
#: ``state_path = ALERTS_DIR.parent / "persistence_state.geojson"``.
DEFAULT_ALERTS_DIR = Path("data/alerts")
PERSISTENCE_STATE_NAME = "persistence_state.geojson"


class DetectionOutputRejected(Rejected):
    """The detection run's outputs are not an assemblable set."""

    subject = "detection output"


def _annotate(message: str) -> str:
    return f"::error::{message}" if os.environ.get("GITHUB_ACTIONS") else f"erro: {message}"


def alert_path(alerts_dir: Path, observed_on: str) -> Path:
    return alerts_dir / ALERT_FILENAME.format(observed_on=observed_on)


def read_feature_collection(path: Path) -> list[dict]:
    """One date's features, or a refusal naming the file.

    A GeoJSON file the detection wrote is trusted for its *contents* and for
    nothing else: the shape is checked here so a truncated or half-written file
    becomes a refusal instead of a release with a silently short object.
    """

    try:
        document = json.loads(path.read_bytes())
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise DetectionOutputRejected(
            [Finding("alert_file_unreadable", f"{path}: {exc}", str(path))]
        ) from exc
    if not isinstance(document, dict) or document.get("type") != "FeatureCollection":
        raise DetectionOutputRejected(
            [
                Finding(
                    "alert_file_not_a_feature_collection",
                    f"{path} is not a GeoJSON FeatureCollection",
                    str(path),
                )
            ]
        )
    features = document.get("features")
    if not isinstance(features, list):
        raise DetectionOutputRejected(
            [
                Finding(
                    "alert_file_without_features",
                    f"{path} has no 'features' array",
                    str(path),
                )
            ]
        )
    return features


def collect_features(
    alerts_dir: Path, states: dict[str, str]
) -> dict[str, list[dict]]:
    """``{observed_on: features}`` for the ledger's dates, from what is on disk.

    **The ledger decides which dates exist**, so this walks ``states`` and not
    the directory — with one deliberate exception below.  Walking the directory
    would let a stray file add a date, and let a missing file quietly remove
    one, which is the difference between a release that refuses and a release
    that is wrong.

    Three translations, and each one is a measurement rather than a convention:

    * **an ``alerts`` date with no file is left absent.**  The assembler then
      raises ``date_without_detection_output``.  Supplying ``[]`` here would
      turn a detection that failed to write into a published claim that the day
      was quiet;
    * **a ``zero_alerts`` date with no file becomes ``[]``.**  Measured from
      the producer: ``scripts/run_detection.py`` adds a date to
      ``alerts_by_date`` only inside the branch that found alerts, and logs
      *"Scene {}: no alerts"* otherwise — so an observed date with zero alerts
      writes **no file at all**.  The release contract requires it to publish
      two empty collections as *a positive observation of absence*, and the
      ledger is the authority that says anyone looked;
    * **a ``zero_alerts`` date whose file has features is a refusal.**  The
      ledger says every acquisition reported nothing and the detection output
      says otherwise; one of the two inputs is wrong and publishing either
      would make the release contradict the ledger it ships.  The assembler
      does not catch this — it checks the mirror case, features on an
      ``no_valid_coverage`` date — so the check belongs here, where both
      inputs are in hand.

    A date on disk that the ledger does **not** reconcile is **ignored and
    reported**, not refused — and the first draft of this function got that
    wrong in a way worth recording, because it is the workspace's own standing
    trap: *never assert an invariant the producer does not promise*.  Passing
    such a file through makes the assembler raise
    ``features_for_an_unreconciled_date``, which reads like a useful
    cross-check until you measure who fills the directory:

    * in CI, ``detect_gee.yml`` fetches only the persistence state, so
      ``data/alerts/`` holds exactly the dates that run wrote — and the check
      would pass;
    * locally and in the site build, ``fetch_alerts_from_r2.py`` with no
      ``--latest`` pulls **the whole archive** into the same directory
      (``--out`` defaults to ``ALERTS_DIR``) — and the check would refuse every
      real run, because 40 historical dates are present and one ledger
      reconciles three.

    So "every file in the alerts directory belongs to this run" is a property
    of one of two documented usages, not a promise of the producer, and the
    entry point cannot tell which one filled the directory.  Encoding it would
    be the 2026-09-07 outage again in a new place.  Ignoring is what is sound;
    printing the count is what keeps it visible.
    """

    features: dict[str, list[dict]] = {}
    findings: list[Finding] = []

    for observed_on, state in sorted(states.items()):
        path = alert_path(alerts_dir, observed_on)
        present = path.is_file()

        if state == ra.UNOBSERVED_STATE:
            # Nothing was observed. The assembler refuses features here, so
            # pass the file through if the detection wrote one.
            if present:
                features[observed_on] = read_feature_collection(path)
            continue

        if state == "zero_alerts":
            if not present:
                features[observed_on] = []
                continue
            supplied = read_feature_collection(path)
            if supplied:
                findings.append(
                    Finding(
                        "zero_alert_date_with_detection_features",
                        f"the ledger reconciles {observed_on} as 'zero_alerts' — "
                        f"every acquisition reported no observation — and "
                        f"{path} holds {len(supplied)} feature(s). Publishing "
                        "either version would make the release contradict the "
                        "ledger it ships.",
                        str(path),
                    )
                )
                continue
            features[observed_on] = supplied
            continue

        # 'alerts', or a state the assembler will reject as unknown: hand over
        # only what the detection actually wrote.
        if present:
            features[observed_on] = read_feature_collection(path)

    if findings:
        raise DetectionOutputRejected(findings)
    return features


def ignored_dates(alerts_dir: Path, states: dict[str, str]) -> list[str]:
    """Dates present on disk that this run's ledger does not reconcile.

    Reported, never refused — see ``collect_features``.  An operator running
    against a full local archive should see "37 ignored" and recognise it as
    normal; one who expected a three-date run and sees zero ignored has
    learned something too.
    """

    found = {
        path.stem[len("alerts_") :]
        for path in alerts_dir.glob("alerts_*.geojson")
        if path.is_file()
    }
    return sorted(found - set(states))


def read_persistence_state(path: Path) -> tuple[str, int]:
    """``(sha256, bytes)`` of the run's persistence state, from the file.

    Computed, never asserted.  The release manifest carries this pair as the
    state watermark's evidence, and a hand-typed digest is a claim about bytes
    nobody read.
    """

    try:
        body = path.read_bytes()
    except OSError as exc:
        raise DetectionOutputRejected(
            [
                Finding(
                    "persistence_state_unreadable",
                    f"{path}: {exc}. The persistence state is what a release's "
                    "watermark is evidence for; a run without it is not "
                    "publishable.",
                    str(path),
                )
            ]
        ) from exc
    return sha256_bytes(body), len(body)


def build_candidate_store() -> cs.ConditionalStore:
    """A candidate-identity store, refusing anything but the staging bucket.

    ``assert_staging_target`` runs inside ``build_client`` before a credential
    is read, so ``araripe-cogs`` is refused by name rather than by permission.
    """

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


def emit_output(name: str, value: str) -> None:
    """Hand one value to the next job, when running inside Actions."""

    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def assemble(args) -> ra.AssembledRun:
    """The whole read side: ledger, features, state — then the assembler."""

    ri.validate_run_id(args.run)
    ledger_document = json.loads(args.ledger.read_text(encoding="utf-8"))

    # The Package 2B.2A gate decides which dates exist and in what state, from
    # the producer's own bytes. `dates_by_state` is the assembler's function,
    # not a second reading of the ledger, so the entry point and the run it
    # assembles cannot disagree about what a date is.
    acceptance = ra.check_processing_ledger(ledger_document)
    states = ra.dates_by_state(acceptance)

    features = collect_features(args.alerts_dir, states)
    state_sha, state_bytes = read_persistence_state(args.state)

    return ra.assemble_run(
        args.run,
        ledger_document,
        features,
        persistence_state_sha256=state_sha,
        persistence_state_bytes=state_bytes,
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="mode", required=True)
    for mode, help_text in (
        ("plan", "assemble and print, touching no object store"),
        ("apply", "assemble, then write runs/<run-id>/ once"),
    ):
        part = sub.add_parser(mode, help=help_text)
        part.add_argument("--run", required=True, help="the run id; one path segment")
        part.add_argument(
            "--ledger",
            required=True,
            type=Path,
            help="the processing ledger this run produced — an INPUT; this "
            "script never writes one",
        )
        part.add_argument(
            "--alerts-dir",
            type=Path,
            default=DEFAULT_ALERTS_DIR,
            help=f"where save_alerts wrote {ALERT_FILENAME.format(observed_on='<date>')} "
            f"(default: {DEFAULT_ALERTS_DIR})",
        )
        part.add_argument(
            "--state",
            type=Path,
            default=None,
            help=f"the persistence state (default: <alerts-dir>/../{PERSISTENCE_STATE_NAME})",
        )
        part.add_argument(
            "--json", action="store_true", help="print the run manifest instead"
        )
    args = parser.parse_args(argv)
    if args.state is None:
        args.state = args.alerts_dir.parent / PERSISTENCE_STATE_NAME

    try:
        run = assemble(args)
    except (Rejected, ReleaseBuildError, ContractBindingError, ValueError) as exc:
        print(_annotate(f"{type(exc).__name__}: {exc}"), file=sys.stderr)
        for finding in getattr(exc, "findings", ()):
            print(f"  {finding}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(run.document, indent=2, sort_keys=True))
    else:
        print(ra.describe(run))
        skipped = ignored_dates(args.alerts_dir, ra.dates_by_state(run.acceptance))
        print(
            f"ignored     : {len(skipped)} date(s) on disk this ledger does not "
            "reconcile" + (f" ({skipped[0]} … {skipped[-1]})" if skipped else "")
        )

    if args.mode == "plan":
        print("\nplan — nothing was written, no credential was read")
        emit_output("run_id", run.run_id)
        return 0

    try:
        store = build_candidate_store()
        written = ra.upload(store, run)
    except (cs.ObjectStoreError, RuntimeError) as exc:
        print(_annotate(f"{type(exc).__name__}: {exc}"), file=sys.stderr)
        return 1

    print()
    for line in written:
        print(line)
    print(f"\n{run.prefix} deposited — no pointer was read or written")
    emit_output("run_id", run.run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
