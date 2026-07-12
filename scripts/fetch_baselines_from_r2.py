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
def main(prefix, out, bucket):
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    client = get_r2_client()

    paginator = client.get_paginator("list_objects_v2")
    n = 0
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.endswith(".tif"):
                continue
            dest = out_dir / Path(key).name
            client.download_file(bucket, key, str(dest))
            n += 1
            print(f"  {key} -> {dest} ({obj['Size']//1_000_000} MB)")
    print(f"\nDownloaded {n} baseline COG(s) from s3://{bucket}/{prefix} to {out_dir}")
    if n == 0:
        print("Nothing found — did you run scripts/upload_to_r2.py first (from the "
              "machine that has data/baselines/)?")


if __name__ == "__main__":
    main()
