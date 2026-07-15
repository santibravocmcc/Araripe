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
`data/alerts/alerts_YYYY-MM-DD.geojson`.

> Every run also writes a full-detail log to `logs/run_detection_from_gee_<timestamp>.log`
> (the console shows INFO; the file keeps DEBUG). Add `--log-level DEBUG` to mirror
> everything on the terminal. Same for `run_detection.py` and `run_detection_gee.py`. Processing all 2026 dates re-detects the
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

---

## Fully automated: GEE detection inside GitHub Actions (headless)

`scripts/run_detection_gee.py` runs the whole GEE flow unattended — no Cloud
Shell, no Google Drive. It authenticates Earth Engine with a **service account**,
builds each date's composite server-side, **pulls it down synchronously in tiles**
(`getDownloadURL`, no async Export tasks), and feeds the composites into the same
detection logic as the manual path (`run_detection_from_gee.run_detection_on_dir`).

The workflow is `.github/workflows/detect_gee.yml` (manual `workflow_dispatch` by
default so you can validate it before scheduling).

### One-time setup (your Google Cloud account)

1. **Register the Cloud project for Earth Engine** at
   `https://console.cloud.google.com/earth-engine` and **enable the Earth Engine
   API** on it. (Unregistered projects lost EE access in 2024.)
2. **Create a service account** (IAM & Admin → Service accounts) in that project
   and grant it the **Earth Engine Resource Writer** role
   (`roles/earthengine.writer`) — **Viewer is NOT enough**: it lacks
   `earthengine.computations.create` and `earthengine.thumbnails.create`, so
   computing/downloading composites fails with a 403. Also add **Service Usage
   Consumer** (`roles/serviceusage.serviceUsageConsumer`) if you later get a
   `serviceusage.services.use` denial. Via gcloud:
   ```bash
   gcloud projects add-iam-policy-binding ee-araripe \
     --member="serviceAccount:<SA_EMAIL>" --role="roles/earthengine.writer"
   ```
3. **Create a JSON key** for the service account and download it.
4. In the GitHub repo settings:
   - add a **secret** `GEE_SA_KEY` = the *entire contents* of that JSON key file;
   - add a repo **variable** `EE_PROJECT` = your EE project id (defaults to `ee-araripe`);
   - ensure the `R2_*` secrets (above) are set so the baselines can be fetched.

### Running it

- **Manually:** GitHub → Actions → "GEE Deforestation Detection (headless)" →
  *Run workflow*, optionally filling `start` / `end` (blank = last 16 days).
- **On a schedule:** once a manual run succeeds end-to-end, uncomment the
  `schedule:` block in `detect_gee.yml` **and** disable the `schedule:` in
  `update_data.yml` (running both would double-detect and fight on `git push`).

### Locally (interactive EE creds, no service account)

```bash
python scripts/run_detection_gee.py --project ee-araripe --start 2026-04-28 --end 2026-05-15
```

### Streaming vs GEE in CI — which to schedule?

A GitHub runner is **not** network-throttled the way a home connection in Brazil
is, so the streaming path (`update_data.yml` → `run_detection.py`, now fetching
baselines from R2 and merging same-date tiles correctly) already works in CI and
needs no Earth Engine service account. The GEE path is the "cleaner" option
(GEE's compute, one AOI composite per date), but adds the service-account setup
above. Pick one to put on the cron; keep the other as `workflow_dispatch` backup.

> Validation note: the EE-touching download in `run_detection_gee.py` /
> `gee_download.py` needs live Earth Engine credentials and has not been run in
> this repo's offline test suite (the pure tiling/mosaic helpers *are* tested).
> Do a manual `workflow_dispatch` run and confirm the alerts look right before
> moving the cron onto it.
