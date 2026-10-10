#!/usr/bin/env python3
"""Build the sources document of a green release, locally, and write nothing to a store.

Contract: ``docs/contracts/phase2b/GREEN_SOURCES_CONTRACT_V1.md``.

    python scripts/plan_green_sources.py \
        --release release.json [--context context.json] \
        --ledger ledger-1.json --ledger ledger-2.json ... \
        --out .cache/sources-output

The ledgers are the release's own, in order: the version-1 ledger, or each
member's for a version-2/3 release.  ``--context`` is the live land-cover
context, when there is one; without it the document carries no 2025 record.

Before building, the records in ``config/green_sources_v1.json`` are checked
against the repository — the replay freeze for what a release does not seal
(the annotation crops, by sha256 since freeze v2; the baseline years; the
Sentinel-2 collection), and each tracked crop and its ``.report.json`` by
sha256.  A record that disagrees with
the file it names stops the plan.

This script writes only a local file.  Publishing is
``scripts/publish_green_sources.py`` (PHASE_6X), whose ``plan`` runs this
module's ``repository_findings`` before it builds; its lane is
``.github/workflows/v2_green_sources.yml``.  ``config.settings`` is never
imported — it loads the production ``.env``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.publication import green_sources as gs  # noqa: E402
from src.publication.findings import Rejected  # noqa: E402

SPEC_PATH = ROOT / "config" / "green_sources_v1.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def repository_findings(spec: dict, root: Path = ROOT) -> list[str]:
    """Where the records disagree with the files and the freeze they name."""

    problems: list[str] = []
    freeze_path = root / spec["basis"]["freeze_path"]
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    if freeze.get("freeze_sha256") != spec["basis"]["freeze_sha256"]:
        problems.append(f"the spec names freeze {spec['basis']['freeze_sha256']}, the file says {freeze.get('freeze_sha256')}")
    rasters = freeze["mapbiomas"]["rasters"]
    for record in spec["sources"]:
        sid = record["source_id"]
        if record["role"] == gs.ROLE_DETECTION:
            frozen = freeze["cloud_and_mosaic"]["detection_export"]["collection_id"]
            if record["dataset"] != frozen:
                problems.append(f"{sid}: dataset {record['dataset']} but the freeze exports {frozen}")
            if sorted(record["baseline_years"]) != sorted(freeze["baseline"]["source_years"]):
                problems.append(f"{sid}: baseline_years differ from the freeze's source_years")
            continue
        crop = record["crop"]
        path = root / crop["path"]
        if not path.is_file():
            problems.append(f"{sid}: {crop['path']} is not in this checkout")
            continue
        if path.stat().st_size != crop["bytes"] or _sha256(path) != crop["sha256"]:
            problems.append(f"{sid}: {crop['path']} does not have the bytes and sha256 the record names")
        if record["role"] == gs.ROLE_RELEASE:
            # Bound to the freeze the replay detected under, by sha256 since
            # freeze v2 (PHASE_6W) -- version 1 photographed path and bytes only.
            frozen = rasters[record["collection_key"]]
            if (frozen["path"], frozen["bytes"], frozen.get("sha256")) != (crop["path"], crop["bytes"], crop["sha256"]):
                problems.append(f"{sid}: the freeze photographs {frozen['path']} ({frozen['bytes']} bytes, "
                                f"sha256 {frozen.get('sha256')}) for {record['collection_key']}")
        # Both annotation roles now name a crop with a report (the 2023 crops,
        # which had none, are no longer a record of any role).
        report = json.loads(path.with_suffix(".report.json").read_text(encoding="utf-8"))
        pairs = (
            ("crop sha256", crop["sha256"], report["crop"]["sha256"]),
            ("source md5", record["source_checksum"]["md5"], report["source"]["md5"]),
            ("source sha256", record["source_checksum"]["sha256"], report["source"]["sha256"]),
            ("origin_url", record["origin_url"], report["origin_url"]),
            ("collection", record["collection"], report["collection"]),
            ("year", record["year"], report["year"]),
        )
        problems += [f"{sid}: {name} {ours!r} but the crop report says {theirs!r}"
                     for name, ours, theirs in pairs if ours != theirs]
    return problems


def _load(path: str | None):
    return None if path is None else json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release", required=True)
    parser.add_argument("--context")
    parser.add_argument("--ledger", action="append", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--spec", default=str(SPEC_PATH))
    args = parser.parse_args(argv)

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    problems = repository_findings(spec)
    if problems:
        for line in problems:
            print(f"refused: {line}", file=sys.stderr)
        return 2
    release, context = _load(args.release), _load(args.context)
    ledgers = [_load(path) for path in args.ledger]
    try:
        document = gs.build_sources(release, context, spec, ledgers)
        body = gs.serialise(document)
        gs.check_sources(json.loads(body), release, context, ledgers)
    except Rejected as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / gs.SOURCES_DOCUMENT_NAME).write_bytes(body)
    print(f"sources   : {document['sources_id']}")
    print(f"release   : {document['release_id']}")
    print(f"context   : {document['context_id']}")
    print(f"bytes     : {len(body)}  sha256 {hashlib.sha256(body).hexdigest()}")
    for line in document["attribution"]:
        print(f"  [{line['applies_to']}] {line['text']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
