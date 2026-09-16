#!/usr/bin/env python3
"""Seal the old (blue) generation as a citable, immutable inventory.

    python scripts/attest_old_generation.py \
        --site-repo ../site --out docs/implementation/OLD_GENERATION_ATTESTATION_<date>.json

Roadmap Phase 4 bullet 1 — *"Preserve the old generation as an immutable
historical release."*  Since Phase 5 became a scientific publication that
bullet stopped being prudence: a paper cites **one** generation, and the one
the candidate is about to supersede has to remain identifiable afterwards.

Why this is an attestation and not a published release
------------------------------------------------------
A "release" in this system is a store prefix whose identity is *derived from a
v3 processing ledger* (``src/publication/green_release.release_identity``).  The
blue generation has no v3 ledger — measured, and recorded in
``docs/implementation/PHASE_2B_GATE_2026-09-08.md`` §4: no producer on ``main``
writes one.  So the blue generation cannot be given a release identity without
inventing its ledger, and inventing one would mint an identity that claims a
provenance nobody recorded.

What it *can* have, and what this produces, is an inventory that pins the exact
bytes of the generation at named commits.  Both halves are already immutable —
git objects are content-addressed — so the missing thing was never durability,
it was a single document that says *which* objects and *which* commits are the
generation, with the digests to prove it.

The cross-check that makes it evidence rather than a listing
------------------------------------------------------------
``data/timeseries/RELEASE.json`` is the producer's own sealed claim about the
time-series database: a path, a byte count and a SHA-256, written by the
workflow run it names.  This script recomputes that digest from the tracked
blob and **fails closed if they disagree**.  So the attestation is anchored in
what the producer promised rather than in what a later reader measured, and a
drift between the two is a finding instead of a silently newer number.

Read-only by construction: everything comes from ``git cat-file``, no working
tree is trusted, no network is contacted, no credential is read, and nothing in
either repository is modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

#: The prefix under which the site tracks the published alert corpus.
SITE_ALERTS_PREFIX = "public/data/alerts/"

#: The backend paths that carry the blue time-series generation.
BACKEND_PATHS = ("data/timeseries/RELEASE.json", "data/timeseries/timeseries.db")

ATTESTATION_SCHEMA = "araripe-old-generation-attestation-v1"


class AttestationError(RuntimeError):
    """The old generation cannot be sealed as described."""


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ("git", "-C", str(repo)) + args,
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise AttestationError(
            "git %s failed in %s: %s" % (" ".join(args), repo, result.stderr.strip())
        )
    return result.stdout


def _git_bytes(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ("git", "-C", str(repo)) + args,
        capture_output=True, check=False,
    )
    if result.returncode != 0:
        raise AttestationError(
            "git %s failed in %s: %s"
            % (" ".join(args), repo, result.stderr.decode("utf-8", "replace").strip())
        )
    return result.stdout


def _commit(repo: Path, ref: str) -> str:
    return _git(repo, "rev-parse", ref).strip()


def inventory(repo: Path, ref: str, paths) -> list[dict]:
    """One row per tracked object: path, git blob id, size and content digest.

    The blob id and the content digest are both recorded on purpose. The blob
    id is what git uses to address the object and is a SHA-1 over a header plus
    the content; the content digest is a plain SHA-256 over the bytes a
    consumer would download. Recording only the first would tie the citation to
    git; only the second would lose the ability to fetch it back by address.
    """

    rows = []
    for path in sorted(paths):
        listing = _git(repo, "ls-tree", "-l", ref, "--", path).strip()
        if not listing:
            raise AttestationError(
                "%s does not exist at %s in %s; the generation cannot be "
                "sealed around an object that is not there" % (path, ref, repo)
            )
        fields = listing.split()
        blob_id, size = fields[2], fields[3]
        body = _git_bytes(repo, "cat-file", "blob", f"{ref}:{path}")
        if size != "-" and int(size) != len(body):
            raise AttestationError(
                "%s: git reports %s bytes and cat-file returned %d"
                % (path, size, len(body))
            )
        rows.append({
            "path": path,
            "git_blob_id": blob_id,
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        })
    return rows


def verify_release_claim(rows: list[dict], release_body: bytes) -> dict:
    """Check the producer's own sealed claim about the time-series database."""

    claim = json.loads(release_body)
    declared = claim.get("timeseries") or {}
    path = declared.get("path")
    by_path = {row["path"]: row for row in rows}
    row = by_path.get(path)
    if row is None:
        raise AttestationError(
            "RELEASE.json declares %r, which is not in the sealed inventory" % path
        )
    if row["sha256"] != declared.get("sha256"):
        raise AttestationError(
            "RELEASE.json claims sha256 %s for %s and the tracked blob hashes "
            "to %s; the producer's seal and the tracked bytes disagree"
            % (declared.get("sha256"), path, row["sha256"])
        )
    if row["bytes"] != declared.get("bytes"):
        raise AttestationError(
            "RELEASE.json claims %r bytes for %s and the tracked blob is %d"
            % (declared.get("bytes"), path, row["bytes"])
        )
    return {
        "verified": True,
        "declared_by": "data/timeseries/RELEASE.json",
        "schema": claim.get("schema"),
        "latest_observation": claim.get("latest_observation"),
        "published_utc": claim.get("published_utc"),
        "producer_run_id": claim.get("run_id"),
        "producer_run_url": claim.get("run_url"),
        "producer_workflow": claim.get("workflow"),
        "timeseries_sha256": declared.get("sha256"),
        "timeseries_bytes": declared.get("bytes"),
    }


def build(backend: Path, site: Path, *, backend_ref: str, site_ref: str) -> dict:
    from src.detection.identity import canonical_sha256

    backend_commit = _commit(backend, backend_ref)
    site_commit = _commit(site, site_ref)

    backend_rows = inventory(backend, backend_ref, BACKEND_PATHS)
    site_paths = [
        line.strip()
        for line in _git(site, "ls-tree", "-r", "--name-only", site_ref).splitlines()
        if line.strip().startswith(SITE_ALERTS_PREFIX)
    ]
    if not site_paths:
        raise AttestationError(
            "no object under %s at %s in %s; the published alert corpus is the "
            "public face of the generation and an empty inventory would seal "
            "nothing" % (SITE_ALERTS_PREFIX, site_ref, site)
        )
    site_rows = inventory(site, site_ref, site_paths)

    release_body = _git_bytes(
        backend, "cat-file", "blob", f"{backend_ref}:data/timeseries/RELEASE.json"
    )
    release = verify_release_claim(backend_rows, release_body)

    document = {
        "schema": ATTESTATION_SCHEMA,
        "what_this_is": (
            "an immutable inventory of the blue (old) generation, pinned at "
            "named commits in both repositories, with the producer's own "
            "release claim verified against the tracked bytes"
        ),
        "why_not_a_store_release": (
            "a release identity in this system is derived from a v3 processing "
            "ledger, and no producer on the blue path writes one; minting an "
            "identity for the blue generation would claim a provenance nobody "
            "recorded"
        ),
        "backend": {
            "ref": backend_ref,
            "commit": backend_commit,
            "objects": backend_rows,
        },
        "site": {
            "ref": site_ref,
            "commit": site_commit,
            "alerts_prefix": SITE_ALERTS_PREFIX,
            "object_count": len(site_rows),
            "objects": site_rows,
        },
        "producer_release_claim": release,
        "totals": {
            "object_count": len(backend_rows) + len(site_rows),
            "bytes": sum(row["bytes"] for row in backend_rows + site_rows),
        },
    }
    # One digest over the whole inventory, so a citation can be one string.
    document["inventory_sha256"] = canonical_sha256({
        "backend": {"commit": backend_commit, "objects": backend_rows},
        "site": {"commit": site_commit, "objects": site_rows},
    })
    return document


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--site-repo", required=True,
                        help="path to the site repository (no default: a "
                             "machine-specific path must not be baked in)")
    parser.add_argument("--backend-repo", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--backend-ref", default="origin/main")
    parser.add_argument("--site-ref", default="origin/main")
    parser.add_argument("--out", default=None, help="write the document here")
    args = parser.parse_args(argv)

    try:
        document = build(
            Path(args.backend_repo), Path(args.site_repo),
            backend_ref=args.backend_ref, site_ref=args.site_ref,
        )
    except AttestationError as exc:
        print("refused: %s" % exc, file=sys.stderr)
        return 1

    body = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(body, encoding="utf-8")
        print("backend        : %s" % document["backend"]["commit"])
        print("site           : %s" % document["site"]["commit"])
        print("objects        : %d (%d bytes)"
              % (document["totals"]["object_count"], document["totals"]["bytes"]))
        print("release claim  : verified against the tracked blob")
        print("inventory      : sha256 %s" % document["inventory_sha256"])
        print("wrote          : %s" % args.out)
    else:
        print(body, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
