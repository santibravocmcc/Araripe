#!/usr/bin/env python3
"""Put baseline 2.1.0 in the green bucket once, and fetch the months a run needs.

    # once, by an operator, with the named AWS CLI profile (never the keys):
    AWS_PROFILE=araripe-r2-staging R2_ENDPOINT_URL=… \
        python scripts/baseline_v2_staging.py upload --source data/baselines_v2/2.1.0

    # in the deposit lane, before detection, for the months the window touches:
    python scripts/baseline_v2_staging.py fetch --month 8 --out data/baselines_v2/2.1.0

Why this exists
---------------
``docs/implementation/PHASE_6E_2026-09-28.md`` §2.2 measured that the baseline
the replay compares against — ``2.1.0``, 72 rasters, 13 GB — existed **only**
on the owner's machine: ``baselines_v2/2.1.0/`` in ``araripe-v2-staging`` held
0 objects, and ``PACKAGE_2A6D_PROMPT.md`` §3 recorded it as *"local only …
nothing has been uploaded"*.  A detection run on a GitHub runner cannot see a
laptop, and the blue fetcher (``scripts/fetch_baselines_from_r2.py``) reads
``araripe-cogs`` with the production key and imports ``config.settings``.

The keys are not chosen here.  ``config/baseline_manifest_v2_1.json`` has
declared every object's key, byte count and SHA-256 since Package 2A.6C.1;
this script only makes the declaration true, and then checks it at both ends.

The discipline, which is the candidate lane's
---------------------------------------------
* ``upload`` verifies **all 72** local files against the manifest before it
  writes **any**; a baseline half-uploaded from a wrong local copy would be
  immutable and undeletable.
* Every write is ``put_if_absent``: a re-run is ``unchanged`` object by object,
  and different bytes under a declared key are a refusal, never an overwrite.
* ``fetch`` refuses a body whose length or SHA-256 differs from the manifest,
  and writes through a temporary name so a failed run leaves no plausible
  half-file for the detection to read.
* Nothing is deleted and nothing outside ``baselines_v2/2.1.0/`` is addressed.

It is a lane-2 entry point (candidate identity, ``R2_STAGING_*``) and, like
``assemble_green_run.py`` and ``stage_green_run.py``, it opts into the named
profile so an operator never exports the secret.  It must not import
``config.settings`` (the production ``.env`` loads at import), so the manifest
is read as the JSON file it is.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.publication import conditional_store as cs  # noqa: E402
from src.publication.conditional_store import ObjectStoreError  # noqa: E402

ACCESS_KEY_VAR = "R2_STAGING_ACCESS_KEY_ID"
SECRET_KEY_VAR = "R2_STAGING_SECRET_ACCESS_KEY"
BUCKET_VAR = "R2_STAGING_BUCKET"
ENDPOINT_VAR = "R2_ENDPOINT_URL"

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "baseline_manifest_v2_1.json"
VERSION = "2.1.0"
KEY_PREFIX = f"baselines_v2/{VERSION}/"
OBJECT_COUNT = 72
CONTENT_TYPE = "image/tiff"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ManifestError(ValueError):
    """The manifest does not describe the generation this script moves."""


def load_objects(path: Path = MANIFEST) -> list[dict]:
    """The 72 declared objects, after the checks the transfer relies on.

    Not the full validation — ``src.detection.baseline_manifest_v2`` does that,
    and the detection runs it before reading a raster.  These are the fields
    this script trusts: where each object goes and what its bytes must be.
    """

    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("baseline_version") != VERSION:
        raise ManifestError(
            f"{path.name} declares {manifest.get('baseline_version')!r}, not {VERSION}"
        )
    objects = manifest.get("objects") or []
    if len(objects) != OBJECT_COUNT:
        raise ManifestError(f"{path.name} lists {len(objects)} objects, not {OBJECT_COUNT}")
    seen = set()
    for item in objects:
        key, filename = item.get("key", ""), item.get("filename", "")
        if key != KEY_PREFIX + filename or "/" in filename or not filename.endswith(".tif"):
            raise ManifestError(f"object {key!r} is not {KEY_PREFIX}<filename>.tif")
        if not _SHA256.match(str(item.get("sha256", ""))):
            raise ManifestError(f"object {key} has no SHA-256")
        if not isinstance(item.get("bytes"), int) or item["bytes"] <= 0:
            raise ManifestError(f"object {key} has no byte count")
        if not isinstance(item.get("month"), int) or not 1 <= item["month"] <= 12:
            raise ManifestError(f"object {key} has no month")
        if key in seen:
            raise ManifestError(f"object {key} is listed twice")
        seen.add(key)
    return objects


def sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def check_bytes(item: dict, body: bytes, where: str) -> None:
    if len(body) != item["bytes"]:
        raise ObjectStoreError(
            f"{where} is {len(body)} bytes; the manifest declares {item['bytes']}"
        )
    digest = sha256_bytes(body)
    if digest != item["sha256"]:
        raise ObjectStoreError(
            f"{where} has SHA-256 {digest[:12]}…; the manifest declares {item['sha256'][:12]}…"
        )


def build_store() -> cs.ConditionalStore:
    bucket = os.environ.get(BUCKET_VAR, cs.STAGING_BUCKET)
    client = cs.build_client(
        bucket,
        os.environ.get(ENDPOINT_VAR),
        {
            "access_key_id": os.environ.get(ACCESS_KEY_VAR, ""),
            "secret_access_key": os.environ.get(SECRET_KEY_VAR, ""),
            "region": os.environ.get("AWS_REGION", "auto"),
        },
        profile_fallback=True,
    )
    return cs.ConditionalStore(client, bucket)


def upload(store, source: Path, objects: list[dict]) -> dict[str, int]:
    """Verify every local file, then write each one if absent."""

    for item in objects:
        path = source / item["filename"]
        if not path.is_file():
            raise ObjectStoreError(f"{path} is missing; nothing was written")
        check_bytes(item, path.read_bytes(), str(path))
    print(f"verified {len(objects)} local files against the manifest; writing")

    counts: dict[str, int] = {}
    for index, item in enumerate(objects, 1):
        outcome = store.put_if_absent(
            item["key"], (source / item["filename"]).read_bytes(), CONTENT_TYPE
        )
        counts[outcome.result] = counts.get(outcome.result, 0) + 1
        print(f"  [{index:2d}/{len(objects)}] {outcome.result:9s} {item['key']}", flush=True)
    return counts


def fetch(store, out: Path, months: list[int], objects: list[dict]) -> list[Path]:
    """Download and verify the objects of ``months`` into ``out``."""

    wanted = [item for item in objects if item["month"] in set(months)]
    if not wanted:
        raise ObjectStoreError(f"no manifest object belongs to months {months}")
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for item in wanted:
        target = out / item["filename"]
        if target.is_file() and target.stat().st_size == item["bytes"] \
                and sha256_bytes(target.read_bytes()) == item["sha256"]:
            print(f"  present   {target.name}")
            written.append(target)
            continue
        body = store.require(item["key"]).body
        check_bytes(item, body, f"{store.bucket}/{item['key']}")
        partial = target.with_name(target.name + ".partial")
        partial.write_bytes(body)
        partial.replace(target)
        print(f"  fetched   {target.name}  ({len(body)} bytes, sha256 ok)", flush=True)
        written.append(target)
    return written


def _annotate(message: str) -> str:
    return f"::error::{message}" if os.environ.get("GITHUB_ACTIONS") else f"erro: {message}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    up = sub.add_parser("upload", help="write the 72 declared objects if absent")
    up.add_argument("--source", type=Path, required=True)
    fe = sub.add_parser("fetch", help="download and verify the objects of some months")
    fe.add_argument("--month", type=int, action="append", required=True,
                    choices=range(1, 13), metavar="1-12")
    fe.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        objects = load_objects()
        store = build_store()
        if args.command == "upload":
            counts = upload(store, args.source, objects)
            print(f"upload done — {counts}; nothing was deleted or overwritten")
        else:
            written = fetch(store, args.out, sorted(set(args.month)), objects)
            print(f"fetch done — {len(written)} rasters verified in {args.out}")
    except (ManifestError, ObjectStoreError) as exc:
        print(_annotate(str(exc)), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
