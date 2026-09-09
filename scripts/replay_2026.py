#!/usr/bin/env python3
"""Phase 4: reprocess 2026 into a staged candidate, one physical datatake at a time.

    # enumerate and screen only; no download, no detection, no writes:
    python scripts/replay_2026.py plan --start 2026-01-01 --end 2026-08-31 \
        --out-dir <isolated>

    # one bounded chronological batch, end to end:
    python scripts/replay_2026.py run --start 2026-08-25 --end 2026-08-31 \
        --out-dir <isolated> --state-path <isolated>/persistence_state.geojson

What this is, and what it deliberately is not
---------------------------------------------
It is the Phase 4 driver: it enumerates the physical acquisitions of a window,
screens them on measured extent coverage, pulls the composites worth pulling,
runs the **existing** detection science over each, and records one terminal v3
ledger row per expected acquisition.

It is **not** a second implementation of the science.  Every scientific step is
the same function the scheduled pipeline calls — ``detect_deforestation``,
``assess_scene_quality``, ``vectorize_alerts``, ``classify_fire_vs_mechanical``,
``annotate_alerts_all_collections``, ``update_tracks``.  What differs is the
*loop*, and it has to: the ledger accounts per physical acquisition while
persistence contributes per UTC date, so the per-datatake half and the per-date
half are separate passes.  Rewriting ``run_detection_from_gee`` to do both
would put a replay-shaped loop inside the blue path, and blue is frozen.

The two units, and why they are not in conflict
-----------------------------------------------
* the **ledger** accounts per physical datatake (roadmap bullet 2, exit gate);
* **persistence** contributes at most once per event and UTC date (bullet 7),
  and ``contribution_key`` is keyed by an ``acq-v1`` identity, one per date.

So a date's per-datatake alert frames are concatenated and ``update_tracks`` is
applied **once** for that date.

What it never touches
---------------------
Production.  It writes only under ``--out-dir`` and ``--state-path``, both
required and both expected to be isolated; it never dispatches a workflow,
never reaches R2, and ``--persistence-mode`` is fixed at ``rebuild`` because a
replay walks dates the live mode is built to refuse.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SCL_CLEAR = [2, 4, 5, 6, 7, 11]
BANDS = ["ndmi", "nbr", "evi2", "bsi"]
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

#: Reducer scale for the coverage screen.  Coarse on purpose: the screen only
#: rejects far below the gate, and 100 m makes 107 measurements cheap.
SCREEN_SCALE_M = 100

#: Concurrent tile requests per composite.  The high-volume endpoint exists for
#: this.  Measured sequentially first: 55 tiles, 525 s for one composite.
DEFAULT_WORKERS = 8


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Earth Engine side ────────────────────────────────────────────────────────


def _prep(img, ee):
    """Cloud-mask + reflectance + indices.

    Character for character the preparation ``build_detection_gee.py`` and
    ``run_detection_gee.py`` apply, so baseline and observation stay on one
    scale.  ``tests/test_replay_driver.py`` compares this function's source
    against the export's rather than trusting the comment.
    """
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
    num = swir.add(red).subtract(nir.add(blue))
    den = swir.add(red).add(nir.add(blue))
    bsi = num.divide(den).rename("bsi")
    return (ndmi.addBands(nbr).addBands(evi2).addBands(bsi)
            .copyProperties(img, ["system:time_start"]))


def _base_collection(ee, aoi, start, end, max_cloud, export):
    return (ee.ImageCollection(export.COLLECTION_ID)
            .filterBounds(aoi)
            .filterDate(start, end)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", max_cloud)))


def enumerate_window(ee, export, *, start, end, max_cloud):
    """The window's scene rows, physical datatakes and per-datatake coverage.

    One ``reduceColumns`` for the metadata — the call whose column order Phase
    3 could not prove and this driver verifies on every run — then one coarse
    reducer per datatake for the screen.
    """
    aoi = ee.Geometry.Rectangle(export.AOI_BOUNDS)
    base = _base_collection(ee, aoi, start, end, max_cloud, export)
    props = list(export.SCENE_PROPERTIES)
    rows = base.reduceColumns(
        ee.Reducer.toList(len(props), 1), props
    ).getInfo().get("list", [])
    if rows and len(rows[0]) != len(props):
        raise SystemExit(
            "reduceColumns returned rows of width %d, expected %d; the column "
            "contract this driver depends on does not hold" % (len(rows[0]), len(props))
        )
    records = [dict(zip(props, row)) for row in rows]
    datatakes = export.group_into_datatakes(records)

    # Independent cross-check of the column order, every run. It is one extra
    # aggregate_array per property and it is the difference between "the
    # columns were in this order the day we looked" and "they are".
    for index, prop in enumerate(props):
        got = sorted(str(row[index]) for row in rows)
        want = sorted(str(v) for v in base.aggregate_array(prop).getInfo())
        if got != want:
            raise SystemExit(
                "reduceColumns column %d does not carry %s; the seven-column "
                "order is not what this driver assumes" % (index, prop)
            )

    def valid_fraction(collection):
        def valid(img):
            scl = img.select("SCL")
            m = scl.eq(SCL_CLEAR[0])
            for c in SCL_CLEAR[1:]:
                m = m.Or(scl.eq(c))
            r = img.select(["B2", "B4", "B8", "B8A", "B11", "B12"]).updateMask(m)
            return r.reduce(ee.Reducer.count()).eq(6).rename("v").unmask(0)
        return (collection.map(valid).max().unmask(0)
                .reduceRegion(ee.Reducer.mean(), aoi, SCREEN_SCALE_M,
                              maxPixels=int(1e9)).get("v"))

    coverage = {}
    for chunk_start in range(0, len(datatakes), 8):
        chunk = datatakes[chunk_start:chunk_start + 8]
        features = [
            ee.Feature(None, {
                "k": item["datatake_id"],
                "v": valid_fraction(
                    base.filter(ee.Filter.eq("DATATAKE_IDENTIFIER", item["datatake_id"]))
                ),
            })
            for item in chunk
        ]
        for attempt in range(6):
            try:
                got = ee.FeatureCollection(features).getInfo()
                break
            except Exception:
                if attempt == 5:
                    raise
                time.sleep(4 * (attempt + 1))
        for feature in got["features"]:
            coverage[feature["properties"]["k"]] = float(feature["properties"]["v"])
    return records, datatakes, coverage


def pull_composite(ee, export, item, out_path, *, start, end, max_cloud, workers):
    """Pull one physical datatake's composite over the extent.

    Parallel over tiles.  ``src.acquisition.gee_download.download_image_tiled``
    is the sequential version the scheduled job uses and is deliberately left
    alone: adding concurrency there would change a blue code path to serve a
    replay.
    """
    import requests
    import rasterio
    from rasterio.merge import merge as rio_merge
    from src.acquisition.gee_download import compute_tile_grid

    aoi = ee.Geometry.Rectangle(export.AOI_BOUNDS)
    base = _base_collection(ee, aoi, start, end, max_cloud, export)
    one = base.filter(ee.Filter.eq("DATATAKE_IDENTIFIER", item["datatake_id"]))
    comp = (one.map(lambda img: _prep(img, ee)).mosaic()
            .select(BANDS).clip(aoi).unmask(-9999).toFloat())

    grid = compute_tile_grid(export.AOI_BOUNDS, scale=export.SCALE, tile_px=1024)
    tmp = Path(out_path).parent / (".%s_tiles" % Path(out_path).stem)
    tmp.mkdir(parents=True, exist_ok=True)

    def fetch(indexed):
        k, (tw, ts, te, tn) = indexed
        region = ee.Geometry.Rectangle([tw, ts, te, tn], proj="EPSG:4326",
                                       geodesic=False)
        params = {"region": region, "scale": export.SCALE, "crs": export.TARGET_CRS,
                  "format": "GEO_TIFF", "filePerBand": False}
        dest = tmp / ("tile_%04d.tif" % k)
        for attempt in range(6):
            try:
                url = comp.getDownloadURL(params)
                resp = requests.get(url, timeout=600)
                if resp.status_code == 200:
                    dest.write_bytes(resp.content)
                    return dest
                if resp.status_code not in (429, 500, 502, 503, 504):
                    resp.raise_for_status()
                raise RuntimeError("HTTP %d" % resp.status_code)
            except Exception:
                if attempt == 5:
                    raise
                time.sleep(2 ** attempt)
        raise RuntimeError("unreachable")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        tiles = list(pool.map(fetch, list(enumerate(grid))))

    handles = [rasterio.open(path) for path in sorted(tiles)]
    try:
        mosaic, transform = rio_merge(handles)
        profile = handles[0].profile
    finally:
        for handle in handles:
            handle.close()
    profile.update(height=mosaic.shape[1], width=mosaic.shape[2],
                   transform=transform, count=mosaic.shape[0],
                   compress="deflate", predictor=2, tiled=True)
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(mosaic)
    for path in tiles:
        path.unlink(missing_ok=True)
    tmp.rmdir()
    return Path(out_path)


# ── commands ─────────────────────────────────────────────────────────────────


def _load_export():
    import importlib.util
    path = Path(__file__).resolve().parent / "build_detection_gee.py"
    spec = importlib.util.spec_from_file_location("build_detection_gee", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _preflight():
    """Everything that must hold before a single EECU-second is spent."""
    from src.replay import freeze
    from src.replay.composition_unit import load_decision
    from src.replay.overlap_decision import load_decision as load_overlap

    frozen = freeze.load_freeze()
    baseline = frozen["baseline"]["replay_generation"]
    if not baseline.get("decided"):
        raise SystemExit("the replay baseline is not decided; Phase 4 does not default it")
    decision = load_decision()
    # The overlap rule is the owner's, read and never defaulted. There is no
    # command-line flag for it on purpose: a scientific rule that an operator
    # could override per invocation is not a recorded decision.
    overlap = load_overlap()
    return frozen, baseline, decision, overlap


def command_plan(args):
    import ee
    export = _load_export()
    from src.replay.enumeration import (
        expected_acquisitions, screen_by_coverage, screen_summary,
    )

    frozen, baseline, decision, overlap = _preflight()
    print("freeze          : %s" % frozen["freeze_sha256"])
    print("baseline        : %s (%s, %s)"
          % (baseline["version"], baseline["decided_by"], baseline["authorized_on"]))
    print("composition unit: %s under %s (%s)"
          % (decision.unit, decision.composite_method_id, decision.decision_sha256[:12]))
    print("grid            : %s" % decision.grid_decision)
    print("overlap rule    : %s (%s, %s)"
          % (overlap.min_overlap_fraction, overlap.decided_by,
             overlap.decision_date))
    print()

    ee.Initialize(project=args.project)
    records, datatakes, coverage = enumerate_window(
        ee, export, start=args.start, end=args.end, max_cloud=args.max_cloud
    )
    manifest = export.build_run_manifest(
        start=args.start, end=args.end, max_cloud=args.max_cloud,
        datatakes=datatakes, exported_dates=export.dates_of(datatakes),
        composition_unit="datatake",
    )
    acquisitions = expected_acquisitions(manifest)
    screened = screen_by_coverage(
        acquisitions, extent_coverage=coverage,
        minimum_fraction=args.min_clear / 100.0,
    )
    summary = screen_summary(screened)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "run_manifest_v3.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "screen.json").write_text(
        json.dumps({
            "summary": summary,
            "min_clear_percent": args.min_clear,
            "screen_scale_m": SCREEN_SCALE_M,
            "acquisitions": [
                {
                    "acquisition_id": item.acquisition_id,
                    "datatake_id": item.acquisition.datatake_id,
                    "platform": item.acquisition.platform,
                    "observed_on": item.observed_on,
                    "acquisition_timestamp_utc": (
                        item.acquisition.acquisition_timestamp_utc),
                    "extent_coverage_fraction": item.extent_coverage_fraction,
                    "pull": item.pull,
                }
                for item in screened
            ],
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print("scenes %d -> datatakes %d on %d date(s)"
          % (len(records), len(datatakes), len(export.dates_of(datatakes))))
    print("run manifest     : %s" % manifest["run_manifest_id"])
    print("expected         : %d" % summary["expected_acquisitions"])
    print("to pull          : %d" % summary["to_pull"])
    print("screened out     : %d (highest rejected coverage %.2f%%)"
          % (summary["rejected_on_measured_coverage"],
             100 * (summary["highest_rejected_coverage"] or 0.0)))
    print("wrote            : %s" % (out / "screen.json"))
    return 0


def command_run(args):
    """One bounded chronological batch, end to end.

    Per datatake: pull, detect, assess quality, vectorize, classify, annotate.
    Per UTC date, once all of its acquisitions are accounted for: concatenate
    that date's alert frames, apply persistence, save, and derive the daily
    summary.  A date is only summarised after every acquisition the manifest
    expects for it is terminal, which is roadmap bullet 4 verbatim.
    """
    import ee
    import geopandas as gpd
    import pandas as pd

    export = _load_export()
    from config.settings import (
        DETECTION_ALGORITHM_VERSION, MONITORING_EXTENT_ID,
        SCENE_ANOMALY_REJECT_FRAC, DEFAULT_LANDCOVER_COLLECTION,
    )
    from src.detection.alerts import save_alerts, summarize_alerts, vectorize_alerts
    from src.detection.baseline import load_baseline_pair
    from src.detection.baseline_selection import resolve_baseline
    from src.detection.change_detect import detect_deforestation
    from src.detection.identity import create_acquisition_identity
    from src.detection.landcover import annotate_alerts_all_collections
    from src.detection.ledger_v3 import ProcessingLedgerV3
    from src.detection.persistence import (
        AmbiguousLineageError, load_persistence_state, save_persistence_state,
        update_tracks,
    )
    from src.detection.scene_quality import assess_scene_quality
    from src.replay.enumeration import (
        expected_acquisitions, gate_rejection, lineage_failure, reconciles,
        screen_by_coverage, screen_rejection, screen_summary,
    )
    from src.replay.seasonal_regime import composition_regime_record
    from scripts.run_detection_from_gee import INDICES, _load_composite

    frozen, baseline_decision, decision, overlap = _preflight()
    baseline = resolve_baseline(args.baseline_version)
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    composites = out / "composites"; composites.mkdir(exist_ok=True)
    alerts_dir = out / "alerts"; alerts_dir.mkdir(exist_ok=True)

    print("baseline generation %s from %s" % (baseline.version, baseline.directory))
    print("composition unit    %s under %s" % (decision.unit, decision.composite_method_id))
    print("overlap rule        %s (%s, majority rule: %s) — the ambiguous-"
          "lineage refusal is REDUCED, not impossible"
          % (overlap.min_overlap_fraction, overlap.decided_by,
             overlap.is_majority_rule))

    # The manifest is the WHOLE replay window's, written once by `plan`, and
    # a batch is a chronological slice of its acquisitions. Re-enumerating per
    # batch would mint a different run_manifest_id each time, and the ledger
    # binds one manifest: the year's rows would belong to a dozen ledgers that
    # cannot be reconciled into one candidate.
    manifest_path = out / "run_manifest_v3.json"
    screen_path = out / "screen.json"
    if not manifest_path.exists() or not screen_path.exists():
        raise SystemExit(
            "run `plan` first: %s and %s are the whole window's enumeration, "
            "and a batch is a slice of them" % (manifest_path, screen_path))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    acquisitions = expected_acquisitions(manifest)
    coverage = {
        row["datatake_id"]: row["extent_coverage_fraction"]
        for row in json.loads(screen_path.read_text(encoding="utf-8"))["acquisitions"]
    }
    screened_all = screen_by_coverage(
        acquisitions, extent_coverage=coverage,
        minimum_fraction=args.min_clear / 100.0)
    by_datatake = {item["datatake_id"]: item for item in manifest["datatakes"]}
    # the batch: acquisitions whose UTC date falls in [--batch-start, --batch-end)
    screened = [
        item for item in screened_all
        if args.batch_start <= item.observed_on < args.batch_end
    ]
    if not screened:
        raise SystemExit("no expected acquisition falls in %s..%s"
                         % (args.batch_start, args.batch_end))
    print("batch         : %s..%s -> %d of %d expected acquisition(s)"
          % (args.batch_start, args.batch_end, len(screened), len(screened_all)))

    # Which seasonal source regime each month of the window was composed
    # against.  This is the counterpart of the cost the owner accepted when he
    # chose 2.1.0: it admits pre-Collection-1 products in months 1-4, so those
    # months may have to be redone when ESA's reprocessing reaches them.
    # Without this record, redoing four months means redoing twelve, because
    # nothing says which months depended on the retiring regime.  It is a pure
    # function of the window's months and the generation manifest, so every
    # batch of one replay writes it byte for byte identically.
    regime_record = composition_regime_record(
        baseline.load_manifest(),
        months={int(item.observed_on[5:7]) for item in acquisitions},
        baseline_version=baseline.version,
        window_start=args.start,
        window_end_exclusive=args.end,
    )
    regime_record["persistence_overlap_rule"] = overlap.as_dict()
    (out / "composition_regimes.json").write_text(
        json.dumps(regime_record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print("regime scope  : %s"
          % json.dumps(regime_record["rework_scope_by_regime"]))
    print("pending on ESA: month(s) %s of %d in the window"
          % (regime_record["pending_on_esa_reprocessing"]["months"],
             len(regime_record["months"])))

    ee.Initialize(project=args.project)

    rows_path = out / "terminal_rows.json"
    rows_by_id = _read_rows(rows_path)
    already = {i for i in rows_by_id}
    if already:
        print("resuming      : %d terminal row(s) already on disk" % len(already))

    ledger = ProcessingLedgerV3(
        run_manifest_id=manifest["run_manifest_id"],
        run_manifest_sha256=manifest["run_manifest_sha256"],
        acquisitions=acquisitions,
        monitoring_extent_id=manifest["monitoring_extent_id"],
        algorithm_version=DETECTION_ALGORITHM_VERSION,
        created_at=_utc_now())

    def flush_rows() -> None:
        """Merge this batch's terminal rows into the accumulating file.

        Called at the top of every loop iteration rather than only at the end.
        A batch that dies part-way used to lose its whole accounting — measured
        on 2026-09-09, when an ambiguous-lineage failure in the per-date pass
        discarded seventeen acquisitions' worth of finished work whose
        composites were already on disk. The rows are per-acquisition and
        independently valid, so writing them early is not a partial document:
        `ledger.json` is still written only when the whole set is terminal.
        """
        for row in ledger.terminal_rows:
            rows_by_id[row["acquisition_id"]] = row
        _write_rows(rows_path, rows_by_id)

    # ── per acquisition, in timestamp then acquisition-ID order ──────────────
    frames_by_date: dict[str, list] = {}
    pending: dict[str, list] = {}
    for item in sorted(screened,
                       key=lambda s: (s.acquisition.acquisition_timestamp_utc,
                                      s.acquisition_id)):
        pending.setdefault(item.observed_on, []).append(item)

    for item in sorted(screened,
                       key=lambda s: (s.acquisition.acquisition_timestamp_utc,
                                      s.acquisition_id)):
        flush_rows()
        label = "%s %s" % (item.observed_on, item.acquisition.datatake_id)
        if item.acquisition_id in already:
            print("  done      %s  (terminal in an earlier batch)" % label)
            continue
        if not item.pull:
            ledger.record_terminal(
                acquisition_id=item.acquisition_id,
                status="rejected_low_coverage",
                reason=screen_rejection(item), terminal_at=_utc_now())
            print("  screened  %s  (%.2f%% of extent)"
                  % (label, 100 * item.extent_coverage_fraction))
            continue

        target = composites / ("%s.tif" % export.composite_name(
            "datatake", observed_on=item.observed_on,
            datatake_id=item.acquisition.datatake_id))
        try:
            if not target.exists():
                started = time.time()
                pull_composite(ee, export, by_datatake[item.acquisition.datatake_id],
                               target, start=args.start, end=args.end,
                               max_cloud=args.max_cloud, workers=args.workers)
                print("  pulled    %s  (%.0fs, %.0f MB)"
                      % (label, time.time() - started, target.stat().st_size / 1e6))
        except Exception as exc:
            ledger.record_terminal(
                acquisition_id=item.acquisition_id, status="failed_download",
                reason={"code": "composite-download-failed",
                        "message": str(exc)[:400]}, terminal_at=_utc_now())
            print("  DOWNLOAD FAILED %s: %s" % (label, exc))
            continue

        try:
            idx_ds, bsi = _load_composite(target)
            ref = idx_ds[list(idx_ds.data_vars)[0]]
            month = int(item.observed_on[5:7])
            means, stds = {}, {}
            for name in INDICES:
                if name not in idx_ds:
                    continue
                try:
                    mean, std = load_baseline_pair(name, month, generation=baseline)
                except FileNotFoundError:
                    continue
                means[name] = mean.reindex_like(ref, method="nearest", tolerance=15)
                stds[name] = std.reindex_like(ref, method="nearest", tolerance=15)
            if not means:
                raise RuntimeError("no baseline raster for month %d" % month)
            detection = detect_deforestation(idx_ds, means, stds, spi_3month=None)
            quality = assess_scene_quality(
                detection, minimum_required_fraction=args.min_clear / 100.0,
                anomaly_reject_fraction=SCENE_ANOMALY_REJECT_FRAC)
        except Exception as exc:
            ledger.record_terminal(
                acquisition_id=item.acquisition_id, status="failed_processing",
                reason={"code": "detection-failed", "message": str(exc)[:400]},
                terminal_at=_utc_now())
            print("  PROCESSING FAILED %s: %s" % (label, exc))
            continue

        artifact = _sha256_file(target)
        if quality.scene_decision != "accepted":
            status, reason = gate_rejection(quality)
            ledger.record_terminal(
                acquisition_id=item.acquisition_id, status=status,
                reason=reason, terminal_at=_utc_now())
            print("  %s %s  (coverage %.1f%%)"
                  % (status, label, 100 * quality.valid_coverage_fraction))
            continue

        frame = vectorize_alerts(detection["confidence"])
        if not frame.empty:
            frame["scene_decision"] = quality.scene_decision
            frame["valid_coverage_fraction"] = quality.valid_coverage_fraction
            frame["minimum_required_fraction"] = quality.minimum_required_fraction
            frame["scene_alert_fraction"] = quality.alert_fraction_of_valid
            frame["scene_qa_flags"] = "|".join(quality.qa_flags)
            frame["scene_rejection_reason"] = quality.rejection_reason
            frame["source_datatake_id"] = item.acquisition.datatake_id
            frame["source_platform"] = item.acquisition.platform
            frame["source_acquisition_id_v3"] = item.acquisition_id
            try:
                frame = annotate_alerts_all_collections(
                    frame, default_collection=DEFAULT_LANDCOVER_COLLECTION)
            except Exception as exc:
                print("     land-cover annotation failed (%s)" % exc)
            frames_by_date.setdefault(item.observed_on, []).append(frame)
        # The terminal row waits for persistence: observation IDs are minted
        # there, and complete_with_alerts requires them.
        item_state = {"artifact_sha256": artifact, "quality": quality,
                      "n": 0 if frame.empty else len(frame)}
        _CARRY[item.acquisition_id] = item_state
        print("  detected  %s  (%d polygon(s), coverage %.1f%%)"
              % (label, 0 if frame.empty else len(frame),
                 100 * quality.valid_coverage_fraction))

    # ── per UTC date: persistence once, then the terminal rows it minted ─────
    state = load_persistence_state(Path(args.state_path)) if Path(args.state_path).exists() else None
    accepted_ids = set(_CARRY)
    for date in sorted({i.observed_on for i in screened}):
        flush_rows()
        day_items = [i for i in screened if i.observed_on == date
                     and i.acquisition_id in accepted_ids
                     and i.acquisition_id not in already]
        if not day_items:
            continue
        frames = frames_by_date.get(date, [])
        scene_ids = sorted({s for i in day_items for s in i.acquisition.scene_ids})
        acq_v1 = create_acquisition_identity(
            collection_id=manifest["collection_id"],
            observed_on=date, scene_ids=scene_ids,
            monitoring_extent_id=MONITORING_EXTENT_ID,
            # the replay's method, not blue's: the contribution key hashes it,
            # so a replay contribution can never collide with a live one.
            composite_method_id=decision.composite_method_id)
        if frames:
            merged = gpd.GeoDataFrame(
                pd.concat(frames, ignore_index=True), crs=frames[0].crs)
            try:
                merged, state = update_tracks(
                    merged, state, date, acquisition=acq_v1,
                    algorithm_version=DETECTION_ALGORITHM_VERSION,
                    baseline_version=baseline.version,
                    monitoring_extent_id=MONITORING_EXTENT_ID, mode="rebuild",
                    min_overlap_frac=overlap.min_overlap_fraction)
            except AmbiguousLineageError as exc:
                # The accepted Package 2A.1 contract says ambiguous
                # many-to-many split/merge components "fail closed for
                # reviewed correction", and no reviewed-correction mechanism
                # exists yet.  So this date cannot be given event lineage
                # under the frozen rules.
                #
                # It is recorded, not skipped.  `failed_processing` is one of
                # the seven terminal statuses precisely for this, and roadmap
                # bullet 4 names it; the exit gate needs one terminal row per
                # expected acquisition, and a date silently dropped would
                # leave the gate unclosable while looking complete.  The blue
                # path does drop it — `run_detection_from_gee.py` catches
                # every exception around its per-date block and continues —
                # which is why production never stopped on this and why its
                # time-series carries fewer dates than were observed.
                #
                # Nothing is loosened here: `state` is unchanged because the
                # assignment never happened, no alerts are saved for the date,
                # and no science parameter is touched.  The reviewed
                # correction is Phase 5's, and it now has the exact list.
                status, reason = lineage_failure(exc)
                for i in day_items:
                    ledger.record_terminal(
                        acquisition_id=i.acquisition_id,
                        status=status, reason=reason,
                        terminal_at=_utc_now())
                print("  AMBIGUOUS LINEAGE %s: %d acquisition(s) recorded "
                      "failed_processing (%s)" % (date, len(day_items), exc))
                continue
            save_alerts(merged, date, alerts_dir=alerts_dir)
            print("  date %s: %d alert(s) from %d acquisition(s)"
                  % (date, len(merged), len(day_items)))
        else:
            merged = None
            print("  date %s: zero alerts from %d acquisition(s)" % (date, len(day_items)))
        for i in day_items:
            carry = _CARRY[i.acquisition_id]
            if merged is not None and carry["n"]:
                mine = merged[merged["source_acquisition_id_v3"] == i.acquisition_id]
                observation_ids = _observation_ids(
                    mine, i, DETECTION_ALGORITHM_VERSION, baseline.version,
                    _utc_now())
            else:
                observation_ids = []
            ledger.record_terminal(
                acquisition_id=i.acquisition_id,
                status="complete_with_alerts" if observation_ids else "complete_zero_alerts",
                observation_ids=observation_ids, terminal_at=_utc_now(),
                artifact_sha256=carry["artifact_sha256"])

    if state is not None:
        save_persistence_state(state, Path(args.state_path))

    # Rows accumulate ACROSS batches. The ledger is bound to the whole
    # window's 107 expected acquisitions and ``to_dict`` refuses to serialize
    # until every one of them is terminal — measured, not assumed: the first
    # batch of this driver raised IncompleteDateError here, which is the guard
    # working. So each batch appends its rows and only the batch that completes
    # the set writes ledger.json.
    flush_rows()

    finding = reconciles(expected=acquisitions, rows=rows_by_id)
    print()
    print("batch rows    : %d" % len(ledger.terminal_rows))
    print("rows on disk  : %d of %d expected" % (finding["terminal"], finding["expected"]))
    print("reconciles    : %s" % finding["complete"])
    print("screen (window): %s" % json.dumps(screen_summary(screened_all)))
    (out / "reconciliation.json").write_text(
        json.dumps(finding, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if finding["complete"]:
        whole = ProcessingLedgerV3(
            run_manifest_id=manifest["run_manifest_id"],
            run_manifest_sha256=manifest["run_manifest_sha256"],
            acquisitions=acquisitions,
            monitoring_extent_id=manifest["monitoring_extent_id"],
            algorithm_version=DETECTION_ALGORITHM_VERSION,
            created_at=_utc_now())
        for row in sorted(rows_by_id.values(),
                          key=lambda r: (r["acquisition_timestamp_utc"],
                                         r["acquisition_id"])):
            whole.record_terminal(
                acquisition_id=row["acquisition_id"], status=row["status"],
                observation_ids=row["output"]["observation_ids"],
                reason=row["reason"], terminal_at=row["terminal_at"],
                artifact_sha256=row["output"]["artifact_sha256"])
        document = whole.to_dict()
        (out / "ledger.json").write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print("ledger        : %s  -> %s" % (document["ledger_id"], out / "ledger.json"))
    else:
        print("ledger        : not serialized; %d acquisition(s) still to process"
              % len(finding["missing"]))
    return 0


#: Per-acquisition carry between the two passes.  Module level so the two
#: loops share it without threading a parameter through every branch.
_CARRY: dict = {}


def _read_rows(path) -> dict:
    """Terminal rows accumulated by earlier batches, keyed by acquisition."""
    if not Path(path).exists():
        return {}
    return {
        row["acquisition_id"]: row
        for row in json.loads(Path(path).read_text(encoding="utf-8"))
    }


def _write_rows(path, rows_by_id) -> None:
    ordered = sorted(rows_by_id.values(),
                     key=lambda r: (r["acquisition_timestamp_utc"],
                                    r["acquisition_id"]))
    Path(path).write_text(
        json.dumps(ordered, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256_file(path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _observation_ids(frame, item, algorithm_version, baseline_version, created_at):
    """Mint obs-v3 IDs for one acquisition's share of a date's alerts.

    The area is taken from the frame's own metric geometry rather than
    recomputed here: two areas for one polygon is two answers to one question.
    """
    from src.detection.identity_v3 import create_observation_v3

    wgs84 = frame if str(frame.crs) == "EPSG:4326" else frame.to_crs("EPSG:4326")
    areas = (frame["area_ha"] if "area_ha" in frame.columns
             else frame.to_crs("EPSG:32724").geometry.area / 10000.0)
    ids = []
    for geometry, area_ha in zip(wgs84.geometry, list(areas)):
        observation = create_observation_v3(
            acquisition=item.acquisition,
            geometry=geometry,
            algorithm_version=algorithm_version,
            baseline_version=baseline_version,
            area_ha=float(area_ha),
            created_at=created_at,
        )
        ids.append(observation.observation_id)
    return ids


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "run"):
        p = sub.add_parser(name)
        p.add_argument("--project", default="ee-araripe")
        p.add_argument("--start", required=True)
        p.add_argument("--end", required=True, help="exclusive")
        p.add_argument("--max-cloud", type=int, default=60)
        p.add_argument("--min-clear", type=float, default=20.0)
        p.add_argument("--out-dir", required=True)
        p.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
        if name == "run":
            p.add_argument("--state-path", required=True,
                           help="isolated persistence state; rebuild mode requires it")
            p.add_argument("--baseline-version", default="2.1.0")
            p.add_argument("--batch-start", required=True,
                           help="first UTC date of this bounded batch, inclusive")
            p.add_argument("--batch-end", required=True,
                           help="one past the last UTC date of this batch")
    args = parser.parse_args(argv)
    if args.command == "plan":
        return command_plan(args)
    return command_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
