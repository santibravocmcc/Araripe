# Running detection via Google Earth Engine (2026 and beyond)

Same idea as the baseline rebuild: let GEE do the heavy pixel work on Google's
servers and download only small per-date results, avoiding the AWS streaming
bottleneck. Produces the same `data/alerts/alerts_YYYY-MM-DD.geojson` the site
consumes, using the **unchanged** local detection logic against the reflectance
baselines.

## Step 1 — compute per-date composites in Cloud Shell

In Google Cloud Shell (project `ee-araripe`, already authenticated), create
`build_detection_gee.py` (content is in `scripts/build_detection_gee.py`) and run:

```bash
python3 build_detection_gee.py --project ee-araripe --start 2026-01-01 --end 2026-07-13
# (or --start 2026-04-28 to only cover dates after the last existing alerts)
```

It queues one export task per acquisition date (each date's Sentinel-2 tiles are
mosaicked into one AOI-wide image; NDMI/NBR/EVI2/BSI on reflectance). Watch with
`earthengine task list`. Results land in Google Drive folder `araripe_detection`.

## Step 2 — download and run detection locally

Download the per-date GeoTIFFs to your Mac (e.g. `~/Downloads/araripe_detection/`),
then in the Araripe repo:

```bash
python scripts/run_detection_from_gee.py --in-dir ~/Downloads/araripe_detection
# offline/quicker (skip the CHIRPS drought fetch): add --no-spi
```

This runs the existing pipeline (z-score vs the reflectance baselines → scene-wide
guard → vectorize → fire/mechanical → land cover → temporal persistence) and writes
`data/alerts/alerts_YYYY-MM-DD.geojson`. Processing all 2026 dates re-detects the
Jan–Apr files too, now consistently in reflectance scale. (This also fixes the old
streaming bug where same-date tiles overwrote each other — GEE gives one clean
AOI-wide composite per date.)

## Step 3 — publish to the live site

The static site reads alerts by cloning the Araripe repo. So:

```bash
# 1. commit the new alerts to the Araripe repo (alerts are Git-LFS tracked)
git add data/alerts/ data/timeseries/ && git commit -m "detect: 2026 alerts (GEE)" && git push

# 2. rebuild the site's data (in the site repo) and push -> Cloudflare deploys
cd ../Observatorio_Chapada_do_Araripe/site
python scripts/prepare_data.py alerts timeseries
git add public/data && git commit -m "chore: update alerts (2026)" && git push
```
(Or just trigger the site's `update-data.yml` workflow manually once the Araripe
alerts are pushed — it clones Araripe, runs `prepare_data.py`, and deploys.)

---

## Publishing the baselines to R2 (for future automation)

The baselines are git-ignored local data. To make them available off your Mac
(e.g. for a scheduled CI run), publish them to Cloudflare R2 (10 GB free):

```bash
# From your Mac (where data/baselines/ exists), with your R2 creds in the env:
export R2_ENDPOINT_URL=... R2_ACCESS_KEY=... R2_SECRET_KEY=...
python scripts/upload_to_r2.py            # uploads data/baselines/*.tif -> araripe-cogs/baselines/
```
To pull them back on another machine / CI runner:
```bash
export R2_ENDPOINT_URL=... R2_ACCESS_KEY=... R2_SECRET_KEY=...
python scripts/fetch_baselines_from_r2.py   # -> data/baselines/
```
Set the three `R2_*` values as **GitHub Secrets** on the repo to let a workflow
fetch them before detection. (Creating the R2 API token is done in the Cloudflare
dashboard → R2 → Manage API Tokens — that's an account action only you can do.)
