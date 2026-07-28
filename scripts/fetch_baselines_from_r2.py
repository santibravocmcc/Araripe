"""Download the baseline COGs from Cloudflare R2 into data/baselines/.

Companion to scripts/upload_to_r2.py. Once the reflectance baselines have been
uploaded (``python scripts/upload_to_r2.py`` from the machine that has them),
this pulls them back down on any other machine / CI runner that needs to run
detection — closing the gap that baselines are git-ignored local data.

Auth: reads R2_ENDPOINT_URL / R2_ACCESS_KEY / R2_SECRET_KEY from the environment
(same as upload_to_r2.py). The bucket is R2_BUCKET_NAME (config, 'araripe-cogs').

Usage:
    R2_ENDPOINT_URL=... R2_ACCESS_KEY=... R2_SECRET_KEY=... \
      python scripts/fetch_baselines_from_r2.py
    python scripts/fetch_baselines_from_r2.py --prefix baselines/ --out data/baselines
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import BASELINES_DIR, R2_BUCKET_NAME
from config.settings import BASELINE_MANIFEST_PATH
from src.detection.baseline_manifest import (
    BaselineAuditError,
    expected_filenames,
    load_manifest,
    sha256_file,
)


def get_r2_client():
    import boto3

    endpoint = os.environ.get("R2_ENDPOINT_URL")
    access = os.environ.get("R2_ACCESS_KEY")
    secret = os.environ.get("R2_SECRET_KEY")
    if not (endpoint and access and secret):
        raise SystemExit("R2 credentials not set: R2_ENDPOINT_URL, R2_ACCESS_KEY, R2_SECRET_KEY")
    return boto3.client("s3", endpoint_url=endpoint,
                        aws_access_key_id=access, aws_secret_access_key=secret)


@click.command()
@click.option("--prefix", default="baselines/", help="Object key prefix in the bucket.")
@click.option("--out", default=str(BASELINES_DIR), help="Local output directory.")
@click.option("--bucket", default=R2_BUCKET_NAME)
@click.option(
    "--manifest",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    default=BASELINE_MANIFEST_PATH,
    show_default=True,
    help="Authoritative object inventory and SHA-256 manifest.",
)
@click.option("--list-only", is_flag=True, help="List/count the baseline objects in R2 "
              "without downloading — use to verify the R2 copy (e.g. 72 .tif) is complete "
              "before deleting the local data/baselines/ to free disk.")
def main(prefix, out, bucket, manifest, list_only):
    document = load_manifest(manifest)
    expected = {obj["key"]: obj for obj in document["objects"]}
    canonical_prefix = "baselines/"
    if prefix != canonical_prefix:
        raise click.ClickException(
            f"authoritative manifest requires prefix {canonical_prefix!r}, got {prefix!r}"
        )

    client = get_r2_client()
    paginator = client.get_paginator("list_objects_v2")
    remote = {}
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            if not obj["Key"].endswith(".tif"):
                continue
            remote[obj["Key"]] = obj

    if sorted(remote) != sorted(expected):
        missing = sorted(set(expected) - set(remote))
        unexpected = sorted(set(remote) - set(expected))
        raise click.ClickException(
            f"R2 baseline inventory differs from manifest; missing={missing}, "
            f"unexpected={unexpected}"
        )
    for key, obj in remote.items():
        manifest_obj = expected[key]
        etag = obj["ETag"].strip('"')
        if obj["Size"] != manifest_obj["bytes"] or etag != manifest_obj["r2_etag"]:
            raise click.ClickException(
                f"{key} metadata differs from manifest "
                f"(size {obj['Size']}, ETag {etag})"
            )

    if list_only:
        n, total = 0, 0
        for key in sorted(remote):
            obj = remote[key]
            n += 1
            total += obj["Size"]
            print(f"  {key} ({obj['Size']//1_000_000} MB)")
        print(f"\n{n} baseline COG(s) in s3://{bucket}/{prefix} ({total/1e9:.2f} GB total)")
        print(
            "OK: all 72 object names, sizes, and ETags match the authoritative "
            f"baseline {document['baseline_version']} manifest."
        )
        return

    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for filename in expected_filenames():
        key = f"{prefix}{filename}"
        obj = expected[key]
        dest = out_dir / filename
        if (
            dest.is_file()
            and dest.stat().st_size == obj["bytes"]
            and sha256_file(dest) == obj["sha256"]
        ):
            n += 1
            print(f"  {key} -> {dest} (already verified)")
            continue
        partial = dest.with_suffix(dest.suffix + ".part")
        partial.unlink(missing_ok=True)
        client.download_file(bucket, key, str(partial))
        try:
            if partial.stat().st_size != obj["bytes"]:
                raise BaselineAuditError(f"{key} downloaded byte-size mismatch")
            if sha256_file(partial) != obj["sha256"]:
                raise BaselineAuditError(f"{key} downloaded SHA-256 mismatch")
            partial.replace(dest)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        n += 1
        print(f"  {key} -> {dest} ({obj['bytes']//1_000_000} MB, SHA-256 verified)")
    print(f"\nDownloaded {n} baseline COG(s) from s3://{bucket}/{prefix} to {out_dir}")
    print(
        f"All files match baseline {document['baseline_version']} inventory "
        f"{document['aggregate']['inventory_sha256']}."
    )


if __name__ == "__main__":
    main()
