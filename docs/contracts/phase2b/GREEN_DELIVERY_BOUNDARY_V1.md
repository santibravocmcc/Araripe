# Phase 2B.3 — the green delivery boundary

**Contract version:** `araripe.green.delivery/1`
**Recorded:** 2026-09-07
**Production mutation:** none

Package 2B.2B defined what a green release *is* and Package 2B.2C defined how
one is *published*. Neither said what may be **read by the public**, because
nothing served green storage at all. This document is that boundary: which
objects may leave `araripe-v2-staging`, through which route, with which
headers, and what is deliberately not claimed.

Machine-readable forms:
[`delivery_conformance_vectors.json`](delivery_conformance_vectors.json) — the
request/outcome vectors every implementation must reproduce. The authority is
[`src/publication/delivery_boundary.py`](../../../src/publication/delivery_boundary.py);
the vectors are the reference between it and the Worker Package 2B.4 will
write.

---

## 1. Two boundaries in one bucket

`araripe-v2-staging` holds processing inputs and published products side by
side. It has no public access of its own — measured on creation (2026-08-11)
and unchanged: R2 managed public access disabled, no custom domain, no CORS
policy. So the boundary is **not the bucket**; it is whatever a Worker chooses
to serve.

| Class | Keys | Exposure |
| --- | --- | --- |
| pointer | `pointers/green/current.json` | **public** |
| live release | `releases/<live>/…` | **public** |
| any other release | `releases/<other>/…` | private |
| processing input | `runs/<run-id>/…` | private |
| verification artifact | `green-isolation-proof/…`, `promotion-identity-probe/…`, `readonly-identity-probe/…` | private |
| anything else | — | **private**, and reported |

The last row is the policy's shape, not a footnote. A prefix nobody has
classified is private, so a future producer writing to a new root is invisible
until someone decides it should not be. An error toward "private" is a visible
bug; an error toward "public" is a disclosure.

### Public is the *live* release, never `releases/`

Serving the whole `releases/` prefix would publish exactly what the publication
design spent Package 2B.2B refusing to publish. Both cases are in the bucket
right now, put there by the 2026-09-07 proofs:

* `rel-g1-9f1ed344…` — **promotion refused** (`coverage_regression`). Its
  objects were written, correctly: publishing is safe and idempotent, and only
  promotion has a gate. Serving it would publish data the system declined.
* `rel-g1-5ffad23a…` — **rolled back away from**. It was live at `sequence 2`
  and is not live now. Serving it would contradict the live release.

"Published" and "live" are different states. Only the second is public, and the
pointer is what distinguishes them.

## 2. The route

    /data/green/current.json            → pointers/green/current.json
    /data/green/release.json            → releases/<live>/release.json
    /data/green/ledger.json             → releases/<live>/ledger.json
    /data/green/<declared path>         → releases/<live>/<declared path>

`GET` and `HEAD` only; every other method is refused before anything is
resolved.

### The key is never built from the request

The path after the mount is looked up in an **allowlist built from the live
release's own manifest** — `objects[].path` — and the key is then
`release_prefix + that declared path`. A URL cannot address `runs/`, a probe
prefix, or another release, because those strings never enter a key. The only
strings that do are the ones the live manifest declares.

That is why every miss returns one code, `not_declared_by_the_live_release`:
`../../etc/passwd`, `runs/proof-a/run.json` and a simple typo are the same kind
of miss. A denylist would have to imagine the first two and would still be a
denylist.

### Why `/data/green/` and not `/data/`

The site already serves `/data/alerts/manifest.json`, `/data/territorio/…` and
`/data/educacao/…` as static assets from its build. A mount at `/data/` would
shadow them and switch every consumer the moment it deployed — the opposite of
the Package 2B.3 bullet *copy and verify before switching consumers; retain the
old paths for rollback*. The green namespace is additive; moving consumers onto
it is a later, deliberate step, and renaming it is Phase 6's.

## 3. Headers, and the ones deliberately absent

| Header | Value | Why |
| --- | --- | --- |
| `Content-Type` | the manifest's `content_type`, validated | declared by the producer, never sniffed |
| `Cache-Control` (pointer) | `no-store` | see below |
| `Cache-Control` (everything else) | `public, max-age=60, must-revalidate` | see below |
| `ETag` | `"<the manifest's sha256>"` | a checksum a consumer can compute |
| `X-Araripe-Sha256` | the declared sha256 | the same value, unquoted, for verification |
| `X-Araripe-Release-Id` | the live release id | which release answered |
| `X-Content-Type-Options` | `nosniff` | the type is declared; a browser's guess must not win |
| `Content-Disposition` | `attachment; filename="…"` when `?download=1` | filename from the *declared* path |
| `Access-Control-Allow-Origin` | **absent** | see below |

### The pointer is never cached

It is the only mutable object in the layout, so a cached copy is precisely how
a rollback fails to take effect: the release it names is still complete and
still served, and the consumer keeps following the superseded one. `no-store`
rather than `no-cache` because the document is ~1.5 KiB and there is no
revalidation saving worth the ambiguity.

### Everything else revalidates within a minute

A product's URL is stable while its bytes are not, because it resolves
*through* the pointer. Sixty seconds plus mandatory revalidation bounds how
long a consumer may serve a superseded release after a promotion or rollback,
and the ETag makes each revalidation a `304`.

An immutable, release-addressed namespace would allow a year of caching, and it
is **deliberately not offered**: it would make every non-live release publicly
addressable, which is the one thing §1 exists to prevent.

### No cross-origin permission, because there is no cross origin

This is the point of a same-origin route. Measured against the blue path on
2026-09-07 — `https://pub-5eb389cffff54421916187be69dd659b.r2.dev/site-full/run-2026-08-30.geojson`:

    GET with Origin  → 200, Access-Control-Allow-Origin:
                            https://observatoriodachapadadoararipe.com
                            Vary: Origin
    OPTIONS preflight→ 204, Access-Control-Allow-Methods: GET
    HEAD             → 200, and NO Access-Control-Allow-Origin
                            (the allowed-method list is GET only)
    Content-Length   → 14 429 260 bytes
    Cache-Control    → absent
    ETag             → "82d98a0bca9f8a9669fba81d824c79db-2"

So today a browser fetches 13.8 MiB cross-origin, under a bucket CORS policy
naming the final domain, with no cache directive at all. Emitting
`Access-Control-Allow-Origin: *` from the green route would rebuild that
surface *wider* than it started. A cross-origin consumer is a decision, not a
default.

That measured ETag is also the contract's own §7 point observed in production:
the `-2` suffix is a multipart ETag, the MD5 of the part MD5s. It is not
comparable to a `sha256`, which is why this route serves the manifest's
checksum as the validator instead of passing the store's token through.

### `content_type` is the one field the producer does not promise

`green-release-v1.schema.json` constrains `path` with a strict `logical_path`
pattern and `sha256` with a hex pattern, and leaves `content_type` as
`{"type": "string", "minLength": 1}`. A value carrying CR or LF would split the
response, so it is validated as a media type here rather than trusted.

This is `LEDGER_CONTRACT_BINDING_V1.md` §5 read in the other direction: never
*assert* an invariant the producer does not promise, and never *rely* on one
either.

## 4. Deliberate non-requirements

1. **No claim that the bucket is private.** The boundary is the route. If
   managed public access were ever enabled on `araripe-v2-staging`, everything
   in it would be reachable regardless of this document — which is why the
   audit in `cloudflare_green_control.py` asserts the Worker's isolation
   fail-closed and why enabling public access is not an operation the broker
   has.
2. **No claim about the site's existing `/data/…` assets.** They are the blue
   path and stay exactly as they are until a consumer is deliberately switched.
3. **No range, no compression, no conditional-request semantics are specified.**
   They are the Worker's to implement from the platform's defaults; nothing in
   the boundary depends on them.
4. **The ledger is public, and that is a decision.** It carries acquisition
   ids, timestamps, statuses and checksums — no credential, no endpoint, no
   personal data — and without it a consumer cannot check the manifest's claims
   at all. Verifiability is the reason; if the ledger ever carried something
   that should not leave, this is the line to revisit.

## 5. What this package could not validate, and why

The roadmap bullet says *prepare and validate a same-origin `/data/...` route
**against the isolated staging Worker***. The preparation is here. **The live
validation could not be run**, and the reason is a property of the isolation
itself:

`observatorio-chapada-v2-staging` exists and already carries the right binding
— `STAGING_BUCKET` → `araripe-v2-staging`, plus `STAGING_LIMITER`. But its
`public_subdomain_enabled` is `false`, it has no custom domain and no zone
route, and `scripts/cloudflare_green_control.py::audit` **asserts all three
fail-closed**. There is no hostname at which it can be reached, and giving it
one is a control-plane mutation that:

* is not among the broker's three allowlisted operations (`audit`,
  `enforce-worker-isolation`, `disable-site-branch-deploy`); and
* would make the broker's own audit fail, because `enforce-worker-isolation`
  exists precisely to turn that subdomain back off.

So the route is pinned by vectors instead, and the live check is named as a
blocked capability in
[`GREEN_RETENTION_AND_MIGRATION.md`](../../operations/GREEN_RETENTION_AND_MIGRATION.md)
§5 rather than silently skipped.

**Nothing about the Worker's R2 binding narrows this.** Measured against
Cloudflare's documentation: an `r2_buckets` binding takes `binding`,
`bucket_name` and `jurisdiction`, and "an R2 bucket is able to READ, LIST,
WRITE, and DELETE objects". There is no read-only binding and no prefix
binding. The Worker's *code* is the entire boundary, which is why that code's
policy lives here and is pinned by vectors rather than left to the Worker.

## 6. Scope boundary — where 2B.3 stops

* **The Worker itself is Package 2B.4.** The site repository is not touched by
  this package. Note that the site's `main` branch deploys the **production**
  Worker `observatorio-chapada` through its Worker Builds production trigger,
  so adding a route to `worker/index.js` is a production deployment, not a
  staging one.
* **The final-domain route is Phase 6**, and nothing here attaches or switches
  it.
* **The blue public path stays live and untouched.** Turning it off is
  rehearsed, not executed — `GREEN_RETENTION_AND_MIGRATION.md` §4.
