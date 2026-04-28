---
title: Araripe Deforestation Monitor
emoji: 🌳
colorFrom: green
colorTo: red
sdk: streamlit
sdk_version: "1.40.0"
app_file: app.py
pinned: false
license: apache-2.0
---

# Araripe

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Data: CC BY 4.0](https://img.shields.io/badge/Data-CC_BY_4.0-lightgrey.svg)](DATA_LICENSE)
[![DOI](https://img.shields.io/badge/DOI-pending_first_release-orange.svg)](https://zenodo.org/)

Zero-cost deforestation monitoring system for Chapada do Araripe, Brazil.

Detects vegetation loss across the Cerrado/Caatinga transition zone (~7-8S, 39-40W) using Sentinel-2 and Landsat satellite imagery, processed weekly via GitHub Actions and visualized through a Streamlit dashboard.

## Architecture

```
Sentinel-2 / Landsat (STAC APIs)
        │
        ▼
  GitHub Actions (weekly cron)
    ├── Cloud masking (SCL / QA_PIXEL)
    ├── Index computation (NDMI, NBR, EVI2)
    ├── Z-score anomaly detection vs monthly baselines
    └── Alert vectorization + confidence classification
        │
        ├── Alerts (GeoJSON) → GitHub repo
        ├── COGs → Cloudflare R2 (zero egress)
        └── Time series → SQLite
                │
                ▼
        Streamlit Dashboard (Hugging Face Spaces)
```

## Key Design Decisions

- **NDMI and NBR over NDVI** as primary indices — Caatinga's seasonal NDVI amplitude (0.30-0.50) overlaps with deforestation signals, while moisture indices maintain clearer separation
- **Monthly baselines** (12 months x 3-5 years) enable season-aware anomaly detection
- **Drought adjustment** via SPI widens z-score thresholds during El Nino events to avoid false positives
- **All processing on GitHub Actions** — the dashboard only serves pre-computed results

## Quick Start

```bash
# Create and activate conda environment (recommended)
conda env create -f environment.yml
conda activate araripe

# Or install via pip (requires system GDAL: brew install gdal / apt install gdal-bin)
pip install -r requirements.txt

# Copy env template and add your credentials
cp .env.example .env

# Run the dashboard locally
streamlit run app.py

# Run detection pipeline manually
python scripts/run_detection.py

# Build baselines from historical data (one-time setup)
python scripts/build_baseline.py --years 5 --indices ndmi,nbr,evi2
```

## Project Structure

```
├── app.py                      # Streamlit dashboard entry point
├── config/
│   ├── settings.py             # AOI, thresholds, paths, API endpoints
│   └── bands.py                # Band mappings: S2, Landsat, HLS
├── src/
│   ├── acquisition/            # STAC queries, COG streaming
│   ├── processing/             # Cloud masking, indices, composites
│   ├── detection/              # Baselines, z-score detection, alerts
│   ├── timeseries/             # Time series DB, STL, trends
│   └── visualization/          # Maps (Leafmap), charts (Plotly)
├── scripts/
│   ├── build_baseline.py       # One-time baseline computation
│   ├── run_detection.py        # Weekly detection pipeline
│   └── upload_to_r2.py         # Upload COGs to Cloudflare R2
├── data/
│   ├── aoi/                    # Study area GeoJSON
│   ├── baselines/              # Monthly baseline COGs
│   ├── alerts/                 # Detection alert GeoJSONs
│   └── timeseries/             # SQLite database
├── tests/                      # Unit tests
└── .github/workflows/          # Weekly automation
```

## Data Sources

| Source | Collection | Resolution | Auth |
|---|---|---|---|
| Element84 Earth Search | sentinel-2-l2a | 10-20m | None |
| Planetary Computer | sentinel-2-l2a, landsat-c2-l2 | 10-30m | Free SAS token |
| NASA HLS | HLSL30, HLSS30 | 30m (harmonized) | Earthdata login |

## Detection Method

1. Query recent cloud-free imagery (< 20% cloud cover)
2. Mask clouds via SCL (Sentinel-2) or QA_PIXEL (Landsat)
3. Compute NDMI, NBR, EVI2 per pixel
4. Compare against matching monthly baseline (z-score + delta)
5. Classify confidence: **High** (z < -3.0 in both NDMI & NBR), **Medium** (z < -2.5), **Low** (z < -2.0)
6. Vectorize to polygons, filter < 1 ha, save as GeoJSON

## Environment Variables

Copy `.env.example` to `.env` and configure:

- `CDSE_USERNAME` / `CDSE_PASSWORD` — Copernicus Data Space (optional)
- `EARTHDATA_USERNAME` / `EARTHDATA_PASSWORD` — NASA Earthdata (for HLS)
- `R2_ENDPOINT_URL` / `R2_ACCESS_KEY` / `R2_SECRET_KEY` — Cloudflare R2 storage

## Running Tests

```bash
pytest tests/ -v
```

## License

- **Source code:** [Apache License 2.0](LICENSE) — permissive, with explicit
  patent grant and a `NOTICE` file that propagates attribution to derivative
  works.
- **Data products** (`data/baselines/`, `data/alerts/`, `data/timeseries/`,
  `data/aoi/`): [Creative Commons Attribution 4.0 International](DATA_LICENSE)
  (CC-BY-4.0). You may share and adapt the data, including for commercial use,
  as long as you credit the project.

The repository is intentionally public so the methodology can be replicated in
other regions. Copyright protects authorship regardless of visibility — the
combination of license + DOI + `CITATION.cff` is what preserves credit.

## How to cite

If you use this software, the baseline products, or the alert outputs in your
research, please cite the project. The canonical metadata lives in
[`CITATION.cff`](CITATION.cff) (GitHub renders a "Cite this repository"
button in the right-hand sidebar).

After the first tagged release the project will receive a persistent
[Zenodo](https://zenodo.org) DOI; the badge above will then point at it. Until
then, please cite as:

> Bravo, S. (2026). *Chapada do Araripe Deforestation Monitor* (Version 1.0.0)
> [Computer software]. https://github.com/santibravocmcc/Araripe

BibTeX:

```bibtex
@software{bravo_araripe_2026,
  author  = {Bravo, Santiago},
  title   = {Chapada do Araripe Deforestation Monitor},
  year    = {2026},
  version = {1.0.0},
  url     = {https://github.com/santibravocmcc/Araripe}
}
```

### Replicating in another region

Fork the repository, replace the polygon in `data/aoi/` with the boundary of
your study area, adjust `AOI_BBOX` in [`config/settings.py`](config/settings.py),
rebuild the baselines (`python scripts/build_baseline.py`), and credit the
upstream project per the Apache-2.0 NOTICE and the CC-BY-4.0 attribution
clause.
