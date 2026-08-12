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
plain-language method, `ROADMAP.md` for approved decisions and sequencing, and
the relevant focused document under `docs/`. Treat `config/settings.py` and the
implementation as the runtime source of truth when prose is stale.

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
