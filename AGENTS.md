# Araripe backend repository

Read `../AGENTS.md` first when this repository is inside the shared
`Observatorio_Chapada_do_Araripe` workspace.

## Repository map

- `config/` defines paths, collections, bands, thresholds, and runtime settings.
- `src/` contains acquisition, processing, detection, persistence, and
  time-series code.
- `scripts/` contains operational entry points and data utilities.
- `tests/` contains the backend regression suite.
- `data/` contains a mixture of tracked reference data, Git LFS artifacts, and
  large ignored local inputs. Check tracking before editing or staging it.
- `.github/workflows/` owns scheduled monitoring automation.

Start with `README.md` for setup and architecture, `COMO_FUNCIONA.md` for the
plain-language method, and the relevant focused document under `docs/`. Treat
`config/settings.py` and the implementation as the runtime source of truth when
prose is stale.

**`ROADMAP.md` is two different documents with one name.** The copy on `main`
(~240 lines) tracks explicitly not-yet-implemented items and is *not* the plan.
The canonical plan — decision ledger, numbered topic table with approval
status, Phases 0-6, packages and exit gates — is `ROADMAP.md` on the planning
branch (~980 lines, currently `claude/phase2a6d-mapbiomas`; confirm against the
newest record in `docs/implementation/`). Read it with
`git show <planning-branch>:ROADMAP.md`. Planning against `main`'s copy
duplicates approved work — see the note at the top of that file.

## Orient before editing

Do this first, every session — the shared `../AGENTS.md` has the full protocol:

    git fetch origin
    git status --short --branch
    git log --oneline -5 origin/main

- Read canonical documents from `origin/main` (`git show origin/main:<path>`),
  not from the working tree, unless the task is explicitly about a branch. The
  checked-out branch may be far behind, and branching from `origin/main`
  silently changes what a familiar filename contains.
- `main` squash-merges, so `git log origin/main..origin/<branch>` still lists
  commits whose content already landed, and `git branch --merged` hides them.
  Decide by content or by squash subject (`git log origin/main --grep '(#12)'`),
  never by ancestry.
- Before proposing new work, search the full roadmap's topic table, the package
  implementation-status lines, and `docs/implementation/`. Scientific fixes
  routinely exist as tested code on a science branch while the defect is still
  live on `main`; that separation is deliberate.
- Never assert an invariant the producer does not promise. Before a validation
  fails closed on a property, find where that property is guaranteed or
  reproduce it — on 2026-09-07 `first_seen <= last_seen` was assumed, was never
  guaranteed by `update_tracks`, and stopped the pipeline over 0.10% of rows
  (`tests/test_update_tracks.py::test_last_seen_can_move_backwards`).
- Commit bodies must carry the verified base (`origin/main` at its 40-character
  SHA), what was checked including negative results, and re-runnable evidence
  for any claim about another component.

## Working contract

- Use the existing `araripe` conda environment for local Python verification:
  `/opt/anaconda3/envs/araripe/bin/python`.
- Run the focused tests for a small change and the full gate before handoff:
  `/opt/anaconda3/envs/araripe/bin/python -m pytest -q`.
- Keep imports repository-relative; do not add machine-specific absolute paths.
- Never expose `.env` values or commit ignored national MapBiomas rasters,
  baselines, scene caches, logs, temporary packs, or generated alerts.
- Treat R2, GEE, GitHub Actions, publication state, and persistence state as
  production systems. Default to local/read-only checks unless live mutation is
  explicitly in scope.
- `main` is pull-request-only: the ruleset "Protect main — pull requests only"
  has an empty bypass list, so nobody — including `github-actions[bot]` — can
  push to it. Land every change through a pull request, and expect the
  scheduled workflows to publish `data/timeseries/` through the automatic PR
  lane recorded in `ROADMAP.md` §6. Never add a bypass actor, relax the
  ruleset, or flip repository settings to restore a direct push.
- Before an external mutation, or whenever a needed credential/connection may
  be unavailable, load `.agents/skills/araripe-safe-handoff/SKILL.md`. A blocked
  operation must stop before promotion, save a recoverable checkpoint under
  `docs/handoffs/`, name the missing capability, and provide a Codex handoff
  prompt. Never broaden a credential or switch environments silently.
- Preserve the scientific and publication constraints in `ROADMAP.md`,
  especially the wider monitoring extent, raw detections, immutable releases,
  explicit completeness states, and fail-closed state handling.
- Changes to the dashboard belong in the sibling `../site` repository and must
  follow its `AGENTS.md`.
- Production is frozen through Phases 2B-5. Never modify or deploy
  `observatorio-chapada`, `araripe-cogs`, the final public domain, DNS, routes,
  blue workflows/schedules, canonical pointers, or current site artifacts.
  Read-only production checks are allowed only when needed to prove isolation.
- Claude must never receive or use a direct Cloudflare control-plane token.
  Its only control-plane path is the reviewed
  `.github/workflows/cloudflare_green_control.yml` broker on the trusted
  default branch. Use only its named allowlisted operations; never recreate
  them with `curl`, Wrangler, `gh api`, or a broader credential.
- The broker credential is a GitHub Environment secret. Never retrieve, echo,
  export, copy, rotate, or place it in local configuration. If a needed green
  operation is absent from the broker, stop and request a reviewed allowlist
  extension or create a safe handoff; do not bypass the broker.
- Risk-based autonomy (Package 2B.0): the following proceed without repeated
  approval — local development and alternative local branches; object
  operations in `araripe-v2-staging`; manual green workflows that hold only
  the staging-scoped identity; read-only verifications; commits, branch
  pushes, and opening pull requests. A minimal, additive, inert pull request
  proven not to change blue runtime files may also be merged without a new
  approval.
- Explicit human approval remains mandatory for any action with authority or
  potential effect on production: blue workflows, the production Worker,
  `araripe-cogs`, the final public domain, DNS, routes, canonical pointers,
  the public site, cutover steps, and any Cloudflare token with
  account-level edit permission.
- GitHub Environment `v2-staging` holds only the bucket-scoped staging
  identity and needs no reviewer. Environment `cloudflare-green-control`
  keeps its required human reviewer because its token carries account-level
  edit permission. No agent may approve its own Environment run or bypass a
  pending approval, failure, or refusal.
