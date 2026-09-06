"""Execute the Earth Engine half of the baseline 2.0.0 rebuild (Package 2A.6C).

This is the production-scale executor that
``src/processing/baseline_rebuild_v2.py`` anticipates: it derives every plan
from Earth Engine ``reduceRegion`` counts, with no local pixels, and consumes —
never redefines — the closed science:

- the effective reviewed-baseline registry through
  ``load_baseline_rebuild_registry`` (a recorded review, never a fallback);
- the deterministic rebuild plan and its v3 run-manifest binding through
  ``build_baseline_rebuild_plan`` / ``run_manifest_binding_from_plan``;
- the per-datatake execution plan through ``build_rebuild_gee_plan`` with
  ``count_source="gee_reduce_region"``;
- ``scl-explicit-allowlist-v2`` (accept SCL 4/5/6/7 only) and
  ``coverage-ranked-first-valid-v1`` exactly as the plan states them; and
- v3 acquisition identities through ``create_acquisition_v3``, so the platform
  gate is the contract's, not this script's.

Deliberately separate from the v1 ``scripts/build_baseline_gee.py``, which
stays byte-unchanged audit material for the accepted 1.0.0 generation.

Two Earth Engine behaviours are corrected here rather than inherited:

- **Division by zero.** Earth Engine returns ``0`` — a perfectly valid index
  value — where an index denominator is zero, instead of a non-finite result.
  The accepted policy is
  ``nonfinite_index_values_become_missing_and_are_counted``, so every index
  denominator is tested explicitly and a zero denominator is masked away. Left
  uncorrected, a degenerate pixel would enter the median and the dispersion as
  a real observation of exactly 0.
- **Mosaic priority.** ``mosaic()`` keeps the *last* valid image per pixel, so
  the images are supplied in the plan's ``mosaic_input_order``, which is the
  reverse of ``first_valid_order``.
- **Non-deterministic histogram.** ``ee.Reducer.frequencyHistogram`` returned
  different totals for the same composite on repeated evaluation at this
  region size, so contributor accounting uses exact integer indicator sums,
  which were byte-stable across trials.
- **Reduction totals are not pixel identities.** Two independently reduced
  sums over the same 54-megapixel composite differ by a couple of pixels at
  tile boundaries. Every integrity identity is therefore evaluated *per pixel*
  inside a single expression and only then reduced, which is exact and needs
  no tolerance.

Phases (each resumable; state in the evidence directory):

    enumerate Phase 1 (metadata) — enumerate source scenes regime by regime
    counts    Phase 1 (counts) — per-scene valid-pixel counts under the v2 mask
    export    Phase 2 — plans, reconciliation, monthly statistics, 12 exports
    tasks     poll the export tasks
    fetch     Phase 3 — download one monthly export from the v2 Drive folder
    evidence  Phase 3 — assemble the execution evidence for the manifest CLI

Nothing here writes to R2, dispatches a workflow, touches production, or reads
the immutable baseline 1.0.0.
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import (  # noqa: E402
    BASELINE_MAX_CLOUD_COVER,
    BASELINE_SOURCE_YEARS,
    GEE_COLLECTION_ID,
)
from src.detection.baseline_manifest import (  # noqa: E402
    MONITORING_EXTENT_BOUNDS,
    MONITORING_EXTENT_ID,
)
from src.detection.baseline_manifest_v2 import (  # noqa: E402
    BASELINE_V2_COUNTS_LOCAL_DIR,
    BASELINE_V2_EXPORTS_LOCAL_DIR,
    require_baseline_v1_untouched,
)
from src.detection.identity_v3 import create_acquisition_v3  # noqa: E402
from src.processing.composition_v2 import (  # noqa: E402
    COMPOSITION_METHOD_ID,
    normalize_platform,
)
from src.processing.scl_mask_v2 import (  # noqa: E402
    SCL_ACCEPTED_CLASSES,
    normalize_processing_baseline_value,
)
from src.processing.baseline_rebuild_v2 import (  # noqa: E402
    BASELINE_V2_DRIVE_FOLDER,
    BASELINE_V2_EXPORT_PREFIX,
    BASELINE_V2_GRID_CONTRACT,
    BASELINE_V2_GRID_ID,
    COUNT_EXPORT_FILL,
    REBUILD_BAND_NAMES,
    REBUILD_EXPORT_BAND_NAMES,
    REBUILD_INDEX_NAMES,
    REFLECTANCE_SCALE_DIVISOR,
    STATISTIC_EXPORT_SENTINEL,
    baseline_query_fingerprint,
    build_baseline_rebuild_plan,
    build_rebuild_gee_plan,
    load_source_regimes,
    month_export_filename,
    regime_for_month,
    run_manifest_binding_from_plan,
    union_registry,
)

PROJECT_ID = "ee-araripe-baseline-v2"
STATE_PATH = BASELINE_V2_COUNTS_LOCAL_DIR.parent / "rebuild_state.json"
ENUMERATION_PATH = (
    BASELINE_V2_COUNTS_LOCAL_DIR.parent / "source_enumeration.json"
)
SCENE_PROPERTIES = (
    "system:index",
    "PRODUCT_ID",
    "DATATAKE_IDENTIFIER",
    "SPACECRAFT_NAME",
    "PROCESSING_BASELINE",
    "MGRS_TILE",
    "CLOUDY_PIXEL_PERCENTAGE",
)


class ExecutorError(click.ClickException):
    """The rebuild execution violates the Package 2A.6C contract."""


# ─── shared setup ────────────────────────────────────────────────────────────


def _init_ee():
    import ee

    ee.Initialize(project=PROJECT_ID)
    return ee


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"scene_counts": {}, "datatakes": {}, "tasks": {}}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(STATE_PATH)


def _regimes():
    """The accepted seasonal source regimes (Package 2A.6C.1)."""

    return load_source_regimes()


def _load_enumeration() -> dict:
    if not ENUMERATION_PATH.exists():
        raise ExecutorError(
            f"no source enumeration at {ENUMERATION_PATH}; run the enumerate "
            "phase first"
        )
    return json.loads(ENUMERATION_PATH.read_text(encoding="utf-8"))


def _admitted_datatakes(regimes) -> list[dict]:
    """Datatakes whose every scene is reviewed **by its own month's regime**.

    A datatake that mixes admitted and rejected baselines fails closed: the
    composition is scoped to one physical datatake and the mask is undefined
    for a scene with an unreviewed baseline, so a partial datatake is not a
    smaller valid input — it is an invalid one.
    """

    enumeration = _load_enumeration()
    admitted, mixed = [], []
    for entry in enumeration["datatakes"]:
        regime = regime_for_month(regimes, entry["month"])
        effective = set(regime.registry.effective_values)
        observed = set(entry["observed_processing_baselines"])
        if observed <= effective:
            admitted.append({**entry, "source_regime": regime.regime_id})
        elif observed & effective:
            mixed.append(entry)
    if mixed:
        raise ExecutorError(
            f"{len(mixed)} datatake(s) mix reviewed and unreviewed processing "
            "baselines under their own month's regime; the datatake-scoped "
            "composition cannot admit a subset of one physical acquisition"
        )
    admitted.sort(key=lambda e: (e["acquisition_timestamp_utc"], e["datatake_id"]))
    return admitted


def _grid_kwargs() -> dict:
    return {
        "crs": BASELINE_V2_GRID_CONTRACT["crs"],
        "crsTransform": list(BASELINE_V2_GRID_CONTRACT["transform"]),
    }


def _region(ee):
    return ee.Geometry.Rectangle(list(MONITORING_EXTENT_BOUNDS), None, False)


def _valid_mask(ee, scene_id):
    """The ONE shared per-image mask the plan requires.

    ``scl-explicit-allowlist-v2`` intersected with every reflectance band's
    own mask, so ``mosaic()`` can never mix bands of one pixel across scenes.
    """

    image = ee.Image(f"{GEE_COLLECTION_ID}/{scene_id}")
    scl = image.select("SCL")
    accepted = scl.eq(SCL_ACCEPTED_CLASSES[0])
    for value in SCL_ACCEPTED_CLASSES[1:]:
        accepted = accepted.Or(scl.eq(value))
    band_mask = image.select(list(REBUILD_BAND_NAMES)).mask().reduce(
        ee.Reducer.min()
    )
    return accepted.And(band_mask).rename("valid")


def _masked_bands(ee, scene_id):
    image = ee.Image(f"{GEE_COLLECTION_ID}/{scene_id}")
    return image.select(list(REBUILD_BAND_NAMES)).updateMask(
        _valid_mask(ee, scene_id)
    )


def _retry(fn, *, attempts: int = 5, label: str = ""):
    delay = 4.0
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - EE raises many transport types
            if attempt == attempts:
                raise ExecutorError(f"{label}: {exc}") from exc
            time.sleep(delay)
            delay *= 2
    raise AssertionError("unreachable")


# ─── Phase 1 (resumed): per-scene valid-pixel counts ─────────────────────────


def _count_datatake(ee, entry: dict) -> dict[str, int]:
    """One reduceRegion pass returning every scene count of one datatake."""

    scene_ids = [scene["scene_id"] for scene in entry["scenes"]]
    stack = ee.Image.cat(
        [
            _valid_mask(ee, scene_id).unmask(0).rename(f"s{position}")
            for position, scene_id in enumerate(scene_ids)
        ]
    )
    got = _retry(
        lambda: stack.reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=_region(ee),
            maxPixels=int(1e10),
            bestEffort=False,
            **_grid_kwargs(),
        ).getInfo(),
        label=f"count {entry['datatake_id']}",
    )
    return {
        scene_id: int(round(got[f"s{position}"]))
        for position, scene_id in enumerate(scene_ids)
    }


@click.group()
def cli() -> None:
    """Earth Engine executor for the baseline 2.0.0 rebuild."""


@cli.command("enumerate")
def enumerate_cmd() -> None:
    """Phase 1 (metadata): enumerate the source scenes regime by regime.

    Each regime is queried with **its own** scene cloud filter, so the wet
    season is enumerated at its filter and the dry season at the accepted
    default. The result is the input to every later phase.
    """

    ee = _init_ee()
    regimes = _regimes()
    aoi = _region(ee)
    records: list[dict] = []
    for regime in regimes:
        click.echo(
            f"regime {regime.regime_id}: months {list(regime.months)}, "
            f"cloud <{regime.scene_cloud_filter_percent}"
        )
        for year in BASELINE_SOURCE_YEARS:
            for month in regime.months:
                start = ee.Date.fromYMD(year, month, 1)
                collection = (
                    ee.ImageCollection(GEE_COLLECTION_ID)
                    .filterBounds(aoi)
                    .filterDate(start, start.advance(1, "month"))
                    .filter(
                        ee.Filter.lt(
                            "CLOUDY_PIXEL_PERCENTAGE",
                            regime.scene_cloud_filter_percent,
                        )
                    )
                )
                rows = _retry(
                    lambda c=collection: c.reduceColumns(
                        ee.Reducer.toList(len(SCENE_PROPERTIES), 1),
                        list(SCENE_PROPERTIES),
                    ).getInfo().get("list", []),
                    label=f"enumerate {year}-{month:02d}",
                )
                for row in rows:
                    record = dict(zip(SCENE_PROPERTIES, row))
                    record["year"] = year
                    record["month"] = month
                    record["source_regime"] = regime.regime_id
                    records.append(record)
            click.echo(f"  {year}: {sum(1 for r in records if r['year'] == year)} scenes")

    # Group into physical datatakes. The acquisition timestamp is the datatake
    # instant embedded in the identifier, never system:time_start, which is the
    # per-granule instant and disagrees with it for every scene.
    grouped: dict[tuple[str, str], list[dict]] = {}
    for record in records:
        platform = normalize_platform(record["SPACECRAFT_NAME"])
        grouped.setdefault((platform, record["DATATAKE_IDENTIFIER"]), []).append(record)

    datatakes = []
    for (platform, datatake_id), rows in sorted(grouped.items(), key=lambda kv: kv[0][1]):
        instant = datetime.strptime(
            datatake_id.split("_")[1], "%Y%m%dT%H%M%S"
        ).replace(tzinfo=timezone.utc)
        baselines = sorted(
            {
                normalize_processing_baseline_value(
                    row["PROCESSING_BASELINE"],
                    source_field="GEE PROCESSING_BASELINE",
                )
                for row in rows
            }
        )
        datatakes.append(
            {
                "platform": platform,
                "datatake_id": datatake_id,
                "acquisition_timestamp_utc": instant.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "year": instant.year,
                "month": instant.month,
                "source_regime": rows[0]["source_regime"],
                "scene_count": len(rows),
                "observed_processing_baselines": baselines,
                "scenes": [
                    {
                        "scene_id": row["system:index"],
                        "product_id": row["PRODUCT_ID"],
                        "processing_baseline": normalize_processing_baseline_value(
                            row["PROCESSING_BASELINE"],
                            source_field="GEE PROCESSING_BASELINE",
                        ),
                        "mgrs_tile": row["MGRS_TILE"],
                        "cloudy_pixel_percentage": row["CLOUDY_PIXEL_PERCENTAGE"],
                    }
                    for row in sorted(
                        rows, key=lambda r: r["system:index"].encode("utf-8")
                    )
                ],
            }
        )

    document = {
        "enumeration_version": "phase2a6c1-source-enumeration-v1",
        "collection_id": GEE_COLLECTION_ID,
        "years": list(BASELINE_SOURCE_YEARS),
        "monitoring_extent_id": MONITORING_EXTENT_ID,
        "source_regimes": [regime.regime_dict() for regime in regimes],
        "totals": {
            "scene_count": len(records),
            "datatake_count": len(datatakes),
        },
        "datatakes": datatakes,
    }
    ENUMERATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENUMERATION_PATH.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    click.echo(
        f"\n{len(records)} scenes / {len(datatakes)} datatakes -> {ENUMERATION_PATH}"
    )
    admitted = _admitted_datatakes(regimes)
    click.echo(
        f"admitted under their own regime: {len(admitted)} datatakes / "
        f"{sum(e['scene_count'] for e in admitted)} scenes"
    )


@cli.command("counts")
@click.option("--workers", default=6, show_default=True, type=int)
@click.option("--limit", default=0, type=int, help="Stop after N datatakes (0 = all).")
def counts_cmd(workers: int, limit: int) -> None:
    """Phase 1 (resumed): per-scene valid-pixel counts under the v2 mask."""

    ee = _init_ee()
    regimes = _regimes()
    for regime in regimes:
        click.echo(
            f"regime {regime.regime_id}: months {list(regime.months)} "
            f"cloud <{regime.scene_cloud_filter_percent} "
            f"registry {list(regime.registry.effective_values)}"
        )
    admitted = _admitted_datatakes(regimes)
    state = _load_state()
    todo = [e for e in admitted if e["datatake_id"] not in state["scene_counts"]]
    if limit:
        todo = todo[:limit]
    click.echo(
        f"{len(admitted)} admitted datatakes; {len(todo)} still to count "
        f"({len(state['scene_counts'])} already done)"
    )
    if not todo:
        return
    done = 0
    started = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_count_datatake, ee, entry): entry for entry in todo
        }
        for future in as_completed(futures):
            entry = futures[future]
            state["scene_counts"][entry["datatake_id"]] = future.result()
            done += 1
            if done % 10 == 0 or done == len(todo):
                _save_state(state)
                rate = done / max(time.time() - started, 1e-9)
                click.echo(
                    f"  counted {done}/{len(todo)} "
                    f"({rate * 60:.1f}/min, {len(todo) - done} left)"
                )
    _save_state(state)
    total = sum(
        len(v) for v in state["scene_counts"].values()
    )
    click.echo(f"done: {len(state['scene_counts'])} datatakes, {total} scenes")


# ─── Phase 2: plans, reconciliation, composition, statistics, export ─────────


def _datatake_plan(entry: dict, counts: dict[str, int]) -> dict:
    return build_rebuild_gee_plan(
        image_collection_id=GEE_COLLECTION_ID,
        platform=entry["platform"],
        datatake_id=entry["datatake_id"],
        band_names=REBUILD_BAND_NAMES,
        valid_pixel_counts=counts,
        observed_processing_baselines=entry["observed_processing_baselines"],
        count_source="gee_reduce_region",
    )


def _composite(ee, plan: dict):
    """Compose one datatake strictly in the plan's reversed order.

    Returns the composed reflectance bands plus the contributor-rank band, so
    contributor accounting is reconciled from the same construction that
    produces the pixels.
    """

    first_valid_order = list(plan["first_valid_order"])
    layers = []
    for rank, scene_id in enumerate(first_valid_order):
        valid = _valid_mask(ee, scene_id)
        rank_band = (
            ee.Image.constant(rank).toInt16().rename("contributor_rank")
            .updateMask(valid)
        )
        layers.append(_masked_bands(ee, scene_id).addBands(rank_band))
    # mosaic() keeps the LAST valid image per pixel, so the most-preferred
    # scene of first_valid_order must be supplied last.
    ordered = [layers[first_valid_order.index(s)] for s in plan["mosaic_input_order"]]
    return ee.ImageCollection.fromImages(ordered).mosaic()


def _verification_evidence(body: dict) -> dict:
    """Bind one datatake's reconciliation evidence under its own checksum."""

    from src.detection.identity import canonical_sha256

    return {**body, "evidence_sha256": canonical_sha256(body)}


def _reconcile(ee, entry: dict, plan: dict) -> dict:
    """Recompute the plan's counts from the images actually composed.

    Every quantity is an exact integer indicator sum. ``frequencyHistogram``
    was measured to be non-deterministic at this region size (it returned
    different totals for the same input on repeated evaluation, while the
    indicator sums were byte-stable), so contributor accounting is derived the
    same way the per-scene counts are.
    """

    first_valid_order = list(plan["first_valid_order"])
    composite = _composite(ee, plan)
    contributor = composite.select("contributor_rank")

    bands = [
        _valid_mask(ee, scene_id).unmask(0).rename(f"r{position}")
        for position, scene_id in enumerate(first_valid_order)
    ]
    bands += [
        contributor.eq(rank).unmask(0).rename(f"c{rank}")
        for rank in range(len(first_valid_order))
    ]
    composed_mask = contributor.gte(0).unmask(0)
    bands.append(composed_mask.rename("composed"))
    # The partition identity is evaluated PER PIXEL inside one expression and
    # only then reduced. Reducing each side separately and comparing totals is
    # not equivalent: Earth Engine resolves two independent reductions of the
    # same 54-megapixel composite to within a couple of pixels at tile
    # boundaries, which is a property of the reduction, not of the composite.
    # Per pixel the identity is exact, so this gate needs no tolerance.
    counted = contributor.eq(0).unmask(0)
    for rank in range(1, len(first_valid_order)):
        counted = counted.add(contributor.eq(rank).unmask(0))
    bands.append(counted.neq(composed_mask).rename("partition_anomaly"))
    stack = ee.Image.cat(bands)
    got = _retry(
        lambda: stack.reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=_region(ee),
            maxPixels=int(1e10),
            bestEffort=False,
            **_grid_kwargs(),
        ).getInfo(),
        label=f"reconcile {entry['datatake_id']}",
    )
    recomputed = {
        scene_id: int(round(got[f"r{position}"]))
        for position, scene_id in enumerate(first_valid_order)
    }
    expected = dict(plan["expected_scene_valid_pixel_counts"])
    if recomputed != expected:
        raise ExecutorError(
            f"{entry['datatake_id']}: recomputed valid-pixel counts disagree "
            f"with the plan. expected={expected} recomputed={recomputed}"
        )
    ranks = {
        rank: int(round(got[f"c{rank}"]))
        for rank in range(len(first_valid_order))
    }
    composed = int(round(got["composed"]))
    anomalies = int(round(got["partition_anomaly"]))
    if anomalies != 0:
        raise ExecutorError(
            f"{entry['datatake_id']}: {anomalies} pixel(s) are not covered by "
            "exactly one contributor rank; the rank map is not an exhaustive "
            "disjoint partition of the composite"
        )
    top = first_valid_order[0]
    if ranks[0] != expected[top]:
        raise ExecutorError(
            f"{entry['datatake_id']}: the first-ranked scene {top} contributed "
            f"{ranks[0]} pixels but its valid count is {expected[top]}; the "
            "mosaic did not honour the plan's first-valid priority"
        )
    for rank, scene_id in enumerate(first_valid_order):
        if ranks[rank] > expected[scene_id]:
            raise ExecutorError(
                f"{entry['datatake_id']}: scene {scene_id} contributed "
                f"{ranks[rank]} pixels but only {expected[scene_id]} are valid"
            )
    return {
        "counts_reconciled": True,
        "contributor_accounting_reconciled": True,
        "kind": "gee_recomputed_counts_and_contributor_partition",
        "composed_pixel_count": composed,
        "partition_anomaly_pixels": anomalies,
        "contributor_partition_reduction_residual": (
            sum(ranks.values()) - composed
        ),
        "contributor_rank_pixels": {
            str(rank): ranks[rank] for rank in sorted(ranks)
        },
        "recomputed_scene_valid_pixel_counts": recomputed,
    }


def _indices(ee, composite):
    """Indices on composed bands, with the accepted non-finite policy.

    Earth Engine returns 0 for a division by zero, which is a valid index
    value; the accepted policy makes a non-finite result *missing*. Every
    denominator is therefore tested explicitly and a zero denominator masked.
    """

    r = composite.select(list(REBUILD_BAND_NAMES)).divide(REFLECTANCE_SCALE_DIVISOR)
    b4, b8 = r.select("B4"), r.select("B8")
    b8a, b11, b12 = r.select("B8A"), r.select("B11"), r.select("B12")

    ndmi_den = b8a.add(b11)
    nbr_den = b8a.add(b12)
    evi2_den = b8.add(b4.multiply(2.4)).add(1.0)

    ndmi = b8a.subtract(b11).divide(ndmi_den).updateMask(ndmi_den.neq(0)).rename("ndmi")
    nbr = b8a.subtract(b12).divide(nbr_den).updateMask(nbr_den.neq(0)).rename("nbr")
    evi2 = (
        b8.subtract(b4).multiply(2.5).divide(evi2_den)
        .updateMask(evi2_den.neq(0)).rename("evi2")
    )
    return ee.Image.cat([ndmi, nbr, evi2]).toFloat()


def _monthly_image(ee, composites: list):
    collection = ee.ImageCollection.fromImages(composites)
    median = collection.median()
    std = collection.reduce(ee.Reducer.stdDev())
    count = collection.reduce(ee.Reducer.count())
    stats = ee.Image.cat(
        [
            median.select("ndmi").rename("ndmi_median"),
            median.select("nbr").rename("nbr_median"),
            median.select("evi2").rename("evi2_median"),
            std.select("ndmi_stdDev").rename("ndmi_std"),
            std.select("nbr_stdDev").rename("nbr_std"),
            std.select("evi2_stdDev").rename("evi2_std"),
        ]
    ).unmask(STATISTIC_EXPORT_SENTINEL)
    counts = ee.Image.cat(
        [
            count.select("ndmi_count").rename("ndmi_count"),
            count.select("nbr_count").rename("nbr_count"),
            count.select("evi2_count").rename("evi2_count"),
        ]
    ).unmask(COUNT_EXPORT_FILL)
    combined = stats.addBands(counts).toFloat()
    return combined.select(list(REBUILD_EXPORT_BAND_NAMES))


@cli.command("export")
@click.option("--months", default="1,2,3,4,5,6,7,8,9,10,11,12", show_default=True)
@click.option("--workers", default=6, show_default=True, type=int)
@click.option("--dry-run", is_flag=True, help="Reconcile only; start no task.")
def export_cmd(months: str, workers: int, dry_run: bool) -> None:
    """Phase 2: derive plans, reconcile, and export one image per month."""

    ee = _init_ee()
    v1 = require_baseline_v1_untouched()
    click.echo(f"baseline 1.0.0 verified untouched ({v1})")

    regimes = _regimes()
    plan = build_baseline_rebuild_plan(regimes=regimes)
    run_manifest_id, plan_sha256 = run_manifest_binding_from_plan(plan)
    click.echo(f"rebuild plan {plan_sha256}")
    click.echo(f"run manifest {run_manifest_id}")
    for regime in regimes:
        click.echo(
            f"  regime {regime.regime_id}: months {list(regime.months)} "
            f"cloud <{regime.scene_cloud_filter_percent}"
        )

    admitted = _admitted_datatakes(regimes)
    state = _load_state()
    missing = [
        e["datatake_id"] for e in admitted
        if e["datatake_id"] not in state["scene_counts"]
    ]
    if missing:
        raise ExecutorError(
            f"{len(missing)} admitted datatake(s) have no Phase 1 counts; run "
            "the counts phase first"
        )

    wanted = [int(m) for m in months.split(",") if m.strip()]
    by_month: dict[int, list[dict]] = {m: [] for m in wanted}
    for entry in admitted:
        if entry["month"] in by_month:
            by_month[entry["month"]].append(entry)

    # Build every per-datatake plan first, then reconcile in parallel.
    plans: dict[str, dict] = {}
    for entry in admitted:
        if entry["month"] not in by_month:
            continue
        counts = state["scene_counts"][entry["datatake_id"]]
        plans[entry["datatake_id"]] = _datatake_plan(entry, counts)

    todo = [
        e for e in admitted
        if e["month"] in by_month
        and e["datatake_id"] not in state["datatakes"]
    ]
    click.echo(f"reconciling {len(todo)} datatake(s) ...")
    done = 0
    started = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_reconcile, ee, e, plans[e["datatake_id"]]): e
            for e in todo
        }
        for future in as_completed(futures):
            entry = futures[future]
            verification = future.result()
            dt_plan = plans[entry["datatake_id"]]
            acquisition = create_acquisition_v3(
                run_manifest_id=run_manifest_id,
                run_manifest_sha256=plan_sha256,
                collection_id=GEE_COLLECTION_ID,
                platform=entry["platform"],
                datatake_id=entry["datatake_id"],
                acquisition_timestamp_utc=entry["acquisition_timestamp_utc"],
                scene_ids=[s["scene_id"] for s in entry["scenes"]],
                monitoring_extent_id=MONITORING_EXTENT_ID,
                composite_method_id=COMPOSITION_METHOD_ID,
                grid_id=BASELINE_V2_GRID_ID,
            )
            state["datatakes"][entry["datatake_id"]] = {
                "source_regime": regime_for_month(
                    regimes, entry["month"]
                ).regime_id,
                "acquisition_id": acquisition.acquisition_id,
                "platform": entry["platform"],
                "datatake_id": entry["datatake_id"],
                "acquisition_timestamp_utc": entry["acquisition_timestamp_utc"],
                "year": entry["year"],
                "month": entry["month"],
                "scene_count": entry["scene_count"],
                "scenes": [
                    {
                        "scene_id": s["scene_id"],
                        "processing_baseline": s["processing_baseline"],
                    }
                    for s in sorted(
                        entry["scenes"],
                        key=lambda z: z["scene_id"].encode("utf-8"),
                    )
                ],
                "valid_pixel_counts": {
                    k: dt_plan["expected_scene_valid_pixel_counts"][k]
                    for k in sorted(
                        dt_plan["expected_scene_valid_pixel_counts"],
                        key=lambda z: z.encode("utf-8"),
                    )
                },
                "valid_pixel_count_source": "gee_reduce_region",
                "gee_plan_sha256": dt_plan["gee_plan_sha256"],
                "gee_verification": verification,
            }
            done += 1
            if done % 10 == 0 or done == len(todo):
                _save_state(state)
                rate = done / max(time.time() - started, 1e-9)
                click.echo(
                    f"  reconciled {done}/{len(todo)} ({rate * 60:.1f}/min)"
                )
    _save_state(state)

    for month in wanted:
        entries = by_month[month]
        if not entries:
            raise ExecutorError(f"month {month:02d} has no admitted datatake")
        composites = [
            _indices(ee, _composite(ee, plans[e["datatake_id"]])) for e in entries
        ]
        image = _monthly_image(ee, composites)
        description = f"{BASELINE_V2_EXPORT_PREFIX}{month:02d}"
        click.echo(
            f"month {month:02d}: {len(entries)} datatake composites -> {description}"
        )
        if dry_run:
            continue
        task = ee.batch.Export.image.toDrive(
            image=image,
            description=description,
            folder=BASELINE_V2_DRIVE_FOLDER,
            fileNamePrefix=description,
            crs=BASELINE_V2_GRID_CONTRACT["crs"],
            crsTransform=str(list(BASELINE_V2_GRID_CONTRACT["transform"])),
            dimensions=(
                f"{BASELINE_V2_GRID_CONTRACT['width']}x"
                f"{BASELINE_V2_GRID_CONTRACT['height']}"
            ),
            maxPixels=int(1e10),
            fileFormat="GeoTIFF",
        )
        task.start()
        state["tasks"][str(month)] = {
            "task_id": task.id,
            "description": description,
            "datatake_count": len(entries),
            "started_utc": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        }
        _save_state(state)
        click.echo(f"   task {task.id}")
    _save_state(state)
    click.echo(f"\nbaseline 1.0.0 untouched: {require_baseline_v1_untouched()}")


@cli.command("tasks")
def tasks_cmd() -> None:
    """Poll the export tasks recorded in the state file."""

    ee = _init_ee()
    state = _load_state()
    if not state["tasks"]:
        click.echo("no task recorded")
        return
    status = {
        item["id"]: item
        for item in ee.data.getTaskList()
        if item["id"] in {v["task_id"] for v in state["tasks"].values()}
    }
    pending = 0
    for month in sorted(state["tasks"], key=int):
        record = state["tasks"][month]
        info = status.get(record["task_id"], {})
        st = info.get("state", "UNKNOWN")
        if st not in {"COMPLETED", "FAILED", "CANCELLED"}:
            pending += 1
        extra = f"  {info.get('error_message', '')}" if st == "FAILED" else ""
        click.echo(f"  month {int(month):02d} {record['task_id']}  {st}{extra}")
    click.echo(f"\n{pending} task(s) still running")


# ─── Phase 3 support: retrieve one monthly export from Drive ─────────────────


def _drive_service():
    """Build a Drive client from the owner's existing Earth Engine credential.

    No new credential and no broadened scope: the local interactive
    authentication already carries the Drive scope, and the export destination
    is the owner's own Drive folder.
    """

    import ee.oauth
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    stored = json.loads(
        Path("~/.config/earthengine/credentials").expanduser().read_text(
            encoding="utf-8"
        )
    )
    credentials = Credentials(
        None,
        refresh_token=stored["refresh_token"],
        token_uri=ee.oauth.TOKEN_URI,
        client_id=ee.oauth.CLIENT_ID,
        client_secret=ee.oauth.CLIENT_SECRET,
        scopes=stored.get("scopes"),
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


@cli.command("fetch")
@click.option("--month", type=int, required=True)
@click.option(
    "--out-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=str(BASELINE_V2_EXPORTS_LOCAL_DIR),
    show_default=True,
)
def fetch_cmd(month: int, out_dir: Path) -> None:
    """Download one monthly export from the isolated v2 Drive folder."""

    from googleapiclient.http import MediaIoBaseDownload

    if month not in range(1, 13):
        raise ExecutorError("--month must be 1..12")
    service = _drive_service()
    folders = service.files().list(
        q=(
            "mimeType='application/vnd.google-apps.folder' and "
            f"name='{BASELINE_V2_DRIVE_FOLDER}' and trashed=false"
        ),
        fields="files(id,name)",
    ).execute().get("files", [])
    if not folders:
        raise ExecutorError(
            f"no Drive folder named {BASELINE_V2_DRIVE_FOLDER}"
        )
    # Earth Engine races when many export tasks start together and can create
    # the destination folder more than once. Every such folder still carries
    # the canonical v2 name, so version isolation holds; what must stay
    # fail-closed is the *file*, which is searched across all of them and must
    # resolve to exactly one canonical name.
    prefix = f"{BASELINE_V2_EXPORT_PREFIX}{month:02d}"
    canonical = month_export_filename(month)
    found = []
    for folder in folders:
        for item in service.files().list(
            q=(
                f"'{folder['id']}' in parents and name contains '{prefix}' "
                "and trashed=false"
            ),
            fields="files(id,name,size,createdTime)",
        ).execute().get("files", []):
            if item["name"].startswith(prefix):
                found.append({**item, "folder_id": folder["id"]})
    if not found:
        raise ExecutorError(
            f"no export named {prefix}* in {BASELINE_V2_DRIVE_FOLDER}"
        )
    # A re-export leaves the superseded file in Drive under the same canonical
    # name. Which one to take is not a tiebreak to guess: the answer is the
    # file produced by the export task this run recorded, so candidates are
    # bound to that task by its start time. A month with no recorded task, or
    # more than one file after it, still fails closed.
    if len(found) > 1:
        record = _load_state()["tasks"].get(str(month))
        if record is None or not record.get("started_utc"):
            raise ExecutorError(
                f"month {month:02d} resolved to {len(found)} Drive files and "
                "no export task is recorded to disambiguate them"
            )
        started = record["started_utc"]
        fresh = [
            item for item in found if item.get("createdTime", "") >= started
        ]
        if len(fresh) != 1:
            raise ExecutorError(
                f"month {month:02d} resolved to {len(found)} Drive files, of "
                f"which {len(fresh)} were created after its recorded export "
                f"task started ({started}); exactly one is required"
            )
        superseded = [item for item in found if item not in fresh]
        click.echo(
            f"note: {len(superseded)} superseded Drive file(s) for month "
            f"{month:02d} left untouched"
        )
        found = fresh
    entry = found[0]
    if entry["name"] != canonical:
        raise ExecutorError(
            f"month {month:02d} Drive file is named {entry['name']!r}, not the "
            f"canonical {canonical!r}; a sharded or foreign file is never split "
            "into the v2 inventory"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / entry["name"]
    click.echo(
        f"downloading {entry['name']} ({int(entry.get('size', 0)) / 2**30:.2f} GiB)"
    )
    request = service.files().get_media(fileId=entry["id"])
    with open(target, "wb") as handle:
        downloader = MediaIoBaseDownload(handle, request, chunksize=64 * 1024 * 1024)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                click.echo(f"  {int(status.progress() * 100)}%", nl=False)
                click.echo("\r", nl=False)
    click.echo(f"\n-> {target} ({target.stat().st_size / 2**30:.2f} GiB)")



# ─── Phase 3 support: assemble the execution evidence for the manifest ───────


@cli.command("evidence")
@click.option(
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    default="data/baselines_v2/2.0.0_evidence/rebuild_execution_evidence.json",
    show_default=True,
)
def evidence_cmd(output: Path) -> None:
    """Assemble the execution-evidence JSON the manifest CLI consumes."""

    import numpy as np
    import rasterio

    from src.detection.identity import canonical_sha256
    from src.detection.baseline_manifest_v2 import (
        BASELINE_V2_LOCAL_DIR,
        BASELINE_V2_SPLIT_EVIDENCE_FILENAME,
    )
    from src.processing.baseline_rebuild_v2 import (
        BASELINE_REBUILD_MONTH_EVIDENCE_VERSION,
        BASELINE_V2_VERSION,
        COMPOSITE_STACK_ORDER_POLICY,
        MONTHLY_CENTRAL_STATISTIC,
        MONTHLY_DISPERSION_STATISTIC,
        NONFINITE_INDEX_POLICY,
        STATISTICS_COMPUTATION_DTYPE,
        STATISTICS_OUTPUT_DTYPE,
        contribution_count_filename,
    )

    regimes = _regimes()
    plan = build_baseline_rebuild_plan(regimes=regimes)
    run_manifest_id, plan_sha256 = run_manifest_binding_from_plan(plan)
    state = _load_state()

    split_evidence = json.loads(
        (BASELINE_V2_COUNTS_LOCAL_DIR / BASELINE_V2_SPLIT_EVIDENCE_FILENAME)
        .read_text(encoding="utf-8")
    )

    def digest(path: Path) -> dict:
        with rasterio.open(path) as src:
            array = np.ascontiguousarray(src.read(1))
        import hashlib

        return {
            "dtype": str(array.dtype),
            "shape": list(array.shape),
            "sha256": hashlib.sha256(array.tobytes()).hexdigest(),
        }

    months = []
    for month in range(1, 13):
        key = str(month)
        if key not in state["tasks"]:
            raise ExecutorError(f"month {month:02d}: no export task recorded")
        if key not in split_evidence["months"]:
            raise ExecutorError(f"month {month:02d}: not split yet")
        split = split_evidence["months"][key]
        entries = sorted(
            (
                record
                for record in state["datatakes"].values()
                if record["month"] == month
            ),
            key=lambda r: (r["acquisition_timestamp_utc"], r["acquisition_id"]),
        )
        if not entries:
            raise ExecutorError(f"month {month:02d}: no datatake composite")
        datatakes = [
            {
                key_: record[key_]
                for key_ in (
                    "acquisition_id",
                    "platform",
                    "datatake_id",
                    "acquisition_timestamp_utc",
                    "year",
                    "scene_count",
                    "scenes",
                    "valid_pixel_counts",
                    "valid_pixel_count_source",
                    "gee_plan_sha256",
                    "gee_verification",
                )
            }
            for record in entries
        ]
        arrays = {}
        for index in REBUILD_INDEX_NAMES:
            arrays[index] = {
                "median": digest(
                    BASELINE_V2_LOCAL_DIR / f"{index}_month{month:02d}_mean.tif"
                ),
                "std": digest(
                    BASELINE_V2_LOCAL_DIR / f"{index}_month{month:02d}_std.tif"
                ),
                "contribution_count": digest(
                    BASELINE_V2_COUNTS_LOCAL_DIR
                    / contribution_count_filename(index, month)
                ),
            }
        body = {
            "month_evidence_version": BASELINE_REBUILD_MONTH_EVIDENCE_VERSION,
            "baseline_version": BASELINE_V2_VERSION,
            "month": month,
            "composite_stack_order_policy": list(COMPOSITE_STACK_ORDER_POLICY),
            "statistics": {
                "central": MONTHLY_CENTRAL_STATISTIC,
                "dispersion": MONTHLY_DISPERSION_STATISTIC,
                "computation_dtype": STATISTICS_COMPUTATION_DTYPE,
                "output_dtype": STATISTICS_OUTPUT_DTYPE,
                "nonfinite_index_policy": NONFINITE_INDEX_POLICY,
                "empty_stack_pixel_policy": "nan_statistics_zero_count",
            },
            "execution": "earth_engine_server_side",
            "gee_task_id": state["tasks"][key]["task_id"],
            "export_file": split["export_file"],
            "datatakes": datatakes,
            "observed_processing_baselines": sorted(
                {s["processing_baseline"] for d in datatakes for s in d["scenes"]}
            ),
            "observed_platforms": sorted({d["platform"] for d in datatakes}),
            "source_regime": regime_for_month(regimes, month).regime_id,
            "reviewed_processing_baseline_registry": (
                regime_for_month(regimes, month).registry.registry_dict()
            ),
            "arrays": arrays,
        }
        months.append(
            {
                "month": month,
                "source_regime": regime_for_month(regimes, month).regime_id,
                "gee_task_id": state["tasks"][key]["task_id"],
                "export_file": split["export_file"],
                "month_evidence_sha256": canonical_sha256(body),
                "contribution_counts": split["contribution_counts"],
                "datatakes": datatakes,
            }
        )

    document = {
        "reviewed_processing_baseline_registry": union_registry(
            regimes
        ).registry_dict(),
        "source_regimes": [regime.regime_dict() for regime in regimes],
        "rebuild_execution": {
            "rebuild_plan_version": plan["rebuild_plan_version"],
            "rebuild_plan_sha256": plan_sha256,
            "run_manifest_id": run_manifest_id,
            "run_manifest_sha256": plan_sha256,
            "earth_engine": {
                "project_id": PROJECT_ID,
                "image_collection_id": GEE_COLLECTION_ID,
                "query_fingerprint_sha256": baseline_query_fingerprint(regimes),
                "drive_folder": BASELINE_V2_DRIVE_FOLDER,
                "file_name_prefix": BASELINE_V2_EXPORT_PREFIX,
            },
            "months": months,
            "totals": {
                "datatake_count": sum(len(m["datatakes"]) for m in months),
                "scene_count": sum(
                    d["scene_count"] for m in months for d in m["datatakes"]
                ),
            },
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    totals = document["rebuild_execution"]["totals"]
    click.echo(
        f"execution evidence -> {output} "
        f"({totals['datatake_count']} datatakes, {totals['scene_count']} scenes)"
    )


if __name__ == "__main__":
    cli()
