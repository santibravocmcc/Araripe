---
title: Araripe Deforestation Monitor
emoji: 🌳
colorFrom: green
colorTo: red
sdk: streamlit
sdk_version: "1.40.0"
app_file: app.py
pinned: false
license: agpl-3.0
---

# Araripe

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![Data: CC BY-SA 4.0](https://img.shields.io/badge/Data-CC_BY--SA_4.0-lightgrey.svg)](DATA_LICENSE)
[![DOI](https://zenodo.org/badge/1152379890.svg)](https://doi.org/10.5281/zenodo.19885824)

Zero-cost deforestation monitoring system for Chapada do Araripe, Brazil.

Detects vegetation loss across the Cerrado/Caatinga transition zone (~7-8S, 39-40W) using Sentinel-2 and Landsat satellite imagery, processed twice-weekly via GitHub Actions and visualized through a Streamlit dashboard.

## Architecture

```
Sentinel-2 / Landsat (STAC APIs)
        │
        ▼
  GitHub Actions (twice-weekly cron)
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
│   ├── run_detection.py        # Twice-weekly detection pipeline
│   └── upload_to_r2.py         # Upload COGs to Cloudflare R2
├── data/
│   ├── aoi/                    # Study area GeoJSON
│   ├── baselines/              # Monthly baseline COGs
│   ├── alerts/                 # Detection alert GeoJSONs
│   └── timeseries/             # SQLite database
├── tests/                      # Unit tests
└── .github/workflows/          # Twice-weekly automation
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
- `PC_SDK_SUBSCRIPTION_KEY` — Microsoft Planetary Computer (optional, increases rate limits)

## Running Tests

```bash
pytest tests/ -v
```

## License

- **Source code:** [GNU Affero General Public License v3.0 or later](LICENSE)
  (AGPL-3.0-or-later) — a strong copyleft license. You may use, modify, and
  distribute the code, including commercially, but any distributed or modified
  version must be released under the same license with its complete source.
  Its network clause (section 13) closes the "SaaS loophole": if you run a
  modified version as a network service (for example, as a web app on Hugging
  Face Spaces), you must offer that service's users the corresponding source.
- **Data products** (`data/baselines/`, `data/alerts/`, `data/timeseries/`,
  `data/aoi/`): [Creative Commons Attribution-ShareAlike 4.0 International](DATA_LICENSE)
  (CC-BY-SA-4.0). You may share and adapt the data, including for commercial
  use, as long as you credit the project and license any derivatives under the
  same terms (CC-BY-SA-4.0).

The repository is intentionally public so the methodology can be replicated in
other regions. Copyright protects authorship regardless of visibility — the
combination of license + DOI + `CITATION.cff` is what preserves credit.

> **Relicensing & versioning note.** The v1.0.0 snapshot archived on Zenodo
> (version DOI [10.5281/zenodo.19885825](https://doi.org/10.5281/zenodo.19885825))
> remains under its original licenses — Apache-2.0 (code) and CC-BY-4.0 (data)
> — permanently; relicensing is not retroactive. The AGPL-3.0-or-later /
> CC-BY-SA-4.0 terms above apply from **v2.0.0** onward — the release that
> marks the license change. The badge and citation above use the *concept*
> DOI (10.5281/zenodo.19885824), which always resolves to the latest version.

## How to cite

If you use this software, the baseline products, or the alert outputs in your
research, please cite the project. The canonical metadata lives in
[`CITATION.cff`](CITATION.cff) (GitHub renders a "Cite this repository"
button in the right-hand sidebar).

Please cite as:

> Bravo, S. (2026). *Chapada do Araripe Deforestation Monitor* (Version 2.0.0)
> [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.19885824

BibTeX:

```bibtex
@software{bravo_araripe_2026,
  author  = {Bravo, Santiago},
  title   = {Chapada do Araripe Deforestation Monitor},
  year    = {2026},
  version = {2.0.0},
  doi     = {10.5281/zenodo.19885824},
  url     = {https://github.com/santibravocmcc/Araripe}
}
```

### Replicating in another region

Fork the repository, replace the polygon in `data/aoi/` with the boundary of
your study area, adjust `AOI_BBOX` in [`config/settings.py`](config/settings.py),
rebuild the baselines (`python scripts/build_baseline.py`), and credit the
upstream project per the AGPL-3.0 `NOTICE` and the CC-BY-SA-4.0 attribution
clause. Because the code is AGPL-3.0-or-later, any fork you publish — or run
as a hosted service (e.g. on Hugging Face Spaces) — must itself stay open:
release your modified source under the same license and, for a network
service, offer it to that service's users (AGPL section 13). Adapted data
products must likewise be shared under CC-BY-SA-4.0.
