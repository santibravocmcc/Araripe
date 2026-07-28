# Phase 1 Cloudflare Before-State and Rollback Checklist

**Original capture:** 2026-07-24
**Live refresh:** 2026-07-28 15:10–15:15 UTC
**Mode:** Read-only discovery
**Production mutation:** None

This document deliberately separates three evidence classes:

1. **Verified local intent:** configuration committed in the repositories and
   code paths inspected locally.
2. **Historical live evidence:** the read-only R2 snapshot captured on
   2026-07-22 in `TECHNICAL_REVIEW.md`.
3. **Current live state:** sanitized control-plane and public-route evidence
   refreshed on 2026-07-28.

Local intent is not proof of deployment. Historical evidence is not asserted
to remain current. Unknown controls are not treated as absent.

## 1. Access history and current result

### 1.1 Original result on 2026-07-24

- The connected Cloudflare API returned **`Invalid API Token`**.
- The browser session was not authenticated to the Cloudflare dashboard.
- No alternative credentials were opened, printed, copied, or tested.
- No Cloudflare or R2 write was attempted.

### 1.2 Read-only refresh on 2026-07-28

The connected API recovered and successfully read the project account, zone,
DNS, Worker service and builds, Worker bindings and secret names, deployments,
R2 bucket controls and all object metadata, certificate status, managed
rulesets, and account audit logs.

The same connection could not read bulk or individual zone settings, Page
Rules, or DNSSEC. Those endpoints returned authorization errors (`9109` or
`10000`). Token-verification endpoints also returned `Invalid API Token`, so
the connector credential's exact type, identity, expiry, and policy document
remain uncertified even though the resource reads below succeeded.

The zone response exposed effective permissions that include edit-capable
operations. The connection therefore cannot be described as least privilege;
this review nevertheless issued only `GET`, `HEAD`, and bounded one-byte
`GET` requests. No Cloudflare or R2 mutation was made.

## 2. Verified local intended configuration

The following facts are verified from repository files, not from the live
Cloudflare control plane.

| Area | Locally intended state | Source |
|---|---|---|
| Public domain | Final approved domain is `observatoriodachapadadoararipe.com`; same-origin `/data/...` is the approved direction | Backend `ROADMAP.md` |
| Worker name | `observatorio-chapada` | Site `wrangler.jsonc` |
| Compatibility date | `2026-07-09` | Site `wrangler.jsonc` |
| Worker entry | `worker/index.js` | Site `wrangler.jsonc` |
| Static assets | `./dist`, binding name `ASSETS` | Site `wrangler.jsonc` |
| Worker-first routes | `/api/*` | Site `wrangler.jsonc` |
| Workers AI binding | `AI` | Site `wrangler.jsonc` |
| Rate-limit binding | `CHAT_LIMITER`, namespace `1001`, limit 8 per 60 seconds | Site `wrangler.jsonc` |
| Worker-recognized provider names | `GEMINI_API_KEY`, `ZAI_API_KEY`, `GROQ_API_KEY`, `GITHUB_MODELS_TOKEN`, `CEREBRAS_API_KEY`, `NVIDIA_API_KEY` | Site `worker/index.js`; presence is unverified |
| R2 access from Actions | S3-compatible endpoint credentials named `R2_ENDPOINT_URL`, `R2_ACCESS_KEY`, `R2_SECRET_KEY` | Backend and site workflows |
| Configured bucket default | `araripe-cogs`; optional runtime name `R2_BUCKET_NAME` | Backend/site Python code |
| Source prefixes/keys | `baselines/`, `alerts/`, root `persistence_state.geojson` | Backend workflow and scripts |
| Derived full prefix | `site-full/` | Site `scripts/prepare_data.py` |
| Browser full-data route | A hard-coded `https://pub-<identifier>.r2.dev/site-full` URL | Site `src/js/alertas.js`; current reachability unverified |
| Asset cache intent | `/assets/*`: one year immutable; `/data/*`: one hour; `/media/*`: one day | Site `public/_headers` |
| Basic response-header intent | `X-Content-Type-Options: nosniff`; `Referrer-Policy: strict-origin-when-cross-origin` | Site `public/_headers` |
| Deploy tooling | Vite build exists; no pinned Wrangler dependency and no repository deploy, health, or rollback script | Site `package.json` |
| Deployment documentation | Describes Cloudflare Pages and automatic Git deployment, conflicting with Worker configuration | Site `README.md` and `DEPLOY.md` |

Important absences in local intent:

- `wrangler.jsonc` declares no `account_id`, `routes`, custom domains,
  environment sections, R2 bucket bindings, observability configuration, or
  ordinary non-secret variables;
- the GitHub data workflow does not build or deploy;
- no repository file defines R2 CORS or lifecycle policy;
- no release manifest, conditional canonical pointer, or rollback pointer is
  implemented;
- no public/private bucket split is represented.

These absences describe the repositories only. A setting may exist live and
still be absent locally; authorized inspection is required.

## 3. Historical live R2 evidence from 2026-07-22

The table below reproduces the dated read-only snapshot from
`TECHNICAL_REVIEW.md`. It must not be presented as a 2026-07-24 inventory.

| Prefix or object | Object count | Size |
|---|---:|---:|
| `baselines/` | 72 | 13.408 GB |
| `alerts/` | 29 | 1.190 GB |
| `site-full/` | 35 | 0.612 GB |
| root `persistence_state.geojson` | 1 | 0.132 GB |
| **Total** | **137** | **15.342 GB** |

Other dated findings:

- all listed objects reported Standard storage;
- representative objects had suitable content types and byte-range support;
- representative source, baseline, state, and derived public objects were
  retrievable through the public bucket boundary when their paths were known;
- no explicit `Cache-Control` metadata was observed on representative objects;
- an Origin-bearing request to a representative full object did not return
  `Access-Control-Allow-Origin`;
- the site used an `r2.dev` public development hostname rather than a verified
  production custom domain;
- six `site-full/` objects were not referenced by the then-current source
  archive/manifest;
- each site refresh downloaded the complete source archive and reuploaded the
  complete staged full archive;
- bucket-level CORS, lifecycle, encryption configuration, object
  versioning/retention behavior, and token scope could not be inspected with
  the then-available object credential.

The historical review reported the bucket at approximately 5.342 GB above the
then-current 10 GB-month R2 Standard free allocation. On 2026-07-28, the
official pricing page still listed 10 GB-month of Standard storage free and
Standard storage above that at USD 0.015/GB-month. Holding the current
15.432790508 GB for a full month therefore gives a storage-only estimate of
about USD 0.0815/month above the free tier. This excludes operation charges
and future release growth. Source:
<https://developers.cloudflare.com/r2/pricing/>.

## 4. Sanitized live before-state refreshed on 2026-07-28

### 4.1 R2 object inventory

The R2 REST inventory completed in one page at 2026-07-28 15:10 UTC:

| Prefix or object | Objects | Bytes | Latest modification |
|---|---:|---:|---|
| `baselines/` | 72 | 13,408,183,319 | 2026-07-12 18:49 UTC |
| `alerts/` | 31 | 1,250,569,624 | 2026-07-27 10:48 UTC |
| `site-full/` | 37 | 641,493,140 | 2026-07-27 11:00 UTC |
| root `persistence_state.geojson` | 1 | 132,544,425 | 2026-07-27 10:48 UTC |
| **Total** | **141** | **15,432,790,508** | |

All 141 objects reported Standard storage and suitable content types. None had
object-level `Cache-Control` metadata. Representative objects in every prefix
returned the recorded length, ETag, last-modified time, and byte-range support.

The production and default-branch alert manifests both reported 31 runs and
`last_run` `2026-07-26`. Six `site-full/` keys were not referenced by that
manifest: `2025-11-26`, `2025-11-28`, `2025-12-28`, `2026-01-12`,
`2026-02-01`, and `2026-07-04`. They were not deleted.

### 4.2 Current control-plane and public-route evidence

| Control | Current sanitized evidence |
|---|---|
| Account and zone | The expected personal account is readable. `observatoriodachapadadoararipe.com` is an active, unpaused full zone on the Free Website plan. |
| DNS | One proxied apex `AAAA` record targets Cloudflare's `100::` placeholder with automatic TTL. |
| Worker/domain routing | `observatorio-chapada` serves the enabled apex custom domain in production. No zone Worker route exists; Workers routing is through the custom domain. The workers.dev subdomain and previews are enabled. |
| Pages | No Cloudflare Pages project exists in the account. |
| Worker Builds integration | The Worker is connected to `santibravocmcc/observatorio-site`, branch `main`, with `npm run build` then `npx wrangler deploy` on every matching push. Build caching is enabled; previews are disabled. |
| Active deployment | Deployment `06ef186c-f677-4bd5-94a4-ddddb638f298`, Worker version 60 (`50fcd537-e6f9-401b-a1e4-52d0e161ac16`), created 2026-07-27 11:02:53 UTC from site commit `0dcb99fd8be8ac1311f23fb6998ca9f08ed54e69`. |
| Immediate rollback candidate | Deployment `3f89b7b2-57e7-400b-a5ad-c01bbf56dad9`, Worker version 59 (`d8d3b432-5d38-4160-8be2-fdb215d77858`), created 2026-07-27 11:01:43 UTC from site commit `91b229db28ead257500a8e39836fd69f6948a1ea`. No repository-owned rollback command or tested health gate exists. |
| Worker settings | Compatibility date `2026-07-09`, no compatibility flags, standard usage, no placement config, logpush disabled, and no tail consumers or observability configuration. |
| Bindings | `AI`, `ASSETS`, and `CHAT_LIMITER` are present; the rate-limit namespace is `1001`. |
| Provider secret presence | `GEMINI_API_KEY`, `ZAI_API_KEY`, `GROQ_API_KEY`, `GITHUB_MODELS_TOKEN`, `CEREBRAS_API_KEY`, and `NVIDIA_API_KEY` are all bound as `secret_text`. Values were not requested or returned. |
| R2 bucket | `araripe-cogs` exists in the default jurisdiction, location EEUR, with default Standard storage. It is the only bucket returned. |
| R2 public boundary | The managed `r2.dev` domain is enabled and no R2 custom domain exists. Representative baseline, source-alert, persistence-state, and `site-full` objects were all publicly retrievable by known key. The current design therefore exposes internal scientific inputs/state and public derivatives through one public bucket boundary. |
| R2 CORS | One rule allows `GET` from the production origin and `https://observatorio-chapada.sbravo-rehab.workers.dev`, with all request headers. A one-byte range `GET` returned the exact production allow-origin header; `HEAD` is not listed and returned no CORS header. |
| R2 lifecycle/retention | The only lifecycle rule aborts incomplete multipart uploads after seven days. There are no lock rules, event-notification rules, local uploads, Sippy configuration, or exposed object-version rollback mechanism. |
| R2 caching | No current R2 object has explicit `Cache-Control`. The same-origin site manifest and strong products return `Cache-Control: public, max-age=3600` from the Worker assets boundary. |
| Current site data contract | `/data/alerts/manifest.json` and the latest strong product return `200`; the proposed `/data/releases/current.json` pointer returns `404`, as expected before implementation. |
| TLS/certificates | Universal SSL is enabled. Active apex/wildcard certificate packs were present and expire on 2026-10-19. The origin TLS mode remains unreadable with the current connector scope. |
| Rules and security | Only Cloudflare-managed normalization, free WAF, and DDoS L7 rulesets were listed. Zone settings, Page Rules, DNSSEC, and the complete cache/transform/redirect/security setting inventory remain authorization-blocked. |
| Auditability | Account audit logs confirm push-triggered Worker Builds, asset uploads, version creation, deployment, script-setting updates, and the dashboard CORS update. |
| Connector authority | Core reads succeed, but credential introspection fails and the exposed effective permission set includes write-capable operations. Exact token identity, expiry, and least-privilege scope remain unresolved. |

### 4.3 Backend SQLite reconciliation

The current backend default-branch database was inspected from backend commit
`f32c81452b17562bb64a186d1313fdc36ca774a2`, Git blob
`7e9f45295b7cf5e441850e2ede9e45aaeb11fae5`, with file SHA-256
`8ff4de97f35f89b60cb912d79cd047c1b4792582d02e576e126c46ec805d507f`.
The site comparison used commit
`0dcb99fd8be8ac1311f23fb6998ca9f08ed54e69` and manifest blob
`0459b3eebf3d2d355f4b8b795a2aa0287d8b2e05`.

The database contains 36 `alert_stats` dates and 138 `regional_stats` rows,
from 2026-01-02 through 2026-07-26. The current R2 alert set and site manifest
contain 31 dates. For every shared date, alert count, area rounded to the
manifest precision, and high/medium/low confidence counts match exactly.

Five database dates are absent from the current R2 alert set and site manifest:

| Database-only date | Alerts | Area (ha) |
|---|---:|---:|
| 2026-01-12 | 3,776 | 26,450.32 |
| 2026-02-01 | 4,951 | 52,718.32 |
| 2026-03-08 | 17 | 40,524.56 |
| 2026-04-10 | 1 | 1.24 |
| 2026-07-15 | 1 | 143.88 |

The first two dates also have unreferenced `site-full/` objects; the other
three do not appear in the current site manifest or current R2 source-key
inventory. This is now a documented before-state inconsistency, not a Phase 1
cleanup action. The later processing ledger and deterministic replay must
classify these dates before any canonical release promotion; no row or object
was changed or deleted during reconciliation.

### 4.4 Owner-supplied dashboard evidence

On 2026-07-28, the project owner supplied the following names-only Cloudflare
dashboard evidence. No token value, access key, or secret key was provided.

| Token name | Identity class | R2 resources | Displayed permission | Issued | Status | Known consumer |
|---|---|---|---|---|---|---|
| `R2 Account Token-env` | Account API token | `araripe-cogs` | Object Read & Write | 2026-07-16 | Active | Not yet mapped |
| `R2 Account Token` | Account API token | `araripe-cogs` | Object Read & Write | 2026-03-29 | Active | Not yet mapped |
| `observatorio-chapada build token` | User API token | All buckets | Admin Read & Write | 2026-07-09 | Active | Cloudflare Worker Builds |
| `araripe-r2-upload` | User API token | `araripe-cogs` | Object Read & Write | 2026-03-29 | Active | Not yet mapped |

The account-token class is independent of an individual user's continued
organization membership. The two user tokens are tied to the user identity.
All four displayed R2 policies are write-capable; none is evidence of the
target private-reader/public-writer separation. The build token is especially
broad at the R2 boundary because it applies to all buckets with administrative
read/write authority. Phase 1 records this finding but does not rotate it.

The Worker Build dashboard also confirmed:

- repository `santibravocmcc/observatorio-site`;
- build command `npm run build`;
- deploy and version commands `npx wrangler deploy`;
- root directory `/`, production branch `main`, and include path `*`;
- non-production branch builds enabled;
- API token `observatorio-chapada build token`;
- no build variables/secrets and no deploy hooks.

The API inventory had reported preview deployments disabled. The dashboard
evidence shows non-production branch **builds** enabled; these settings can
coexist if branch builds do not create preview deployments. That behavior must
be verified before a later deployment contract relies on previews.

### 4.5 Accountable production-control ownership

The accountable Phase 1 owner for Cloudflare, R2, Worker deployment/rollback,
GitHub workflow configuration, release approval, and incident coordination is
the project owner, `@santibravocmcc`. Automated workflows remain the routine
mutation actors under the role boundaries in the artifact-ownership contract;
this assignment does not authorize a cloud mutation.

The repository records only the public GitHub identity. Any private emergency
contact channel remains outside Git and must not be copied into this package.

## 5. Remaining live inventory checklist

Complete this checklist with authorized, read-only Cloudflare access. Record
names, IDs, statuses, scopes, timestamps, and hashes where useful, but never
secret values.

### 5.1 Account, zone, and DNS

- [x] Identify the exact Cloudflare account containing the project.
- [x] Identify the zone for `observatoriodachapadadoararipe.com`.
- [x] Export the relevant DNS record names, record types, targets, proxy
      status, TTL, and last-modified evidence.
- [x] List Worker routes, custom domains, and Pages domains affecting the
      final domain.
- [ ] Complete the Page Rules, cache, transform, Origin Rule, redirect,
      WAF/bot/rate-control, DNSSEC, and relevant zone-setting inventory after
      granting the missing read scopes.
- [x] Record certificate status without exporting private key material.
- [ ] Record the current origin TLS mode; this setting is authorization-blocked.

### 5.2 Worker and deployment

- [x] List every Worker/Pages project that can serve the final domain.
- [x] Record the active deployment/version ID, creation time, source association
      if available, compatibility date, and rollback candidates.
- [x] Compare the deployed service name, entry point, assets binding, and
      `/api/*` routing with `wrangler.jsonc`.
- [x] Record binding names and types for `ASSETS`, `AI`, and `CHAT_LIMITER`.
- [x] Record presence/absence only for recognized provider secrets.
- [x] Inventory deployment environments, ordinary variables, observability,
      logs, tail consumers, placement, limits, and compatibility flags.
- [x] Verify whether Git integration, Pages, direct Wrangler deployment, or
      another mechanism deploys each push.
- [x] Record the absence of a repository-owned health-check/rollback procedure,
      the active and previous Cloudflare targets, and the exact later
      implementation/rehearsal requirement.

### 5.3 R2

- [x] List all buckets in scope and identify which are public, private, or
      connected to a custom domain.
- [x] Recount objects and bytes by `baselines/`, `alerts/`, `site-full/`, root
      state, and any additional prefix; record inventory time.
- [x] Record representative key, size, ETag/checksum, content type,
      content encoding, cache control, last modified, and range support without
      downloading large payloads unnecessarily.
- [x] Identify stale/unreferenced objects by comparing keys to the current
      manifest; do not delete them.
- [x] Export bucket CORS rules and test exact allowed origins, methods, headers,
      and exposed headers with `GET`/`HEAD` requests.
- [x] Export lifecycle rules, jurisdiction/location, custom domains, public
      development URL state, event notifications, locks/retention features,
      and any object-version or rollback mechanism exposed by the account.
- [x] Verify the current public/private boundary and record the finding without
      changing access. The three internal scientific classes are currently
      publicly retrievable by known key.
- [x] Record request/storage usage metrics needed for a retention estimate.
- [x] Adopt a technical planning envelope of USD 1/month for rollback
      retention. At the refreshed standard-rate estimate, the current
      15.43 GB footprint is approximately USD 0.08/month above the included
      10 GB storage allowance; request charges and future growth remain
      separately monitored.

### 5.4 Credentials and auditability

- [x] Complete the safely recoverable GitHub/R2 principal, provisioning-date,
      displayed resource-scope, permission, and status inventory without
      reading values. Any expiry not displayed by the dashboard remains a
      mandatory pre-implementation recheck.
- [x] Map consumers at the repository-secret-pair level and record the exact
      Worker Build token. GitHub cannot reveal which historical R2 access-key
      ID is behind the backend pair; the July site pair correlates by date but
      is not treated as proof. This irrecoverable before-state ambiguity
      requires replacement, not credential disclosure.
- [x] Define feasible least-privilege private-reader, science-writer,
      public-publisher, and Worker-deploy roles. Live creation and cutover
      remain later implementation work.
- [x] Inspect relevant Cloudflare audit logs for recent deployment, route,
      bucket, CORS, lifecycle, token, and custom-domain changes.
- [x] Record the accountable owner and a non-secret contact identity for each
      production control; private emergency contact details remain outside Git.

## 6. Read-only verification checklist

Before implementation:

- [x] Restore connected access for the core read-only inventory without
      searching local secret files for a workaround.
- [x] Confirm account, zone, Worker, bucket, and domain targets twice before
      any later write request.
- [x] Incorporate sanitized control-plane and public-route evidence above with
      capture timestamps and source identity.
- [x] Use listing, metadata, `HEAD`, and bounded representative `GET` requests;
      avoid bulk downloads when metadata is sufficient.
- [x] Test the final domain, intended same-origin data route, current
      cross-origin full route, content types, range requests, caching, and CORS
      from the exact production origin.
- [x] Reconcile the current default-branch backend SQLite snapshot with R2
      dates. The five database-only dates are documented in section 4.3; R2
      keys, the production/default-branch site manifest, `site-full` keys, and
      deployed assets are also reconciled.
- [x] Identify the currently active and immediately previous deployment.
- [x] Produce a sanitized dependency map and exact rollback targets for owner
      review.
- [x] Stop before mutation while credential scope and the intended
      public/private boundary remain owner decisions.

Passing this checklist performs no production mutation and is sufficient for
Phase 1.2 discovery.

## 7. Future implementation checklist

These are later implementation prerequisites, not authorization to execute:

- [ ] Obtain explicit scope for bucket creation, copy, policy changes, routes,
      custom domains, DNS, deployment, secrets, and pointer promotion.
- [ ] Snapshot and checksum the current source alerts, baseline inventory,
      persistence state, SQLite database, site manifest, site-full inventory,
      active deployment, and both repository commits.
- [ ] Define separate private processing and public release boundaries with
      least-privilege credentials.
- [ ] Copy and verify objects before changing any consumer; do not move or
      delete the originals during initial migration.
- [ ] Publish immutable release prefixes and validate the authoritative
      manifest and per-date ledger before promotion.
- [ ] Add a conditional small release pointer so stale/racing jobs cannot
      replace a newer complete release.
- [ ] Attach the public release route to the final domain, preferably
      same-origin under `/data/...`.
- [ ] Configure and test exact-origin CORS, content types, compression,
      checksums, range requests, and cache policy.
- [ ] Introduce one non-cancelling concurrency group for state-mutating
      detection and a release-ready signal for site refresh.
- [ ] Keep alerts and rainfall independently publishable with separate
      freshness/status records.
- [ ] Pin and script build/deploy/health/rollback tooling and record source
      commit plus release ID in every deployment.
- [ ] Run lifecycle deletion logic only as a reviewed dry run until retention
      and rollback windows are approved.
- [ ] Disable old public/internal paths only after production verification and
      owner approval.

## 8. Future rollback checklist

No current tested rollback contract was found. Every later migration or
promotion must prepare this checklist before cutover:

- [ ] Record the pre-change DNS targets, Worker routes/custom domains, active
      deployment/version, bucket access settings, CORS, lifecycle, cache rules,
      credential principals, and canonical release pointer.
- [ ] Record exact immutable prior-release keys and checksums for alerts,
      state, SQLite-derived products, site-full files, manifest, and public
      assets.
- [ ] Keep old buckets, prefixes, routes, and credentials available but
      least-privileged during the approved rollback window.
- [ ] Define the one-step pointer or route reversal and its authorized actor.
- [ ] Define when DNS or cache purge is necessary and how success will be
      measured without deleting the prior generation.
- [ ] If promotion health checks fail, stop new state mutation, restore the
      prior pointer/deployment/route, and verify final-domain strong/full modes,
      downloads, rainfall, time series, and `/api/chat`.
- [ ] Reconcile the restored public manifest to its backend/site commits,
      workflow runs, object checksums, state watermark, and deployment version.
- [ ] Preserve failed candidate artifacts and logs for diagnosis; do not
      overwrite the prior release or rewrite Git history.
- [ ] Resume automation only after the canonical pointer, persistence
      watermark, queued dates, and site freshness are consistent.
- [ ] Rotate or revoke credentials only when required by the incident or
      approved migration plan; never destroy the only working rollback path
      prematurely.

## 9. Phase 1 disposition

The core Cloudflare/R2 before-state, exact active/previous deployment targets,
owner-supplied token/build evidence, and authenticated GitHub names-only
inventory satisfy the Phase 1.2 discovery boundary. The following are
mandatory pre-implementation rechecks, not a request to reconnect the working
plugin:

- connector-limited zone settings, Page Rules, DNSSEC, and origin TLS mode;
- exact connector credential identity/scope;
- R2 expiry state not shown in the supplied table;
- creation of uniquely named replacement credentials with consumer mappings
  recorded at creation, because exact historical GitHub-secret-to-token
  linkage cannot be recovered safely.

No production write, deployment, rotation, deletion, or rollback rehearsal was
performed.
