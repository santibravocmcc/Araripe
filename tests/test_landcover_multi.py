"""annotate_alerts_all_collections: both MapBiomas collections, side by side."""

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.detection.landcover import (  # noqa: E402
    annotate_alerts_all_collections,
    annotate_alerts_with_landcover,
)

OX, OY, RES, SIZE = 500000, 9200000, 20, 20


def _write_lc(path, code):
    transform = from_origin(OX, OY, RES, RES)
    with rasterio.open(str(path), "w", driver="GTiff", height=SIZE, width=SIZE, count=1,
                       dtype="uint8", crs="EPSG:32724", transform=transform, nodata=0) as dst:
        dst.write(np.full((SIZE, SIZE), code, dtype="uint8"), 1)


def _alert():
    g = box(OX + RES, OY - RES * 11, OX + RES * 10, OY - RES)  # interior box
    return gpd.GeoDataFrame({"confidence": [3]}, geometry=[g], crs="EPSG:32724")


def test_suffix_keeps_columns_separate(tmp_path):
    lc = tmp_path / "lc10.tif"
    _write_lc(lc, 3)  # class 3 = natural
    out = annotate_alerts_with_landcover(_alert(), lc, collection="mapbiomas10m", col_suffix="_10m")
    assert out["lc_group_10m"].iloc[0] == "natural"
    assert out["lc_natural_frac_10m"].iloc[0] == 1.0


def test_both_collections_annotated(tmp_path):
    lc10 = tmp_path / "lc10.tif"; _write_lc(lc10, 3)   # natural (10 m)
    lc30 = tmp_path / "lc30.tif"; _write_lc(lc30, 15)  # farming (30 m, class 15)
    out = annotate_alerts_all_collections(
        _alert(),
        rasters={"mapbiomas10m": lc10, "mapbiomas30m": lc30},
        default_collection="mapbiomas10m",
    )
    # Both collections present, side by side, and can DISAGREE:
    assert out["lc_group_10m"].iloc[0] == "natural"
    assert out["lc_group_30m"].iloc[0] == "farming"
    # Unsuffixed legacy columns mirror the default collection (10 m).
    assert out["lc_group"].iloc[0] == "natural"


def test_missing_raster_skipped(tmp_path):
    lc10 = tmp_path / "lc10.tif"; _write_lc(lc10, 3)
    out = annotate_alerts_all_collections(
        _alert(),
        rasters={"mapbiomas10m": lc10, "mapbiomas30m": tmp_path / "missing.tif"},
        default_collection="mapbiomas10m",
    )
    assert "lc_group_10m" in out.columns
    assert "lc_group_30m" not in out.columns  # missing raster skipped, no crash
