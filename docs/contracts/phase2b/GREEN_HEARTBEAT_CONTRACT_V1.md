# Phase 6 — the green automation heartbeat

**Contract version:** `araripe.green.heartbeat/1`
**Recorded:** 2026-10-02
**Production mutation:** none

The release and the pointer answer *what is published*. Nothing answered *when
the automation last tried, and what happened*. That is the third date of
`PACKAGE_P6_PROMPT.md` §4.1.4 and the "status/health output" of §4.1.6, and
`PHASE_6P_2026-10-02.md` §6 measured that no existing field can stand in for
it:

* `promoted_utc` moves only when the pointer moves, and a rollback renews it
  with older data;
* `coverage.last_observed_on` is the last date *looked at*, not the last
  attempt;
* in the case the date exists to show — the system stopped, as blue has been
  since 2026-09-03 — both stand still, and "ran and found no image" reads the
  same as "did not run".

Machine-readable form:
[`schemas/green-heartbeat-v1.schema.json`](schemas/green-heartbeat-v1.schema.json).
The schema owns shape; [`src/publication/heartbeat.py`](../../../src/publication/heartbeat.py)
owns the relations shape cannot express, and the merge.

---

## 1. Where it lives

    status/green/heartbeat.json

One fixed key, under a root of its own — **not** `releases/` (write-once, and a
release must not carry an execution's timestamp: `green_release.py` refuses
publication provenance so the bytes stay reproducible), **not** `runs/`
(write-once per run, and private), and **not** `pointers/` (that root's one
mutable object answers "what is live", and this one must not).

It is the second mutable object in the bucket. It is outside the release
contract: `GREEN_RELEASE_CONTRACT_V1.md` §1 still has exactly one mutable
object, and nothing in a release, a run or the pointer refers to this one.

## 2. Who writes it

The green deposit lane, `.github/workflows/v2_green_deposit_lane.yml`, in a
third job, `heartbeat`, that runs **after** `detect` and `deposit` under
`if: always()` — so a detection that failed, a deposit that failed, a window
with nothing to do and a cancelled run each leave a beat. A *step* with
`if: always()` inside `deposit` would not do it: that job is skipped whenever
the detection fails or finds nothing to deposit, and a skipped job runs no
step.

The job holds the candidate identity (`R2_STAGING_*`, Environment
`v2-staging`) and runs one script, `scripts/write_green_heartbeat.py`, which
imports no `config` module and does not opt into the local AWS profile: only
the lane writes a beat.

Every write is a **compare-and-swap**: `If-None-Match: *` when the object is
absent, `If-Match: <etag>` otherwise. A lost race re-reads and **re-merges**
— it does not resend the same bytes, which is the `put_if_match` rule ("re-read
and re-evaluate") applied to a document whose evaluation is a merge.

## 3. What it says

    {
      "schema": "araripe.green.heartbeat/1",
      "lane": "deposit",
      "latest":       { attempt },
      "last_success": { attempt } | null
    }

    attempt = {
      "outcome":      deposited | nothing_to_do | no_acquisition | failed | cancelled,
      "stage":        detect | deposit | null,
      "finished_utc": "YYYY-MM-DDTHH:MM:SSZ",
      "run_id":       "ci-<github run id>",
      "run_url":      "https://github.com/<owner>/<repo>/actions/runs/<github run id>"
    }

| outcome | meaning | read from |
| --- | --- | --- |
| `deposited` | a run prefix was written and re-validated | `deposit` succeeded |
| `nothing_to_do` | the chain head already covers every date the settle rule allows | `detect` succeeded, `proceed=false` |
| `no_acquisition` | the window was enumerated and held no image | `detect` succeeded, `deposit=false` |
| `failed` | the attempt did not complete; `stage` names the job | a job failed, or any combination not listed here |
| `cancelled` | the run was cancelled; `stage` names the job | a job was cancelled |

The first three are **successes**: the automation ran and did what the
situation allowed. `stage` is non-null exactly for the last two.

`latest` is the most recently finished attempt. `last_success` is the most
recently finished successful one, **carried forward** across failures — the
distinction `site/scripts/freshness.py` draws between `updated_utc` and
`checked_utc`, and the one that makes "quiet" different from "broken".

`finished_utc` is the heartbeat job's own clock when it records the attempt.

### The merge, and why it is commutative

    latest       = the attempt with the greatest (finished_utc, run number)
    last_success = the same, over successful attempts only

over the current document's two attempts and the new one. Both are maxima, so
the result does not depend on which writer wins a race: two lanes finishing in
either order converge on the same document. That is what makes "re-read and
re-merge" correct here, where the pointer must instead refuse and re-decide.

The producer therefore promises — and `check_heartbeat` enforces on every read
— that `last_success` never finishes after `latest`, and that a successful
`latest` **is** `last_success`.

## 4. What it deliberately does not say

1. **No release.** No `release_id`, no `release_prefix`, no pointer sequence.
   "What is live" has one answer, the pointer, and `SITE_ARTIFACT_CONTRACT_V1.md`
   §8.4 refused a second one once already. A deposited run is not a published
   one: promotion is a different lane with a different identity.
2. **No window and no covered date.** "Attempted 2026-09-28 to 2026-10-01"
   would be read as "data up to 2026-10-01", and a deposit is not a
   publication. The window is one click away, in `run_url` — and, since
   `PHASE_6Y_2026-10-10.md`, written on that run's summary page by the same
   `heartbeat` job, beside the outcome. The summary is a log; this document
   still names no window.
3. **No alert statistic.** The index is the only place a count is shown, and
   its numbers are defined by the release (`SITE_ARTIFACT_CONTRACT_V1.md` §1).
4. **No start time.** The detection runs on another runner, and nothing
   promises its clock agrees with the heartbeat job's; ordering on two clocks
   would assert an invariant nobody guarantees.
5. **No free-text detail.** The outcome and the stage are the classification;
   the log is `run_url`. Free text is how a status document grows into a log.
6. **No run attempt.** `run_id` is `ci-<github.run_id>` as the lane names the
   run prefix (PHASE_6E §4), and a re-run of the workflow writes a later beat
   for the same run.

## 5. How the route serves it

    /data/green/heartbeat.json   → status/green/heartbeat.json

A **fixed name mapped to a fixed key**, exactly as `current.json` is — the
request still never builds a key (`GREEN_DELIVERY_BOUNDARY_V1.md` §2). It is
resolved **before** the pointer and does not need one: the heartbeat must be
readable precisely when nothing has been promoted, or when the pointer cannot
be read.

| | |
| --- | --- |
| methods | `GET`, `HEAD` |
| `Content-Type` | `application/json` |
| `Cache-Control` | `no-store` — mutable, and small |
| absent | `heartbeat_absent` (the Worker answers 503) |
| present but not `araripe.green.heartbeat/1` | `heartbeat_unusable` (500) |
| `/data/green/status/…` | `not_declared_by_the_live_release`, like every other key |

`classify_key` calls `status/green/heartbeat.json` public (`heartbeat`); every
other key under `status/` is unclassified and private. `check_release_layout`
refuses a release that declares a product at `heartbeat.json` (or
`current.json`): the route would answer that name with the heartbeat, and a
product it can never serve is a silent loss.

The conformance vectors are `araripe.green.delivery-vectors/3`: a third and a
fourth fixture (`unpromoted`, `nothing`) and the heartbeat cases.

## 6. What this does not protect

* **The `v2-staging` key writes and deletes the whole bucket**, and after the
  cutover that bucket is the public one. The heartbeat is protected from every
  other holder of that key **only by code** — the same as the pointer is from
  the candidate lanes. The route checks the `schema` field before serving, so
  the URL cannot be made to claim it is something else; it does not
  re-validate the document.
* **A heartbeat job that never runs leaves no beat** — a runner that never
  starts, an Environment refused, a workflow removed. Its signal is the beat's
  **age**: with a twice-weekly cadence, a `finished_utc` older than a few days
  says the automation is not running at all. That reading is the consumer's.
* **A beat is not evidence of correctness.** `deposited` says the gate
  accepted the run, not that the science is right.

## 7. Scope

Built in the session of 2026-10-02 (`PHASE_6Q_2026-10-02.md`): schema,
merge, writer, the lane's `heartbeat` job, the delivery-boundary policy and its
vectors. **Not** built here: the page reading it (the next session), and the
Worker serving it — a site pull request, not merged, because the site's `main`
deploys production.
