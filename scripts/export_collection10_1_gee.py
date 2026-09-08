"""Export the true Collection 10.1 ``classification_2024`` band (Package 2A.6D).

The direct-download 30 m GeoTIFF proved to be Collection 10, not 10.1, so the
2026-08-11 decision record requires a fresh acquisition from the official
Collection 10.1 Earth Engine asset before any replay. This script performs
that acquisition under the locked export contract and writes the
``collection10_1_export_manifest_v1`` provenance manifest.

Every contract term is read from
``config/phase2a_candidate_generation_decisions_v2.json`` — the accepted
decision record — rather than restated here, so the executor cannot drift
from what was decided:

- the band's exact native CRS and transform (no scale argument, no
  reprojection, nearest-only semantics preserved by exporting on the native
  lattice);
- the source mask exported as value 255 and declared as GeoTIFF NoData 255,
  never conflated with class 0;
- Cloud Optimized GeoTIFF output;
- the twenty required provenance fields.

Read-only toward every production system: it writes one file to the owner's
Drive, downloads it locally, and touches no R2 object, no workflow, no
baseline, and no existing national file.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.detection.baseline_manifest import (  # noqa: E402
    MONITORING_EXTENT_BOUNDS,
    MONITORING_EXTENT_BOUNDS_SHA256,
    MONITORING_EXTENT_GEOMETRY_SHA256,
    MONITORING_EXTENT_ID,
)

DECISIONS_PATH = Path("config/phase2a_candidate_generation_decisions_v2.json")
DECISIONS_SHA256 = (
    "ac61fd1e6da376a147013a610652e38a6d3d119dcb8479b01001e156625cf69e"
)
DRIVE_FOLDER = "araripe_mapbiomas_10_1"
OUTPUT_RASTER = Path("data/landcover/mapbiomas_col10_1_gee_30m_2024.tif")
OUTPUT_MANIFEST = Path("config/collection10_1_export_manifest_v1.json")


class ExportError(click.ClickException):
    """The export violates the locked Collection 10.1 contract."""


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_sha256(value) -> str:
    return _sha256_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def _load_contract() -> dict:
    raw = DECISIONS_PATH.read_bytes()
    if _sha256_bytes(raw) != DECISIONS_SHA256:
        raise ExportError(
            "the decision record bytes do not match the accepted checksum; "
            "refusing to derive an export contract from an unreviewed file"
        )
    decisions = json.loads(raw)
    return decisions["phase2a5"]["collection10_1_required_source"]


def _verify_owner_credential() -> None:
    import os

    stored = json.loads(
        Path("~/.config/earthengine/credentials").expanduser().read_text()
    )
    if "refresh_token" not in stored or "private_key" in stored or (
        "client_email" in stored
    ):
        raise ExportError(
            "the local Earth Engine credential is not the owner's interactive "
            "refresh token; the production service account is never used here"
        )
    leaked = [
        key
        for key in os.environ
        if key.startswith(("GEE", "GOOGLE", "EARTHENGINE"))
    ]
    if leaked:
        raise ExportError(f"credential-bearing environment variables set: {leaked}")


def _drive_service():
    import ee.oauth
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    stored = json.loads(
        Path("~/.config/earthengine/credentials").expanduser().read_text()
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


def _native_window(transform: list[float]) -> tuple[list[float], int, int]:
    """The smallest native-lattice window covering the monitoring extent.

    The export stays on the band's own grid — origin snapped to whole source
    pixels — so categorical values are moved bit-for-bit and 'nearest' never
    has to interpolate anything.
    """

    west, south, east, north = MONITORING_EXTENT_BOUNDS
    col0 = math.floor((west - transform[2]) / transform[0])
    col1 = math.ceil((east - transform[2]) / transform[0])
    row0 = math.floor((north - transform[5]) / transform[4])
    row1 = math.ceil((south - transform[5]) / transform[4])
    origin_x = transform[2] + col0 * transform[0]
    origin_y = transform[5] + row0 * transform[4]
    export_transform = [transform[0], 0.0, origin_x, 0.0, transform[4], origin_y]
    return export_transform, col1 - col0, row1 - row0


@click.command()
@click.option("--project", default="ee-araripe-baseline-v2", show_default=True)
@click.option(
    "--poll-seconds", default=30, show_default=True, type=int,
    help="Interval between task-state polls.",
)
def main(project: str, poll_seconds: int) -> None:
    import ee

    contract = _load_contract()
    export_contract = contract["export_contract"]
    if export_contract["scale_argument_permitted"]:
        raise ExportError("contract drift: a scale argument is not permitted")
    if OUTPUT_MANIFEST.exists():
        raise ExportError(
            f"{OUTPUT_MANIFEST} already exists; the export manifest is "
            "immutable once written"
        )
    if OUTPUT_RASTER.exists():
        raise ExportError(
            f"{OUTPUT_RASTER} already exists; refusing to overwrite an "
            "acquired artifact"
        )

    _verify_owner_credential()
    ee.Initialize(project=project)

    asset_id = contract["gee_asset"]
    band_name = contract["band"]
    asset = ee.data.getAsset(asset_id)
    band_names = [band["id"] for band in asset.get("bands", [])]
    if band_name not in band_names:
        raise ExportError(
            f"asset {asset_id} does not carry the required band {band_name}"
        )
    asset_metadata_sha256 = _canonical_sha256(asset)

    image = ee.Image(asset_id)
    projection = image.select(band_name).projection().getInfo()
    if projection.get("crs") is None or projection.get("transform") is None:
        raise ExportError("the selected band exposes no native CRS/transform")
    export_transform, width, height = _native_window(projection["transform"])

    masked_value = int(export_contract["masked_pixel_export_value"])
    nodata_value = int(export_contract["geotiff_nodata_value"])
    band = image.select(band_name).unmask(masked_value).toByte()

    description = "araripe_mapbiomas_col10_1_2024"
    request = {
        "asset_id": asset_id,
        "band": band_name,
        "description": description,
        "drive_folder": DRIVE_FOLDER,
        "crs": projection["crs"],
        "crs_transform": export_transform,
        "dimensions": f"{width}x{height}",
        "masked_pixel_export_value": masked_value,
        "geotiff_nodata_value": nodata_value,
        "cloud_optimized": bool(export_contract["cloud_optimized"]),
        "file_format": export_contract["file_format"],
        "monitoring_extent_id": MONITORING_EXTENT_ID,
        "monitoring_extent_bounds": list(MONITORING_EXTENT_BOUNDS),
    }
    request_sha256 = _canonical_sha256(request)
    click.echo(f"asset      : {asset_id}")
    click.echo(f"band       : {band_name}  (native {projection['crs']})")
    click.echo(f"window     : {width}x{height} @ {export_transform}")
    click.echo(f"request sha: {request_sha256}")

    task = ee.batch.Export.image.toDrive(
        image=band,
        description=description,
        folder=DRIVE_FOLDER,
        fileNamePrefix=description,
        crs=projection["crs"],
        crsTransform=str(export_transform),
        dimensions=f"{width}x{height}",
        maxPixels=int(1e9),
        fileFormat="GeoTIFF",
        formatOptions={"cloudOptimized": True, "noData": nodata_value},
    )
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    task.start()
    click.echo(f"task       : {task.id}  (started {started_at})")

    state = "UNSUBMITTED"
    while state not in {"COMPLETED", "FAILED", "CANCELLED"}:
        time.sleep(poll_seconds)
        status = ee.data.getTaskStatus(task.id)[0]
        state = status.get("state", "UNKNOWN")
        click.echo(f"  {datetime.now(timezone.utc).strftime('%H:%M:%SZ')} {state}")
    completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if state != contract["required_task_state"]:
        raise ExportError(
            f"export task {task.id} ended {state}; the contract requires "
            f"{contract['required_task_state']}: "
            f"{status.get('error_message', 'no error message')}"
        )

    service = _drive_service()
    folders = service.files().list(
        q=(
            "mimeType='application/vnd.google-apps.folder' and "
            f"name='{DRIVE_FOLDER}' and trashed=false"
        ),
        fields="files(id,name)",
    ).execute().get("files", [])
    candidates = []
    for folder in folders:
        for item in service.files().list(
            q=f"'{folder['id']}' in parents and trashed=false",
            fields="files(id,name,size,createdTime)",
        ).execute().get("files", []):
            if item["name"].startswith(description):
                candidates.append(item)
    fresh = [c for c in candidates if c.get("createdTime", "") >= started_at]
    if len(fresh) != 1:
        raise ExportError(
            f"expected exactly one Drive file for this task, found "
            f"{len(fresh)} created after {started_at} "
            f"({[c['name'] for c in candidates]})"
        )
    if fresh[0]["name"] != f"{description}.tif":
        raise ExportError(
            f"Drive file {fresh[0]['name']!r} is not the canonical single "
            f"{description}.tif; a sharded export is refused"
        )

    from googleapiclient.http import MediaIoBaseDownload

    OUTPUT_RASTER.parent.mkdir(parents=True, exist_ok=True)
    request_media = service.files().get_media(fileId=fresh[0]["id"])
    with open(OUTPUT_RASTER, "wb") as handle:
        downloader = MediaIoBaseDownload(handle, request_media, chunksize=32 * 2**20)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    output_bytes = OUTPUT_RASTER.stat().st_size
    output_sha256 = _sha256_bytes(OUTPUT_RASTER.read_bytes())
    click.echo(f"downloaded : {OUTPUT_RASTER} ({output_bytes:,} bytes)")

    import numpy as np
    import rasterio

    with rasterio.open(OUTPUT_RASTER) as src:
        header = {
            "driver": src.driver,
            "crs": str(src.crs),
            "width": src.width,
            "height": src.height,
            "transform": list(src.transform)[:6],
            "dtype": src.dtypes[0],
            "band_count": src.count,
            "nodata": None if src.nodata is None else int(src.nodata),
            "overview_levels": src.overviews(1),
            "blocks_tiled": src.profile.get("tiled", False),
        }
        values = src.read(1)

    problems = []
    if header["crs"] != projection["crs"]:
        problems.append(f"crs {header['crs']} != {projection['crs']}")
    if (header["width"], header["height"]) != (width, height):
        problems.append("dimensions differ from the requested native window")
    if [round(v, 12) for v in header["transform"]] != [
        round(v, 12) for v in export_transform
    ]:
        problems.append("transform differs from the requested native lattice")
    if header["dtype"] != "uint8":
        problems.append(f"dtype {header['dtype']} is not uint8")
    if header["nodata"] != nodata_value:
        problems.append(f"GeoTIFF nodata {header['nodata']} != {nodata_value}")
    if problems:
        raise ExportError(
            "the delivered file violates the export contract: "
            + "; ".join(problems)
        )

    unique, counts = np.unique(values, return_counts=True)
    histogram = {str(int(code)): int(count) for code, count in zip(unique, counts)}
    nodata_count = int(histogram.get(str(nodata_value), 0))
    class0_count = int(histogram.get("0", 0))

    manifest = {
        "schema_version": "1.0.0",
        "manifest_id": "collection10_1_export_manifest_v1",
        "source_id": contract["source_id"],
        "decision_binding": {
            "path": str(DECISIONS_PATH),
            "sha256": DECISIONS_SHA256,
        },
        "asset_id": asset_id,
        "asset_metadata_json_sha256": asset_metadata_sha256,
        "asset_update_time": asset.get("updateTime"),
        "band_names": band_names,
        "selected_band": band_name,
        "source_projection": {
            "crs": projection["crs"],
            "transform": projection["transform"],
        },
        "monitoring_extent_id": MONITORING_EXTENT_ID,
        "monitoring_extent_sha256": {
            "bounds_sha256": MONITORING_EXTENT_BOUNDS_SHA256,
            "geometry_sha256": MONITORING_EXTENT_GEOMETRY_SHA256,
        },
        "export_request": request,
        "export_request_json_sha256": request_sha256,
        "earth_engine_project_id": project,
        "principal": "owner interactive local authentication",
        "task_id": task.id,
        "task_state": state,
        "started_at": started_at,
        "completed_at": completed_at,
        "drive_folder": DRIVE_FOLDER,
        "output_path": str(OUTPUT_RASTER),
        "output_bytes": output_bytes,
        "output_sha256": output_sha256,
        "output_header": header,
        "class_histogram": histogram,
        "nodata_pixel_count": nodata_count,
        "unknown_class0_pixel_count": class0_count,
        "masked_value_is_distinct_from_class0": True,
        "existing_national_file_modified": False,
        "mislabeled_collection10_crop_reused": False,
    }
    required = set(contract["required_export_manifest_fields"])
    missing = sorted(required - set(manifest))
    if missing:
        raise ExportError(f"manifest is missing required fields: {missing}")
    OUTPUT_MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    click.echo(f"manifest   : {OUTPUT_MANIFEST}")
    click.echo(
        f"histograma : {len(histogram)} classes | nodata(255)={nodata_count:,} "
        f"| classe 0={class0_count:,}"
    )


if __name__ == "__main__":
    main()
