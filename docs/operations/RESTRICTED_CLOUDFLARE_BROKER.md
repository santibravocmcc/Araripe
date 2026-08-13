# Restricted Cloudflare green-control broker

**Defined:** 2026-08-12

**Status:** Local, inactive, and not merged or dispatched

## Purpose

This broker lets Claude request a small set of Cloudflare control-plane
operations without ever receiving a Cloudflare token. GitHub Actions holds the
credential in the protected Environment `cloudflare-green-control`; the
workflow and Python controller fix every account, Worker, bucket, zone,
repository, trigger, command, and expected safety property in reviewed code.

It is not a general Cloudflare shell. There is no arbitrary command, URL,
resource name, JSON body, Wrangler argument, route, domain, DNS, delete,
production deploy, or secret-read input.

## Technical boundary

The workflow is manual-only, default-branch-only, repository-guarded,
read-only to GitHub contents, serialized, time-bounded, and protected by a
GitHub Environment. Mutation operations require the exact confirmation
`GREEN-ONLY`.

The initial allowlist is:

1. `audit` — verifies the exact isolated Worker bindings, private subdomain,
   absence of domains/routes/schedules, final-domain ownership, and the site
   non-production build trigger.
2. `enforce-worker-isolation` — can only disable `workers.dev` and previews on
   `observatorio-chapada-v2-staging`, then reruns the full audit.
3. `disable-site-branch-deploy` — can only change the already-identified
   non-production trigger deploy command to `exit 0`, after validating the
   trigger, repository, owner, provider, branches, build command, root, and
   production script tag. This prevents arbitrary candidate-branch content
   from choosing any Wrangler target or binding. It then reruns the full audit.

The token is technically account-scoped because Cloudflare does not scope
Workers Scripts or Workers Builds Configuration permissions to one
Worker/trigger. The security
boundary therefore combines a token stored only in GitHub, fixed code,
default-branch protection, CODEOWNERS, Environment approval, exact identifiers,
and post-mutation read-back. Claude cannot call the token directly.

## Production denylist

Through Phases 2B-5 the broker must never expose an operation that can:

- upload, deploy, configure, or delete Worker `observatorio-chapada`;
- read or mutate objects or configuration in `araripe-cogs`;
- attach a route or domain, edit DNS, or touch the final public domain;
- edit blue workflows, schedules, current data paths, production secrets, or
  canonical release pointers;
- accept a caller-supplied resource name, API path, command, URL, or body.

A new green operation requires a reviewed code change, tests proving exact
targets and forbidden production behavior, owner approval, and an updated
checkpoint. Phase 6 cutover operations do not belong in this broker.

## One-time Cloudflare credential

Create a custom **user API token** in Cloudflare. Workers Builds currently
supports user tokens, and the initial broker needs only:

- Account -> Workers Scripts -> Edit;
- Account -> Workers Builds Configuration -> Edit;
- Zone -> Workers Routes -> Read, restricted to the exact
  `observatoriodachapadadoararipe.com` zone.

Restrict the Account resources to the exact Observatorio Cloudflare account.
Do not grant Workers Routes Edit, DNS, API Tokens, Account Settings Edit,
Workers R2 Storage Edit, or access to all accounts/zones. Name the token
`github-araripe-green-control` and set a finite TTL covering only isolated
development if the dashboard permits it.

The token secret is shown once. Paste it directly into the GitHub Environment
secret described below. Do not save it in AWS profiles, `.env`, shell history,
macOS notes, chat, Claude/Codex settings, repository secrets, or repository
files.

## Protected GitHub Environment

In `santibravocmcc/Araripe`, create Environment
`cloudflare-green-control` with:

- required reviewer: the repository owner;
- deployment branches: selected/protected branch `main` only;
- secret: `CLOUDFLARE_GREEN_CONTROL_TOKEN`;
- variable `CLOUDFLARE_ACCOUNT_ID=9416750169311ee4afc18a8ff3c771d4`;
- variable `CLOUDFLARE_ZONE_ID=ffb40294871f38028e925208c3f9110a`;
- variable `CLOUDFLARE_CONTROL_SCOPE=green-only`.

If the current GitHub plan does not make required reviewers and deployment
branch restrictions available for this private repository, do not install the
token. Keep Cloudflare control in Codex until an equivalent protected boundary
is available.

Enable a `main` ruleset that requires a pull request and CODEOWNER approval for
the broker workflow, controller, tests, operating document, `AGENTS.md`, and
`CLAUDE.md`; block force pushes and deletion. Do not allow Claude to approve
its own broker changes or Environment deployment request.

## Use from Claude

Claude may authenticate to GitHub and dispatch an already-merged operation,
but must not edit the broker and dispatch that edit in the same task. A human
reviews every mutation request in the Environment. Start with `audit`; the
trigger mutation intentionally disables non-production deployment. A later
green site deploy must use a separate protected default-branch workflow that
builds an explicitly reviewed commit and fixes the Worker name and bindings
outside candidate-controlled configuration.

The broker produces normalized, non-secret output. Environment secrets cannot
be retrieved through the workflow. If a run fails closed, do not retry with a
different token or direct Cloudflare command; inspect the failure and create a
safe handoff.

## Future green capabilities

R2 object work remains under the bucket-scoped S3 identities already created.
If Package 2B.3 later needs bucket CORS/lifecycle administration, add a separate
protected R2-control broker and separate token rather than expanding this
Worker/CI token. This preserves separation of duties and avoids giving a single
workflow unnecessary account-wide R2 authority.
