# Manual Setup Tasks

Status as of 2026-03-29.

---

## DONE: Hugging Face Space deployed

- HF CLI authenticated as `santibravo`
- Repo uploaded to https://huggingface.co/spaces/santibravo/araripe-monitor
- Space SDK set to Streamlit, building now

---

## Step 1: Authenticate GitHub CLI (2 minutes)

Run in your terminal (not inside Claude Code):

```bash
gh auth login
# Choose: GitHub.com
# Choose: HTTPS
# Choose: Login with a web browser
# Follow the browser flow
```

---

## Step 2: Set GitHub Secrets (3 minutes)

After `gh auth login`, run these commands to add the secrets
that the weekly GitHub Actions workflow needs:

### STAC fallback credentials

```bash
cd /Users/sbravo/Documents/Projetos/Araripe

# Earthdata (NASA HLS fallback)
gh secret set EARTHDATA_USERNAME --body "santiago_bravo"
gh secret set EARTHDATA_PASSWORD  # will prompt for value — paste your password

# Copernicus Data Space (fallback)
gh secret set CDSE_USERNAME --body "santiago.bravo@alumni.usp.br"
gh secret set CDSE_PASSWORD  # will prompt for value — paste your password
```

### Cloudflare R2 credentials (later, after R2 setup)

```bash
gh secret set R2_ENDPOINT_URL  # will prompt — paste your R2 endpoint
gh secret set R2_ACCESS_KEY    # will prompt — paste your R2 access key
gh secret set R2_SECRET_KEY    # will prompt — paste your R2 secret key
```

---

## Step 3: Push latest code to GitHub (1 minute)

```bash
cd /Users/sbravo/Documents/Projetos/Araripe
git add -A
git commit -m "feat: fix detection pipeline, add deployment guides"
git push origin main
```

---

## Step 4: Test the GitHub Actions workflow

After pushing and setting secrets:

1. Go to https://github.com/santibravocmcc/Araripe/actions
2. Click "Weekly Deforestation Detection"
3. Click "Run workflow" > "Run workflow"
4. Wait ~20-30 minutes for completion

---

## Step 5 (Optional): Cloudflare R2 bucket

See DEPLOYMENT_GUIDE.md section 3 for full instructions.
Skip for now — the dashboard uses local data files.

---

## Verification checklist

- [x] `hf auth whoami` shows `santibravo`
- [ ] HF Space loads at huggingface.co/spaces/santibravo/araripe-monitor
- [ ] `gh auth status` shows logged in
- [ ] `gh secret list` shows EARTHDATA_USERNAME, EARTHDATA_PASSWORD, CDSE_USERNAME, CDSE_PASSWORD
- [ ] GitHub Actions "Weekly Deforestation Detection" runs successfully

---

## Security reminder

Rotate these passwords (they were exposed in a chat session):
- Earthdata: https://urs.earthdata.nasa.gov > My Profile > Change Password
- Copernicus: https://dataspace.copernicus.eu > Account Settings
