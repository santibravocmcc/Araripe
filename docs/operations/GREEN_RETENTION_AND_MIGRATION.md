# Green retention, migration order, and the rehearsal that is not executed

**Written:** 2026-09-07, Package 2B.3
**Bucket:** `araripe-v2-staging`
**Objects deleted so far, in the history of this project:** none

This document covers the three Package 2B.3 bullets that are procedure rather
than code: *copy and verify before switching consumers; retain the old paths
for rollback; do not delete during initial migration*; *define conservative
lifecycle and rollback retention, in reviewed dry-run form first*; and *prepare
and rehearse disabling the blue public internal-bucket path, but do not execute
it before the Phase 6 cutover*.

---

## 1. Deletion is a capability, and this package does not add it

Nothing has ever been deleted here, and not by policy: `ConditionalStore`
exposes one read and two conditional writes, and has no delete and no
unconditional put. Staleness is recorded as a tombstone on the pointer rather
than acted on (`GREEN_RELEASE_CONTRACT_V1.md` §8).

**That is still true after this package.** `src/publication/retention.py`
produces a *plan*; no code path in this repository can carry one out, and
`tests/test_retention.py::test_no_deletion_is_expressible_from_the_retention_path`
reads that from the files rather than promising it in prose.

The reason to keep it that way for now is measured, not cautious by habit. R2
has no permission level between read and write, and
`scripts/probe_readonly_identity.py --expect read-write` confirmed on
2026-09-07 that the bucket-scoped staging key **holds DELETE**
(`GREEN_LEAST_PRIVILEGE_IDENTITIES.md` §1). The credential cannot be the
boundary, so the code has to be — and a boundary made of an absent operation is
the strongest kind available.

The migration this policy would support has also not happened: no consumer
reads the green route yet, because there is no route yet (§5). The roadmap's
own sequencing — *do not delete during initial migration* — therefore points at
the same answer.

## 2. The policy

Three dispositions, and the middle one is the point.

| Disposition | Meaning |
| --- | --- |
| `retain` | a positive rule keeps the object |
| `review` | the store does not contain what a decision would need; kept, and the plan says what is missing |
| `eligible` | a positive rule permits removal, and its horizon has passed |

A two-way policy would have to answer every question, so it would answer some
of them by assumption. `review` is what makes "we cannot tell" a first-class
outcome instead of a silent `eligible`.

| Class | Rule |
| --- | --- |
| `pointers/green/current.json` | `retain`, always |
| the live release | `retain` |
| a release named in `supersedes` / `rolled_back_from` | `retain` — the immediate rollback context |
| any other release | **`review`** — see §3 |
| a run prefix whose release cannot be resolved | `review` |
| a run prefix whose release is not published-and-complete | `retain` — it is the only copy |
| a run prefix inside the horizon (30 days) | `retain` |
| a ripe run prefix | `review`, until the loss of `run.json` is accepted by name |
| a verification artifact while Phases 2B–5 are open | `retain` — it is a proof's evidence |
| a verification artifact after the phase closes, past 180 days | `eligible` |
| anything else | **`review`** — the policy fails closed on an unclassified prefix |

**No release is ever `eligible`, at any age, with every option turned on.**
That is a property test, not a coincidence
(`test_no_release_is_ever_eligible_at_any_age`).

### Why a ripe run prefix still needs a named decision

A published release holds the ledger and the objects it published — it never
holds `run.json`, the operator's declared inputs. And
`GREEN_RELEASE_CONTRACT_V1.md` §4 non-requirement 2 says a release is *not*
obliged to publish every sealed artifact, so "the release exists and is
complete" does not mean "everything in the run prefix survives elsewhere". The
planner therefore states what would be lost and requires
`--accept-run-manifest-loss` rather than deciding it by default.

### The link a run prefix has to its release is recomputed, never read

Nothing in the store records it: a release manifest carries the *ledger's*
`run_manifest_id`, not the `runs/<run-id>/` prefix it was read from. The edge
is derivable because the release identity is a pure function of the ledger
(`GREEN_RELEASE_CONTRACT_V1.md` §2), and the planner derives it by running the
same Package 2B.2A gate the publication runs — so a ledger that would be
rejected yields no link at all, and the prefix stays in `review`.

## 3. The finding that decides release retention: there is no promotion history

`pointers/green/current.json` is **one mutable object**, overwritten on every
move. It carries the live release plus a single step of context. Read from the
real bucket on 2026-09-07 at `sequence 3`:

| field | value |
| --- | --- |
| `release_id` | `rel-g1-ae3f6e1d…` (live) |
| `supersedes` | `rel-g1-5ffad23a…`, sequence 2 |
| `rolled_back_from` | `rel-g1-5ffad23a…`, sequence 2 |
| — | `rel-g1-9f1ed344…` appears **nowhere** |

So today the two cases the roadmap distinguishes are distinguishable: one
release **was live and was rolled back from**, the other **was never promoted**
because its promotion was refused for coverage regression.

**One more pointer write and they are not.** The next promotion overwrites the
pointer; `rel-g1-5ffad23a…` drops out of it and becomes indistinguishable from
a release that was never live. Since a release that was once live is the
natural target of a future rollback, "delete every release the pointer does not
reference" would delete precisely the one an operator would ask for back.

`tests/test_retention.py::test_a_release_that_was_live_becomes_undecidable_after_one_more_move`
is that fact as an executable test.

### The prerequisite, specified and deliberately not built

Making release retention decidable needs a **durable, write-once promotion
history** — one immutable object per pointer write, e.g.
`pointers/green/history/<sequence>.json`, carrying what the pointer carried at
that sequence. It is additive, it fits the layout, and it is the natural place
for the answer.

It is **not built by this package**, for a specific reason: it would add a
write to `atomic_publish.promote` and `rollback`, and that path was proven end
to end against real R2 five times on 2026-09-07. Changing it means those proofs
no longer cover the code that runs. Building it, re-proving it, and only then
extending the policy is the right order, and it is a package of its own.

Until it exists, no release is deletable. That is the correct answer, not a
gap.

## 4. The reviewed dry-run of 2026-09-07

    R2_STAGING_BUCKET=araripe-v2-staging \
    R2_ENDPOINT_URL=https://9416750169311ee4afc18a8ff3c771d4.r2.cloudflarestorage.com \
    python scripts/plan_retention.py --as-of 2026-09-07T23:00:00Z

Read-only, with the candidate identity. Result over the real 29 objects:

    retain     26
    review      3   (kept; the store cannot decide)
    eligible    0   (0 byte(s))

    by reason:
         6  phase_evidence_retained
         1  pointer_is_the_layout
         3  promotion_history_not_recorded
         4  release_is_live
         4  release_is_referenced
        11  within_run_horizon

The three `review` objects are exactly `rel-g1-9f1ed344…` — the refused
release. The four `release_is_referenced` objects are exactly
`rel-g1-5ffad23a…` — the rolled-back-from one. **Both are kept, and the plan
gives different reasons**, which is what the roadmap asked the policy to
distinguish.

**Nothing is eligible, and that is the correct answer today.** A dry-run whose
first output proposed deleting something would be the surprising result, not
this one.

## 5. Migration order — copy, verify, switch, keep the old path

The green route is **additive** and shares no path with anything a consumer
reads today. That is the whole of "do not delete during initial migration": the
old path is not modified, so rollback is doing nothing.

| Step | State | Who |
| --- | --- | --- |
| 1 | green objects published to `araripe-v2-staging` | done (2026-09-07 proofs) |
| 2 | delivery boundary and route policy fixed, with vectors | **done, this package** |
| 3 | Worker route implemented against the vectors | Package 2B.4 |
| 4 | staging Worker reachable, route verified live | **blocked — see below** |
| 5 | site consumer switched from `pub-…r2.dev` to the same-origin route | Package 2B.4 / Phase 6 |
| 6 | blue public path disabled | **Phase 6 only** |

### Step 4 is blocked, and the blocker is the isolation working

`observatorio-chapada-v2-staging` exists with the right binding, but
`public_subdomain_enabled` is `false`, `custom_domain_count` is `0` and
`route_count` is `0` — and `scripts/cloudflare_green_control.py::audit` asserts
all three fail-closed. There is no hostname to test against.

Giving it one is a control-plane mutation that is **not** among the broker's
three allowlisted operations (`audit`, `enforce-worker-isolation`,
`disable-site-branch-deploy`), and `enforce-worker-isolation` exists precisely
to turn that subdomain back off. Per the Package 2B.0 handoff rule the correct
action is to stop and name the capability rather than substitute `curl`,
Wrangler, another workflow or a broader credential.

**Named capability:** a reachable hostname for
`observatorio-chapada-v2-staging` — a `workers.dev` subdomain, or a zone route
on a non-final hostname — held open only for the duration of the verification,
with the audit's assertions updated to match while it is open and
`enforce-worker-isolation` run to close it afterwards. That is a broker change
plus a reviewed mutation, and by the rules it must not be authored and
dispatched in the same task.

Once a hostname exists, the live checks are exactly the conformance vectors
plus these, which only a browser and a network can answer:

* `Content-Length` and `sha256` of a served product match its manifest entry;
* `Cache-Control` on the pointer is `no-store` and a rollback is visible to a
  reloaded page within one minute;
* no `Access-Control-Allow-Origin` appears on any response, and a same-origin
  `fetch()` therefore needs no preflight;
* the full-alert browser mode renders from the green route with the filters
  that today pull ~13.8 MiB cross-origin;
* `?download=1` produces a file named from the declared path.

## 6. The rehearsal: disabling the blue public path — NOT executed

The blue public path is R2 managed public access on **`araripe-cogs`**, serving
`https://pub-5eb389cffff54421916187be69dd659b.r2.dev/site-full/…`. It is live;
measured 2026-09-07 (§3 of `GREEN_DELIVERY_BOUNDARY_V1.md`).

Its only consumer is `site/src/js/alertas.js`, which holds the base URL in
`R2_ALERTS_BASE` and uses it for the `full` variant — every candidate alert, as
opposed to the `strong` subset that ships in the site build. The file's own
comment says why: the full files exceed the Cloudflare assets limit.

### The order that matters, and the outage it prevents

Disabling public access **before** the consumer is switched blanks the
full-alert view: `alertas.js` falls back to "visão completa indisponível (só
forte)" and every filter that relaxes past the strong subset returns nothing.
So the order is not a preference:

1. green route live and verified (§5 steps 3–4);
2. `R2_ALERTS_BASE` switched to the same-origin path, deployed, verified in a
   browser;
3. **only then** disable managed public access on `araripe-cogs`;
4. verify the site again — the full view must still work, now same-origin.

### The operation, and who may run it

Disabling managed public access on `araripe-cogs` is a **production**
control-plane mutation. It is not in the broker, it must not be added to the
broker (the broker's stated design is "production operations do not exist in
this file"), and it is a **Phase 6** action under explicit human approval.

**Rollback:** re-enable managed public access on `araripe-cogs`. The
`pub-<id>.r2.dev` hostname is derived from the bucket, so the same URL returns;
`alertas.js` needs no change to recover. Capture the exact hostname before
disabling, from the dashboard, and record it in the Phase 6 cutover document.

**What must be true before it is executed**, and each is checkable:

* no request to the blue public path originates from the site — verifiable by
  grepping the deployed bundle for `r2.dev`;
* the green route serves every file the manifest lists as `file` for every run
  the site offers;
* a rollback of the pointer is visible in the browser within the cache window;
* the `strong` subset still ships in the build, so a total failure of the green
  route degrades to today's default view rather than to nothing.

**Nothing in this package performs step 3, or any part of the rehearsal against
a live resource.** The only production contact made while writing this document
was three unauthenticated HTTP reads of already-public URLs, recorded in
`GREEN_DELIVERY_BOUNDARY_V1.md` §3.
