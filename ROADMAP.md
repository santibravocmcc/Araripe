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

**Status:** closed 2026-08-13 (PR #10, merge `8daa181`; broker audit run
`31719834876`; green proofs `31720230963`, `31720226492`, `31720228888`;
approved mutation run `31724415945`). Production (blue) remains frozen: the
scheduled workflows `detect_gee.yml` and `update_data.yml`, Worker
`observatorio-chapada`, bucket `araripe-cogs`, the final public domain, DNS,
and routes stay unchanged until the separately approved cutover. The complete
remediation plan (34 topics, Phases 0–7) is maintained on the planning branch
`codex/technical-review-roadmap`; this section records only what is installed
on `main`.

Green components are additive and isolated: the private bucket
`araripe-v2-staging`, the unrouted Worker `observatorio-chapada-v2-staging`,
manual-only v2 workflows in distinct concurrency lanes, and the restricted
Cloudflare green-control broker. The wildcard non-production site deploy
command is temporarily inert (`exit 0`); a reviewed green site deploy path is
future Package 2B.4 work. Package 2A.6 (candidate-generation science) is open
and not started; it proceeds as Packages 2A.6A–2A.6D on the isolated science
base branch. See `docs/implementation/PHASE_2B0_2026-08-11.md`,
`docs/operations/CLOUDFLARE_GREEN_AFTER_STATE_2026-08-13.md`,
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

## 6. Time-series publication lane (2026-08-17 incident)

**Status:** fixed 2026-08-17 on branch `fix/timeseries-pr-lane`; one manual
repository setting is still required (below).

On 2026-08-13 the repository ruleset "Protect main — pull requests only"
(id 20803594, empty bypass list) was installed. The first scheduled run after
it — `detect_gee.yml` run `32004421793`, 2026-08-17 — completed detection and
every R2 write, then failed with `GH013` on the final `git push`:
`github-actions[bot]` can no longer push to `main`. Nothing was lost (alerts
for 2026-08-02/05/10/15 reached `araripe-cogs`, and the persistence state was
saved), but the `data/timeseries/` commit was rejected, so the published series
stalled at 2026-08-10 and the job reported failure.

Decision: keep `main` strictly pull-request-only and give automation its own PR
lane. `detect_gee.yml` and `update_data.yml` now commit `data/timeseries/` on a
throwaway branch `auto/timeseries-<run id>`, open a pull request, and
squash-merge it — the ruleset requires zero approvals, so the `GITHUB_TOKEN`
can merge its own PR. The step refuses to open a PR that stages anything
outside `data/timeseries/`, and no new credential was introduced: the token
only gains `pull-requests: write`.

Required manual step (human, once): enable Settings > Actions > General >
"Allow GitHub Actions to create and approve pull requests". Without it the
`GITHUB_TOKEN` cannot open the PR and the lane fails. Granting it is
inconsequential for review integrity here because the ruleset requires zero
approving reviews anyway.

Rejected alternatives: a GitHub App token or deploy key on the ruleset bypass
list (a new credential whose only purpose is to restore direct writes to
`main`; the `GITHUB_TOKEN` itself cannot be a bypass actor), and
`continue-on-error` on the step (green runs with a silently frozen series).

Recovery of the missed date is automatic: time-series writes are
`INSERT OR REPLACE` keyed by `UNIQUE(date, index_name, region)` and the
detection window on `main` is `SEARCH_DAYS_BACK = 16`, so the first successful
run before ~2026-08-31 recomputes 2026-08-15 and closes the gap.

Structural follow-up (not scheduled): move `timeseries.db` out of git into R2
beside the alerts so no automated write to `main` is needed at all. That moves
the canonical DB and drops its git history, so it belongs in a reviewed
package, not in this fix.

Schedule spacing: the site refresh
(`../site/.github/workflows/update-data.yml`) moved from Mon/Thu 07:30 UTC to
Tue/Fri 06:00 UTC — a full 24 h after the backend run instead of 90 min. On
2026-08-17 GitHub started the backend cron 67 min late, which is enough to make
the site read a `main` whose time-series PR has not landed yet. **Pending:** the
change lives on the site branch `fix/site-cron-24h` and is NOT merged, so the
site still runs Mon/Thu 07:30 UTC (run of 2026-08-24 confirms it).

### 6.1 The PR lane worked but still reported failure (fixed 2026-08-24)

The runs of 2026-08-20 (`32341699596`) and 2026-08-24 (`32700387452`) both
**published successfully** — PRs #13 and #14 are squash-merged on `main` and the
series is current — and both reported failure. The log ends:

```
opened  https://github.com/santibravocmcc/Araripe/pull/14
merged  https://github.com/santibravocmcc/Araripe/pull/14
##[error]Process completed with exit code 1.
```

Root cause: three ingredients, none sufficient alone.

1. `conda-incubator/setup-miniconda` deletes `~/.bashrc`, `~/.bash_profile` and
   `~/.profile`, then writes a `~/.profile` ending in `set -eo pipefail`. Every
   `bash -l {0}` step in the job therefore inherits **errexit**.
2. A non-interactive login shell sources `~/.bash_logout` **only when the `exit`
   builtin runs explicitly** (bash manual). Steps that end at EOF never do.
3. The runner's `~/.bash_logout` runs `/usr/bin/clear_console -q` when
   `SHLVL = 1` (it is, and the binary exists), which fails with no TTY. Under
   errexit that failure replaces the requested status, so `exit 0` yields 1.

Only the publish step ends with an explicit `exit 0`, which is exactly why it
was the only step that failed while the whole pipeline succeeded.

Verified on real runners (throwaway branch `probe/login-shell-exit`, deleted):
`bash -l` + `exit 0` fails **only** with conda's profile present; adding
`set +e` to the same step makes it pass; a non-login `shell: bash` passes; and
the fixed shape — no explicit `exit 0` — passes in every combination, including
a full replay of the real `git commit` / `push` / `gh pr create` /
`gh pr merge --squash --delete-branch` sequence against a throwaway base.
Note when reading such probes: with `continue-on-error: true` the API's
`conclusion` field reads `success` even for a failed step; use `outcome`.

Fix (branch `fix/publish-step-exit-status`): the publish step in both workflows
declares `shell: bash` (it is pure git/gh and needs no conda env, so the login
shell buys nothing) **and** no longer calls `exit 0` — the "nothing to publish"
case became an `else` branch and the merge loop sets a flag and `break`s. Either
change alone is sufficient; both are kept so the step stays correct if someone
later changes the shell back. Behaviour is otherwise identical, and all four
paths were re-tested locally (no change / DB only / DB + stray path refused /
merge never ready).

Bug class to remember: **never end a `bash -l {0}` step with an explicit
`exit 0`** in a job that uses `setup-miniconda`. Ending at EOF, or overriding to
`shell: bash`, is safe.
