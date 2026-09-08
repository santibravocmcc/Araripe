# Phase 0.1 and Phase 0.2 Pre-Move Preflight

**Captured:** 2026-07-23T17:25:47-03:00
**Scope:** Phase 0.1 and preparation only from Phase 0.2 of `ROADMAP.md`
**Move status:** **HOLD — NOT EXECUTED**

This report records the state before relocation. It does not authorize or
perform the repository move, initialize Git in the common parent, change paths
for a not-yet-moved checkout, or run the post-move comparison/build gate.

## 1. Exact migration targets

| Role | Verified path | Result |
|---|---|---|
| Backend source | `/Users/sbravo/Documents/Projetos/Araripe` | Exists; Git top level; device `16777234` |
| Common parent | `/Users/sbravo/Documents/Projetos/Observatorio_Chapada_do_Araripe` | Exists; no `.git`; device `16777234` |
| Backend destination | `/Users/sbravo/Documents/Projetos/Observatorio_Chapada_do_Araripe/Araripe` | Absent at preflight |
| Site repository | `/Users/sbravo/Documents/Projetos/Observatorio_Chapada_do_Araripe/site` | Exists as an independent Git repository |

The source and destination parent are on the same filesystem. No symlinks were
found in either repository. The exact future topology is:

```text
Observatorio_Chapada_do_Araripe/   # no Git repository here
├── Araripe/                       # backend Git repository
└── site/                          # site Git repository
```

Before a later move, re-run the target-absence and device checks. Do not merge
into or overwrite an existing `.../Observatorio_Chapada_do_Araripe/Araripe`.

## 2. Planning baseline and Git state

### Backend

- Pre-move path: `/Users/sbravo/Documents/Projetos/Araripe`
- Planning branch: `codex/technical-review-roadmap`
- Planning-baseline commit: `724c5c7cd106ed6aad64e95890d2b44319e86595`
- Baseline commit subject: `docs: secure technical review baseline`
- `main`: `adf570f05d8240b1a1993630fcb60be280cd2710`,
  tracking `origin/main`
- Planning branch has no upstream configured.
- Remotes:
  - `origin`: `https://github.com/santibravocmcc/Araripe.git`
  - `hf`: `https://huggingface.co/spaces/santibravo/araripe-monitor`
- Baseline inventory: 119 tracked paths and 34 LFS path records.
- LFS status reported no staged or unstaged LFS changes.
- The only preflight data scope was
  `data/landcover/updated/` (four local MapBiomas files, 7.1 GiB). It was not
  staged or committed and is now explicitly ignored.

The baseline commit includes the technical review, summary, monitoring
overview, their PDFs, and the roadmap. The checksum manifest and this preflight
report are separate Phase 0 evidence.

### Site

- Path: `/Users/sbravo/Documents/Projetos/Observatorio_Chapada_do_Araripe/site`
- Branch: `main`
- Commit: `832015d7f67fdd80c8d436212db68ba370932017`
- Upstream: `origin/main`, `+0/-0`
- Remote: `https://github.com/santibravocmcc/observatorio-site.git`
- Inventory: 188 tracked paths, no LFS path records, no untracked paths.
- `git lfs status` was clean.
- `git fsck --full --strict` completed with exit 0 and reported one dangling
  tree only; no missing or corrupt objects.

## 3. Credentials and local secret configuration

The contents of credential-looking files were not opened, copied into this
report, or checksummed.

- Moved out of the future shared workspace:
  - `Backup-codes-obschapadadoararipe (1).txt`
  - `token.rtf`
- Private location:
  `/Users/sbravo/Documents/Projetos/.Observatorio_Chapada_do_Araripe-private`
- Private directory mode: `0700`
- Both quarantined file modes: `0600`
- Backend `.env`: ignored by Git, not tracked, mode `0600`
- Site `.env`: ignored by Git, not tracked, mode `0600`
- Redacted path-only checks found no migration path values in either live
  `.env`.

The two `.env.example` files remain tracked examples. No secret values are
included here.

## 4. MapBiomas input inventory

All four inputs are local-only under `data/landcover/updated/`. Their SHA-256
manifest is `docs/migration/mapbiomas-inputs-2026-07-23.sha256`.

| Relative path | Bytes | Modified (-03:00) | SHA-256 |
|---|---:|---|---|
| `ATBD-Collection-10.1.pdf` | 4,476,538 | 2026-07-23T09:55:09 | `859f388422e25aacaaa2fe8024ed631496fc24a1be237a88d58732439ab2ed19` |
| `ATBD_Col3_10m_Caatinga_v1.pdf` | 3,364,548 | 2026-07-23T09:55:35 | `21f960d54b75303a33fcf74d59a91b9575959e6421e3e1b101b4523efa1472b4` |
| `brazil_coverage_2024.tif` | 802,022,037 | 2026-07-23T09:49:39 | `1be96442929c98cdbe0126d5c83d65a8142b61642ec14fb0ad1dfdfa3bf68d6c` |
| `brazil_lulc_10m_2024.tif` | 6,766,932,375 | 2026-07-23T09:50:07 | `2ba20d400976020b4e7472a37de04fe1755c6f23631008b39da388001a034f59` |

Raster metadata:

| File | Driver/type | Size | CRS | Bounds | NoData |
|---|---|---:|---|---|---:|
| `brazil_coverage_2024.tif` | GTiff / uint8 / 1 band | 154,470 × 146,483 | EPSG:4326 | `[-74.0209997484, -34.0406695449, -32.3921711670, 5.4357057842]` | unset |
| `brazil_lulc_10m_2024.tif` | GTiff / uint8 / 1 band | 464,738 × 476,391 | EPSG:4326 | `[-74.7215060069, -35.1876384997, -32.9733811558, 7.6072931520]` | 0 |

Post-move verification command, to be run from the relocated backend root:

```sh
shasum -a 256 -c docs/migration/mapbiomas-inputs-2026-07-23.sha256
```

## 5. Backend Git object-store verification

- Repository size at final capture: 27 GiB.
- `.git`: 18 GiB; `.git/objects`: 17 GiB; `.git/lfs`: 1.5 GiB.
- `git fsck --full --strict --no-reflogs` completed with exit 0.
- No missing or corrupt objects were reported.
- Dangling commits, trees, and blobs were reported and preserved.
- Final `git count-objects -vH`:
  - loose objects: 1,047, 7.06 GiB;
  - packed objects: 407 in 5 packs, 6.46 GiB;
  - prune-packable: 183;
  - one preserved temporary pack: 3.12 GiB.
- The initial scan saw two temporary packs totaling 7.71 GiB; one was no
  longer present by the final count. No prune, GC, repack, cleanup, or history
  rewrite command was run during this preflight.
- Available disk space was approximately 200 GiB.

The integrity check satisfies the roadmap's verify-or-back-up choice. The
temporary pack and dangling objects must not be cleaned as part of the move.
Run the same counts immediately before relocation and investigate any further
unexplained change.

## 6. Common-parent inventory and classification

| Item | Size | Files | Classification / disposition |
|---|---:|---:|---|
| `site/` | 3.6 GiB | 2,789 | Active independent site repository; keep in place |
| `observatorio_atual/` | 6.4 MiB | 55 | Active/legacy data input; retain |
| `design_handoff_observatorio/` | 2.8 MiB | 10 | Design/content reference; retain |
| `folio-2025-main/` | 346 MiB | 1,226 | Third-party reference; retain pending provenance reconciliation |
| `chapada_araripe_perfil.mp4` | 370,895,118 bytes | 1 | Source media; retain |

`folio-2025-main` has no embedded Git repository. Its local `license.md` says
MIT and credits Bruno Simon (2025), while `package.json` declares ISC and has
no author or repository URL. Its provenance/license metadata therefore remains
an explicit follow-up; it must not be treated as first-party material.

The common parent also contains its own `.claude/launch.json`, which launches
the site using the relative prefix `site` and remains valid.

## 7. Path-dependency audit

### Must change only after the move

| Repository/file | Current dependency | Required post-move value |
|---|---|---|
| Site `scripts/prepare_data.py:23` | fallback `site/../../Araripe` | fallback `site/../Araripe` |
| Site `.env.example:11` | example `ARARIPE_DIR=../../Araripe` | `ARARIPE_DIR=../Araripe` |
| Site `README.md:26` | documents `../../Araripe` | document `../Araripe` |
| Backend `README.md:59` | `../Observatorio_Chapada_do_Araripe/site` | `../site` |
| Backend `docs/DETECTION_GEE.md:59` | `../Observatorio_Chapada_do_Araripe/site` | `../site` |
| Backend `AUDITORIA_TECNICA.md:144` | link through `../Observatorio_Chapada_do_Araripe/site` | link through `../site` |

Changing these before relocation would break the current checkout, so no path
edits were made in this pre-move phase.

### Audited and unaffected

- Site workflow `ARARIPE_DIR=${{ runner.temp }}/Araripe` is CI-local.
- Backend ignored `.claude/launch.json` uses the absolute site path, which does
  not change.
- Common-parent `.claude/launch.json` uses relative `site`.
- `data/landcover/mapbiomas10m_araripe_2023.report.json` records a historical
  source path under `Downloads`; it is provenance, not a runtime dependency.
- No migration-dependent path was found in either live `.env`.
- No repository symlinks were found.

## 8. Move-time hold points

At preflight, `lsof` observed three `zsh` and six `node_repl` processes with
their current working directory inside the backend, in addition to transient
audit processes. They must be closed or reopened outside the source before a
later move.

The next phase must:

1. Reconfirm both Git states, LFS states, MapBiomas checksums, object counts,
   free space, device IDs, and exact destination absence.
2. Close/reopen Codex, Claude Code, editors, terminals, Git clients, and any
   process whose current directory is the source.
3. Move the complete source directory to the exact destination without
   initializing Git in the parent or cleaning `.git`.
4. Apply the six path updates above.
5. Reopen tools at the new location and verify both repositories, backend
   imports/tests, site data preparation, and production build.
6. Compare generated outputs before accepting the move.

Until those steps are explicitly authorized and executed, the repository must
remain at its current source path.
