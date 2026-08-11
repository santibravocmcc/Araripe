---
name: araripe-safe-handoff
description: Preflight Araripe roadmap operations that may need GitHub, R2, Cloudflare, GEE, or another external capability; stop safely and create a recoverable Claude-to-Codex handoff when the required connection or credential is unavailable. Use before external mutations and whenever an operation cannot be completed by the current tool.
---

# Araripe safe handoff

Keep every pause recoverable and every external mutation inside its approved
environment.

## 1. Classify the required capability

Before changing anything, classify each step as one of:

- `local`: repository files and deterministic local tests;
- `github`: repository, Actions, environments, secrets, or pull requests;
- `earth-engine`: asset metadata, export tasks, baseline reconstruction, or
  local/GEE parity under one explicitly approved Earth Engine project;
- `r2-staging-object`: S3 object operations only in `araripe-v2-staging`;
- `cloudflare-control-plane`: buckets, CORS, lifecycle, Workers, routes, DNS,
  Builds, bindings, or credentials;
- `production`: any canonical pointer, production Worker, public route, current
  workflow, `araripe-cogs`, or final-domain operation.

State the target and intended mutation. Never substitute staging for production
or production for staging silently.

## 2. Preflight before mutation

1. Read `ROADMAP.md`, the relevant implementation record, and repository
   `AGENTS.md` files.
2. Record repository branch, commit, and dirty state.
3. Resolve the exact Cloudflare account, bucket, object/prefix, Worker,
   environment, repository, workflow, release pointer, or Earth Engine project,
   authenticated principal, source asset, task, and export destination.
4. Confirm that the available credential or connector covers that exact target.
5. Confirm the recovery boundary: immutable target, expected prior pointer,
   rollback target, or no-production-mutation assertion.

For `earth-engine`, fail closed unless the approved project, authenticated
principal, source asset, intended task, and export destination are all explicit.
Never fall back silently to another project, principal, asset, or destination.

Claude's approved credential is an R2 S3 credential restricted to
`araripe-v2-staging`. It is not a Wrangler or Cloudflare control-plane token.
Never ask for, accept, print, or save a secret in chat, Git, `AGENTS.md`,
`CLAUDE.md`, or a repository `.env`.

## 3. Execute atomically

- Finish one coherent atomic step before starting another.
- Write new artifacts under unique immutable keys before changing any pointer.
- Validate bytes, schema, checksum, and target before promotion.
- Do not update a ledger or pointer when any required artifact is incomplete.
- Do not delete or overwrite the legacy/current production path during the
  parallel green build.

## 4. If capability is missing

Stop before the mutation. If a mutation already started, complete only the
smallest safe atomic unit, validate the resulting state, and do not promote it.
Do not retry with broader credentials or a different environment.

Create a regular, current-user-owned, mode-`0600` JSON draft at an absolute
non-symlink path under `/private/tmp` from
`references/handoff-input.example.json`; never pass handoff content on the
command line. Keep it bounded and remove it after use. Follow
`references/handoff-template.md`, then run:

```bash
python .agents/skills/araripe-safe-handoff/scripts/create_handoff.py \
  --input /private/tmp/araripe-handoff-input.json
```

The helper anchors output to the declared Git repository, requires explicit
pointer/public/production/rollback evidence, rejects duplicate or oversized
input and common/opaque secret forms, including branch names. Suspicious opaque
Git path components are replaced by labelled SHA-256 digests; the only exact
path exception is the expected checkpoint itself. The helper neutralizes inline
HTML/Markdown and unsafe controls, refuses symlink escapes, and terminates
Git-state capture when its bound is crossed. It renders one
complete checkpoint from the state immediately before installation and records
the checkpoint path as the exact expected Git delta. It then fsyncs the
complete temporary file, installs it exactly once with an exclusive hard link,
refuses every existing target rather than replacing it, and fsyncs the
directory. Its final path is under `docs/handoffs/`. Review it and remove the
input draft.

The checkpoint records:

- the exact missing capability and target, never a secret value;
- branches, commits, dirty state, completed work, and known external mutations;
- verification performed, current safe state, rollback information, and the
  first remaining step;
- the credential/connector the user must activate;
- a self-contained copy/paste prompt for Codex.

Then tell the user plainly that the operation stopped safely, where the
checkpoint is, what must be activated, and provide the same handoff prompt in
the response. Do not describe the blocked task as complete.

## 5. Resume safely

On resume, read the checkpoint first and re-check every recorded branch, commit,
resource, pointer, and external state. If reality differs, stop and reconcile
the difference before continuing. Never trust a stale checkpoint as current
cloud state.

## 6. Finish

Run proportional tests. Commit only coherent tracked files, with no secret or
generated private artifact. Update the roadmap/implementation record and state
explicitly which production resources were not changed.
