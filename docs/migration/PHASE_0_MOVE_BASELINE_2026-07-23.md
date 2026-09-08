# Phase 0.2 Move Baseline

**Captured:** 2026-07-23T18:00:48-03:00
**Authorized destination:**
`/Users/sbravo/Documents/Projetos/Observatorio_Chapada_do_Araripe/Araripe`

This is the last committed verification baseline before moving the complete
backend repository. The move itself is deliberately the final filesystem
operation of the task. Post-move verification must begin in a fresh session
opened at the destination.

## Fresh move-time checks

- Backend starting commit:
  `2082c1c5026856ebf3d8f516b7892da26ab57fd5`
- Site starting commit:
  `832015d7f67fdd80c8d436212db68ba370932017`
- Both repositories were clean and their LFS statuses were clean.
- The exact destination was absent.
- The common parent had no `.git`.
- Source and destination parent were on device `16777234`.
- Approximately 198 GiB was available.
- All four MapBiomas SHA-256 checks passed.
- `git fsck --full --strict --no-reflogs` completed with exit 0; no missing or
  corrupt backend objects were reported.
- The preserved 3.12 GiB temporary pack and dangling objects were not cleaned.
- Credential files remain in
  `/Users/sbravo/Documents/Projetos/.Observatorio_Chapada_do_Araripe-private`
  with directory mode `0700` and file mode `0600`.
- Only Codex runtime processes held the backend as their current directory.

## Verification baselines

- Backend tests:
  `/opt/anaconda3/envs/araripe/bin/python -m pytest -q`
  completed with **96 passed**.
- The default `/opt/anaconda3/bin/python` could not collect the suite because
  `loguru` is not installed there; the existing `araripe` environment is the
  project test environment.
- Site production build: `npm run build` succeeded.
- Build output manifest: 126 files; manifest SHA-256
  `0419e2da08ecb65fa4bdc84fa45628e368febbb695d0cbaf9665e19da96fcd80`.
- The production build repeated successfully after the path update and its
  sorted manifest was byte-for-byte identical.
- Existing `site/public/data` manifest: 91 files; manifest SHA-256
  `b2390ab775ecfc9a118b30d04bf8382884622f2ed0742fdf5cf036073e5f8885`.
- `npm run data` was not executed because it can load live R2 credentials,
  download production alerts, and upload full-run artifacts. That live
  operation requires separate explicit authorization and is not necessary for
  the local directory move.

## Committed path preparation

Backend documentation now addresses the future sibling site as `../site`.
The independent site repository was committed on
`codex/workspace-consolidation` at `c5ec119` with:

- local backend fallback `../Araripe`;
- `.env.example` value `ARARIPE_DIR=../Araripe`;
- README local-data path `../Araripe`.

Immediately before the move, verify both new commits, clean worktrees, the
destination's continued absence, source/destination device equality, and that
no non-Codex watcher has appeared.

## Required fresh-session acceptance

From the relocated backend:

1. Verify both Git repositories, branches, commits, remotes, status, and LFS.
2. Re-run the MapBiomas checksum manifest.
3. Re-run the 96 backend tests in the `araripe` environment.
4. Confirm the site's `../Araripe` fallback resolves to the relocated backend.
5. Re-run the local production build and compare its sorted manifest hash.
6. Run site data preparation only with separately approved R2 behavior, then
   compare generated public-data outputs before accepting them.
