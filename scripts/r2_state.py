#!/usr/bin/env python3
"""Get/put the gap-tolerant persistence-state GeoJSON in Cloudflare R2.

The persistence state is a single object (`persistence_state.geojson`) holding
the running alert "tracks" (n_sightings, first_seen, last_seen, geometry). The
scheduled detection fetches it before running (so streaks chain across runs,
tolerating gaps) and pushes the updated version afterwards.

Usage:
    python scripts/r2_state.py get data/persistence_state.geojson
    python scripts/r2_state.py put data/persistence_state.geojson

Needs R2_ENDPOINT_URL / R2_ACCESS_KEY / R2_SECRET_KEY in the environment.
"""
import os
import sys

KEY = "persistence_state.geojson"


def _client():
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY"],
        aws_secret_access_key=os.environ["R2_SECRET_KEY"],
    )


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("get", "put"):
        sys.exit("usage: r2_state.py {get|put} <local_path>")
    action, path = sys.argv[1], sys.argv[2]
    bucket = os.environ.get("R2_BUCKET_NAME", "araripe-cogs")
    client = _client()
    if action == "get":
        try:
            client.download_file(bucket, KEY, path)
            print(f"fetched {KEY} -> {path}")
        except Exception as e:  # first-ever run: no state yet — start fresh
            print(f"no {KEY} in R2 (primeira execução?): {e}")
    else:  # put
        if not os.path.exists(path):
            print(f"aviso: {path} não existe — nada enviado")
            return
        client.upload_file(path, bucket, KEY, ExtraArgs={"ContentType": "application/geo+json"})
        print(f"put {path} -> {KEY}")


if __name__ == "__main__":
    main()
