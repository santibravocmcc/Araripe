# Claude Code and the green R2 bucket

**Rewritten:** 2026-10-14, Phase 6 cutover runsheet step A8
([`PHASE_6ZF_2026-10-14.md`](../implementation/PHASE_6ZF_2026-10-14.md)).
**Original decision:** 2026-08-11 (kept below as history).

**Cloudflare account:** `9416750169311ee4afc18a8ff3c771d4`

**Bucket:** `araripe-v2-staging`

## The role of the bucket now

On 2026-09-30 the owner chose option (a) (`PACKAGE_P6_PROMPT.md` §3): at the
Phase 6 cutover `araripe-v2-staging` stops being a sandbox and becomes the
canonical green bucket the public site reads. Despite its name it is no
longer disposable: it holds the green release chain, the promotion pointer and
its history, the deposit chain, and the context and sources documents.

## Claude holds no credential for it

Since 2026-10-14 Claude has **no local credential** for this bucket, and none
for any other.

- Every write reaches the bucket through a reviewed GitHub lane on the
  backend `main`, under one of two GitHub Environment identities, both
  scoped to this one bucket at Object Read & Write:
  - `v2-staging` (R2 token `github-araripe-v2-staging-rw`, issued
    2026-08-11) — candidate replay, deposit lane, status lane, staging step
    of the operational publish;
  - `v2-promotion` (R2 token `araripe-green-promotion-rw`, issued
    2026-09-07) — releases and the pointer, including rollback, and the
    context and sources documents.
- Claude reads the bucket's state through those lanes (for example
  `v2_green_status.yml`, read-only) or through what the public route serves.
- Claude dispatches lanes; it never approves an Environment run, never
  creates, rolls or revokes a token, and never reads, prints, exports or
  copies a secret value. Token lifecycle is the owner's, in the dashboard.
- No `aws` profile, `.env`, `wrangler` login or Cloudflare API token on the
  owner's workstation may be offered to Claude for this bucket. If a task
  seems to need one, stop and use the backend `araripe-safe-handoff` skill;
  the answer is a lane, not a key.

Bucket configuration (public access, CORS, domains, lifecycle), Workers,
routes and DNS remain control-plane work outside Claude's reach; see
`AGENTS.md` and `cloudflare_green_control.yml`.

## The revocation, as measured on 2026-10-14

The owner listed the R2 Account API tokens in the dashboard. Two
`araripe-v2-staging` Object Read & Write tokens dated 2026-08-11 existed:
`claude-araripe-v2-staging-rw` and `github-araripe-v2-staging-rw`. The
workstation held two AWS profiles, `araripe-r2-staging` and
`araripe-r2-github-staging`, whose masked access-key IDs end in different
characters (`aws configure list`, no value read). `PHASE_2B0_2026-08-11.md`
records that the `v2-staging` Environment secrets were transferred on
2026-08-13 from the separate GitHub identity's local profile, and the
Environment page showed both secrets last updated about two months earlier.

1. The owner **deleted** `claude-araripe-v2-staging-rw` in the dashboard
   (deletion, not roll).
2. 2026-10-14T11:51:46Z — `aws s3 ls s3://araripe-v2-staging/pointers/green/
   --profile araripe-r2-staging --endpoint-url …` returned
   `An error occurred (Unauthorized) when calling the ListObjectsV2
   operation: Unauthorized`.
3. Same call with `--profile araripe-r2-github-staging`: listed
   `history/` and `current.json` — that token is alive.
4. `v2_green_status.yml` dispatched from `main`, run `38559580150`: read
   every product with the Environment key (`alerts.shown`,
   `alerts.observed`, `deposits.unpublished`, `context`, `sources` all `ok`).
   The run concluded `failure` only on `automation.latest late` — 6 days
   since the last automated run (2026-10-07), past the owner's 5-day limit,
   because no green schedule is merged before step B6. Not a credential
   failure.
5. The owner then removed both profiles from `~/.aws/credentials` and
   `~/.aws/config`; `aws configure list-profiles` returns nothing and
   `--profile araripe-r2-github-staging` reports the profile not found.
   `github-araripe-v2-staging-rw` itself was **not** revoked: it lives on in
   the `v2-staging` Environment.

**Way back:** the owner creates a new token with the same scope; nothing in
production depends on the revoked one.

## History: the 2026-08-11 setup (superseded)

From 2026-08-11 to 2026-10-14 the bucket was an isolated development sandbox
and Claude held a bucket-scoped S3 credential in the local AWS profile
`araripe-r2-staging` (token `claude-araripe-v2-staging-rw`, Object Read &
Write on this bucket only). Its acceptance test (list/put/get/delete on
`araripe-v2-staging`, `AccessDenied` on `araripe-cogs`) is recorded in
`PHASE_2B0_2026-08-11.md`. The profile was opt-in per call site: only the
local deposit scripts accepted it, and no remaining runsheet step depends on
it. A separate GitHub identity (profile `araripe-r2-github-staging`) was
verified the same day and installed in the `v2-staging` Environment.

Two lessons from that period still hold:

- An R2 S3 credential scoped to one bucket can list, read, write, copy and
  **delete** every object in it; only application code (immutable run
  prefixes, conditional writes) limits what it does. Scope is proven only by a
  real call being refused, never by reading configuration.
- Cloudflare Workers permissions are account-scoped, not limited to one
  Worker, so a Wrangler token for green would also reach production.

## Primary references

- Cloudflare R2 tokens: <https://developers.cloudflare.com/r2/api/tokens/>
- R2 S3 authentication: <https://developers.cloudflare.com/r2/get-started/s3/>
- Claude Code settings: <https://code.claude.com/docs/en/settings>
