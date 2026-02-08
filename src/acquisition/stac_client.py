"""Query STAC APIs for Sentinel-2, Landsat, and HLS imagery."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from loguru import logger
from pystac import ItemCollection
from pystac_client import Client

from config.settings import (
    AOI_BBOX,
    ELEMENT84_URL,
    HLS_LANDSAT_COLLECTION,
    HLS_SENTINEL_COLLECTION,
    LANDSAT_COLLECTION,
    MAX_CLOUD_COVER,
    MAX_ITEMS_PER_SEARCH,
    NASA_STAC_URL,
    PLANETARY_COMPUTER_URL,
    SEARCH_DAYS_BACK,
    SENTINEL2_COLLECTION,
)


def _build_datetime_range(
    start: Optional[str] = None,
    end: Optional[str] = None,
    days_back: int = SEARCH_DAYS_BACK,
) -> str:
    """Build an ISO 8601 datetime range string for STAC queries.

    If start/end are not provided, defaults to the last `days_back` days.
    """
    if start and end:
        return f"{start}/{end}"
    end_dt = datetime.utcnow()
    start_dt = end_dt - timedelta(days=days_back)
    return f"{start_dt.strftime('%Y-%m-%d')}/{end_dt.strftime('%Y-%m-%d')}"


def search_element84(
    bbox: list[float] = AOI_BBOX,
    datetime_range: Optional[str] = None,
    max_cloud_cover: int = MAX_CLOUD_COVER,
    max_items: int = MAX_ITEMS_PER_SEARCH,
    collection: str = SENTINEL2_COLLECTION,
) -> ItemCollection:
    """Search Element84 Earth Search for Sentinel-2 L2A scenes.

    No authentication required.
    """
    logger.info("Querying Element84 Earth Search for {}", collection)
    catalog = Client.open(ELEMENT84_URL)

    if datetime_range is None:
        datetime_range = _build_datetime_range()

    search = catalog.search(
        collections=[collection],
        bbox=bbox,
        datetime=datetime_range,
        query={"eo:cloud_cover": {"lt": max_cloud_cover}},
        max_items=max_items,
    )
    items = search.item_collection()
    logger.info("Element84 returned {} items", len(items))
    return items


def search_planetary_computer(
    bbox: list[float] = AOI_BBOX,
    datetime_range: Optional[str] = None,
    max_cloud_cover: int = MAX_CLOUD_COVER,
    max_items: int = MAX_ITEMS_PER_SEARCH,
    collection: str = SENTINEL2_COLLECTION,
) -> ItemCollection:
    """Search Microsoft Planetary Computer for Sentinel-2 or Landsat scenes.

    Requires the `planetary-computer` package for SAS token signing.
    """
    import planetary_computer

    logger.info("Querying Planetary Computer for {}", collection)
    catalog = Client.open(
        PLANETARY_COMPUTER_URL,
        modifier=planetary_computer.sign_inplace,
    )

    if datetime_range is None:
        datetime_range = _build_datetime_range()

    search = catalog.search(
        collections=[collection],
        bbox=bbox,
        datetime=datetime_range,
        query={"eo:cloud_cover": {"lt": max_cloud_cover}},
        max_items=max_items,
    )
    items = search.item_collection()
    logger.info("Planetary Computer returned {} items", len(items))
    return items


def search_nasa_hls(
    bbox: list[float] = AOI_BBOX,
    datetime_range: Optional[str] = None,
    max_cloud_cover: int = MAX_CLOUD_COVER,
    max_items: int = MAX_ITEMS_PER_SEARCH,
) -> ItemCollection:
    """Search NASA CMR STAC for HLS (Harmonized Landsat Sentinel) data.

    Requires NASA Earthdata login credentials (via `earthaccess`).
    """
    import earthaccess

    logger.info("Authenticating with NASA Earthdata")
    earthaccess.login(strategy="environment")

    logger.info("Querying NASA HLS")
    catalog = Client.open(NASA_STAC_URL)

    if datetime_range is None:
        datetime_range = _build_datetime_range()

    search = catalog.search(
        collections=[HLS_LANDSAT_COLLECTION, HLS_SENTINEL_COLLECTION],
        bbox=bbox,
        datetime=datetime_range,
        max_items=max_items,
    )
    items = search.item_collection()
    # Filter cloud cover client-side (NASA STAC doesn't always support query param)
    filtered = ItemCollection(
        [
            item
            for item in items
            if item.properties.get("eo:cloud_cover", 100) < max_cloud_cover
        ]
    )
    logger.info("NASA HLS returned {} items ({} after cloud filter)", len(items), len(filtered))
    return filtered


def search_sentinel2_with_fallback(
    bbox: list[float] = AOI_BBOX,
    datetime_range: Optional[str] = None,
    max_cloud_cover: int = MAX_CLOUD_COVER,
    max_items: int = MAX_ITEMS_PER_SEARCH,
) -> ItemCollection:
    """Search for Sentinel-2 imagery, falling back across providers.

    Order: Element84 → Planetary Computer.
    """
    items = search_element84(
        bbox=bbox,
        datetime_range=datetime_range,
        max_cloud_cover=max_cloud_cover,
        max_items=max_items,
    )
    if len(items) > 0:
        return items

    logger.warning("Element84 returned no results, falling back to Planetary Computer")
    return search_planetary_computer(
        bbox=bbox,
        datetime_range=datetime_range,
        max_cloud_cover=max_cloud_cover,
        max_items=max_items,
    )


def search_landsat(
    bbox: list[float] = AOI_BBOX,
    datetime_range: Optional[str] = None,
    max_cloud_cover: int = MAX_CLOUD_COVER,
    max_items: int = MAX_ITEMS_PER_SEARCH,
) -> ItemCollection:
    """Search for Landsat Collection 2 Level 2 imagery via Planetary Computer."""
    return search_planetary_computer(
        bbox=bbox,
        datetime_range=datetime_range,
        max_cloud_cover=max_cloud_cover,
        max_items=max_items,
        collection=LANDSAT_COLLECTION,
    )
