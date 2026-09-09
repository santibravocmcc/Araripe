#!/usr/bin/env python3
"""Phase 3: write the replay freeze, the post-cutoff queue, and the photograph.

    python scripts/snapshot_replay_freeze.py --site-root ../site
    python scripts/snapshot_replay_freeze.py --site-root ../site --r2-read

Read-only. Nothing here writes to R2, to git, or to the site; the only writes
are the three local documents named by ``--out-dir``, plus the freeze at
``config/phase3_replay_freeze_v1.json`` when ``--write-freeze`` is passed.

Why this is not a fourth audit tool
-----------------------------------
``scripts/audit_baselines.py``, ``scripts/audit_timeseries.py`` and
``scripts/r2_state.py`` already exist and were read before this was written
(the briefing asks for exactly that). This does not replace them:

* the time-series half **calls** ``src.timeseries.audit.audit_legacy_database``,
  which is what ``audit_timeseries.py`` calls;
* the baseline half deliberately does **not** call
  ``compare_local_files_to_manifest``, because the v1 rasters are not local —
  production fetches them from R2 at run time — so it records each
  generation's manifest and inventory checksums instead, and separately says
  whether the rasters happened to be present and verified;
* the R2 half reuses the read-only list/head shape of
  ``audit_baselines._read_r2_inventory`` rather than importing it, because
  that module imports ``config.settings`` and would drag the repository
  ``.env`` into a tool whose whole point is to need no credential.

Without ``--r2-read`` the alert inventory is recorded as **unmeasured, with
the reason**, which is the honest state on a machine that holds no R2 key —
and holding none is what the production freeze means.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.detection.baseline_selection import BASELINE_GENERATIONS
from src.replay import cutoff as cutoff_module
from src.replay import freeze as freeze_module
from src.replay import snapshot as snapshot_module

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = Path("docs/implementation")
ALERT_PREFIX = "alerts/"


def _read_r2_alerts(bucket: str, endpoint: str, prefix: str = ALERT_PREFIX) -> dict:
    """Read-only list metadata for the published alert objects.

    List and head only. No object body is downloaded, nothing is written, and
    no key is echoed. Credentials come from the environment the operator
    already has, exactly as ``audit_baselines.py --r2-read`` takes them.
    """

    import boto3

    access = os.environ.get("R2_ACCESS_KEY")
    secret = os.environ.get("R2_SECRET_KEY")
    if not (endpoint and access and secret):
        raise click.ClickException(
            "R2 credentials not set: R2_ENDPOINT_URL, R2_ACCESS_KEY, R2_SECRET_KEY"
        )
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        region_name="auto",
    )
    objects = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            objects.append(
                {
                    "key": obj["Key"],
                    "bytes": obj["Size"],
                    "etag": obj["ETag"].strip('"'),
                    "last_modified": obj["LastModified"].isoformat(),
                }
            )
    objects.sort(key=lambda item: item["key"])
    from src.detection.identity import canonical_sha256

    return {
        "bucket": bucket,
        "prefix": prefix,
        "object_count": len(objects),
        "total_bytes": sum(item["bytes"] for item in objects),
        "inventory_sha256": canonical_sha256(objects),
        "keys_first": [item["key"] for item in objects[:3]],
        "keys_last": [item["key"] for item in objects[-3:]],
        "listing_is_etag_not_sha256": (
            "R2 ETags are opaque; a multipart upload's ETag is not the "
            "object's MD5, let alone its SHA-256, so this inventory seals "
            "sizes and ETags and never claims content digests"
        ),
    }


@click.command()
@click.option(
    "--site-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=None,
    help="Path to the sibling site checkout (e.g. ../site). Omitted subjects "
    "are recorded as unmeasured with their reason.",
)
@click.option(
    "--out-dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=DEFAULT_OUT_DIR,
    show_default=True,
)
@click.option(
    "--stamp",
    default=None,
    help="Date stamp for the output filenames (default: the frozen release's "
    "latest_observation, so the filenames carry a measured date and not the "
    "machine clock).",
)
@click.option(
    "--r2-read",
    is_flag=True,
    help="Also take a read-only list of the published alert objects.",
)
@click.option("--bucket", default="araripe-cogs", show_default=True)
@click.option(
    "--write-freeze",
    is_flag=True,
    help="Write config/phase3_replay_freeze_v1.json as well.",
)
def main(
    site_root: Path | None,
    out_dir: Path,
    stamp: str | None,
    r2_read: bool,
    bucket: str,
    write_freeze: bool,
) -> None:
    """Produce the three Phase 3 documents from the current tree."""

    freeze_document = freeze_module.build_freeze()
    freeze_module.validate_freeze(freeze_document)

    provisional = cutoff_module.read_provisional_cutoff()
    db_path = REPO_ROOT / "data" / "timeseries" / "timeseries.db"
    observed = snapshot_module.observed_dates_from_timeseries(db_path)
    queue_document = cutoff_module.build_queue(
        cutoff=provisional.date,
        observed_dates=observed,
        observation_source=(
            "data/timeseries/timeseries.db: distinct date in regional_stats "
            "united with alert_stats"
        ),
        cutoff_is_provisional=True,
        cutoff_evidence=provisional.to_dict(),
    )
    cutoff_module.validate_queue(queue_document)

    generations = [
        {
            "version": generation.version,
            "manifest_path": generation.manifest_path,
            "directory": generation.directory,
            "key_prefix": generation.key_prefix,
        }
        for _, generation in sorted(BASELINE_GENERATIONS.items())
    ]
    alerts = (
        _read_r2_alerts(bucket, os.environ.get("R2_ENDPOINT_URL", ""))
        if r2_read
        else None
    )
    snapshot_document = snapshot_module.build_snapshot(
        backend_root=REPO_ROOT,
        site_root=site_root,
        baseline_generations=generations,
        r2_alerts=alerts,
    )
    snapshot_module.validate_snapshot(snapshot_document)

    stamp = stamp or freeze_document["release"]["latest_observation"]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, document in (
        (f"PHASE_3_SNAPSHOT_{stamp}.json", snapshot_document),
        (f"PHASE_3_POST_CUTOFF_QUEUE_{stamp}.json", queue_document),
    ):
        path = out_dir / name
        path.write_text(
            json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        written.append(path)
    if write_freeze:
        written.append(freeze_module.write_freeze(freeze_document))

    unmeasured = snapshot_module.unmeasured_subjects(snapshot_document)
    drift = snapshot_module.release_drift(
        snapshot_document, frozen_release=freeze_document["release"]
    )
    for path in written:
        click.echo(f"wrote {path}")
    click.echo(f"freeze_sha256   {freeze_document['freeze_sha256']}")
    click.echo(f"queue_sha256    {queue_document['queue_sha256']}")
    click.echo(f"snapshot_sha256 {snapshot_document['snapshot_sha256']}")
    click.echo(
        f"cutoff (provisional) {queue_document['cutoff']['date']}: "
        f"{queue_document['in_batch']['count']} date(s) in the batch, "
        f"{queue_document['queued']['count']} queued"
    )
    click.echo(
        "unmeasured subjects: " + (", ".join(unmeasured) if unmeasured else "none")
    )
    if drift["drifted"]:
        click.echo(
            "NOTE: the live time-series database differs from the frozen "
            "photograph — expected, the blue lane keeps publishing"
        )


if __name__ == "__main__":
    main()
