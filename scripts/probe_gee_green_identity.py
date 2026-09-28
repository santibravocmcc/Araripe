#!/usr/bin/env python3
"""Prove the green Earth Engine identity computes, downloads, and cannot write.

``docs/implementation/PHASE_6E_2026-09-28.md`` §1 decided that the green
deposit lane gets its **own** Earth Engine identity instead of reusing
``GEE_SA_KEY``, the blue production service account (declared *Earth Engine
Resource Writer*, which Google documents as able to *"create, modify and
delete assets"* and *"create long running export tasks"*).  The owner created
it following ``docs/operations/GEE_GREEN_IDENTITY_SETUP.md``: a custom role with
three permissions, and the key stored only in the ``v2-staging`` Environment.

That role list is a design, not a measurement.  This script is the
measurement, and it has the same two polarities as
``scripts/probe_promotion_identity.py``:

* **what the detection needs must work** — initialise with the key, compute a
  value, reduce a Sentinel-2 image over the monitoring extent, and download a
  small GeoTIFF through ``getDownloadURL`` (the call ``scripts/replay_2026.py``
  pulls composites with);
* **what the blue identity can do and this one must not** — creating an asset
  and starting an export must both be **refused, for a permission reason**.  A
  refusal for another reason (a missing parent, a malformed name) proves
  nothing about scope and fails the probe as inconclusive.

If a refused call is instead **accepted**, the probe fails and says what was
created.  Nothing it creates is deleted — the folder name is fixed, so a second
run finds it rather than making another; an accepted export is cancelled,
because a running task would go on to write.

What it never does
------------------
It never reads ``GEE_SA_KEY`` and refuses to run if that name is set: a green
probe that could silently fall back to the blue key would prove the wrong
identity.  It never prints the key or any part of it — only the service
account's e-mail, which is not a secret and is what shows *which* identity
answered.  It imports nothing from ``config`` (``config/settings.py`` loads the
production ``.env`` at import).

    GEE_GREEN_SA_KEY='<json>' python scripts/probe_gee_green_identity.py
"""
from __future__ import annotations

import json
import os
import re
import sys

#: The Environment secret the owner created, and the only name read.
KEY_VAR = "GEE_GREEN_SA_KEY"
#: The blue key's name.  Its presence is a refusal, not a fallback.
BLUE_KEY_VAR = "GEE_SA_KEY"

PROJECT = "ee-araripe"
EXPECTED_EMAIL = "araripe-green-detect@ee-araripe.iam.gserviceaccount.com"

COLLECTION_ID = "COPERNICUS/S2_SR_HARMONIZED"
#: About 1.1 km square near Crato, inside ``AOI_BOUNDS`` of
#: ``scripts/build_detection_gee.py`` ([-40.89, -7.84, -38.95, -6.96]).
PROBE_BOX = (-39.46, -7.26, -39.45, -7.25)
#: A closed window the replay already processed (the candidate's last week).
PROBE_WINDOW = ("2026-08-01", "2026-08-31")

#: Fixed, so a probe run that is wrongly allowed to create it does not litter
#: the project with one folder per run.
REFUSED_FOLDER = f"projects/{PROJECT}/assets/green-identity-probe-must-be-refused"
REFUSED_EXPORT = f"projects/{PROJECT}/assets/green-identity-probe-export-must-be-refused"

TIFF_MAGIC = (b"II*\x00", b"MM\x00*")

#: What a scope refusal looks like.  Anything else is not evidence of scope.
PERMISSION_REFUSAL = re.compile(
    r"permission|denied|forbidden|does not have|not authori[sz]ed|403",
    re.IGNORECASE,
)

CHECKS: list[tuple[str, bool, str]] = []


class ProbeStop(RuntimeError):
    """A precondition failed; nothing after it would mean anything."""


def record(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


def _short(exc: BaseException) -> str:
    return " ".join(str(exc).split())[:200]


def read_key(environ) -> dict:
    """The parsed key, after the checks that decide whether it is the right one."""

    if BLUE_KEY_VAR in environ:
        record(f"the blue key name {BLUE_KEY_VAR} is absent", False,
               "it is set in this environment; a green probe must not be able to "
               "fall back to the production identity")
        raise ProbeStop("blue key name present")
    record(f"the blue key name {BLUE_KEY_VAR} is absent", True)

    raw = environ.get(KEY_VAR, "")
    if not raw.strip():
        record(f"{KEY_VAR} is set", False, "missing or empty")
        raise ProbeStop("missing key")
    try:
        key = json.loads(raw)
    except ValueError:
        record(f"{KEY_VAR} is a JSON service-account key", False,
               "not valid JSON — paste the whole downloaded .json file")
        raise ProbeStop("unparsable key") from None
    if not isinstance(key, dict) or key.get("type") != "service_account" \
            or not key.get("private_key") or not key.get("client_email"):
        record(f"{KEY_VAR} is a JSON service-account key", False,
               "JSON, but not a service-account key")
        raise ProbeStop("not a service-account key")
    record(f"{KEY_VAR} is a JSON service-account key", True)

    email = key["client_email"]
    record("the key belongs to the green detection account",
           email == EXPECTED_EMAIL,
           f"client_email {email}" if email != EXPECTED_EMAIL else email)
    if email != EXPECTED_EMAIL:
        raise ProbeStop("wrong account")
    return key


def initialise(ee, key: dict) -> None:
    credentials = ee.ServiceAccountCredentials(
        email=key["client_email"], key_data=json.dumps(key)
    )
    ee.Initialize(credentials, project=PROJECT)
    record(f"initialise Earth Engine as the service account on {PROJECT}", True)


def probe_compute(ee) -> None:
    try:
        value = ee.Number(20).add(22).getInfo()
        record("an interactive computation answers", value == 42, f"got {value!r}")
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        record("an interactive computation answers", False, _short(exc))


def _probe_image(ee):
    box = ee.Geometry.Rectangle(list(PROBE_BOX))
    collection = (ee.ImageCollection(COLLECTION_ID)
                  .filterBounds(box)
                  .filterDate(*PROBE_WINDOW))
    return box, collection


def probe_catalog_reduce(ee) -> None:
    try:
        box, collection = _probe_image(ee)
        size = collection.size().getInfo()
        if not size:
            record("Sentinel-2 is readable and reducible over the extent", False,
                   f"0 images in {PROBE_WINDOW} over the probe box")
            return
        mean = (collection.first().select("B8")
                .reduceRegion(ee.Reducer.mean(), box, 20).get("B8").getInfo())
        record("Sentinel-2 is readable and reducible over the extent",
               isinstance(mean, (int, float)),
               f"{size} images; B8 mean {mean!r}")
    except Exception as exc:  # noqa: BLE001
        record("Sentinel-2 is readable and reducible over the extent", False, _short(exc))


def probe_download(ee, http_get) -> None:
    try:
        box, collection = _probe_image(ee)
        url = collection.first().select("B8").getDownloadURL({
            "region": box, "scale": 20, "format": "GEO_TIFF", "bands": ["B8"],
        })
        response = http_get(url, timeout=120)
        body = response.content or b""
        ok = response.status_code == 200 and body[:4] in TIFF_MAGIC
        record("a GeoTIFF downloads through getDownloadURL", ok,
               f"HTTP {response.status_code}, {len(body)} bytes"
               + ("" if body[:4] in TIFF_MAGIC else ", not a TIFF"))
    except Exception as exc:  # noqa: BLE001
        record("a GeoTIFF downloads through getDownloadURL", False, _short(exc))


def _refused(name: str, exc: BaseException) -> None:
    message = _short(exc)
    if PERMISSION_REFUSAL.search(message):
        record(name, True, f"refused: {message}")
    else:
        record(name, False,
               f"refused, but NOT for a permission reason, so this proves nothing "
               f"about scope: {message}")


def probe_asset_creation_is_refused(ee) -> None:
    name = "creating an asset is refused"
    try:
        ee.data.createAsset({"type": "FOLDER"}, REFUSED_FOLDER)
    except Exception as exc:  # noqa: BLE001 - the refusal is the pass condition
        _refused(name, exc)
        return
    record(name, False,
           f"THE FOLDER WAS CREATED at {REFUSED_FOLDER} — the identity can write "
           "assets and is over-scoped. It is left in place and recorded; narrow "
           "the role before anything else")


def probe_export_is_refused(ee) -> None:
    name = "starting an export is refused"
    try:
        task = ee.batch.Export.table.toAsset(
            collection=ee.FeatureCollection([ee.Feature(None, {"probe": 1})]),
            description="green-identity-probe-must-be-refused",
            assetId=REFUSED_EXPORT,
        )
        task.start()
    except Exception as exc:  # noqa: BLE001 - the refusal is the pass condition
        _refused(name, exc)
        return
    detail = "THE EXPORT STARTED — the identity can create export tasks and is over-scoped"
    try:
        task.cancel()
        detail += "; the task was cancelled before it could write"
    except Exception as exc:  # noqa: BLE001
        detail += f"; cancelling it FAILED ({_short(exc)}) — check the task list"
    record(name, False, detail)


def report() -> int:
    failed = [name for name, ok, _ in CHECKS if not ok]
    print()
    if failed:
        print(f"::error::{len(failed)} of {len(CHECKS)} checks failed: "
              + "; ".join(failed), file=sys.stderr)
        return 1
    print(f"all {len(CHECKS)} checks passed — the green identity computes and "
          "downloads, and cannot create assets or exports")
    return 0


def main(argv=None, *, environ=None, ee=None, http_get=None) -> int:
    environ = os.environ if environ is None else environ
    print("green Earth Engine identity probe")
    print(f"  project  : {PROJECT}")
    print(f"  key      : {'set' if environ.get(KEY_VAR, '').strip() else 'MISSING'}")
    print()
    try:
        key = read_key(environ)
        if ee is None:
            import ee  # noqa: PLC0415 - only after the key checks pass
        if http_get is None:
            import requests  # noqa: PLC0415
            http_get = requests.get
        try:
            initialise(ee, key)
        except Exception as exc:  # noqa: BLE001
            record(f"initialise Earth Engine as the service account on {PROJECT}",
                   False, _short(exc))
            raise ProbeStop("initialise") from None
    except ProbeStop:
        return report()

    probe_compute(ee)
    probe_catalog_reduce(ee)
    probe_download(ee, http_get)
    probe_asset_creation_is_refused(ee)
    probe_export_is_refused(ee)
    return report()


if __name__ == "__main__":
    sys.exit(main())
