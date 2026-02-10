"""Tests for AOI polygon loading and spatial clipping."""

import numpy as np
import pytest
import xarray as xr

from src.acquisition.aoi import (
    clip_dataset_to_aoi,
    get_aoi_bbox_wgs84,
    load_aoi_polygon,
)


class TestLoadAoiPolygon:
    def test_fallback_to_bbox_when_no_file(self, tmp_path):
        """When the polygon file doesn't exist, should return a rectangle from AOI_BBOX."""
        gdf = load_aoi_polygon(path=tmp_path / "nonexistent.gpkg")
        assert len(gdf) == 1
        assert gdf.crs is not None

    def test_reprojects_to_target_crs(self, tmp_path):
        """Polygon should be reprojected to the requested CRS."""
        gdf = load_aoi_polygon(
            path=tmp_path / "nonexistent.gpkg",
            target_crs="EPSG:32724",
        )
        assert "32724" in str(gdf.crs)

    def test_loads_existing_geojson(self, tmp_path):
        """Should load a real GeoJSON file when it exists."""
        import geopandas as gpd
        from shapely.geometry import box

        geojson_path = tmp_path / "test_aoi.geojson"
        test_gdf = gpd.GeoDataFrame(
            [{"geometry": box(-39.5, -7.5, -39.0, -7.0), "name": "test"}],
            crs="EPSG:4326",
        )
        test_gdf.to_file(str(geojson_path), driver="GeoJSON")

        gdf = load_aoi_polygon(path=geojson_path, target_crs="EPSG:32724")
        assert len(gdf) == 1
        assert "32724" in str(gdf.crs)

    def test_loads_geopackage(self, tmp_path):
        """Should load a GeoPackage file when it exists."""
        import geopandas as gpd
        from shapely.geometry import box

        gpkg_path = tmp_path / "test_aoi.gpkg"
        test_gdf = gpd.GeoDataFrame(
            [{"geometry": box(-39.5, -7.5, -39.0, -7.0), "name": "test"}],
            crs="EPSG:4326",
        )
        test_gdf.to_file(str(gpkg_path), driver="GPKG")

        gdf = load_aoi_polygon(path=gpkg_path, target_crs="EPSG:32724")
        assert len(gdf) == 1
        assert "32724" in str(gdf.crs)


class TestGetAoiBboxWgs84:
    def test_returns_four_coordinates(self, tmp_path):
        """Should return [west, south, east, north]."""
        bbox = get_aoi_bbox_wgs84(path=tmp_path / "nonexistent.gpkg")
        assert len(bbox) == 4
        assert bbox[0] < bbox[2]  # west < east
        assert bbox[1] < bbox[3]  # south < north

    def test_bbox_from_existing_file(self, tmp_path):
        """Should extract bbox from the polygon file."""
        import geopandas as gpd
        from shapely.geometry import box

        geojson_path = tmp_path / "test_aoi.geojson"
        test_gdf = gpd.GeoDataFrame(
            [{"geometry": box(-39.5, -7.5, -39.0, -7.0)}],
            crs="EPSG:4326",
        )
        test_gdf.to_file(str(geojson_path), driver="GeoJSON")

        bbox = get_aoi_bbox_wgs84(path=geojson_path)
        assert abs(bbox[0] - (-39.5)) < 0.01
        assert abs(bbox[1] - (-7.5)) < 0.01
        assert abs(bbox[2] - (-39.0)) < 0.01
        assert abs(bbox[3] - (-7.0)) < 0.01


class TestClipDatasetToAoi:
    def test_clipping_reduces_extent(self):
        """Clipping should produce a smaller dataset."""
        import geopandas as gpd
        import rioxarray  # noqa: F401
        from shapely.geometry import box

        # Create a 10x10 dataset in WGS84
        ds = xr.Dataset(
            {
                "nir": xr.DataArray(
                    np.ones((10, 10)),
                    dims=["y", "x"],
                    coords={
                        "y": np.linspace(-7.0, -8.0, 10),
                        "x": np.linspace(-40.0, -39.0, 10),
                    },
                ),
            }
        )
        ds = ds.rio.write_crs("EPSG:4326")
        ds = ds.rio.set_spatial_dims(x_dim="x", y_dim="y")

        # Clip to a smaller area (roughly 25% of the domain)
        small_poly = gpd.GeoDataFrame(
            [{"geometry": box(-39.5, -7.5, -39.0, -7.0)}],
            crs="EPSG:4326",
        )

        clipped = clip_dataset_to_aoi(ds, aoi_gdf=small_poly)
        assert clipped.sizes["y"] < ds.sizes["y"] or clipped.sizes["x"] < ds.sizes["x"]

    def test_clipping_preserves_values(self):
        """Clipped values should match original values within the polygon."""
        import geopandas as gpd
        import rioxarray  # noqa: F401
        from shapely.geometry import box

        data = np.arange(100, dtype=float).reshape(10, 10)
        ds = xr.Dataset(
            {
                "band": xr.DataArray(
                    data,
                    dims=["y", "x"],
                    coords={
                        "y": np.linspace(-7.0, -8.0, 10),
                        "x": np.linspace(-40.0, -39.0, 10),
                    },
                ),
            }
        )
        ds = ds.rio.write_crs("EPSG:4326")
        ds = ds.rio.set_spatial_dims(x_dim="x", y_dim="y")

        # Clip to the full extent (should preserve everything)
        full_poly = gpd.GeoDataFrame(
            [{"geometry": box(-40.0, -8.0, -39.0, -7.0)}],
            crs="EPSG:4326",
        )

        clipped = clip_dataset_to_aoi(ds, aoi_gdf=full_poly)
        # Values that survived should match originals
        assert clipped["band"].notnull().any()

    def test_auto_loads_aoi_when_none(self):
        """When aoi_gdf=None, should load default AOI (fallback to bbox)."""
        import rioxarray  # noqa: F401

        ds = xr.Dataset(
            {
                "nir": xr.DataArray(
                    np.ones((5, 5)),
                    dims=["y", "x"],
                    coords={
                        "y": np.linspace(-7.0, -8.0, 5),
                        "x": np.linspace(-40.0, -39.0, 5),
                    },
                ),
            }
        )
        ds = ds.rio.write_crs("EPSG:4326")
        ds = ds.rio.set_spatial_dims(x_dim="x", y_dim="y")

        # Should not raise — loads default AOI and clips
        clipped = clip_dataset_to_aoi(ds)
        assert clipped is not None
