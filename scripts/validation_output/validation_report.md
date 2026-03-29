# Baseline Data Validation Report

**Files analyzed:** 106
**Directory:** `01` (month 01)

---

## Cloud Contamination Assessment

### Overall: **FAIL**

### Issues (require action)
- [FAIL] EVI2: 45.7% avg pixels outside [-1, 1] — strong cloud/corruption signal
- [FAIL] EVI2: 48.4% avg pixels > 0.95 — likely unmasked bright clouds

### Warnings (review recommended)
- [WARN] NDMI: 69.0% avg pixels are exactly 0 (NoData) — check if legitimate values near zero are being lost
- [WARN] NBR: 69.0% avg pixels are exactly 0 (NoData) — check if legitimate values near zero are being lost
- [WARN] EVI2: 69.0% avg pixels are exactly 0 (NoData) — check if legitimate values near zero are being lost

---

## Per-Band Aggregate Statistics

| Metric | NDMI | NBR | EVI2 |
|--------|------|-----|------|
| Mean | 0.0583 | 0.2788 | 0.9740 |
| Std | 0.1245 | 0.1675 | 0.4037 |
| Median | 0.0646 | 0.2909 | 0.9896 |
| Min | -0.5585 | -0.5832 | -0.4146 |
| Max | 0.5502 | 0.7474 | 2.0888 |
| P1 | -0.2204 | -0.1157 | 0.1995 |
| P99 | 0.3042 | 0.5876 | 1.7436 |
| NoData fraction | 68.98% | 68.98% | 68.97% |
| Out-of-range fraction | 0.00% | 0.00% | 45.67% |
| Suspect high (>0.95) | 0.00% | 0.00% | 48.38% |
| Suspect low (<-0.95) | 0.00% | 0.00% | 0.00% |
| Near-zero fraction | 1.66% | 1.19% | 0.01% |
| Skewness | -0.1522 | -0.2661 | 0.0317 |
| Kurtosis | 0.1053 | 0.1939 | -0.3699 |

---

## Temporal Coverage

| Year | Scene count |
|------|------------|
| 2023 | 22 |
| 2024 | 30 |
| 2025 | 16 |
| 2026 | 38 |

## Tile Coverage

| Tile | Scene count |
|------|------------|
| 24MTS | 15 |
| 24MTT | 22 |
| 24MUS | 16 |
| 24MUT | 13 |
| 24MVS | 16 |
| 24MVT | 13 |
| 24MWS | 11 |

---

## Figures

![histogram_ndmi](histogram_ndmi.png)

![histogram_nbr](histogram_nbr.png)

![histogram_evi2](histogram_evi2.png)

![tile_summary](tile_summary.png)

---

## Recommendations

1. **Cloud contamination detected.** Before compositing into baselines, apply cloud masks retroactively by fetching SCL bands from STAC for each scene date and masking contaminated pixels in the index files.
2. Re-run this validation after masking to confirm the issue is resolved.