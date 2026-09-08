# Configuration Register — 2026-07-24

**Status:** Phase 1 names-only register accepted on 2026-07-28;
implementation and rotation pending
**Date:** 2026-07-24; sanitized control-plane evidence refreshed 2026-07-28
**Scope:** GitHub Actions, backend runtime, site data preparation, Cloudflare
Worker/static assets, R2 access roles, and external providers

## 1. Safety statement

This register records configuration **names and intended roles only**. It
contains no secret value, token, credential, private endpoint, account
identifier, or service-account document.

No `.env` file was opened or read to create this document. Both repositories
may auto-load ignored local `.env` files, but local presence and content remain
outside this register.

For every entry below:

- live existence is **unverified** unless a later sanitized control-plane audit
  explicitly records it;
- actual IAM/token scope is **unverified**;
- a repository reference proves only that code expects a name, not that the
  value exists or works;
- proposed target names are not evidence that a secret, variable, bucket, or
  binding has been created;
- Phase 1 performs no rotation or live preflight that writes production state.

Initial access result on 2026-07-24:

- the connected GitHub capability verified repository metadata and the three
  default-branch workflow files, but does not expose repository
  secret/variable or credential-scope inventory;
- the configured local `gh` authentication reported its token invalid, so it
  was not used to infer live secret/variable presence, branch protection, or
  token authority;
- no alternate credential or local secret file was opened or tested.

Sanitized GitHub refresh on 2026-07-28:

- browser-based authorization restored the local `gh` session for
  `@santibravocmcc`; the token value was not displayed or copied;
- authenticated read-only API calls confirmed administrator access to
  `santibravocmcc/Araripe` and
  `santibravocmcc/observatorio-site`;
- repository secret **names**, creation/update timestamps, repository
  variables, environments, Actions policy, workflow-token defaults, artifact
  retention, workflow state, rulesets, and default-branch protection were
  inventoried without reading any secret value;
- both repositories have Actions enabled for all actions, do not require
  action SHA pinning, default `GITHUB_TOKEN` to read-only, and disallow the
  token from approving pull-request reviews;
- both workflows explicitly request `contents: write`. The public backend
  `main` branch has no protection or effective rules. The private site
  repository's current plan does not expose branch protection/rulesets, so no
  enforceable default-branch rule was evidenced;
- neither repository has an Actions environment or repository variable. This
  exposes a live `EE_PROJECT` mismatch: a repository **secret** with that name
  exists in the backend, but the workflow reads `vars.EE_PROJECT`, so the
  checked-in `ee-araripe` fallback is currently effective.

Sanitized Cloudflare refresh on 2026-07-28:

- the live `observatorio-chapada` Worker contains the three declared
  non-secret bindings and all six recognized provider secret names;
- secret values were neither requested nor returned;
- Worker Builds links production to `santibravocmcc/observatorio-site`
  `main`, runs `npm run build`, then `npx wrangler deploy`, and records the
  source commit on the deployment;
- the connector's core reads work, but its identity, expiry, and exact scope
  remain unresolved; the exposed effective permissions include write-capable
  operations, so the connection is not certified as least privilege;
- owner-supplied dashboard evidence identifies four active, write-capable R2
  tokens. `observatorio-chapada build token` is mapped to Worker Builds; the
  July 16 account token correlates with the site secret provisioning date, but
  GitHub's names-only API cannot prove which access-key ID is stored. The two
  March 29 tokens cannot be distinguished retroactively without reading
  secret material;
- those historical ambiguities are accepted as before-state findings, not
  invitations to reveal credentials. Phase 2/6 preflight must replace them
  with uniquely named, role-specific credentials and record the mapping at
  creation.

## 2. Current GitHub Actions register

### 2.1 Backend repository

| Name | Kind | Referenced by | Required now | Current exposure | Intended minimum scope | Live presence/scope |
|---|---|---|---|---|---|---|
| `R2_ENDPOINT_URL` | GitHub secret in current workflows; non-secret endpoint by nature | `detect_gee.yml`, `update_data.yml`, R2 scripts | Required for production R2 operation; current workflow conditions can skip some fetch/upload steps when absent | Job-wide in both backend jobs | Connect only to the approved Cloudflare account endpoint; target representation should be a non-secret variable where policy permits | Present at repository scope; value not inspected |
| `R2_ACCESS_KEY` | GitHub secret | Both backend workflows and R2 scripts | Required with the endpoint for production | Job-wide in both backend jobs | Current shared credential should be replaced by role-specific credentials; no public-bucket authority for a private reader | Present at repository scope; exact March 29 R2 token identity is not recoverable names-only |
| `R2_SECRET_KEY` | GitHub secret | Both backend workflows and R2 scripts | Required with the access key | Job-wide in both backend jobs | Same role boundary as its paired access key; never exposed to processing steps that do not call R2 | Present at repository scope; paired value not inspected |
| `GEE_SA_KEY` | GitHub secret | Scheduled `detect_gee.yml`; GEE initialization code | Required for unattended scheduled GEE production | Job-wide, including checkout, environment setup, R2 fetch, detection, upload, and Git steps | One dedicated service account limited to the approved Earth Engine project and only the computation/thumbnail operations required by detection | Present at repository scope; upstream IAM scope not inspected |
| `EE_PROJECT` | GitHub repository variable | Scheduled `detect_gee.yml` | Required logically; workflow currently has a code/YAML fallback | Job-wide non-secret environment | Name only the registered, EE-enabled project authorized for the dedicated service account | **Repository variable absent.** Same-name repository secret is present but unused by `vars.EE_PROJECT`; fallback `ee-araripe` applies |
| `EARTHDATA_USERNAME` | GitHub secret | Manual streaming workflow detection step | Optional for code paths/providers that do not require authenticated Earthdata; required when that path downloads protected Earthdata | Step-scoped in the manual detection step | Read/download access to required NASA Earthdata products only; preferably a dedicated automation identity if provider policy supports it | Present at repository scope; upstream account scope not inspected |
| `EARTHDATA_PASSWORD` | GitHub secret | Manual streaming workflow detection step | Paired with `EARTHDATA_USERNAME` | Step-scoped in the manual detection step | Same read-only product scope as the paired username | Present at repository scope; value not inspected |
| `GITHUB_TOKEN` | GitHub-issued ephemeral token | Checkout and direct bot push | Currently required because the workflows commit the SQLite database | Workflow permission grants `contents: write`; token is persisted by checkout for later Git commands | Target routine data publication uses R2 and needs only `contents: read`; if a transitional commit remains, isolate it in a separate job with `contents: write` | Repository default is read; both workflows elevate to `contents: write`; `main` has no protection or effective rules |

Current backend workflows do not declare a concurrency group. The scheduled
and manual jobs can therefore share the same state and credential authority
while overlapping.

Additional repository-scoped secrets present but not referenced by either
current default-branch backend workflow are `CDSE_USERNAME`, `CDSE_PASSWORD`,
and `HF_TOKEN`. Their values and upstream scope were not inspected. The
backend has no repository variable and no Actions environment.

### 2.2 Site repository

| Name | Kind | Referenced by | Required now | Current exposure | Intended minimum scope | Live presence/scope |
|---|---|---|---|---|---|---|
| `R2_ENDPOINT_URL` | GitHub secret in current workflow; endpoint by nature | Site alert preparation | Required to ingest live R2 alerts and upload full products | Alert-generation step only | Target non-secret endpoint plus role-specific credentials; no state/baseline access for the public-product writer unless explicitly required | Present at repository scope; value not inspected |
| `R2_ACCESS_KEY` | GitHub secret | Site alert preparation | Required with endpoint | Alert-generation step only | Current code both reads private source alerts and writes public full products; target splits those into private-reader and public-writer roles | Present at repository scope; July 16 provisioning correlates with `R2 Account Token-env`, but access-key identity is not exposed |
| `R2_SECRET_KEY` | GitHub secret | Site alert preparation | Required with access key | Alert-generation step only | Same split-role requirement as the paired access key | Present at repository scope; paired value not inspected |
| `EARTHDATA_USERNAME` | GitHub secret | Site rainfall job | Required for unattended authenticated GPM downloads | Rainfall-generation step only | Read/download access to required GPM products only | Present at repository scope; upstream account scope not inspected |
| `EARTHDATA_PASSWORD` | GitHub secret | Site rainfall job | Required with username | Rainfall-generation step only | Same read-only product scope as the paired username | Present at repository scope; value not inspected |
| `GITHUB_TOKEN` | GitHub-issued ephemeral token | Checkout and two generated-data pushes | Currently required by direct generated commits | Workflow-level `contents: write`; checkout persists credentials | Target routine data publication needs `contents: read`; remove generated pushes after automatic R2 publication is verified | Repository default is read; workflow elevates to `contents: write`; private-repository plan exposes no enforceable `main` protection/rules |

No `${{ vars.* }}` reference exists in the current site workflow. The site has
no repository variable or Actions environment. An additional
repository-scoped secret named `EARTHDATA` is present but is not referenced by
the current default-branch workflow. The workflow has no explicit deploy job
or deploy credential contract. The later sanitized Cloudflare refresh
verified a live Worker Builds integration from `main`; its named build token
is known, but its exact Cloudflare token scope remains a mandatory
pre-implementation recheck.

### 2.3 Repository policy and workflow summary

| Control | `Araripe` | `observatorio-site` |
|---|---|---|
| Visibility/default branch | Public / `main` | Private / `main` |
| Administrator evidence | Authenticated caller has `admin` | Authenticated caller has `admin` |
| Active workflows | `detect_gee.yml`, `update_data.yml` | `update-data.yml` |
| Actions policy | Enabled; all actions allowed; SHA pinning not required | Enabled; all actions allowed; SHA pinning not required |
| Default workflow token | Read-only; cannot approve PR reviews | Read-only; cannot approve PR reviews |
| Workflow override | Both request `contents: write` | Requests `contents: write` |
| Default-branch enforcement | No classic protection, ruleset, or effective rule | Protection/rulesets unavailable under the current private-repository plan; no enforceable rule evidenced |
| Repository variables | None | None |
| Actions environments | None | None |
| Artifact/log retention | 90 days | 90 days |
| Public-fork approval | First-time contributors require approval | Not applicable to the private repository |

Relevant repository-secret provisioning dates are:

| Repository | Names | Created | Last updated when different |
|---|---|---|---|
| `Araripe` | `R2_ENDPOINT_URL`, `R2_ACCESS_KEY`, `R2_SECRET_KEY` | 2026-03-29 | Access key 2026-03-29 16:09 UTC; secret key 2026-03-29 16:09 UTC |
| `Araripe` | `EARTHDATA_USERNAME`, `EARTHDATA_PASSWORD`, `CDSE_USERNAME`, `CDSE_PASSWORD`, `HF_TOKEN` | 2026-03-29 | Same day as creation |
| `Araripe` | `GEE_SA_KEY`, same-name secret `EE_PROJECT` | 2026-07-14 | Same day as creation |
| `observatorio-site` | `EARTHDATA` | 2026-07-09 | Same day as creation |
| `observatorio-site` | `R2_ENDPOINT_URL`, `R2_ACCESS_KEY`, `R2_SECRET_KEY` | 2026-07-16 | Same day as creation |
| `observatorio-site` | `EARTHDATA_USERNAME`, `EARTHDATA_PASSWORD` | 2026-07-17 | Same day as creation |

Dates are configuration metadata only. They support correlation but do not
prove which hidden access-key ID is stored in a secret.

These settings are a before-state, not approval to retain them. Phase 6 must
pin reviewed third-party Actions, introduce CI and enforceable branch
protection, and isolate any transitional `contents: write` publication job.

## 3. Current runtime and non-secret configuration

### 3.1 Backend runtime names

| Name | Source/reference | Required or optional | Purpose | Target treatment |
|---|---|---|---|---|
| `R2_BUCKET_NAME` | Backend settings/code default; not mapped in current workflows | Optional override | Selects the current R2 bucket | Replace implicit shared-bucket default with explicit private/public bucket variables after names are approved |
| `R2_ENDPOINT_URL` | Environment | Required for live R2 | S3-compatible endpoint | Validate format/account before any object operation; do not log private endpoint details |
| `GEE_SA_KEY_FILE` | Local runtime alternative in GEE initialization code | Optional local alternative to `GEE_SA_KEY` | Path to a service-account key file | Local only; outside repository; never print or commit path contents |
| `START` | Scheduled workflow step environment | Optional manual input | Inclusive detection start date | Validate ISO date and authorized replay window before processing |
| `END` | Scheduled workflow step environment | Optional manual input | Exclusive detection end date | Validate ISO date, ordering, and authorized replay window |
| `AOI_BBOX` | `config/settings.py` | Required fallback/current setting | Bounding coordinates | Target release uses a versioned wider-extent artifact; this name cannot silently redefine it |
| `AOI_GEOPACKAGE` | `config/settings.py` | Required canonical input candidate | APA reference path | Record checksum/version; distinguish APA context from wider monitoring extent |
| `TARGET_CRS` | `config/settings.py` | Required | Processing CRS | Record in release manifest |
| `SEARCH_DAYS_BACK` | `config/settings.py` | Required | Routine imagery lookback | Roadmap target is five days; changes require tests and versioned algorithm metadata |
| `REFLECTANCE_SCALING` | `config/settings.py` | Required and coupled | Controls reflectance scaling | Must match the selected baseline version; preflight rejects an incompatible pair |
| `BASELINE_YEARS` | `config/settings.py` | Required for baseline build | Historical baseline selection | Move effective years into baseline manifest/provenance |
| `MAX_CLOUD_COVER` | `config/settings.py` | Required | Scene metadata filter | Record effective value in algorithm version |
| `MIN_CLEAR_PERCENTAGE_BASELINE` | `config/settings.py` | Required | Baseline-scene QA threshold | Record in baseline manifest |
| `SCENE_ANOMALY_REJECT_FRAC` | `config/settings.py` | Required | Scene rejection threshold | Record in algorithm version and validate denominator implementation |
| `Z_THRESHOLD_HIGH` | `config/settings.py` | Required | Detection rule | Record in algorithm version |
| `Z_THRESHOLD_MEDIUM` | `config/settings.py` | Required | Detection rule | Record in algorithm version |
| `Z_THRESHOLD_LOW` | `config/settings.py` | Required | Detection rule | Record in algorithm version |
| `DELTA_THRESHOLD_HIGH` | `config/settings.py` | Required | Detection rule | Record in algorithm version |
| `DELTA_THRESHOLD_MEDIUM` | `config/settings.py` | Required | Detection rule | Record in algorithm version |
| `DELTA_THRESHOLD_LOW` | `config/settings.py` | Required | Detection rule | Record in algorithm version |
| `MIN_ALERT_AREA_HA` | `config/settings.py` | Required | Polygon-area rule | Record in algorithm version |
| `MAX_ALERT_AREA_HA` | `config/settings.py` | Required | Polygon-area rule | Record in algorithm version |
| `SPI_DROUGHT_THRESHOLD` | `config/settings.py` | Required when drought adjustment is evaluated | Drought method input | Record enabled/disabled state and method version per release |
| `DROUGHT_Z_ADJUSTMENT` | `config/settings.py` | Required when drought adjustment is evaluated | Drought threshold adjustment | Same conditional/versioned treatment |
| `LANDCOVER_RASTERS` | `config/settings.py` | Required for current annotation | MapBiomas crop mapping | Replace implicit filenames with versioned collection/crop manifest |
| `DEFAULT_LANDCOVER_COLLECTION` | `config/settings.py` | Required | Default annotation collection | Record collection identity in release |
| `NATURAL_VEG_MIN_FRAC` | `config/settings.py` and site derivation semantics | Required for current strong derivative | Natural-cover threshold | Derivative-only; never controls retention/existence of raw detections |
| `SCENE_CACHE_DIR` | `config/settings.py` | Optional cache path | Local scene cache | Non-canonical; lifecycle only after reconstructability checks |

### 3.2 Site preparation runtime names

| Name | Source/reference | Required or optional | Purpose | Target treatment |
|---|---|---|---|---|
| `ARARIPE_DIR` | Site workflow and `prepare_data.py` | Required in CI; local default exists | Backend checkout/input location | Validate repository and source commit before preparation |
| `TERRITORIO_SRC` | Site rainfall workflow and territory scripts | Required in CI; local default exists | Rainfall and territory source location | Replace Git-vendored operational source path with private input/cache location after migration |
| `R2_BUCKET_NAME` | Site preparation code default; not workflow-mapped | Optional override | Current shared bucket | Target explicit private-source and public-release bucket variables |
| `EARTHDATA_TOKEN` | Site local example/runtime | Optional local alternative | Earthdata authentication | Not a substitute for an unattended rotation contract |
| `MIN_DETECTION_DATE` | Site preparation code constant | Required current filter | Earliest displayed monitoring date | Target derived from release scope/ledger, not an unversioned client-side publication assumption |
| `R2_ALERTS_BASE` | Site client constant | Required for current full mode | Public full-alert base URL | Remove after same-origin manifest migration; no endpoint hard-coded in client |
| `MAPBIOMAS_BASE` | Site client constant | Required for current overlays | Same-origin overlay base | Replace with release-manifest-relative URLs |

### 3.3 GitHub workflow context names

These are platform context/runtime names, not repository secrets:

| Name | Current use | Target rule |
|---|---|---|
| `RUNNER_TEMP` | Temporary backend clone and runner files | Ephemeral only; never a canonical store |
| `GITHUB_WORKSPACE` | Site rainfall source path | Validate path; no secret content |
| `github.event.inputs.start` | Manual scheduled-workflow date input | Strict ISO/range preflight |
| `github.event.inputs.end` | Manual scheduled-workflow date input | Strict ISO/range preflight |

## 4. Cloudflare Worker and provider register

### 4.1 Declared non-secret bindings

| Name | Kind | Declared in repository | Required or optional | Current exposure | Intended scope | Live presence/scope |
|---|---|---|---|---|---|---|
| `ASSETS` | Worker static-assets binding | `site/wrangler.jsonc` | Required for the combined Worker/assets design | Worker runtime | Read only from the deployed `dist` asset namespace | Present on active Worker version; effective namespace policy not inspected |
| `AI` | Workers AI binding | `site/wrangler.jsonc` | Optional provider, but configured in source | Worker runtime | Inference only for approved model(s); no R2 or account-management scope | Present on active Worker version; effective model/account policy not inspected |
| `CHAT_LIMITER` | Rate-limit binding | `site/wrangler.jsonc` | Required for the current anti-abuse design | Worker runtime | Apply only to chat requests; target failure behavior must be explicitly chosen and tested | Present on active Worker version; namespace `1001`; runtime behavior not mutated or load-tested |

Repository configuration also names the Worker, compatibility date, asset
directory, API-first route list, and rate-limit namespace/configuration. The
2026-07-28 inventory matched these non-secret values to the live deployment;
the target contract still requires a repository-owned reproducible deployment
and rollback record.

### 4.2 Provider secret names

| Name | Provider role | Required or optional | Current exposure | Intended minimum scope | Live presence/scope |
|---|---|---|---|---|---|
| `GEMINI_API_KEY` | Gemini inference adapter | Optional; at least one usable provider/binding is needed for chat | Worker runtime only when bound | Model inference only; no broader Google project administration | Present as `secret_text` on active Worker; value and upstream scope not inspected |
| `ZAI_API_KEY` | Z.ai inference adapter | Optional | Worker runtime only when bound | Model inference only | Present as `secret_text` on active Worker; value and upstream scope not inspected |
| `GROQ_API_KEY` | Groq inference adapter | Optional | Worker runtime only when bound | Model inference only | Present as `secret_text` on active Worker; value and upstream scope not inspected |
| `GITHUB_MODELS_TOKEN` | GitHub Models adapter | Optional | Worker runtime only when bound | Models/inference access only; no repository, workflow, package, or organization write scope | Present as `secret_text` on active Worker; value and upstream scope not inspected |
| `CEREBRAS_API_KEY` | Cerebras inference adapter | Optional | Worker runtime only when bound | Model inference only | Present as `secret_text` on active Worker; value and upstream scope not inspected |
| `NVIDIA_API_KEY` | NVIDIA inference adapter | Optional | Worker runtime only when bound | Model inference only | Present as `secret_text` on active Worker; value and upstream scope not inspected |

Provider secrets must not enter browser bundles, GitHub data-refresh workflows,
logs, public error responses, release manifests, or health output. A sanitized
health check may report provider availability by stable provider name, never a
secret fragment or upstream private error.

The live deployment mechanism is Cloudflare Worker Builds connected to
`santibravocmcc/observatorio-site`, production branch `main`, with
`npm run build` followed by `npx wrangler deploy`. The active deployment records
site commit `0dcb99fd8be8ac1311f23fb6998ca9f08ed54e69`. No explicit
repository-controlled Cloudflare deployment credential is documented, and the
Cloudflare-side deployment principal, credential scope, and rollback authority
remain unverified before a deployment contract can be implemented.

## 5. Proposed target R2 roles and names

The current `R2_ACCESS_KEY`/`R2_SECRET_KEY` pair combines unrelated read and
write operations. The following names are a proposed contract for later
implementation and rotation. They do not exist merely because they appear
here.

Non-secret repository/environment variables:

| Proposed name | Purpose | Intended scope |
|---|---|---|
| `R2_ENDPOINT_URL` | Approved account S3 endpoint | Endpoint only; no authority |
| `R2_PRIVATE_BUCKET_NAME` | Private source/state/baseline bucket | Target value `araripe-processing-private`; verify availability before creation |
| `R2_PUBLIC_BUCKET_NAME` | Public release-only bucket | Target value `araripe-public-releases`; verify availability before creation |
| `R2_STAGING_PREFIX` | Run-specific private staging root | Name only; must include unique run identity |
| `PUBLIC_DATA_BASE_PATH` | Final same-origin route under `/data` | Target value `/data/releases`; pointer `/data/releases/current.json` |

Proposed GitHub secrets:

| Proposed name | Consumer step | Minimum object authority |
|---|---|---|
| `R2_PRIVATE_READER_ACCESS_KEY` | Baseline/source/state fetch preflight and fetch steps | List only the required private bucket prefixes; get/head required baseline, source, manifest, and selected state objects; no put/delete/public bucket |
| `R2_PRIVATE_READER_SECRET_KEY` | Paired with private reader access key | Same role |
| `R2_SCIENCE_WRITER_ACCESS_KEY` | Science staging upload and conditional working-state promotion steps | Put only unique science staging/release keys; read/head verification; conditional update only of the private state pointer; no public bucket and no broad delete |
| `R2_SCIENCE_WRITER_SECRET_KEY` | Paired with science writer access key | Same role |
| `R2_PUBLIC_PUBLISHER_ACCESS_KEY` | Validated public copy/upload and release-pointer promotion steps | Put/head immutable public release keys; conditional update of the public release pointer; no private state/baseline/source access and no broad delete |
| `R2_PUBLIC_PUBLISHER_SECRET_KEY` | Paired with public publisher access key | Same role |

If Cloudflare token policy cannot express a required prefix or conditional
boundary, use separate buckets and narrower jobs rather than treating a prefix
as an access-control boundary. Delete authority is not included in routine
publisher roles. Lifecycle/deletion uses a separately approved, short-lived
maintenance authority after a reviewed dry run.

## 6. Target exposure by step

GitHub Actions cannot reduce `GITHUB_TOKEN` permissions at individual steps,
so a write-capable Git step must be isolated in a separate job. Other secrets
can and should be injected only into the step that consumes them.

| Step/job role | Allowed names | Explicitly excluded |
|---|---|---|
| Checkout/build/test | `GITHUB_TOKEN` with `contents: read`; non-secret runtime variables | R2 write credentials, GEE key, Earthdata credentials, Worker provider secrets |
| R2 private preflight/fetch | Private reader pair, endpoint, private bucket name | Science/public writer pairs, provider secrets |
| GEE authentication preflight/detection | `GEE_SA_KEY`, `EE_PROJECT`; local files already fetched | R2 credentials after fetch, Earthdata credentials, public publisher |
| Streaming Earthdata acquisition | `EARTHDATA_USERNAME`, `EARTHDATA_PASSWORD` or an approved alternative; only for that step | GEE key, public publisher, Worker provider secrets |
| Science staging upload/state promotion | Science writer pair, endpoint, private bucket name, release/run identity | Private reader after input verification, public publisher |
| Public-product build | Verified local/private inputs; no live public write credential | State writer, GEE key, provider secrets |
| Public release upload/verification/pointer promotion | Public publisher pair, endpoint, public bucket name, validated manifest and expected previous pointer version | Private baseline/source/state reader, GEE key, Earthdata credentials |
| Rainfall acquisition | Earthdata pair only | R2 science-state credentials, provider secrets |
| Rainfall public promotion | Public publisher pair scoped to rainfall release keys/pointer component | Earthdata credentials after source acquisition |
| Worker runtime | Declared bindings and only configured provider secrets | GitHub/R2/GEE/Earthdata credentials |
| Transitional Git commit, if temporarily retained | Separate job with `GITHUB_TOKEN: contents: write` and reviewed generated paths only | All provider and cloud writer secrets not needed by the commit |

The Worker build/deploy credential has no R2 authority in the target contract.
The current `observatorio-chapada build token` all-bucket R2 administration is
an explicitly recorded migration gap, not a target permission.

The target end state removes routine generated data pushes to `main`; code and
configuration changes continue through normal Git review while operational
data publication remains automatic through R2.

## 7. Preflight contract

Preflights are required before a mutating step. They report pass/fail and
sanitized identifiers only.

### 7.1 R2

- confirm every required name is present without echoing it;
- validate endpoint and approved bucket-name configuration;
- authenticate with the exact role used by the next step;
- private reader: head/list only the required prefixes/objects and validate the
  baseline/source/state manifest and expected checksums;
- distinguish an explicit missing object from authorization, network, timeout,
  service, parse, and schema failures;
- allow empty-state initialization only with an explicit first-generation
  contract; all other state failures abort;
- writer: verify authority against a unique non-production preflight/staging
  key or provider-supported permission check; do not test against a canonical
  fixed key;
- before promotion, verify every uploaded object by size/checksum and compare
  the expected prior pointer version/ETag;
- never log signed URLs, endpoint credentials, authorization headers, or
  private object contents.

### 7.2 GEE

- confirm `GEE_SA_KEY` and `EE_PROJECT` are present without printing them;
- parse the credential in memory and reject malformed input without returning
  its content;
- initialize Earth Engine against the expected project;
- verify only the minimal computation/read operation needed for the run;
- confirm requested dates and wider-extent version before processing.

### 7.3 Earthdata

- confirm the selected credential pair or approved alternative is present;
- authenticate and perform a metadata/search check for the required product;
- validate product, version, date coverage, and expected granule count before
  accepting a write;
- an incomplete weekly/monthly acquisition must produce an explicit incomplete
  status, not a green freshness update.

### 7.4 Worker/deployment

- confirm `ASSETS`, `AI` when selected, `CHAT_LIMITER`, and at least one approved
  provider are available without exposing binding content;
- build from the lockfile and record site commit, deployment ID, compatibility
  date, non-secret binding names, and selected data-manifest compatibility
  range;
- verify static assets, `/api/chat` sanitized behavior, same-origin `/data`
  pointer/manifest, strong/full downloads, content types, and rollback target;
- do not treat a successful code deployment as proof that a data release is
  complete or fresh.

## 8. Rotation contract

Phase 1 does not rotate anything. Later coordinated rotation follows this
sequence:

1. identify the credential owner, consumers, last verified use, intended
   minimum scope, and rollback contact without recording its value;
2. create a new narrowly scoped credential alongside the old one;
3. validate it against staging/read-only preflights;
4. update only the consuming secret/binding and run the relevant end-to-end
   staging check;
5. observe one successful unattended cycle where required;
6. revoke the old credential;
7. verify revocation and audit logs;
8. record rotation date, credential role/version, and next review date without
   storing secret material.

Additional rules:

- rotate the existing shared R2 credential into role-specific private-reader,
  science-writer, and public-publisher credentials before bucket cutover;
- rotate `GEE_SA_KEY` with overlapping service-account validation, then revoke
  the old key;
- coordinate Earthdata rotation so scheduled rainfall and the manual fallback
  do not silently lose freshness;
- rotate Worker provider secrets independently; one provider rotation must not
  expose or rewrite other providers;
- emergency revocation favors stopping publication over falling back to a
  broader credential;
- never paste a credential into an issue, document, workflow log, release
  manifest, chat, or commit.

### 8.1 Ownership, cadence, and notification defaults

- Accountable credential, deployment, rollback, and incident owner:
  project owner `@santibravocmcc`; private contact details remain outside Git.
- Target Worker deploy credential:
  `observatorio-worker-deploy`, account/service identity, Workers deployment
  authority only, no R2 object or bucket administration.
- Production account/service credentials:
  review every 90 days and rotate at least every 180 days, with an overlap
  preflight before revocation.
- User-bound/development credentials:
  review every 90 days and replace or rotate within 90 days when they reach a
  production path.
- Provider credentials:
  follow any shorter provider maximum and review presence/scope every 90 days;
  rotate immediately on suspected exposure or owner departure.
- Initial non-secret notification destination:
  GitHub Actions job summary and failed-run notification to the repository
  owner. A later observability package may add a private channel without
  storing its address here.

## 9. Phase 1 disposition and mandatory pre-implementation rechecks

The names-only register is accepted for Phase 1. The GitHub control-plane
inventory is complete, the four owner-supplied R2 token records and Worker
Build consumer are recorded, and the target role split, owner, review cadence,
rotation sequence, and non-mutating preflights are defined.

The hidden value behind an existing GitHub secret cannot be matched
retroactively to a Cloudflare access-key ID through a names-only API. The
backend pair dates to the same day as two candidate R2 tokens; the site pair
correlates with the July 16 account token, but correlation is not proof.
Reading or comparing secret values would violate this register's safety
boundary. This is therefore an accepted before-state ambiguity, not missing
owner input and not a Phase 1 blocker.

Before any implementation, credential, route, or bucket change:

1. reconfirm connector-limited zone settings, Page Rules, DNSSEC, and origin
   TLS mode;
2. confirm the Cloudflare connector/deployment principal identity, expiry, and
   exact scope;
3. confirm whether the four R2 tokens have explicit expiry dates that were not
   displayed in the supplied table;
4. create uniquely named private-reader, science-writer, public-publisher, and
   Worker-deploy credentials with exact resource scope, then record each
   consumer at creation;
5. use the staging/read-only preflights in this register and observe the
   required successful cycle before revoking an old credential;
6. correct the `EE_PROJECT` variable/secret mismatch, pin reviewed Actions,
   and add enforceable branch controls in their scheduled implementation
   phases.

No credential was read, changed, rotated, or tested with a production write
to accept this register.

## 10. Isolated staging addendum — 2026-08-11

`araripe-v2-staging` now exists as a private, additive object sandbox. It has
no public managed domain, custom domain, CORS policy, Worker binding, or
production role. It is separate from the future private-processing and
public-release buckets.

Claude Code may receive one R2 S3 `Object Read & Write` identity restricted to
that exact bucket, stored outside the repositories as AWS profile
`araripe-r2-staging`. It must not receive `CLOUDFLARE_API_TOKEN` in the
production account. Exact endpoint and setup are versioned in
`docs/operations/CLOUDFLARE_STAGING_ACCESS_FOR_CLAUDE.md`.

GitHub must use a different identity in Environment `v2-staging`. This
Environment and identity had not yet been created as of 2026-08-11:

- secrets `R2_STAGING_ACCESS_KEY_ID` and
  `R2_STAGING_SECRET_ACCESS_KEY`;
- variables `R2_STAGING_BUCKET`, `R2_ENDPOINT_URL`, and `AWS_REGION=auto`;
- no Worker/zone/DNS authority and no reuse as a publisher credential.

Object-prefix conventions are not access-control boundaries. Promotion,
canonical buckets, Workers, routes, DNS, Builds, CORS, lifecycle, and token
creation remain separately gated Cloudflare control-plane operations.
