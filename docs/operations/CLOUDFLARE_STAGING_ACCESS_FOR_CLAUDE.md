# Claude Code access to isolated R2 staging

**Decision date:** 2026-08-11

**Cloudflare account:** `9416750169311ee4afc18a8ff3c771d4`

**Only approved Claude bucket:** `araripe-v2-staging`

## Boundary

Claude Code may read and write objects only in the disposable private bucket
`araripe-v2-staging`. It must not receive a Cloudflare/Workers API token in the
production account.

An R2 S3 credential scoped to one bucket can list, read, write, copy, multipart
upload, and delete objects in that bucket. It cannot configure buckets, CORS,
lifecycle, public domains, Workers, routes, DNS, Builds, bindings, or
credentials. Those control-plane tasks require the connected Cloudflare
capability in Codex and the safe-handoff protocol.

Cloudflare Workers permissions are account-scoped rather than safely limited to
one existing Worker. Giving Claude a production-account Wrangler token would
therefore create an unnecessary path to the production Worker. A separate
Cloudflare account would be required if Claude ever had to own the complete
control plane; that is not needed for this roadmap.

## Current live state

The bucket `araripe-v2-staging` was created on 2026-08-11 as an additive green
resource. Verification immediately after creation showed:

- R2 managed public access disabled;
- no custom domain;
- no CORS policy;
- no object-lock rule;
- only Cloudflare's default seven-day incomplete-multipart cleanup;
- no change to `araripe-cogs`, the production Worker, routes, DNS, Worker
  Builds, the apex domain, or existing GitHub Actions.

This bucket is an object-level development sandbox. It is not a canonical
release bucket, public bucket, or promotion target.

## One-time token creation in Cloudflare

The user must perform this once because the connected capability cannot create
an R2 access-key secret and the one-time secret must not enter an agent
transcript.

1. Open **Cloudflare → Storage & databases → R2 → Overview → API Tokens →
   Manage**.
2. Choose **Create Account API token** when available; otherwise create a User
   API token.
3. Name it `claude-araripe-v2-staging-rw`.
4. Select **Object Read & Write**.
5. Select **Apply to specific buckets only** and choose exactly
   `araripe-v2-staging`.
6. Create it and copy the **Access Key ID** and **Secret Access Key** once.
7. Never paste either value into chat, a repository file, `CLAUDE.md`,
   `AGENTS.md`, or Claude settings.

Do not select Admin Read & Write, all buckets, Workers Scripts, DNS, or Zone
permissions.

## Install and verify the local client

AWS CLI v2.36.20 was installed with Homebrew on this Mac on 2026-08-11. Verify
the client before creating the profile:

```bash
aws --version
```

The output must identify AWS CLI v2. On another workstation, install it first
with `brew install awscli`. Do not continue if `aws --version` fails.
Installing the client does not grant Cloudflare access and does not contain a
credential.

## Store it outside the repositories

Do **not** use a repository `.env`. Configure a named AWS profile:

```bash
aws configure --profile araripe-r2-staging
```

Enter the access-key ID and secret when prompted, use region `auto`, and use
`json` as the output format. The AWS CLI stores the credential in
`/Users/sbravo/.aws/credentials`, outside both repositories.
Protect and verify the resulting file before launching Claude:

```bash
chmod 600 /Users/sbravo/.aws/credentials
stat -f '%Lp %N' /Users/sbravo/.aws/credentials
```

The output must start with `600`. Do not print the file itself.

Launch Claude Code from the backend repository with only non-secret settings
in the shell:

```bash
export AWS_PROFILE=araripe-r2-staging
export AWS_REGION=auto
export AWS_ENDPOINT_URL=https://9416750169311ee4afc18a8ff3c771d4.r2.cloudflarestorage.com
export R2_STAGING_BUCKET=araripe-v2-staging
claude
```

Do not place `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, or
`CLOUDFLARE_API_TOKEN` in a repository file. Claude documentation warns that a
secret read by a tool or printed by a command is retained in plaintext session
history.

The following entries were merged into the existing local
`.claude/settings.local.json` on 2026-08-11 without changing its allow rules.
Repeat this merge in a new workstation or checkout:

```json
{
  "permissions": {
    "deny": [
      "Read(//Users/sbravo/.aws/credentials)",
      "Read(//Users/sbravo/.config/observatorio/**)",
      "Read(./.env)",
      "Read(./.env.*)"
    ]
  }
}
```

These rules reduce accidental reads but are not the security boundary: Claude
Bash can still invoke other programs, so the dedicated disposable bucket and
bucket-scoped token are the actual boundary.

## Acceptance test

Run the following without printing credentials:

```bash
aws s3 ls s3://araripe-v2-staging \
  --profile araripe-r2-staging \
  --endpoint-url https://9416750169311ee4afc18a8ff3c771d4.r2.cloudflarestorage.com
```

The same command against `s3://araripe-cogs` must fail with access denied.
Then perform one put/get/delete smoke test only under a unique
`credential-smoke-test/<uuid>/` key. Delete permission exists within this
staging bucket, so application code must still use immutable run prefixes and
must never treat this identity as a promotion credential.

## GitHub is a separate identity

Do not reuse Claude's credential in Actions. Package 2B.0 will create a GitHub
Environment named `v2-staging` with a separate bucket-scoped identity:

- secrets: `R2_STAGING_ACCESS_KEY_ID`, `R2_STAGING_SECRET_ACCESS_KEY`;
- variables: `R2_STAGING_BUCKET=araripe-v2-staging`,
  `R2_ENDPOINT_URL`, and `AWS_REGION=auto`.

Map the secrets to standard AWS variable names only on the exact object step.
Do not add `CLOUDFLARE_API_TOKEN` to this environment. Promotion will use a
different protected identity after the publication contract is implemented.

## Revocation

Revoke `claude-araripe-v2-staging-rw` when isolated Phase 2B development ends,
if the credential may have been displayed, or before repurposing the bucket.
Never expand its scope; create a new role for a new purpose.

## Primary references

- Cloudflare R2 tokens: <https://developers.cloudflare.com/r2/api/tokens/>
- R2 S3 authentication: <https://developers.cloudflare.com/r2/get-started/s3/>
- Temporary R2 credentials: <https://developers.cloudflare.com/r2/api/s3/temporary-credentials/>
- Wrangler environment variables: <https://developers.cloudflare.com/workers/wrangler/system-environment-variables/>
- Claude Code settings: <https://code.claude.com/docs/en/settings>
- Claude Code permissions: <https://code.claude.com/docs/en/permissions>
- Claude Code directory and local data: <https://code.claude.com/docs/en/claude-directory>
