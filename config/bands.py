"""Band mappings for Sentinel-2, Landsat 8/9, and HLS datasets.

Each sensor dict maps logical band names to asset keys used in STAC items.
Wavelengths and resolutions are provided for reference.
"""

# ─── Sentinel-2 L2A (Element84 / Planetary Computer) ─────────────────────────
SENTINEL2_BANDS = {
    "blue":       {"asset": "blue",       "band": "B2",  "wavelength_nm": 490,  "resolution_m": 10},
    "green":      {"asset": "green",      "band": "B3",  "wavelength_nm": 560,  "resolution_m": 10},
    "red":        {"asset": "red",        "band": "B4",  "wavelength_nm": 665,  "resolution_m": 10},
    "rededge1":   {"asset": "rededge1",   "band": "B5",  "wavelength_nm": 705,  "resolution_m": 20},
    "rededge2":   {"asset": "rededge2",   "band": "B6",  "wavelength_nm": 740,  "resolution_m": 20},
    "rededge3":   {"asset": "rededge3",   "band": "B7",  "wavelength_nm": 783,  "resolution_m": 20},
    "nir":        {"asset": "nir",        "band": "B8",  "wavelength_nm": 842,  "resolution_m": 10},
    "nir08":      {"asset": "nir08",      "band": "B8A", "wavelength_nm": 865,  "resolution_m": 20},
    "swir16":     {"asset": "swir16",     "band": "B11", "wavelength_nm": 1610, "resolution_m": 20},
    "swir22":     {"asset": "swir22",     "band": "B12", "wavelength_nm": 2190, "resolution_m": 20},
    "scl":        {"asset": "scl",        "band": "SCL", "wavelength_nm": None, "resolution_m": 20},
}

# ─── Landsat 8/9 Collection 2 Level 2 ────────────────────────────────────────
LANDSAT_BANDS = {
    "blue":   {"asset": "blue",   "band": "B2", "wavelength_nm": 482,  "resolution_m": 30},
    "green":  {"asset": "green",  "band": "B3", "wavelength_nm": 562,  "resolution_m": 30},
    "red":    {"asset": "red",    "band": "B4", "wavelength_nm": 655,  "resolution_m": 30},
    "nir08":  {"asset": "nir08",  "band": "B5", "wavelength_nm": 865,  "resolution_m": 30},
    "swir16": {"asset": "lwir16", "band": "B6", "wavelength_nm": 1610, "resolution_m": 30},
    "swir22": {"asset": "swir22", "band": "B7", "wavelength_nm": 2200, "resolution_m": 30},
    "qa":     {"asset": "qa_pixel", "band": "QA_PIXEL", "wavelength_nm": None, "resolution_m": 30},
}

# ─── NASA HLS (Harmonized Landsat Sentinel) ──────────────────────────────────
# HLS uses a common 30m grid with harmonized band names
HLS_BANDS = {
    "blue":   {"asset": "B02", "wavelength_nm": 490,  "resolution_m": 30},
    "green":  {"asset": "B03", "wavelength_nm": 560,  "resolution_m": 30},
    "red":    {"asset": "B04", "wavelength_nm": 665,  "resolution_m": 30},
    "nir":    {"asset": "B8A", "wavelength_nm": 865,  "resolution_m": 30},
    "swir16": {"asset": "B11", "wavelength_nm": 1610, "resolution_m": 30},
    "swir22": {"asset": "B12", "wavelength_nm": 2190, "resolution_m": 30},
    "qa":     {"asset": "Fmask", "wavelength_nm": None, "resolution_m": 30},
}

# ─── Index formulas: maps index name → required logical band names ───────────
INDEX_BANDS = {
    "ndvi":  ["nir", "red"],
    "evi2":  ["nir", "red"],
    "ndmi":  ["nir08", "swir16"],
    "nbr":   ["nir08", "swir22"],
    "savi":  ["nir", "red"],
    "bsi":   ["blue", "nir", "red", "swir16"],
}

# For Landsat, nir08 is the only NIR band available (equivalent to S2 B8A)
LANDSAT_INDEX_BANDS = {
    "ndvi":  ["nir08", "red"],
    "evi2":  ["nir08", "red"],
    "ndmi":  ["nir08", "swir16"],
    "nbr":   ["nir08", "swir22"],
    "savi":  ["nir08", "red"],
    "bsi":   ["blue", "nir08", "red", "swir16"],
}


def get_asset_key(sensor: str, logical_band: str) -> str:
    """Return the STAC asset key for a logical band name and sensor.

    Parameters
    ----------
    sensor : str
        One of "sentinel2", "landsat", or "hls".
    logical_band : str
        Logical band name (e.g., "nir", "swir16", "scl").

    Returns
    -------
    str
        The STAC asset key to use when accessing the item's assets dict.
    """
    band_maps = {
        "sentinel2": SENTINEL2_BANDS,
        "landsat": LANDSAT_BANDS,
        "hls": HLS_BANDS,
    }
    mapping = band_maps[sensor]
    return mapping[logical_band]["asset"]
