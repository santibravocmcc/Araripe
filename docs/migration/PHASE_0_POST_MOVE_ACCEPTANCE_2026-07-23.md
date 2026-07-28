# Phase 0 Post-Move Acceptance and Operating Contract

**Captured:** 2026-07-23T18:26:12-03:00
**Workspace:**
`/Users/sbravo/Documents/Projetos/Observatorio_Chapada_do_Araripe`

This report closes the local filesystem and runtime checks after the backend
move and records the Phase 0.3 Codex/Claude operating-contract implementation.
No cloud state, R2 object, deployment, secret, Git history, or Git index was
mutated during acceptance.

## 1. Repository and workspace acceptance

The common parent has no `.git`, the old backend path no longer exists, and the
common parent, backend, and site are all on device `16777234`.

| Repository | Branch | Accepted HEAD | Remote |
|---|---|---|---|
| Backend | `codex/technical-review-roadmap` | `e34dd27d3728161a603733ef79a0c95214b233d6` | `https://github.com/santibravocmcc/Araripe.git` |
| Site | `codex/workspace-consolidation` | `c5ec119f44b27fc2dfc4ab987f031b49e06a46ef` | `https://github.com/santibravocmcc/observatorio-site.git` |

Both LFS statuses were clean. Strict Git integrity checks completed with exit
zero in both repositories. The backend retained its documented dangling
objects and 3.12 GiB temporary pack; the site retained its one documented
dangling tree. Nothing was pruned, repacked, cleaned, or rewritten.

The credential quarantine remains outside the shared workspace with directory
mode `0700` and file modes `0600`. Both ignored `.env` files remain mode `0600`
and contain no pre-move repository path. Their values were not displayed.

## 2. Path acceptance

- The site fallback `site/../Araripe` resolves to the relocated backend.
- The six committed runtime/documentation path changes listed in the preflight
  are present.
- The old absolute backend path and old `../../Araripe` fallback are absent
  from active configuration, code, and documentation. Historical migration
  evidence, logs, and provenance records intentionally retain their original
  paths.
- Twelve ignored Claude permission entries were updated from the old backend
  path to the relocated backend path.
- The backend, site, and common-parent launch configurations resolve at the new
  workspace layout.

## 3. Runtime and generated-output acceptance

| Gate | Result |
|---|---|
| Four MapBiomas input checksums | All SHA-256 checks passed |
| Backend import smoke | Passed for configuration, acquisition, detection, processing, persistence, and time-series modules |
| Backend regression suite | `96 passed` |
| Site backend fallback | Resolved to the accepted backend root |
| Read-only data preparation | Completed from the existing 30-file cached R2 snapshot with R2 variables explicitly blank |
| Prepared public data | 91 files; SHA-256 manifest `b2390ab775ecfc9a118b30d04bf8382884622f2ed0742fdf5cf036073e5f8885` |
| Prepared alert manifest | 27 runs through 2026-07-11; totals unchanged |
| Production build | Passed; 126 files |
| Build manifest | `0419e2da08ecb65fa4bdc84fa45628e368febbb695d0cbaf9665e19da96fcd80` |

The prepared-data and build hashes exactly match the pre-move baselines.
Preparation produced no tracked data diff and printed the expected confirmation
that full alert files were not uploaded because R2 was disabled. The build
retained its pre-existing non-fatal warning for a Three.js chunk over 500 kB.

## 4. Phase 0.3 operating contract

The workspace now has a concise shared map and repository-specific instructions:

| Scope | Codex instruction | Claude adapter |
|---|---|---|
| Common workspace | `AGENTS.md` | `CLAUDE.md` containing `@AGENTS.md` |
| Backend repository | `Araripe/AGENTS.md` | `Araripe/CLAUDE.md` containing `@AGENTS.md` |
| Site repository | `site/AGENTS.md` | `site/CLAUDE.md` containing `@AGENTS.md` |

The shared contract preserves the independent repositories, directs executors
to the relevant repository instructions and canonical documents, separates
validation and later commits by repository, and records the project’s secret,
generated-data, cloud-mutation, deployment, and scientific boundaries.

Codex CLI `0.146.0-alpha.3` was validated without a model request using
`codex debug prompt-input`. Fresh prompt rendering loaded the common-parent
contract, and separate backend/site renderings loaded the corresponding
repository contract and validation command. This follows the current
[Codex guidance for durable `AGENTS.md` instructions](https://developers.openai.com/codex/codex-manual.md).

Claude Code `2.1.112` is installed. All three adapters are exact one-line
`@AGENTS.md` imports, every target exists, and the import layout matches the
current Claude Code project-memory contract. A managed-sandbox launch reached
Claude Code but could not complete the interactive `/context` display because
network access to Anthropic was unavailable. In a normal connected terminal,
accept the import prompt if it appears and use `/memory` to confirm loaded
`CLAUDE.md` files; current Claude Code documentation identifies `/memory` as
the file-discovery diagnostic, while `/context` describes context-window use.
See the official
[Claude Code project-memory documentation](https://code.claude.com/docs/en/memory)
and [configuration diagnostics](https://code.claude.com/docs/en/debug-your-config).

## 5. Working-tree handoff

Before this implementation, both repositories were clean. The expected
uncommitted Phase 0.3 additions are:

- Backend: `AGENTS.md`, `CLAUDE.md`, and this acceptance report.
- Site: `AGENTS.md` and `CLAUDE.md`.
- Common parent: `AGENTS.md` and `CLAUDE.md` (the parent intentionally has no
  Git repository).

The ignored backend `.claude/settings.local.json` also contains the machine-local
post-move path correction.
