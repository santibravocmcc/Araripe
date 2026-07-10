"""Tests for alert vectorization, incl. the exact-polygon confidence mask."""

import geopandas as gpd
import numpy as np
import rioxarray  # noqa: F401 — registers the .rio accessor
import xarray as xr
from shapely.geometry import Polygon

from src.detection.alerts import _assign_polygon_confidence


def _confidence_raster():
    """4x4 confidence raster, 20 m pixels, EPSG:32724, top-left origin (0, 80).

    All pixels are confidence 1 except the top-right pixel which is 3.
    Pixel centers: x=[10,30,50,70], y=[70,50,30,10] (row 0 = top).
    """
    conf = np.ones((4, 4), dtype=np.int8)
    conf[0, 3] = 3  # top-right high-confidence pixel (map ~ x[60,80], y[60,80])
    da = xr.DataArray(
        conf,
        dims=["y", "x"],
        coords={"y": [70.0, 50.0, 30.0, 10.0], "x": [10.0, 30.0, 50.0, 70.0]},
    )
    da.rio.write_crs("EPSG:32724", inplace=True)
    return da


def test_confidence_uses_exact_polygon_not_bounding_box():
    """A polygon whose bbox contains the high pixel but whose *interior* does
    not must be assigned the interior max (1), not the bbox max (3)."""
    conf = _confidence_raster()
    # Lower-left triangle: bbox = whole raster (includes top-right high pixel),
    # but the top-right corner is outside the triangle.
    tri = Polygon([(0, 0), (0, 80), (80, 0)])
    gdf = gpd.GeoDataFrame({"geometry": [tri]}, crs="EPSG:32724")

    result = _assign_polygon_confidence(gdf, conf)
    assert result == [1], f"expected interior max 1, got {result}"


def test_confidence_reports_high_when_polygon_contains_high_pixel():
    """A polygon that actually covers the high pixel gets confidence 3."""
    conf = _confidence_raster()
    # Small square around the top-right high pixel center (x=70, y=70).
    sq = Polygon([(60, 60), (60, 80), (80, 80), (80, 60)])
    gdf = gpd.GeoDataFrame({"geometry": [sq]}, crs="EPSG:32724")

    result = _assign_polygon_confidence(gdf, conf)
    assert result == [3], f"expected 3, got {result}"
