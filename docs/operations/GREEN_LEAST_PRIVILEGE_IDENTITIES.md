# Least-privilege green identities — what R2 actually allows, measured

**Written:** 2026-09-07, Package 2B.3
**Account:** `9416750169311ee4afc18a8ff3c771d4`
**Only approved bucket:** `araripe-v2-staging`

The roadmap bullet is *introduce least-privilege credentials and step-level
secret exposure*. This document separates the half that can be narrowed from
the half that cannot, and says which measurement establishes each.

`PROMOTION_IDENTITY_SETUP.md` already stated the conclusion — *"o limite real é
o código, não o token"*. That was documentation. It is now measured.

---

## 1. What R2 offers, read from the API and confirmed by a real call

R2 API tokens come in four permission levels — **Admin Read & Write**, **Admin
Read only**, **Object Read & Write**, **Object Read only** — and only the two
Object levels can be scoped to buckets
(<https://developers.cloudflare.com/r2/api/tokens/>). The Access Policy's
resource is a **bucket**:

    "com.cloudflare.edge.r2.bucket.<ACCOUNT_ID>_<JURISDICTION>_<BUCKET_NAME>": "*"

Three consequences, and each one decides something in this package:

1. **There is no prefix scoping.** A token that may write `releases/` may also
   write `runs/`, `pointers/` and anything else in the bucket. The
   private/public boundary therefore *cannot* be a credential.
2. **There is no level between read and write.** `Object Read & Write` is one
   level, and it includes DELETE.
3. **`Object Read only` exists and is bucket-scopable.** That is the one real
   narrowing available, and §3 is where it applies.

### The DELETE measurement

Point 2 was an inference from the level names until it was tested. Run on
2026-09-07 with `scripts/probe_readonly_identity.py --expect read-write`
against the local bucket-scoped staging key (`run-id local-2b3-measure-1`):

    PASS  target guard and conditional-write support
    PASS  list araripe-v2-staging
    PASS  araripe-cogs is refused for this identity — code AccessDenied
    PASS  writing into the staging bucket succeeds — result created
    PASS  this identity holds DELETE inside the bucket
          — accepted on an absent key; nothing was destroyed

The delete was issued against a key that **did not exist**, and the probe
refuses to run it against one that does; S3 semantics make deleting an absent
key a no-op, so a held permission destroys nothing and still answers the
question.

**So every identity able to publish a green release is also able to erase
one.** That single fact is why Package 2B.3 keeps deletion out of the code
entirely (`GREEN_RETENTION_AND_MIGRATION.md` §1): if the boundary cannot be the
token, it has to be the code, and the code has no delete operation at all.

### Worker bindings narrow nothing either

An `r2_buckets` binding accepts `binding`, `bucket_name` and `jurisdiction`,
and the Workers API reference states plainly that "an R2 bucket is able to
READ, LIST, WRITE, and DELETE objects". There is no read-only binding and no
prefix binding. The staging Worker's `STAGING_BUCKET` binding can therefore
address every object in the bucket, and only its **code** stops it — which is
why that code's policy is a contract with conformance vectors
(`docs/contracts/phase2b/GREEN_DELIVERY_BOUNDARY_V1.md`).

## 2. The identities today, and what each one actually needs

| Identity | Held by | R2 level | Writes it performs | Needs write? |
| --- | --- | --- | --- | --- |
| `araripe-r2-staging` | the owner's workstation | Object R&W, one bucket | ad-hoc run uploads, proofs | yes |
| `v2-staging` | GitHub Environment | Object R&W, one bucket | `green-isolation-proof/run-…/probe.json` only | **only for one probe step** |
| `v2-promotion` | GitHub Environment | Object R&W, one bucket | `releases/…`, the pointer | yes |
| `STAGING_BUCKET` | Worker binding | full CRUD, one bucket | none | **no** |

The interesting row is `v2-staging`. Its operational job — the `stage` job of
`v2_operational_publish.yml` — runs `scripts/stage_green_run.py`, which is
handed a `ReadOnlyStore` whose three write methods raise, and which therefore
**writes nothing**. The only reason that identity holds write at all is the
last step of `v2_candidate_replay.yml`, the Package 2B.0 isolation probe, which
writes one immutable object to prove green *can* write to staging while being
refused on production.

## 3. The one narrowing that is real, and how to prove it

**Proposal: a third identity, `v2-staging-readonly`, at `Object Read only`,
scoped to `araripe-v2-staging`, used by the `stage` job.**

Not a narrowing of `v2-staging` itself: that would break the 2B.0 isolation
probe's write step, and losing the write half of that proof is a worse trade
than gaining a smaller key for one job.

What it buys is defence in depth on the boundary that matters most. The
`stage` job is the one that reads **operator-supplied input** — a run id from a
`workflow_dispatch` — and it currently holds a key that could write or delete
any object in the bucket, including a live release. Nothing in the code path
does; the point of a smaller key is that it stays true when the code is wrong.

### The setup is the owner's — no agent may create a credential

1. Cloudflare → R2 → **Manage API Tokens** → **Create Account API token**.
2. Name `araripe-green-staging-ro`, permission **Object Read only**.
3. **Apply to specific buckets only** → exactly `araripe-v2-staging`.
4. New GitHub Environment `v2-staging-readonly`, secrets
   `R2_READONLY_ACCESS_KEY_ID` / `R2_READONLY_SECRET_ACCESS_KEY`, the same
   three variables (`R2_STAGING_BUCKET`, `R2_ENDPOINT_URL`, `AWS_REGION`),
   deployment branches **`main` only**, no required reviewer.

Do not paste either value into chat, a repository file, or a `.env`.

**Nothing in this repository names `v2-staging-readonly` yet, deliberately.**
GitHub does not fail on an unknown environment name — it *creates* one "with no
protection rules or secrets configured", which is a repository configuration
change and the wrong one. The wiring waits until the Environment exists, the
same way Package 2B.2C waited for `v2-promotion`.

### And then prove the scope, because configuration proves nothing

On 2026-09-07 the first promotion key had a **perfect** Environment — correct
secret names, `branch: main` policy, all three variables — and reached the
**production** bucket. The scope that mattered lived in Cloudflare and is
invisible from GitHub (`GREEN_PROOFS_2026-09-07.md` §2).

> Credential scope is only ever proven by a real call that must be refused.

`scripts/probe_readonly_identity.py` is that call, in both directions:

    R2_STAGING_BUCKET=araripe-v2-staging \
    R2_ENDPOINT_URL=https://9416750169311ee4afc18a8ff3c771d4.r2.cloudflarestorage.com \
    python scripts/probe_readonly_identity.py --run-id <run>-<attempt>

Expected, with the default `--expect read-only`, **five of five**:

| Check | Pass condition |
| --- | --- |
| target guard and conditional-write support | accepted |
| list `araripe-v2-staging` | succeeds |
| `araripe-cogs` is refused | **AccessDenied** |
| writing into the staging bucket is refused | **AccessDenied** |
| deleting from the staging bucket is refused | **AccessDenied** |

The last two are inverted checks, and an inverted check with the polarity wrong
is worse than no check — it would certify exactly the credential it exists to
catch. Both polarities are asserted in
`tests/test_readonly_identity_probe.py`, in both directions and for both
operations, the same discipline
`test_a_readable_production_bucket_is_a_failure` established for isolation.

## 4. What cannot be narrowed, and why saying so is the deliverable

**The promotion identity stays `Object Read & Write` on the whole bucket.** It
must write `releases/<id>/…` and `pointers/green/current.json`, R2 has no
prefix scoping, and there is no write-without-delete level. So the token that
publishes a release can also delete every release. There is no configuration
that changes this; the mitigations are:

* `ConditionalStore` exposes one read and two conditional writes — no delete,
  no unconditional put — so the capability is unreachable from the code;
* every release object is written with `If-None-Match: *` under a prefix
  derived from its ledger, so a rewrite is not expressible either;
* the pointer moves only by compare-and-swap, inside a serialized lane;
* `assert_staging_target` refuses `araripe-cogs` by name before a credential is
  read.

**The Worker binding stays full CRUD**, for the same reason, and the route's
allowlist is what makes that safe (`GREEN_DELIVERY_BOUNDARY_V1.md` §2).

**The blue identities are not touched.** `R2_ACCESS_KEY`, `R2_SECRET_KEY` and
`GEE_SA_KEY` are production credentials in frozen workflows; narrowing them is
a blue change requiring explicit human approval, and it belongs with the Phase 6
cutover.

## 5. Step-level secret exposure

The second half of the bullet is entirely inside the workflow files, and
`tests/test_secret_exposure.py` pins it.

**Every green workflow already exposed its secrets at the step rather than the
job**, so the sweep records an existing property rather than fixing a defect —
except for one thing it did find.

The `stage` job of `v2_operational_publish.yml` exported the candidate key
**twice**: once as `R2_STAGING_ACCESS_KEY_ID` / `R2_STAGING_SECRET_ACCESS_KEY`,
which `stage_green_run.py` reads and passes to `boto3.client` explicitly, and
once as `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`, which nothing reads.

The unused pair was not inert. It put the credential into **boto3's default
credential chain**, so any AWS call in that step — one that never went through
`build_client` and its bucket-and-endpoint guard — would have been
authenticated. Given §1's measurement, that is a key holding write and delete
over the whole bucket, available past the guard. Removed, and pinned:

* no green workflow references a secret at workflow or job level;
* a step running a repository script may export only names that script reads;
* no `run:` body interpolates a secret expression;
* no step holds the candidate and promotion identities together.

**The blue workflows do not have the first property**, and that is recorded as
an assertion rather than fixed: `detect_gee.yml`, `update_data.yml` and
`esa_reprocessing_watch.yml` expose `R2_ACCESS_KEY`, `R2_SECRET_KEY` and
`GEE_SA_KEY` at the job, so every step of a blue run — including checkout —
holds them. Narrowing that is a blue change and belongs with Phase 6, and
recording it as a test means it cannot drift unnoticed in the meantime.
