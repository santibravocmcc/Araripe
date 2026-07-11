# Rebuilding the baseline with Google Earth Engine (recommended)

**Why:** streaming hundreds of Sentinel-2 scenes from AWS to a home connection in
Brazil is the bottleneck (~1 MB/s, intermittently throttled — measured). Earth
Engine (EE) computes the monthly composites **on Google's servers** and you
download only the small results (12 GeoTIFFs). This sidesteps the download
problem entirely and, as a bonus, produces a true **median** composite and uses
the offset-harmonized `S2_SR_HARMONIZED` collection (no scale/offset juggling).

The output matches the local pipeline exactly: years {2017, 2019, 2021, 2022,
2025}, cloud-masked (SCL clear classes {2,4,5,6,7,11}), NDMI/NBR/EVI2 on
reflectance, per calendar month, EPSG:32724 at 20 m, over the Araripe AOI.

---

## One-time setup (~5 min, mostly in the browser)

1. **Register for Earth Engine** (free for research/non-commercial): go to
   <https://earthengine.google.com>, click *Get Started*, sign in with a Google
   account, and create (or select) a **Google Cloud project**. Note the project
   ID (e.g. `ee-yourname`).
2. **Authenticate locally** (one browser popup, stores a token):
   ```bash
   # use this repo's environment (the one with earthengine-api installed)
   earthengine authenticate
   ```

## Step 1 — queue the composites on Google's servers

```bash
python scripts/build_baseline_gee.py --project YOUR_PROJECT_ID
# options: --max-cloud 40  --months 1,2,3  --drive-folder araripe_baselines  --dry-run
```
This starts **12 export tasks** (one per month). They run on Google's side
(minutes to ~1 h total). Watch progress in the EE Code Editor **Tasks** tab
(<https://code.earthengine.google.com>) or with:
```bash
earthengine task list
```

## Step 2 — download the results from Google Drive

When the tasks finish, the 12 files
`araripe_baseline_month01.tif … araripe_baseline_month12.tif` appear in your
Google Drive folder (`araripe_baselines` by default). Download them to a local
folder, e.g. `~/Downloads/araripe_baselines/`. (Drive downloads use Google's
CDN and are fast; the whole set is small.)

## Step 3 — split into the baseline files the detector reads

```bash
python scripts/split_gee_baselines.py --in-dir ~/Downloads/araripe_baselines --out-dir data/baselines
```
This writes the 72 `data/baselines/<index>_month<NN>_{mean,std}.tif` COGs
(nodata = NaN). **Back up the current DN baselines first** if you want a rollback:
```bash
mkdir -p data/baselines_dn_backup && cp data/baselines/*.tif data/baselines_dn_backup/
```

## Step 4 — activate the EVI2 fix (the coupling)

The GEE baselines are in **surface reflectance**, so the detection side must also
produce reflectance. Set the flag in `config/settings.py`:
```python
REFLECTANCE_SCALING = True
```
Then verify:
```bash
pytest -q
# quick sanity: rebuilt EVI2 should be ~0.1–0.5 (reflectance), NOT ~0.99 (old DN)
python -c "import rasterio,numpy as np; a=rasterio.open('data/baselines/evi2_month07_mean.tif').read(1); print('EVI2 median', round(float(np.nanmedian(a[np.isfinite(a)])),3))"
```

## Step 5 (production) — publish the new baselines

The baselines are git-ignored (local data). For the GitHub Actions detection to
use them, upload the new set to wherever the workflow reads baselines (R2 / HF /
LFS) — same as any baseline update.

---

## Browser-only alternative (no local install)

You can also paste an equivalent script into the EE **Code Editor**
(<https://code.earthengine.google.com>, JavaScript) and click *Run* — the export
tasks and the Drive output are identical. Ask for the `.js` snippet if you prefer
this path; the Python script above is the maintained reference.

## If you'd rather fix the local download instead

The benchmark found the local slowness was largely a client-side GDAL config
issue: with the range-cache disabled every provider collapsed to ~0.1 MB/s, and
`CHUNK_SIZE=512` (config/settings.py) fragments reads. Raising `CHUNK_SIZE` (e.g.
2048) and keeping `VSI_CACHE=TRUE` speeds up the local `build_baseline.py` on any
provider. Provider-switching does **not** help — Planetary Computer measured ~2×
slower than the current AWS source from Brazil.
