"""Per-date detection composites via Google Earth Engine (for Cloud Shell).

Companion to build_baseline_gee.py, but for DETECTION instead of the baseline:
instead of one median per calendar month over many years, this computes ONE
cloud-masked composite PER ACQUISITION DATE over the AOI, for a date range
(default: all of 2026). Each date's Sentinel-2 tiles are mosaicked into a single
AOI-wide image, and NDMI/NBR/EVI2/BSI are computed on surface reflectance — the
exact same prep as the baseline, so the two are on the same scale.

Output: one small 4-band GeoTIFF per date to Google Drive
    araripe_detect_YYYY-MM-DD.tif   (bands: ndmi, nbr, evi2, bsi)
Masked/out-of-AOI pixels are filled with -9999 (restored to NaN downstream).

Then, on your Mac, run scripts/run_detection_from_gee.py on the downloaded files
to produce data/alerts/alerts_YYYY-MM-DD.geojson via the EXISTING detection logic
(z-score vs the reflectance baselines -> vectorize -> land cover -> fire/mechanical
-> temporal persistence).

This sidesteps the AWS streaming bottleneck entirely (compute runs on Google's
servers; you download only small per-date results).

Physical datatake metadata (Phase 3, activation 2)
--------------------------------------------------
The v3 processing ledger accounts for physical acquisitions, not calendar
dates: ``ProcessingLedgerV3`` and ``CompositionRunV3`` are on ``main`` and
require ``platform``, ``datatake_id`` and ``acquisition_timestamp_utc`` per
acquisition. Measured before this change: ``build_baseline_v2_gee.py``
mentioned those fields 80 times and this script zero, so the ledger could only
ever be prepared by hand. This script now enumerates the physical datatakes of
every queried date and writes a v3 run manifest next to the date-keyed
acquisition manifest, which is what makes the ledger a **product of the run**
rather than a declaration about it.

Two documents are written, and the older one is unchanged:

* ``araripe_detection_acquisitions.json`` — the date-keyed acquisition-v1
  manifest ``src/detection/identity.load_composite_acquisition`` reads. Its
  shape is a downstream contract; nothing here touches it.
* ``araripe_detection_run_manifest_v3.json`` — new. One entry per physical
  datatake with its provider-native scenes, plus the run-level bindings and
  the derived ``run_manifest_id``/``run_manifest_sha256`` that
  ``CompositionRunV3`` takes. It carries no ``acquisition_id``: that identity
  binds the composite method and the grid, and this export decides neither
  for the replay — see ``build_run_manifest``.

The acquisition instant is read from the datatake identifier, **never** from
``system:time_start``: the latter is the per-granule instant and disagrees with
the datatake instant for every scene (the same finding
``build_baseline_v2_gee.py`` records at its grouping step).

Why the pure helpers are at module level and Earth Engine is not
---------------------------------------------------------------
This file is copied into Cloud Shell and run there with nothing but
``earthengine-api`` installed, so it cannot import the repository's library and
the derivation is necessarily a second copy of it. A second copy that nobody
checks is how two implementations drift, so ``import ee`` and every server call
now live inside ``main()`` and the derivation is importable:
``tests/test_detection_export_datatakes.py`` runs these functions against the
library's ``normalize_platform`` and ``create_acquisition_v3`` and fails if the
two disagree.

Cloud Shell setup (once): pip install --user earthengine-api; earthengine authenticate
Run:
    python3 build_detection_gee.py --project ee-araripe
    python3 build_detection_gee.py --project ee-araripe --start 2026-04-28 --end 2026-07-12
"""

import hashlib
import json
import sys
from datetime import datetime, timezone

SCL_CLEAR = [2, 4, 5, 6, 7, 11]
TARGET_CRS = "EPSG:32724"
SCALE = 20
AOI_BOUNDS = [
    -40.89236812577142,
    -7.840780758480428,
    -38.95208146319247,
    -6.957104781339829,
]
MONITORING_EXTENT_ID = "araripe-implementation-rectangle-v1"
COLLECTION_ID = "COPERNICUS/S2_SR_HARMONIZED"
COMPOSITE_METHOD_ID = "daily_mosaic-v1"

#: Phase 4's composition unit, decided in
#: ``config/phase4_composition_unit_decision_v1.json`` and enforced at run time
#: by ``src.replay.composition_unit``. One physical datatake per composite,
#: because the v3 ledger cannot honestly represent a composition unit coarser
#: than its accounting unit: on a date carrying two datatakes there is no
#: terminal status for "this acquisition's pixels went into the other one's
#: composite". Deliberately NOT ``coverage-ranked-first-valid-v1`` — that names
#: the library's ranked first-valid selection, and an Earth Engine ``mosaic()``
#: is not proven equal to it.
COMPOSITE_METHOD_ID_DATATAKE = "datatake_mosaic-v1"

#: The two units this export can enumerate and compose. ``date`` is what blue
#: has always written and is untouched; ``datatake`` is Phase 4's.
COMPOSITION_UNITS = ("date", "datatake")

#: Scene properties pulled once per query window, in this order. Mirrors
#: ``SCENE_PROPERTIES`` in build_baseline_v2_gee.py; the parity test compares
#: the two tuples so a field added there is not silently missing here.
SCENE_PROPERTIES = (
    "system:index",
    "PRODUCT_ID",
    "DATATAKE_IDENTIFIER",
    "SPACECRAFT_NAME",
    "PROCESSING_BASELINE",
    "MGRS_TILE",
    "CLOUDY_PIXEL_PERCENTAGE",
)

#: The grid this export REQUESTS. Deliberately not the baseline's
#: ``araripe-baseline-epsg32724-20m-grid-v1``: that one is pinned by an
#: explicit ``crsTransform``, and this export passes only ``crs`` and
#: ``scale``, so its origin is Earth Engine's choice. Claiming the baseline
#: grid here would assert an invariant the producer does not promise — and
#: ``run_detection_from_gee.py`` reindexes the baseline onto the composite with
#: a 15 m nearest-neighbour tolerance, which is the evidence that alignment was
#: never assumed. Pinning the transform would remove that reindex and change
#: exported pixels, so it is a Phase 4 decision, not a metadata one.
GRID_ID = "araripe-detection-export-epsg32724-20m-v1"

#: Version token of the run manifest document this script writes.
DETECTION_RUN_MANIFEST_VERSION = "phase3-detection-export-run-manifest-v1"

ACQUISITION_MANIFEST_NAME = "araripe_detection_acquisitions.json"
RUN_MANIFEST_NAME = "araripe_detection_run_manifest_v3.json"

_DATATAKE_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S"
_UNIT_SEPARATOR = "\x1f"
_LINE_FEED = "\n"


# ── args (simple, no click, for Cloud Shell) ──────────────────────────────────
def _arg(flag, default=None, argv=None):
    argv = sys.argv if argv is None else argv
    return argv[argv.index(flag) + 1] if flag in argv else default


# ── pure derivation, importable and parity-tested ─────────────────────────────


def normalize_platform(value):
    """``sentinel-2b``/``S2B`` -> ``S2B``; anything else fails closed.

    A standalone copy of ``src.processing.composition_v2.normalize_platform``,
    kept mechanical for constellation units A-D. Whether a normalized unit is
    *representable* is the acquisition-v3 contract's decision, not this
    function's, which is why an unreviewed future unit is rejected downstream
    rather than here.
    """

    if not isinstance(value, str) or not value.strip():
        raise ValueError("platform must be a non-empty string")
    text = value.strip().lower().replace("sentinel-2", "s2").replace("sentinel2", "s2")
    if len(text) != 3 or not text.startswith("s2") or text[2] not in "abcd":
        raise ValueError("platform %r is not a Sentinel-2 unit label" % (value,))
    return "S2" + text[2].upper()


def datatake_instant(datatake_id):
    """The sensing instant embedded in a provider datatake identifier.

    ``GS2A_20260830T130251_012345_N05.11`` -> ``2026-08-30T13:02:51Z``. Read
    from the identifier and never from ``system:time_start``, which is the
    per-granule instant.
    """

    if not isinstance(datatake_id, str) or not datatake_id.strip():
        raise ValueError("datatake_id must be a non-empty string")
    parts = datatake_id.strip().split("_")
    if len(parts) < 2:
        raise ValueError(
            "datatake_id %r embeds no sensing instant" % (datatake_id,)
        )
    instant = datetime.strptime(parts[1], _DATATAKE_TIMESTAMP_FORMAT)
    return instant.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def qualify_scene_id(value):
    """Provider-native scene index -> the collection-qualified scene ID."""

    text = str(value)
    if text.startswith(COLLECTION_ID + "/"):
        return text
    return COLLECTION_ID + "/" + text


def decimal_text(value):
    """A float as its shortest round-tripping decimal string.

    Every number this document seals is stored as a string or an ``int``, and
    :func:`canonical_bytes` refuses a float outright. The reason is measured,
    not stylistic: the library's canonical form is RFC 8785 (JCS), and
    ``json.dumps`` — all Cloud Shell has — disagrees with it on floats whose
    value is integral (``1.0`` against ``1``) and on exponent notation
    (``1e-07`` against ``1e-7``). With no float in the document the two forms
    agree for **every** document this script can produce, instead of agreeing
    for the ones tried so far.
    """

    return repr(float(value))


def _reject_floats(value, path="$"):
    if isinstance(value, float):
        raise ValueError(
            "%s is a float; seal numbers as int or decimal_text() so the "
            "canonical bytes agree with the library's RFC 8785 form" % (path,)
        )
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_floats(item, "%s.%s" % (path, key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_floats(item, "%s[%d]" % (path, index))


def canonical_bytes(document):
    """Canonical JSON bytes: sorted keys, tight separators, UTF-8, no float.

    Agrees byte for byte with ``src.detection.identity.canonical_json_bytes``
    for any float-free document; ``tests/test_detection_export_datatakes.py``
    proves that on the real run manifest and on the float rejection.
    """

    _reject_floats(document)
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def canonical_sha256(document):
    return hashlib.sha256(canonical_bytes(document)).hexdigest()


def acquisition_v1_identity(observed_on, scene_ids):
    """The acquisition-v1 identity this script has always written."""

    scene_ids = sorted(set(scene_ids))
    identity_input = _UNIT_SEPARATOR.join(
        [
            "acquisition-v1",
            COLLECTION_ID,
            observed_on,
            _LINE_FEED.join(scene_ids),
            MONITORING_EXTENT_ID,
            COMPOSITE_METHOD_ID,
        ]
    )
    digest = hashlib.sha256(identity_input.encode("utf-8")).hexdigest()
    return {
        "acquisition_id": "acq-v1-" + digest,
        "identity_inputs_sha256": digest,
        "collection_id": COLLECTION_ID,
        "observed_on": observed_on,
        "scene_ids": scene_ids,
        "monitoring_extent_id": MONITORING_EXTENT_ID,
        "composite_method_id": COMPOSITE_METHOD_ID,
    }


def group_into_datatakes(records):
    """Group scene-property rows into physical datatakes.

    ``records`` are dicts carrying at least the keys in ``SCENE_PROPERTIES``.
    Grouping is by ``(platform, DATATAKE_IDENTIFIER)`` — one physical
    acquisition — and a datatake is never split across dates: its
    ``observed_on`` is the UTC date of its own sensing instant, which is what
    lets the ledger group *summaries* by date while accounting for
    acquisitions.

    Scenes inside a datatake are ordered by the UTF-8 bytes of the
    provider-native scene ID, the same total order
    ``build_baseline_v2_gee.py`` uses, so the document is a function of the
    query and not of the order Earth Engine happened to return.
    """

    grouped = {}
    for record in records:
        platform = normalize_platform(record["SPACECRAFT_NAME"])
        key = (platform, record["DATATAKE_IDENTIFIER"])
        grouped.setdefault(key, []).append(record)

    datatakes = []
    for (platform, datatake_id), rows in sorted(
        grouped.items(), key=lambda item: (item[0][1], item[0][0])
    ):
        timestamp = datatake_instant(datatake_id)
        seen = {}
        for row in rows:
            seen[str(row["system:index"])] = row
        ordered = [
            seen[name]
            for name in sorted(seen, key=lambda text: text.encode("utf-8"))
        ]
        datatakes.append(
            {
                "platform": platform,
                "datatake_id": datatake_id,
                "acquisition_timestamp_utc": timestamp,
                "observed_on": timestamp[:10],
                "scene_count": len(ordered),
                "scene_ids": [
                    qualify_scene_id(row["system:index"]) for row in ordered
                ],
                "observed_processing_baselines": sorted(
                    {str(row["PROCESSING_BASELINE"]) for row in ordered}
                ),
                "scenes": [
                    {
                        "scene_id": str(row["system:index"]),
                        "product_id": row["PRODUCT_ID"],
                        "processing_baseline": str(row["PROCESSING_BASELINE"]),
                        "mgrs_tile": row["MGRS_TILE"],
                        "cloudy_pixel_percentage": decimal_text(
                            row["CLOUDY_PIXEL_PERCENTAGE"]
                        ),
                    }
                    for row in ordered
                ],
            }
        )
    return datatakes


def composite_method_for(composition_unit):
    """The composite method ID that goes with a composition unit.

    Fails closed on an unknown unit: a manifest that named a unit this script
    cannot compose would be a document about a run nobody can reproduce.
    """

    if composition_unit not in COMPOSITION_UNITS:
        raise ValueError(
            "composition_unit %r is not one of %s"
            % (composition_unit, ", ".join(COMPOSITION_UNITS))
        )
    return (
        COMPOSITE_METHOD_ID
        if composition_unit == "date"
        else COMPOSITE_METHOD_ID_DATATAKE
    )


def build_run_manifest(
    *, start, end, max_cloud, datatakes, exported_dates, composition_unit="date"
):
    """Assemble the v3 run manifest and derive its own binding.

    ``run_manifest_id`` is ``run-v3-<sha256 of the body>`` and
    ``run_manifest_sha256`` is that digest, the discipline
    ``run_manifest_binding_from_plan`` already uses on the baseline side: the
    same query yields the same binding, and any change to the enumerated
    datatakes yields a different one. No clock, no run id, no actor — those
    describe an execution, and putting them here would make the document's
    bytes non-reproducible.

    No ``expected_acquisitions``, deliberately
    ------------------------------------------
    A first draft of this function pre-computed each ``acquisition_id`` here.
    Measured: they did not match the ones ``CompositionRunV3`` derives, because
    that class binds ``composite_method_id`` to
    ``coverage-ranked-first-valid-v1`` (``src/detection/composition_run_v3.py``
    line 189, the datatake-scoped composition) while this export mosaics a
    whole date under ``daily_mosaic-v1``. The identity is a function of the
    composite method and the grid, and this export decides neither for the
    replay — so it enumerates the physical acquisitions and lets the
    composition run mint their identities. A pre-computed ID that looks right
    and does not match is worse than no ID at all.

    ``composition_unit``
    --------------------
    Phase 4 decided the unit (``config/phase4_composition_unit_decision_v1.json``)
    and this parameter is how the manifest records which one it describes. It
    defaults to ``date``, which is what blue has always exported.

    Note what this is **not**: adding ``composition_unit`` to the sealed body
    changes the bytes, so a date-unit manifest built now has a different
    ``run_manifest_id`` than one built before this change. That is intended and
    it is safe here for a measured reason — ``grep -rn build_detection_gee
    .github/`` returns nothing, no producer on ``main`` writes a v3 ledger
    (``src/publication/run_assembler.py``), and therefore no recorded binding
    cites an old ID. Recording the unit is worth that: the composite method
    alone would leave a reader to infer whether to expect one composite per
    date or one per datatake, and inferring it is how the two halves of this
    system disagreed in the first place.
    """

    body = {
        "run_manifest_version": DETECTION_RUN_MANIFEST_VERSION,
        "collection_id": COLLECTION_ID,
        "monitoring_extent_id": MONITORING_EXTENT_ID,
        "monitoring_extent_bounds_epsg4326": [
            decimal_text(bound) for bound in AOI_BOUNDS
        ],
        "composite_method_id": composite_method_for(composition_unit),
        "composition_unit": composition_unit,
        "grid_id": GRID_ID,
        "acquisition_identity": {
            "minted_by": "src.detection.composition_run_v3.CompositionRunV3",
            "reason": (
                "the acquisition-v3 identity binds composite_method_id and "
                "grid_id, and this export decides neither for the replay"
            ),
        },
        "grid_request": {
            "crs": TARGET_CRS,
            "scale_m": SCALE,
            "crs_transform_pinned": False,
            "note": (
                "crs and scale only; the export origin is Earth Engine's "
                "choice and alignment to the baseline grid is not promised"
            ),
        },
        "query": {
            "start": start,
            "end_exclusive": end,
            "scene_cloud_filter_percent": max_cloud,
            "scl_clear_classes": list(SCL_CLEAR),
            "reflectance_scale_divisor": 10000,
        },
        "exported_dates": sorted(exported_dates),
        "datatakes": datatakes,
    }
    digest = canonical_sha256(body)
    document = dict(body)
    document["run_manifest_id"] = "run-v3-" + digest
    document["run_manifest_sha256"] = digest
    return document


def dates_of(datatakes):
    """The distinct UTC dates the enumerated datatakes fall on."""

    return sorted({item["observed_on"] for item in datatakes})


def composite_name(composition_unit, *, observed_on=None, datatake_id=None):
    """The export/download basename for one composite.

    Date unit keeps ``araripe_detect_YYYY-MM-DD``, which
    ``run_detection_from_gee.py`` already matches on. Datatake unit appends the
    provider datatake ID, so the date stays parseable by the same regex while
    two composites of one date no longer collide — which is the bug the
    date-keyed name would reintroduce the moment a date carries two datatakes.
    """

    if composition_unit == "date":
        if not observed_on:
            raise ValueError("the date unit needs observed_on")
        return "araripe_detect_%s" % observed_on
    if composition_unit == "datatake":
        if not observed_on or not datatake_id:
            raise ValueError("the datatake unit needs observed_on and datatake_id")
        return "araripe_detect_%s_%s" % (observed_on, datatake_id)
    raise ValueError("composition_unit %r is unknown" % (composition_unit,))


def write_json(path, document):
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(document, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


# ── Earth Engine work ─────────────────────────────────────────────────────────


def main(argv=None):
    try:
        import ee
    except ImportError:
        print("Run: pip install --user earthengine-api")
        raise

    project = _arg("--project", "ee-araripe", argv)
    start = _arg("--start", "2026-01-01", argv)
    end = _arg("--end", "2026-07-13", argv)  # exclusive-ish upper bound
    max_cloud = int(_arg("--max-cloud", "60", argv))
    drive_folder = _arg("--drive-folder", "araripe_detection", argv)
    composition_unit = _arg("--composition-unit", "date", argv)
    if composition_unit not in COMPOSITION_UNITS:
        raise SystemExit(
            "--composition-unit must be one of %s" % ", ".join(COMPOSITION_UNITS))

    ee.Initialize(project=project)
    aoi = ee.Geometry.Rectangle(AOI_BOUNDS)

    def prep(img):
        """Cloud-mask + reflectance + indices (matches build_baseline_gee.py +
        the local detector's band choices: ndmi/nbr use B8A; evi2/bsi use B8)."""
        scl = img.select("SCL")
        mask = scl.eq(SCL_CLEAR[0])
        for c in SCL_CLEAR[1:]:
            mask = mask.Or(scl.eq(c))
        r = img.select(["B2", "B4", "B8", "B8A", "B11", "B12"]).divide(10000).updateMask(mask)
        ndmi = r.normalizedDifference(["B8A", "B11"]).rename("ndmi")
        nbr = r.normalizedDifference(["B8A", "B12"]).rename("nbr")
        nir = r.select("B8"); red = r.select("B4"); blue = r.select("B2"); swir = r.select("B11")
        evi2 = (nir.subtract(red).multiply(2.5)
                .divide(nir.add(red.multiply(2.4)).add(1)).rename("evi2"))
        # BSI = ((SWIR1+RED)-(NIR+BLUE))/((SWIR1+RED)+(NIR+BLUE))
        num = swir.add(red).subtract(nir.add(blue))
        den = swir.add(red).add(nir.add(blue))
        bsi = num.divide(den).rename("bsi")
        return (ndmi.addBands(nbr).addBands(evi2).addBands(bsi)
                .copyProperties(img, ["system:time_start"]))

    base = (ee.ImageCollection(COLLECTION_ID)
            .filterBounds(aoi)
            .filterDate(start, end)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", max_cloud)))

    # Distinct acquisition dates (YYYY-MM-DD), computed server-side then pulled.
    dates = base.aggregate_array("system:time_start") \
        .map(lambda t: ee.Date(t).format("YYYY-MM-dd")).distinct().sort().getInfo()

    print("Project %s | %s..%s | %d distinct dates | crs %s @ %dm | Drive '%s'"
          % (project, start, end, len(dates), TARGET_CRS, SCALE, drive_folder))

    # One server call for the whole window's scene properties. The physical
    # datatake decomposition comes from these rows, not from the date list:
    # a date can hold more than one datatake, and the ledger accounts for
    # acquisitions while summarising by date.
    rows = base.reduceColumns(
        ee.Reducer.toList(len(SCENE_PROPERTIES), 1), list(SCENE_PROPERTIES)
    ).getInfo().get("list", [])
    records = [dict(zip(SCENE_PROPERTIES, row)) for row in rows]
    datatakes = group_into_datatakes(records)
    print("  %d scene(s) -> %d physical datatake(s) on %d date(s)"
          % (len(records), len(datatakes), len(dates_of(datatakes))))

    n = 0
    acquisition_manifest = {}

    if composition_unit == "datatake":
        # Phase 4's unit. One composite per physical datatake: the scenes of a
        # single datatake are mosaicked, and two datatakes of one UTC date are
        # never composed together. The date-keyed acquisition-v1 manifest is
        # still written unchanged, because persistence stays date-scoped
        # (contribution_key is keyed by an acq-v1 identity, one per UTC date)
        # while the ledger accounts per acquisition.
        for d in dates:
            day = ee.Date(d)
            daily = base.filterDate(day, day.advance(1, "day"))
            scene_ids = [
                qualify_scene_id(value)
                for value in daily.aggregate_array("system:index").getInfo()
            ]
            acquisition_manifest[d] = acquisition_v1_identity(d, scene_ids)
        for item in datatakes:
            one = base.filter(
                ee.Filter.eq("DATATAKE_IDENTIFIER", item["datatake_id"])
            )
            comp = one.map(prep).mosaic()
            comp = (comp.select(["ndmi", "nbr", "evi2", "bsi"])
                    .clip(aoi).unmask(-9999).toFloat())
            desc = composite_name(
                "datatake",
                observed_on=item["observed_on"],
                datatake_id=item["datatake_id"],
            )
            task = ee.batch.Export.image.toDrive(
                image=comp, description=desc, folder=drive_folder,
                fileNamePrefix=desc, region=aoi, scale=SCALE, crs=TARGET_CRS,
                maxPixels=int(1e10), fileFormat="GeoTIFF")
            task.start(); n += 1
            print("  queued %s (%s)" % (desc, task.id))
        write_json(ACQUISITION_MANIFEST_NAME, acquisition_manifest)
        run_manifest = build_run_manifest(
            start=start, end=end, max_cloud=max_cloud, datatakes=datatakes,
            exported_dates=dates, composition_unit="datatake",
        )
        write_json(RUN_MANIFEST_NAME, run_manifest)
        print("\n%d per-datatake export tasks started. Monitor: earthengine task list" % n)
        print("Run manifest %s (%d physical datatake(s), unit %s)"
              % (run_manifest["run_manifest_id"], len(run_manifest["datatakes"]),
                 run_manifest["composition_unit"]))
        return

    for d in dates:
        day = ee.Date(d)
        daily = base.filterDate(day, day.advance(1, "day"))
        scene_ids = [
            qualify_scene_id(value)
            for value in daily.aggregate_array("system:index").getInfo()
        ]
        acquisition_manifest[d] = acquisition_v1_identity(d, scene_ids)
        # All tiles of this date -> masked+indexed -> mosaic into one AOI image.
        comp = daily.map(prep).mosaic()
        comp = comp.select(["ndmi", "nbr", "evi2", "bsi"]).clip(aoi).unmask(-9999).toFloat()
        desc = composite_name("date", observed_on=d)
        task = ee.batch.Export.image.toDrive(
            image=comp, description=desc, folder=drive_folder, fileNamePrefix=desc,
            region=aoi, scale=SCALE, crs=TARGET_CRS, maxPixels=int(1e10),
            fileFormat="GeoTIFF")
        task.start(); n += 1
        print("  queued %s (%s)" % (desc, task.id))

    write_json(ACQUISITION_MANIFEST_NAME, acquisition_manifest)
    run_manifest = build_run_manifest(
        start=start,
        end=end,
        max_cloud=max_cloud,
        datatakes=datatakes,
        exported_dates=dates,
        composition_unit="date",
    )
    write_json(RUN_MANIFEST_NAME, run_manifest)

    print("\n%d per-date export tasks started. Monitor: earthengine task list" % n)
    print("Run manifest %s (%d physical datatake(s))"
          % (run_manifest["run_manifest_id"], len(run_manifest["datatakes"])))
    print("When done, download the GeoTIFFs from Drive folder '%s', then on your Mac:" % drive_folder)
    print("Also download Cloud Shell files '%s' and '%s' into the same local directory."
          % (ACQUISITION_MANIFEST_NAME, RUN_MANIFEST_NAME))
    print("  python scripts/run_detection_from_gee.py --in-dir <downloaded_dir>")


if __name__ == "__main__":
    main()
