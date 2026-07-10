"""Tests for land-cover annotation of alerts (src/detection/landcover.py)."""

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from src.detection.landcover import (
    annotate_alerts_with_landcover,
    filter_alerts_by_natural_vegetation,
)


def _make_landcover(path):
    """10x10 raster (EPSG:4326): left half savanna (4, natural), right half pasture (15)."""
    arr = np.full((10, 10), 4, dtype="uint8")   # class 4 = savanna (natural)
    arr[:, 5:] = 15                              # class 15 = pasture (farming)
    transform = from_origin(-40.0, -7.0, 0.01, 0.01)  # 0.01° pixels
    profile = dict(driver="GTiff", height=10, width=10, count=1,
                   dtype="uint8", crs="EPSG:4326", transform=transform, nodata=0)
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arr, 1)
    return path


def _alerts():
    # A polygon fully in the natural (left) half and one fully in farming (right).
    natural = box(-39.99, -7.09, -39.96, -7.06)   # left half (cols in savanna)
    farming = box(-39.94, -7.09, -39.91, -7.06)    # right half (cols in pasture)
    return gpd.GeoDataFrame({"id": [1, 2]}, geometry=[natural, farming], crs="EPSG:4326")


def test_annotation_assigns_dominant_group(tmp_path):
    lc = _make_landcover(tmp_path / "lc.tif")
    ann = annotate_alerts_with_landcover(_alerts(), lc)
    assert list(ann["lc_group"]) == ["natural", "farming"]
    assert ann.iloc[0]["lc_class"] == 4
    assert ann.iloc[1]["lc_class"] == 15
    assert ann.iloc[0]["lc_natural_frac"] == 1.0
    assert ann.iloc[1]["lc_natural_frac"] == 0.0


def test_natural_filter_drops_farming(tmp_path):
    lc = _make_landcover(tmp_path / "lc.tif")
    kept = filter_alerts_by_natural_vegetation(_alerts(), lc, min_natural_frac=0.5)
    assert list(kept["id"]) == [1]


def test_empty_alerts_roundtrip(tmp_path):
    lc = _make_landcover(tmp_path / "lc.tif")
    empty = gpd.GeoDataFrame({"id": []}, geometry=[], crs="EPSG:4326")
    ann = annotate_alerts_with_landcover(empty, lc)
    assert ann.empty


def _make_single_class_raster(path, code):
    """10x10 raster (EPSG:4326) entirely of one MapBiomas class code."""
    arr = np.full((10, 10), code, dtype="uint8")
    transform = from_origin(-40.0, -7.0, 0.01, 0.01)
    profile = dict(driver="GTiff", height=10, width=10, count=1,
                   dtype="uint8", crs="EPSG:4326", transform=transform, nodata=0)
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arr, 1)
    return path


def _one_alert():
    return gpd.GeoDataFrame(
        {"id": [1]}, geometry=[box(-39.98, -7.08, -39.94, -7.04)], crs="EPSG:4326"
    )


def test_collection_taxonomies_differ_for_soybean(tmp_path):
    """Code 39 (Soybean) is farming in Collection 10.1 but is not a Collection 2
    class → 'other' under the 10 m table. Verifies per-collection reclassification."""
    lc = _make_single_class_raster(tmp_path / "soy.tif", 39)
    ann30 = annotate_alerts_with_landcover(_one_alert(), lc, collection="mapbiomas30m")
    ann10 = annotate_alerts_with_landcover(_one_alert(), lc, collection="mapbiomas10m")
    assert ann30.iloc[0]["lc_group"] == "farming"
    assert ann10.iloc[0]["lc_group"] == "other"


def test_collection_photovoltaic_75(tmp_path):
    """Code 75 (Photovoltaic) is urban in Collection 10.1, 'other' in Collection 2."""
    lc = _make_single_class_raster(tmp_path / "pv.tif", 75)
    ann30 = annotate_alerts_with_landcover(_one_alert(), lc, collection="mapbiomas30m")
    ann10 = annotate_alerts_with_landcover(_one_alert(), lc, collection="mapbiomas10m")
    assert ann30.iloc[0]["lc_group"] == "urban"
    assert ann10.iloc[0]["lc_group"] == "other"


def test_unknown_collection_raises(tmp_path):
    lc = _make_landcover(tmp_path / "lc.tif")
    import pytest
    with pytest.raises(ValueError):
        annotate_alerts_with_landcover(_one_alert(), lc, collection="bogus")


def test_default_collection_is_10m(tmp_path):
    """The default path preserves the original 10 m behavior (class 4/15)."""
    lc = _make_landcover(tmp_path / "lc.tif")
    ann = annotate_alerts_with_landcover(_alerts(), lc)  # no collection arg
    assert list(ann["lc_group"]) == ["natural", "farming"]
