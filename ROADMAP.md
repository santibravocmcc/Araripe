# Roadmap — Observatório da Chapada do Araripe

Tracked, explicitly-not-yet-implemented items. These are documented here so the
codebase does not overstate its current capabilities.

## 1. BFAST (real structural-break detection)

**Status:** roadmap. **Not implemented.**

The repo contains a *simplified* harmonic-residual check
(`src/timeseries/seasonal.py::harmonic_fit` + `detect_breakpoints`): it fits a
2-harmonic Fourier model and flags observations exceeding 3× RMSE on 3
consecutive dates. This is a BFAST-*Monitor-style* heuristic on 1-D regional
series only, and it is **not connected to the pixel/alert detection pipeline or
the dashboard**. It must not be presented as BFAST.

A real implementation would require:
- Porting or depending on `bfast` / `pybfast` (or `bfast` in R via `rpy2`), or
  implementing the OLS-MOSUM / recursive-residual structural-break tests with
  confidence intervals.
- Proper trend + seasonal decomposition (not just a harmonic residual band).
- A **longer, denser historical time series** per pixel/region. Task 1 (the
  multi-year baseline rebuild via COG streaming, `scripts/build_baseline.py
  --year-set …`) is the first step toward assembling that history; BFAST would
  additionally need the full per-date stack retained, not just monthly
  mean/std composites.
- A decision on spatial scope (per-pixel BFAST over the AOI is expensive;
  region- or parcel-aggregated series are more tractable).

## 2. Sentinel-1 SAR (wet-season cloud penetration)

**Status:** roadmap. **Not implemented.** CDSE/Copernicus dead config was
removed (it was never consumed; see AUDITORIA_TECNICA.md Task 7.3).

SAR is the correct long-term answer to the Nov–Apr cloud gaps that currently
drive optical false positives, but it is a **separate project**, not a
credential toggle:
- Requires its own preprocessing chain: GRD radiometric calibration, speckle
  filtering, terrain (RTC) correction.
- Requires SAR-specific change detection (backscatter/coherence change); it
  cannot reuse the NDMI/NBR/EVI2 optical thresholds.
- Access: `sentinel-1-grd` / `sentinel-1-rtc` are available on Planetary
  Computer and CDSE; CDSE asset download needs OAuth2.

## 3. Per-sensor baselines for Landsat / HLS

**Status:** partial. Landsat and NASA HLS are now wired as optional extra
observation sources (`run_detection.py --extra-sources landsat,hls`) to raise
observation density and strengthen the temporal-persistence filter. However
they are currently compared against the **Sentinel-2 (20 m) baselines** via
nearest-neighbour grid snapping — a cross-sensor approximation. Ideally each
sensor gets its own monthly baseline built from its own archive.

## 4. Independent omission-error reference

**Status:** infrastructure only. `scripts/sample_alerts_for_validation.py`
supports **commission** (false-positive) estimation via stratified sampling +
human visual interpretation. **Omission** (missed clearings) needs an
independent reference clearing layer (e.g. PRODES/DETER or manually digitized
clearings) that is *not* derived from these alerts. Assembling that layer and
the visual interpretation itself are human steps (see AUDITORIA_TECNICA.md
Task 4).

## 5. Package 2B.0 — isolated green foundation and operating policy

**Status:** active. Production (blue) is frozen: the scheduled workflows
`detect_gee.yml` and `update_data.yml`, Worker `observatorio-chapada`, bucket
`araripe-cogs`, the final public domain, DNS, and routes stay unchanged until
the separately approved cutover. The complete remediation plan (34 topics,
Phases 0–7) is maintained on the planning branch
`codex/technical-review-roadmap`; this section records only what is installed
on `main`.

Green components are additive and isolated: the private bucket
`araripe-v2-staging`, the unrouted Worker `observatorio-chapada-v2-staging`,
manual-only v2 workflows in distinct concurrency lanes, and the restricted
Cloudflare green-control broker. See
`docs/implementation/PHASE_2B0_2026-08-11.md`,
`docs/operations/RESTRICTED_CLOUDFLARE_BROKER.md`, and
`docs/operations/GREEN_CONCURRENCY_LANES.md`.

Risk-based approval policy:

- Autonomous (no repeated approval): local development and alternative local
  branches; object operations in `araripe-v2-staging`; manual green workflows
  holding only the staging-scoped identity; read-only verifications; commits,
  branch pushes, and opening pull requests; merging a minimal, additive,
  inert pull request proven not to change blue runtime files.
- Explicit human approval: any action with authority or potential effect on
  production — blue workflows, the production Worker, `araripe-cogs`, the
  final public domain, DNS, routes, canonical pointers, the public site,
  cutover steps, and any Cloudflare token with account-level edit permission.
- GitHub Environment `v2-staging` (bucket-scoped identity) needs no reviewer;
  `cloudflare-green-control` keeps a required human reviewer because its
  token can edit at account level. No agent approves its own Environment run
  or bypasses a pending approval, failure, or broker refusal; a missing
  broker operation means stop and hand off, never Wrangler, `curl`, direct
  API, or a different credential.
