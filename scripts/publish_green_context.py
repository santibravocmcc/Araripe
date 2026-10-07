#!/usr/bin/env python3
"""Build and publish the land-cover context of the live green release.

Contract: ``docs/contracts/phase2b/GREEN_CONTEXT_CONTRACT_V1.md``.

    # 1. download the live release's full alert objects (store; lane only)
    python scripts/publish_green_context.py fetch --out .cache/context-input

    # 2. annotate with the current crops and write the context locally (no store)
    python scripts/publish_green_context.py plan \
        --input .cache/context-input --out .cache/context-output

    # 3. write it, then point contexts/current.json at it (store; lane only)
    python scripts/publish_green_context.py apply --context .cache/context-output

``plan`` contacts no store: it reads the release and the objects ``fetch``
wrote, verifies every object's sha256 against the release, and is therefore
reviewable offline.  ``fetch`` and ``apply`` build the store the way
``publish_green_release.py`` does — from environment variables a lane
provides, never from a local profile.

Which crops: the 2025 MapBiomas crops under ``data/landcover/``, named here
and bound by the sha256 their ``.report.json`` records.  Changing the recipe is
a code change, reviewed like one; a different recipe yields a different
context id, never different bytes under the same one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.publication import conditional_store as cs  # noqa: E402
from src.publication import context_pointer  # noqa: E402
from src.publication import green_context as gc  # noqa: E402
from src.publication import site_artifact as sa  # noqa: E402
from src.publication.findings import Rejected  # noqa: E402
from src.replay.generation import GREEN_LANDCOVER_CROPS  # noqa: E402

LANDCOVER = ROOT / "data" / "landcover"
#: The recipe: one crop per collection key — the green generation's own
#: (``src/replay/generation.py``, PHASE_6W), so the context and the release's
#: labels cannot name different crops.  The annotator's blue default rasters
#: (``config.settings.LANDCOVER_RASTERS``) are deliberately NOT read —
#: importing config.settings loads the production ``.env``.
CROPS = dict(GREEN_LANDCOVER_CROPS)
POINTER_KEY = "pointers/green/current.json"

#: The same names ``publish_green_release.py`` reads, from the same Environment
#: (``v2-promotion``): publishing a context is a publication act.
ACCESS_KEY_VAR = "R2_PROMOTION_ACCESS_KEY_ID"
SECRET_KEY_VAR = "R2_PROMOTION_SECRET_ACCESS_KEY"
BUCKET_VAR = "R2_STAGING_BUCKET"
ENDPOINT_VAR = "R2_ENDPOINT_URL"


def _say(message: str) -> None:
    print(message, flush=True)


def _error(message: str) -> str:
    return f"::error::{message}" if os.environ.get("GITHUB_ACTIONS") else f"erro: {message}"


# ── the recipe ───────────────────────────────────────────────────────────────

def recipe() -> tuple[dict, dict]:
    """``(spec, raster paths)`` from the committed crops and their reports."""

    from src.detection.landcover_core import _TABLES

    entries, paths = [], {}
    for key, stem in CROPS.items():
        tif = LANDCOVER / f"{stem}.tif"
        report = json.loads((LANDCOVER / f"{stem}.report.json").read_text(encoding="utf-8"))
        digest = hashlib.sha256(tif.read_bytes()).hexdigest()
        if digest != report["crop"]["sha256"]:
            raise SystemExit(_error(f"{tif.name} does not match its report ({digest[:12]}…)"))
        entries.append({
            "collection_key": key,
            "collection": report["collection"],
            "year": report["year"],
            "origin_url": report["origin_url"],
            "crop_sha256": digest,
            "source_md5": report["source"]["md5"],
        })
        paths[key] = tif
    return gc.build_spec(entries, _TABLES), paths


def annotate(features: list[dict], rasters: dict) -> list[tuple[str, dict]]:
    """``(observation_id, label values)`` per feature, in input order."""

    import geopandas as gpd

    from src.detection.landcover_core import annotate_alerts_all_collections

    frame = gpd.GeoDataFrame.from_features(
        [{"type": "Feature", "geometry": f["geometry"],
          "properties": {"observation_id": f["properties"]["observation_id"]}} for f in features],
        crs="EPSG:4326",
    )
    annotated = annotate_alerts_all_collections(frame, rasters=rasters, default_collection="mapbiomas10m")
    missing = [field for field in gc.LABEL_FIELDS if field not in annotated.columns]
    if missing:
        raise SystemExit(_error(f"the annotator did not produce {missing}"))
    rows = []
    for record in annotated[["observation_id", *gc.LABEL_FIELDS]].to_dict("records"):
        rows.append((record.pop("observation_id"), record))
    return rows


# ── store (lane only) ────────────────────────────────────────────────────────

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
    )
    return cs.ConditionalStore(client, bucket)


def _object_key(release: dict, entry: dict) -> str:
    owner = entry.get("release_id")
    return f"releases/{owner}/{entry['path']}" if owner else release["release_prefix"] + entry["path"]


def cmd_fetch(args) -> int:
    store = build_store()
    pointer = json.loads(store.require(POINTER_KEY).body)
    release_body = store.require(pointer["release_path"]).body
    if hashlib.sha256(release_body).hexdigest() != pointer["release_document_sha256"]:
        raise SystemExit(_error("the live release document does not match the pointer's checksum"))
    release = json.loads(release_body)
    out = Path(args.out)
    (out / "objects").mkdir(parents=True, exist_ok=True)
    (out / "release.json").write_bytes(release_body)
    by_path = {item["path"]: item for item in release["objects"]}
    for observed_on, full, sha in gc.alert_dates(release):
        target = out / "objects" / full
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == sha:
            continue
        body = store.require(_object_key(release, by_path[full])).body
        if hashlib.sha256(body).hexdigest() != sha:
            raise SystemExit(_error(f"{full} read from the store does not match the release"))
        target.write_bytes(body)
        _say(f"fetched  {observed_on}  {len(body):>11,} bytes")
    _say(f"release  {release['release_id']}")
    return 0


# ── plan (no store) ──────────────────────────────────────────────────────────

def cmd_plan(args) -> int:
    source = Path(args.input)
    release = json.loads((source / "release.json").read_text(encoding="utf-8"))
    spec, rasters = recipe()
    context_id, _ = gc.context_identity(release["release_id"], spec)
    out = Path(args.out)
    tree = out / gc.context_prefix(context_id)
    tree.mkdir(parents=True, exist_ok=True)

    dates, objects = [], []
    total_before = total_after = 0
    for observed_on, full, sha in gc.alert_dates(release):
        body = (source / "objects" / full).read_bytes()
        if hashlib.sha256(body).hexdigest() != sha:
            raise SystemExit(_error(f"{full} on disk does not match the release; run fetch again"))
        features = json.loads(body)["features"]
        labels_doc = gc.labels_document(observed_on, annotate(features, rasters))
        relabelled = gc.relabel(features, labels_doc["labels"], observed_on)
        strong = gc.strong_collection(relabelled)
        for path, document, content_type in (
            (gc.labels_path(full), labels_doc, gc.LABELS_CONTENT_TYPE),
            (gc.strong_path(full), strong, gc.STRONG_CONTENT_TYPE),
        ):
            data = gc.serialise(document)
            (tree / path).parent.mkdir(parents=True, exist_ok=True)
            (tree / path).write_bytes(data)
            objects.append(gc.object_entry(path, data, content_type, observed_on))
        before = len(sa.strong_features(features))
        after = len(strong["features"])
        total_before += before
        total_after += after
        dates.append({
            "observed_on": observed_on,
            "source_path": full,
            "source_sha256": sha,
            "feature_count": len(features),
            "strong_count": after,
        })
        _say(f"{observed_on}  {len(features):>7,} alerts  strong {before:>6,} → {after:>6,}")

    document = gc.context_document(release=release, spec=spec, dates=dates, objects=objects)
    gc.check_context(document, release)
    (tree / gc.CONTEXT_DOCUMENT_NAME).write_bytes(gc.serialise(document))
    _say(f"\ncontext  {context_id}")
    _say(f"release  {release['release_id']}")
    _say(f"dates    {len(dates)}   strong {total_before:,} → {total_after:,}")
    _say(f"wrote    {tree}")
    return 0


# ── apply (store; lane only) ─────────────────────────────────────────────────

def cmd_apply(args) -> int:
    root = Path(args.context)
    found = sorted(root.glob(f"{gc.CONTEXTS_ROOT}*/{gc.CONTEXT_DOCUMENT_NAME}"))
    if len(found) != 1:
        raise SystemExit(_error(f"expected exactly one context under {root}, found {len(found)}"))
    document_body = found[0].read_bytes()
    document = json.loads(document_body)
    tree = found[0].parent

    store = build_store()
    pointer = json.loads(store.require(POINTER_KEY).body)
    if pointer["release_id"] != document["release_id"]:
        raise SystemExit(_error(
            f"the live release is {pointer['release_id']} but this context describes "
            f"{document['release_id']}; a context is only published for the live release"))
    release = json.loads(store.require(pointer["release_path"]).body)
    gc.check_context(document, release)

    prefix = document["context_prefix"]
    for item in document["objects"]:
        body = (tree / item["path"]).read_bytes()
        if hashlib.sha256(body).hexdigest() != item["sha256"]:
            raise SystemExit(_error(f"{item['path']} on disk does not match the context document"))
        # By content: an object an earlier context already stored is "unchanged".
        outcome = store.put_if_absent(gc.object_key(item), body, item["content_type"])
        _say(f"{outcome.result:9}  {item['path']}")
    outcome = store.put_if_absent(prefix + gc.CONTEXT_DOCUMENT_NAME, document_body, "application/json")
    _say(f"{outcome.result:9}  {prefix + gc.CONTEXT_DOCUMENT_NAME}")

    env = os.environ
    result = context_pointer.move(store, document, document_body, {
        "workflow": env.get("GITHUB_WORKFLOW"),
        "run_id": env.get("GITHUB_RUN_ID"),
        "actor": env.get("GITHUB_ACTOR"),
    })
    _say(f"pointer  {gc.CONTEXT_CURRENT_KEY} {result} → {document['context_id']}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="download the live release's full alert objects (store)")
    fetch.add_argument("--out", required=True)
    fetch.set_defaults(func=cmd_fetch)
    plan = sub.add_parser("plan", help="annotate and write the context locally (no store)")
    plan.add_argument("--input", required=True)
    plan.add_argument("--out", required=True)
    plan.set_defaults(func=cmd_plan)
    apply = sub.add_parser("apply", help="publish a planned context and move its pointer (store)")
    apply.add_argument("--context", required=True)
    apply.set_defaults(func=cmd_apply)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (Rejected, cs.ObjectStoreError) as exc:
        print(_error(str(exc)), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
