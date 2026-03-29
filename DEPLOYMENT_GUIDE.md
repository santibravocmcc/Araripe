# Araripe Deployment Guide

This document explains how to deploy the three external services that make the monitoring system fully automated and publicly accessible. Each section explains **what** the service does, **why** it's needed, and **how** to set it up step by step.

---

## Architecture Overview

The system has three moving parts beyond your local machine:

```
GitHub Actions (weekly cron)
    |
    ├── Runs detection pipeline (queries free STAC imagery)
    ├── Saves alert GeoJSON + time series to the repo
    └── Uploads baseline COGs to Cloudflare R2
                                        |
                                        v
                            Cloudflare R2 (COG storage)
                            (free S3-compatible hosting)
                                        |
                                        v
                            Hugging Face Spaces (dashboard)
                            (free Streamlit hosting)
                            reads COGs via HTTP range requests
```

**Why this architecture?** Everything is free-tier. Element84 STAC is open (no auth needed for the primary data source). Cloudflare R2 has zero egress fees. HF Spaces hosts Streamlit for free. GitHub Actions gives 2,000 minutes/month free.

---

## 1. Dashboard Deployment (Hugging Face Spaces)

### What it does
Hosts the Streamlit dashboard (`app.py`) publicly so anyone can view alerts, time series, and the interactive map without installing anything.

### Why Hugging Face Spaces?
- Free Streamlit hosting (2 vCPU, 16 GB RAM)
- No cold-start issues like some alternatives
- Git-based deployment (push to deploy)
- Supports secrets for environment variables

### Setup Steps

#### 1.1 Create a new Space

1. Go to https://huggingface.co/new-space
2. Fill in:
   - **Owner**: your HF username
   - **Space name**: `araripe-monitor` (or similar)
   - **SDK**: select **Streamlit**
   - **Visibility**: Public (or Private if preferred)
3. Click **Create Space**

#### 1.2 Connect your repo

You have two options:

**Option A: Push directly to HF (simplest)**

```bash
# Add HF Spaces as a second remote
cd /Users/sbravo/Documents/Projetos/Araripe
git remote add hf https://huggingface.co/spaces/YOUR_USERNAME/araripe-monitor

# Push to deploy
git push hf main
```

Every `git push hf main` redeploys the dashboard.

**Option B: Sync from GitHub automatically**

1. In your HF Space settings, go to **Repository** > **Link a GitHub repo**
2. Select your GitHub repo
3. The Space will auto-redeploy when you push to GitHub

#### 1.3 Configure the Space

HF Spaces needs a small metadata file at the repo root. Create `README.md` front matter or ensure these settings exist:

The Space will read `app.py` automatically since it's a Streamlit SDK space. If your `app.py` is at the repo root, no extra config is needed.

#### 1.4 Add Space secrets (if needed)

If your dashboard reads any data from R2 or needs credentials:

1. Go to your Space > **Settings** > **Variables and secrets**
2. Add any required variables (e.g., `R2_ENDPOINT_URL` if the dashboard streams COGs from R2)

#### 1.5 Data files

The dashboard reads from:
- `data/alerts/*.geojson` — alert polygons
- `data/timeseries/timeseries.db` — SQLite time series database
- `data/aoi/chapada_araripe.gpkg` — AOI polygon

These are committed to the repo, so they'll be available in the Space automatically. When GitHub Actions updates them (see section 2), push the changes to HF to update the dashboard.

#### 1.6 Verify

Once deployed, your dashboard will be live at:
```
https://huggingface.co/spaces/YOUR_USERNAME/araripe-monitor
```

---

## 2. GitHub Actions (Automated Weekly Detection)

### What it does
Runs the detection pipeline (`scripts/run_detection.py`) every Monday at 06:00 UTC. It queries the latest Sentinel-2 imagery from free STAC APIs, compares against baselines, generates alerts, and commits the results back to the repo.

### Why GitHub Actions?
- 2,000 free minutes/month on the free tier
- The detection pipeline takes ~20-30 minutes per run (well within budget for weekly runs)
- Keeps the alert data up to date without any manual intervention

### Why STAC credentials?

The workflow file (`.github/workflows/update_data.yml`) references four credential secrets:

| Secret | Service | Why needed |
|--------|---------|------------|
| `CDSE_USERNAME` | Copernicus Data Space | **Fallback** STAC API. The primary source (Element84) needs no auth, but if it's down, the pipeline falls back to Copernicus, which requires a free account |
| `CDSE_PASSWORD` | Copernicus Data Space | Password for the above |
| `EARTHDATA_USERNAME` | NASA Earthdata | **Fallback** for HLS (Harmonized Landsat-Sentinel) data. Also free, requires registration |
| `EARTHDATA_PASSWORD` | NASA Earthdata | Password for the above |

**Note:** The primary data source (Element84 Earth Search) requires **no authentication**. These secrets are only for fallback providers. The pipeline will work without them — it just won't have fallback options if Element84 is unavailable.

### Setup Steps

#### 2.1 Push your repo to GitHub

If not already done:
```bash
# Create a repo on GitHub, then:
git remote add origin https://github.com/YOUR_USERNAME/araripe.git
git push -u origin main
```

#### 2.2 Add repository secrets

1. Go to your GitHub repo > **Settings** > **Secrets and variables** > **Actions**
2. Click **New repository secret** for each:

**Required for R2 upload (see section 3):**
- `R2_ENDPOINT_URL` — your Cloudflare R2 S3-compatible endpoint
- `R2_ACCESS_KEY` — R2 API token access key
- `R2_SECRET_KEY` — R2 API token secret key

**Optional (fallback STAC providers):**
- `CDSE_USERNAME` — register free at https://dataspace.copernicus.eu
- `CDSE_PASSWORD`
- `EARTHDATA_USERNAME` — register free at https://urs.earthdata.nasa.gov
- `EARTHDATA_PASSWORD`

#### 2.3 Test the workflow

1. Go to **Actions** tab in your GitHub repo
2. Select "Weekly Deforestation Detection" workflow
3. Click **Run workflow** > **Run workflow** (manual trigger)
4. Monitor the run — it should complete in ~20-30 minutes

#### 2.4 What the workflow does each week

```
1. Checks out the repo
2. Sets up conda environment from environment.yml
3. Runs detection pipeline:
   - Queries Element84 STAC for recent Sentinel-2 scenes
   - Downloads bands via HTTP range requests (no full download)
   - Applies cloud mask, computes indices, compares to baselines
   - Generates alert GeoJSON files
4. Uploads baseline COGs to Cloudflare R2 (if configured)
5. Commits new alerts + time series to the repo
6. Pushes the commit (auto-updates HF Spaces if linked)
```

---

## 3. Cloudflare R2 (Baseline COG Hosting)

### What it does
Stores the 72 baseline COG files (~1.5 GB total) as publicly accessible Cloud Optimized GeoTIFFs. The dashboard can stream pixel data from these files via HTTP range requests without downloading the entire file.

### Why Cloudflare R2?
- **10 GB free storage** (our baselines use ~1.5 GB)
- **Zero egress fees** — unlike AWS S3, reading data from R2 is free regardless of volume
- **S3-compatible API** — works with standard tools (boto3, rasterio, GDAL)
- COGs support HTTP range requests, so the dashboard only fetches the pixels it needs for the current map view

### Why not just commit the COGs to Git?
The 72 baseline files total ~1.5 GB. Git/GitHub repos have soft limits around 1 GB and hard limits at 5 GB. Storing large binary files in Git also bloats every clone. R2 is purpose-built for this.

### Setup Steps

#### 3.1 Create a Cloudflare account

1. Go to https://dash.cloudflare.com/sign-up
2. Create a free account (no credit card required for R2 free tier)

#### 3.2 Enable R2 and create a bucket

1. In the Cloudflare dashboard, go to **R2 Object Storage** in the left sidebar
2. Click **Create bucket**
3. Name it `araripe-cogs` (matches `config/settings.py`)
4. Choose a location hint close to your users (e.g., South America - WNAM)
5. Click **Create bucket**

#### 3.3 Enable public access

For the dashboard to read COGs via HTTP range requests:

1. Go to your bucket > **Settings**
2. Under **Public access**, click **Allow Access**
3. Either:
   - Add a **Custom Domain** (e.g., `cogs.yourdomain.com`), or
   - Use the **R2.dev subdomain** — enable it and note the URL (e.g., `https://pub-xxxx.r2.dev`)

Note the public URL — the dashboard will use this to stream COGs.

#### 3.4 Create API credentials

1. Go to **R2 Object Storage** > **Manage R2 API tokens** (top right)
2. Click **Create API token**
3. Configure:
   - **Token name**: `araripe-upload`
   - **Permissions**: **Object Read & Write**
   - **Specify bucket(s)**: select `araripe-cogs`
4. Click **Create API Token**
5. **Save these values** (shown only once):
   - **Access Key ID** → this is your `R2_ACCESS_KEY`
   - **Secret Access Key** → this is your `R2_SECRET_KEY`
6. Your **R2 endpoint URL** is shown on the R2 overview page:
   ```
   https://<ACCOUNT_ID>.r2.cloudflarestorage.com
   ```
   This is your `R2_ENDPOINT_URL`.

#### 3.5 Upload baselines locally (one-time)

```bash
cd /Users/sbravo/Documents/Projetos/Araripe

# Set credentials
export R2_ENDPOINT_URL="https://<ACCOUNT_ID>.r2.cloudflarestorage.com"
export R2_ACCESS_KEY="your_access_key"
export R2_SECRET_KEY="your_secret_key"

# Upload all 72 baseline COGs
python scripts/upload_to_r2.py --directory data/baselines --prefix baselines/
```

This uploads all `.tif` files from `data/baselines/` to the `baselines/` prefix in your R2 bucket. After this, the COGs are accessible at:
```
https://pub-xxxx.r2.dev/baselines/ndmi_month01_mean.tif
```

#### 3.6 Add R2 credentials to GitHub Actions

Add these three secrets to your GitHub repo (Settings > Secrets > Actions):

| Secret | Value |
|--------|-------|
| `R2_ENDPOINT_URL` | `https://<ACCOUNT_ID>.r2.cloudflarestorage.com` |
| `R2_ACCESS_KEY` | Your R2 API token access key |
| `R2_SECRET_KEY` | Your R2 API token secret key |

Now the weekly GitHub Actions workflow will automatically upload any new/updated COGs after each detection run.

---

## Quick Reference: All Credentials

| Where | Secret | Source | Required? |
|-------|--------|--------|-----------|
| GitHub Actions | `R2_ENDPOINT_URL` | Cloudflare R2 dashboard | Yes (for COG hosting) |
| GitHub Actions | `R2_ACCESS_KEY` | Cloudflare R2 API token | Yes (for COG hosting) |
| GitHub Actions | `R2_SECRET_KEY` | Cloudflare R2 API token | Yes (for COG hosting) |
| GitHub Actions | `CDSE_USERNAME` | https://dataspace.copernicus.eu | Optional (fallback) |
| GitHub Actions | `CDSE_PASSWORD` | Copernicus Data Space | Optional (fallback) |
| GitHub Actions | `EARTHDATA_USERNAME` | https://urs.earthdata.nasa.gov | Optional (fallback) |
| GitHub Actions | `EARTHDATA_PASSWORD` | NASA Earthdata | Optional (fallback) |
| HF Spaces | `R2_ENDPOINT_URL` | Same as above | Only if dashboard streams from R2 |

---

## Recommended Setup Order

1. **Cloudflare R2** — create bucket, get credentials, upload baselines
2. **GitHub repo** — push code, add all secrets
3. **GitHub Actions** — trigger a manual test run, verify it completes
4. **Hugging Face Spaces** — create Space, link to GitHub or push directly
5. **Verify end-to-end** — trigger Actions, check that alerts update in the dashboard
