# Araripe

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
# Install dependencies
pip install -r requirements.txt

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

MIT
