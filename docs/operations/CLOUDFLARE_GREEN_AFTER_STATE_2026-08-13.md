# Package 2B.0 Cloudflare green after-state (acceptance)

**Recorded:** 2026-08-13

**Account:** `9416750169311ee4afc18a8ff3c771d4`

**Scope:** Read-only acceptance record after the single approved Worker Builds
mutation. It complements — and does not modify — the immutable before-state
`docs/operations/CLOUDFLARE_GREEN_BEFORE_STATE_2026-08-11.md`.

## Approved mutation

- Broker run [31724415945](https://github.com/santibravocmcc/Araripe/actions/runs/31724415945)
  of `.github/workflows/cloudflare_green_control.yml` on `main`
  (`8daa1812f8c2f89d6fa13be44c38283242c103bd`), operation
  `disable-site-branch-deploy`, confirmation `GREEN-ONLY`, explicitly approved
  by the user in chat and again through the protected Environment
  `cloudflare-green-control` (required human reviewer). Conclusion: `success`
  at 2026-08-13T17:12Z.
- Target: Worker Builds trigger `Deploy non-production branches`, UUID
  `0040d17d-10be-4329-bba4-ac614a9d5bef`, on the production script tag
  `43503f539c80410b938e3cdf6a4f2bc7`, repository connection
  `santibravocmcc/observatorio-site`.
- Change: deploy command was `npx wrangler deploy`; it is now `exit 0`. The
  trigger name, branch includes (`*`), branch excludes (`main`), build command
  (`npm run build`), root directory (`/`), and repository connection were
  revalidated before the PATCH and are unchanged. The production `main`
  trigger was not touched by any code path.
- Known rollback: restore `deploy_command` to `npx wrangler deploy` on the
  same trigger (value preserved in the immutable before-state and in the
  2026-08-13 audit output). The broker deliberately has no rollback
  operation; restoration is a Codex/dashboard action under explicit approval.

## Post-mutation audit (embedded in the same run)

```json
{
  "account": "approved-account",
  "custom_domain_count": 0,
  "production_mutated": false,
  "public_subdomain_enabled": false,
  "route_count": 0,
  "schedule_count": 0,
  "site_nonproduction_deploy_command": "exit 0",
  "staging_bucket": "araripe-v2-staging",
  "staging_rate_limit_namespace": "2001",
  "staging_worker": "observatorio-chapada-v2-staging"
}
```

Final-domain ownership by the production Worker and the exact staging Worker
binding set are asserted fail-closed inside the audit; the run succeeding is
the proof they held.

## Production unchanged

- `https://observatoriodachapadadoararipe.com` answered HTTP 200 before and
  after the mutation; the cache-busted homepage content SHA-256
  (`91d7c81278ae02e437c62b3adf834e58f1ec202bf23330c8c99fc62131cf1f6a`) is
  byte-identical in both captures.
- Blue workflows on `main` remain byte-identical
  (`detect_gee.yml` blob `d2a6f9b1b7fa4601ea3ec9fddeecf9b166c63c32`,
  `update_data.yml` blob `20d470840dc04b31842d7596cf12623493f9a06e`); no blue
  run executed between the minimal merge and this record (latest blue run is
  the pre-merge 07:44 UTC scheduled detection).
- `araripe-cogs`, DNS, routes, canonical pointers, releases, and site
  artifacts were not touched.

## Same-day green proofs

- Broker read-only audit:
  [run 31719834876](https://github.com/santibravocmcc/Araripe/actions/runs/31719834876)
  (`success`, pre-mutation state recorded
  `site_nonproduction_deploy_command="npx wrangler deploy"`).
- Candidate lane probe:
  [run 31720230963](https://github.com/santibravocmcc/Araripe/actions/runs/31720230963)
  (`success`): staging list allowed with the `v2-staging` Environment
  identity, `araripe-cogs` denied, one immutable per-run object written and
  read back — `green-isolation-proof/run-31720230963-1/probe.json` (retained;
  nothing deleted).
- Promotion lane serialization:
  [run 31720226492](https://github.com/santibravocmcc/Araripe/actions/runs/31720226492)
  (hold 90 s) and
  [run 31720228888](https://github.com/santibravocmcc/Araripe/actions/runs/31720228888)
  (hold 20 s): the second run stayed `pending/queued` for the entire first
  hold (16:21:27–16:22:45 UTC) and ran only after the first completed.
- Lane distinctness: the candidate run executed and completed concurrently
  with the first promotion hold; the `araripe-green-candidate` and
  `araripe-green-promotion` lanes share no lock, and neither queued a blue
  workflow.

## Effect and follow-up

Pushing a non-`main` branch of the site repository now runs the build but
cannot deploy: non-production deployment is temporarily inert by design. A
safe, reviewed green site deploy path — a separate protected default-branch
workflow whose Worker target and bindings are not controlled by the candidate
branch — remains future Package 2B.4 work. The production `main` trigger and
every production resource remain unchanged.
