"""The green generation the replay and its lane detect under.

``docs/implementation/PHASE_6W_2026-10-07.md`` is the decision this module
records.  The owner decided on 2026-10-07 to abandon the MapBiomas 2023 crops
before the cutover ("ninguém usou os dados ainda"); the green series is
therefore re-detected and annotated with the 2025 crops only.

Why a new ``algorithm_version`` and not just new rasters
--------------------------------------------------------
Nothing that names a green object reads the land cover:

* ``observation_id`` = f(acquisition, geometry, ``algorithm_version``,
  ``baseline_version``) — ``src/detection/identity_v3.py``;
* a ledger seals ``algorithm_version`` and the observation ids, and a release
  id is a function of its ledgers — ``src/publication/green_release.py``,
  ``chain_release.chain_release_identity``.

Re-annotating under ``1.0.0`` would mint the same ids for different bytes
(``ImmutableObjectConflict``) or, worse, extend the 2023 chain as if nothing
had changed.  ``1.1.0`` changes every one of those ids, and it is one of the
three fields ``chain_release._GENERATION`` holds constant along a chain, so a
release can never mix the two (PHASE_6H §1: a new generation is a new root).
Minor, not major: the detection is the same; what the product says about each
detection is not.

Why not ``config.settings``
---------------------------
The blue pipeline reads ``DETECTION_ALGORITHM_VERSION`` and
``LANDCOVER_RASTERS`` from ``config/settings.py``, and production is frozen
through Phase 5.  So those stay at ``1.0.0`` and the 2023 crops, exactly as the
baseline decision left ``BASELINE_VERSION`` at ``1.0.0``
(``tests/test_replay_freeze.py::test_decidir_o_replay_nao_move_o_default_do_azul``),
and the replay names its own generation here.  This module imports nothing
from ``config`` — ``config.settings`` loads the production ``.env`` — so the
chain scripts, which must never import it, can read the version too.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

#: The algorithm version of the green generation annotated with MapBiomas 2025.
GREEN_ALGORITHM_VERSION = "1.1.0"

#: The generation it replaces, kept so the refusal can name it.  Its runs and
#: releases stay in the staging bucket, private, and are never deleted.
PREVIOUS_GREEN_ALGORITHM_VERSIONS = ("1.0.0",)

#: The annotation recipe: one crop per collection key, under ``data/landcover``.
#: The same two crops the context layer uses (``scripts/publish_green_context.py``
#: reads this mapping), so the release's own labels and the context's agree by
#: construction.  Each crop is bound by the sha256 its ``.report.json`` records.
GREEN_LANDCOVER_CROPS = {
    "mapbiomas10m": "mapbiomas_col4_10m_2025_araripe",
    "mapbiomas30m": "mapbiomas_col11_30m_2025_araripe",
}

#: Which collection fills the unsuffixed ``lc_*`` columns.
GREEN_DEFAULT_LANDCOVER_COLLECTION = "mapbiomas10m"

_LANDCOVER = Path("data") / "landcover"


class GenerationError(ValueError):
    """A crop is missing or is not the one its report describes."""


def landcover_crops(root: Path) -> dict[str, dict]:
    """``{key: {path, report_path, sha256, bytes, report}}``, every crop verified.

    Reads the whole crop to hash it (17 MB and 1 MB): a crop whose bytes are not
    the ones its report recorded is refused before anything is annotated with
    it, because a wrong raster annotates silently.
    """

    out: dict[str, dict] = {}
    for key, stem in sorted(GREEN_LANDCOVER_CROPS.items()):
        tif = Path(root) / _LANDCOVER / f"{stem}.tif"
        report_path = Path(root) / _LANDCOVER / f"{stem}.report.json"
        if not tif.exists() or not report_path.exists():
            raise GenerationError(f"{key}: {tif.name} or its report is absent")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        body = tif.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if digest != report["crop"]["sha256"] or len(body) != report["crop"]["bytes"]:
            raise GenerationError(
                f"{key}: {tif.name} hashes to {digest} ({len(body)} bytes) and its "
                f"report records {report['crop']['sha256']} ({report['crop']['bytes']})"
            )
        out[key] = {
            "path": tif,
            "report_path": report_path,
            "sha256": digest,
            "bytes": len(body),
            "report": report,
        }
    return out


def landcover_rasters(root: Path) -> dict[str, Path]:
    """The verified crop paths, in the shape ``annotate_alerts_all_collections`` takes."""

    return {key: entry["path"] for key, entry in landcover_crops(root).items()}
