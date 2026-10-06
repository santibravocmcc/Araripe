"""The MapBiomas 2025 crops, and why extending the class tables is inert today.

The 2025 crops (10 m Collection 4, Collection 11) were cut on 2026-10-06 by
``scripts/crop_mapbiomas_national.py``; the national files were not kept, so
each crop's ``.report.json`` is the only binding to the published bytes.

The class tables in ``src/detection/landcover.py`` gained the codes those
legends add. The runtime still annotates with the 2023 crops
(``config.settings.LANDCOVER_RASTERS`` is not changed here), and the last test
pins that none of the added codes occurs in them — which is what makes the
table change inert for every alert annotated today.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import rasterio

from src.detection.landcover import _GROUP_OF_CLASS_10M, _GROUP_OF_CLASS_30M

LANDCOVER = Path(__file__).parents[1] / "data" / "landcover"
MONITORING_EXTENT = (-40.89236812577142, -7.840780758480428, -38.95208146319247, -6.957104781339829)

CROPS = {
    "mapbiomas_col4_10m_2025_araripe": (_GROUP_OF_CLASS_10M, "17dbc582322190b9f8e7a40c16348006"),
    "mapbiomas_col11_30m_2025_araripe": (_GROUP_OF_CLASS_30M, "1c8ee63d2752b08463d703b6ae585101"),
}
ADDED_ON_2026_10_06 = {
    "mapbiomas10m_araripe_2023": (_GROUP_OF_CLASS_10M, {7, 77, 84, 75, 91}),
    "mapbiomas30m_araripe_2023": (_GROUP_OF_CLASS_30M, {7, 77, 84, 91}),
}


def _codes(path: Path) -> set[int]:
    with rasterio.open(path) as ds:
        return {int(c) for c in np.unique(ds.read(1))}


@pytest.mark.parametrize("name", sorted(CROPS))
def test_the_crop_is_the_file_its_report_describes(name):
    report = json.loads((LANDCOVER / f"{name}.report.json").read_text(encoding="utf-8"))
    tif = LANDCOVER / f"{name}.tif"
    assert hashlib.sha256(tif.read_bytes()).hexdigest() == report["crop"]["sha256"]
    # the national bytes: the MD5 equals the bucket ETag read on 2026-10-06
    assert report["source"]["md5"] == CROPS[name][1]
    assert report["origin_url"].startswith(
        "https://storage.googleapis.com/mapbiomas-public/initiatives/brasil/")
    with rasterio.open(tif) as ds:
        assert ds.crs.to_epsg() == 4326 and ds.nodata == 0
        west, south, east, north = ds.bounds
    mw, ms, me, mn = MONITORING_EXTENT
    assert west <= mw and south <= ms and east >= me and north >= mn


@pytest.mark.parametrize("name", sorted(CROPS))
def test_every_code_in_the_2025_crops_has_a_group(name):
    """No code may fall through to "other" at the call site in silence."""
    table = CROPS[name][0]
    codes = _codes(LANDCOVER / f"{name}.tif")
    report = json.loads((LANDCOVER / f"{name}.report.json").read_text(encoding="utf-8"))
    assert codes == {int(c) for c in report["crop"]["histogram"]}
    assert codes - set(table) == set()


@pytest.mark.parametrize("name", sorted(ADDED_ON_2026_10_06))
def test_the_added_codes_do_not_occur_in_the_runtime_crops(name):
    table, added = ADDED_ON_2026_10_06[name]
    assert added <= set(table)
    assert _codes(LANDCOVER / f"{name}.tif") & added == set()
