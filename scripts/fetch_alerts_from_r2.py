"""Download alert GeoJSONs from Cloudflare R2 into data/alerts/.

Alerts are stored in R2 (not git): they grow ~1-2 GB/year, which would blow the
free Git-LFS tier (1 GB storage + 1 GB/month bandwidth) almost immediately,
whereas R2 gives 10 GB free with ZERO egress. Detection uploads each
``alerts_<date>.geojson`` to R2 (``upload_to_r2.py --directory data/alerts
--prefix alerts/ --pattern '*.geojson'``); this pulls them back down.

Two uses:
  * ``--latest N`` — in CI, fetch only the N most recent alerts so the temporal
    persistence step can chain against them (no need to pull the whole archive).
  * (no ``--latest``) — pull the full archive (e.g. the site build, or local dev).

Auth: R2_ENDPOINT_URL / R2_ACCESS_KEY / R2_SECRET_KEY from the environment.

Usage:
    python scripts/fetch_alerts_from_r2.py --latest 3        # CI: recent for persistence
    python scripts/fetch_alerts_from_r2.py                    # everything
    python scripts/fetch_alerts_from_r2.py --list-only        # count without downloading
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ALERTS_DIR, R2_BUCKET_NAME

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def select_latest_keys(keys, latest=0):
    """Return the geojson keys to download.

    ``alerts_YYYY-MM-DD.geojson`` names sort lexicographically = chronologically,
    so the "latest N" are simply the last N after sorting. ``latest<=0`` returns
    all. Pure (no I/O) so it is unit-tested.
    """
    geo = sorted(k for k in keys if k.endswith(".geojson"))
    if latest and latest > 0:
        return geo[-latest:]
    return geo


def get_r2_client():
    import boto3

    endpoint = os.environ.get("R2_ENDPOINT_URL")
    access = os.environ.get("R2_ACCESS_KEY")
    secret = os.environ.get("R2_SECRET_KEY")
    if not (endpoint and access and secret):
        raise SystemExit("R2 credentials not set: R2_ENDPOINT_URL, R2_ACCESS_KEY, R2_SECRET_KEY")
    return boto3.client("s3", endpoint_url=endpoint,
                        aws_access_key_id=access, aws_secret_access_key=secret)


def _all_keys(client, bucket, prefix):
    paginator = client.get_paginator("list_objects_v2")
    out = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            out.append(obj["Key"])
    return out


@click.command()
@click.option("--prefix", default="alerts/", help="Object key prefix in the bucket.")
@click.option("--out", default=str(ALERTS_DIR), help="Local output directory.")
@click.option("--bucket", default=R2_BUCKET_NAME)
@click.option("--latest", default=0, help="Only fetch the N most recent alerts (0 = all).")
@click.option("--list-only", is_flag=True, help="List/count without downloading.")
def main(prefix, out, bucket, latest, list_only):
    client = get_r2_client()
    keys = select_latest_keys(_all_keys(client, bucket, prefix), latest)

    if list_only:
        for k in keys:
            print(f"  {k}")
        print(f"\n{len(keys)} alert file(s) in s3://{bucket}/{prefix}"
              + (f" (showing latest {latest})" if latest else ""))
        return

    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for key in keys:
        dest = out_dir / Path(key).name
        client.download_file(bucket, key, str(dest))
        n += 1
        print(f"  {key} -> {dest}")
    print(f"\nDownloaded {n} alert file(s) from s3://{bucket}/{prefix} to {out_dir}")
    if n == 0:
        print("Nothing found — has detection uploaded alerts to R2 yet "
              "(upload_to_r2.py --directory data/alerts --prefix alerts/ --pattern '*.geojson')?")


if __name__ == "__main__":
    main()
