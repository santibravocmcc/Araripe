#!/usr/bin/env python3
"""Audit the complete 72-object baseline generation without rebuilding it."""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import BASELINES_DIR, R2_BUCKET_NAME
from src.detection.baseline_manifest import (
    audit_baseline_directory,
    build_manifest,
    compare_local_files_to_manifest,
    load_manifest,
)


def _read_r2_inventory(bucket: str, prefix: str = "baselines/") -> list[dict]:
    """Return read-only R2 list metadata; never requests object mutation."""
    import boto3

    endpoint = os.environ.get("R2_ENDPOINT_URL")
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
    inventory: list[dict] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            if not obj["Key"].endswith(".tif"):
                continue
            head = client.head_object(Bucket=bucket, Key=obj["Key"])
            inventory.append(
                {
                    "key": obj["Key"],
                    "size": obj["Size"],
                    "etag": obj["ETag"].strip('"'),
                    "last_modified": obj["LastModified"].isoformat(),
                    "storage_class": obj.get("StorageClass", "Standard"),
                    "http_metadata": {"contentType": head.get("ContentType")},
                }
            )
    return inventory


@click.command()
@click.option(
    "--baseline-dir",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=BASELINES_DIR,
    show_default=True,
)
@click.option(
    "--manifest",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("config/baseline_manifest_v1.json"),
    show_default=True,
)
@click.option(
    "--r2-read",
    is_flag=True,
    help="Read current R2 list/head metadata and reconcile it with local files.",
)
@click.option("--bucket", default=R2_BUCKET_NAME, show_default=True)
@click.option(
    "--write-manifest",
    is_flag=True,
    help="Write the fully audited manifest locally. Does not write to R2.",
)
def main(
    baseline_dir: Path,
    manifest: Path,
    r2_read: bool,
    bucket: str,
    write_manifest: bool,
) -> None:
    """Validate checksums, grids, scale, ranges, and coverage for all baselines."""
    if write_manifest:
        inventory = _read_r2_inventory(bucket) if r2_read else None
        objects = audit_baseline_directory(baseline_dir, inventory)
        document = build_manifest(objects, audit_date=date.today().isoformat())
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        click.echo(f"Wrote accepted baseline manifest: {manifest}")
    else:
        document = load_manifest(manifest)
        compare_local_files_to_manifest(baseline_dir, document)

    aggregate = document["aggregate"]
    click.echo(
        "Baseline audit passed: "
        f"{aggregate['object_count']} objects, "
        f"{aggregate['total_bytes']} bytes, "
        f"minimum extent coverage "
        f"{aggregate['minimum_extent_coverage_fraction']:.6%}, "
        f"inventory SHA-256 {aggregate['inventory_sha256']}."
    )


if __name__ == "__main__":
    main()
