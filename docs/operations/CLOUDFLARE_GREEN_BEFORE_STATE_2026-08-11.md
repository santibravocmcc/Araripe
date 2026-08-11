# Package 2B.0 Cloudflare green before-state

**Recorded:** 2026-08-11

**Account:** `9416750169311ee4afc18a8ff3c771d4`

**Scope:** Read-only re-audit plus creation of one isolated staging Worker.

This record fixes the live control-plane facts used to complete Package 2B.0.
It contains no credential value and authorizes no production cutover.

## Repository state at resume

- Backend: branch `claude/phase2b0-green-isolation`, checkpoint commit
  `68ee384`, clean.
- Site: branch `codex/workspace-consolidation`, commit `fea5e59`, clean.
- Neither branch was pushed or merged during this control-plane step.

## Existing Worker Builds integration

The production Worker build configuration is linked to GitHub repository
`santibravocmcc/observatorio-site` and production branch `main`.

Two active triggers were read back:

1. `Deploy default branch` includes only `main` and runs build command
   `npm run build` followed by deploy command `npx wrangler deploy`.
2. `Deploy non-production branches` includes `*`, excludes `main`, and runs the
   same build and deploy commands.

Cloudflare documents `npx wrangler versions upload` as the safe default for
non-production previews. This account instead has a customized full deploy
command. Because the repository config names the production Worker
`observatorio-chapada`, pushing any site candidate branch is forbidden until a
reviewed staging-only configuration and trigger command are installed
together.

No Worker Builds trigger, repository connection, build token, or production
setting was changed by this audit.

## Production resources preserved

- Worker: `observatorio-chapada`.
- Custom domain: `observatoriodachapadadoararipe.com`, enabled only for the
  production Worker.
- Production rate-limit binding: `CHAT_LIMITER`, namespace `1001`, limit 8 per
  60 seconds.
- Production Worker schedules: none.
- Zone Worker routes: none; delivery uses the existing custom domain.
- Existing production Worker bindings and secrets were not read by value or
  changed.
- Bucket `araripe-cogs`, DNS, site artifacts, blue GitHub workflows, canonical
  pointers, and release state were not mutated.

## Staging bucket read-back

Bucket `araripe-v2-staging` remains Standard storage in the default
jurisdiction with location `EEUR`:

- managed `r2.dev` access disabled;
- no custom domain;
- no CORS configuration;
- no object-lock rule;
- only the default seven-day incomplete multipart abort rule.

The earlier credential test left the bucket empty. This control-plane step did
not write or delete any R2 object.

## Additive staging Worker

Codex created `observatorio-chapada-v2-staging` through the Workers API at
`2026-08-11T22:39:42.857554Z`.

Its complete intended authority is:

- module Worker with an inert `/__health` response and 404 for every other
  path;
- R2 binding `STAGING_BUCKET` -> `araripe-v2-staging`;
- rate-limit binding `STAGING_LIMITER`, namespace `2001`, limit 8 per 60
  seconds;
- no asset bundle, AI binding, plaintext variable, or secret;
- no schedule;
- `workers.dev` disabled and preview URLs disabled;
- no custom domain and no zone route.

The staging Worker is therefore unreachable from the public Internet and has
no path to the production bucket or final domain. Its removal is the complete
rollback for this additive control-plane mutation; removal is not presently
needed because validation passed.

## Remaining Package 2B.0 gates

- The user creates a second R2 `Object Read & Write` key scoped only to
  `araripe-v2-staging`; it must be a different identity from Claude's local
  profile.
- Codex installs that key in GitHub Environment `v2-staging` together with the
  approved non-secret variables, without exposing either value.
- A staging-only site config and safe non-production deploy command are
  reviewed and approved before the current trigger is changed or any site
  candidate branch is pushed.
- The local backend v2 workflow branch is reviewed and merged only after user
  approval, followed by the documented lane and inertness proofs.

Until all items pass, Package 2B.0 remains open and 2B.1 implementation remains
blocked.
