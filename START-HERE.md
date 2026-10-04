# Cruising — free daily bursary checker

This replacement uses no OpenAI API and no paid search API. It checks selected website pages once a day and stores bursary-related links for manual review in Supabase. It is a rule-based website monitor, not an AI researcher.

## What it does

- Checks StudyTrust's bursaries page and CareerWise's homepage.
- Respects robots.txt, fetches only configured pages and limits request sizes/time.
- Finds links whose text or URL mentions bursaries or scholarships.
- Saves new URLs once, with source and discovery date. Repeat runs preserve existing review status.
- Records source failures and warns about empty results.
- Runs on GitHub around 07:17 South African time daily, even when your laptop is off. Scheduled runs can be delayed or missed; inspect run history.

SA Bursaries is configured but disabled because the initial automated request returned HTTP 406. Do not bypass website blocks. Add sources only after checking their terms and automation permissions.

## Limits — please read

These are **unverified links**, which may include general information pages or old bursaries. No funding year, deadlines, eligibility or open status is inferred. The first run is a baseline: a newly saved link does not mean the bursary was newly announced. Existing URLs that change content are not detected as new opportunities. This monitors selected pages, not the whole internet, PDFs or JavaScript-rendered listings.

This package does not implement student alerts, automatic applications, marks matching, weekly emails or deadline reminders. Keep discoveries private until you check the official provider and transfer confirmed details into your app's verified opportunities. Review in Supabase Table Editor; do not expose a backend key to students.

## Step 1 — create the tables

1. Extract this ZIP to a NEW folder. Do not replace your old core.mjs with this package.
2. Open `01-setup.sql` in Notepad and copy all its contents.
3. In Supabase, select your Cruising project → SQL Editor → New query.
4. Paste and click Run. “Success. No rows returned” is expected.

The tables are `bursary_discoveries` and `bursary_free_runs`. They have Row Level Security and no public/student access. Existing app tables are unchanged.

## Step 2 — put the checker in a private GitHub repository

1. Sign in to https://github.com and create a new **private**, empty repository called `cruising-free-agent`. Do not add a README on GitHub yet.
2. Open the extracted `Cruising-Free-Agent` folder. It should contain checker.py, sources.json and START-HERE.md.
3. Click File Explorer's address bar, type `powershell`, press Enter.
4. Run these commands one at a time:

```powershell
git init
git add .
git commit -m "Add free daily bursary checker"
git branch -M main
```

If Git asks for your name/email, configure those locally, then rerun the commit:

```powershell
git config user.name "YOUR NAME"
git config user.email "YOUR GITHUB EMAIL"
```

5. Replace YOUR-USERNAME below with your actual GitHub username:

```powershell
git remote add origin https://github.com/YOUR-USERNAME/cruising-free-agent.git
git push -u origin main
```

Complete browser sign-in if prompted. The `.github/workflows/daily.yml` file must be uploaded too; `git add .` includes it. Never upload secret values, passwords, or your old API key.

## Step 3 — add two GitHub Actions secrets

In the new GitHub repository go to Settings → Secrets and variables → Actions → New repository secret.

Create:

| Name | Value |
| --- | --- |
| SUPABASE_URL | https://ekhptaxrcamkejnfgico.supabase.co |
| SUPABASE_SERVICE_ROLE_KEY | Your project's legacy `service_role` backend API key |

Find the service_role key in Supabase project settings → API Keys → legacy anon/service_role keys. This is NOT the publishable key, database password, OPENAI_API_KEY or CRUISING_AGENT_SECRET. It grants administrative database access: paste it only into the GitHub secret box. Never send it in chat or put it into code. Only trusted administrators should have write access to this repository because workflows can use its secrets.

## Step 4 — keep it within free limits

Use your existing Supabase **Free** organization and GitHub **Free**, with the standard `ubuntu-latest` runner already configured here. This workflow has a five-minute job timeout: 31 scheduled runs budget about 155 runner minutes monthly, plus manual runs. GitHub Free includes 2,000 minutes monthly for private repositories, shared with your other workflows. This package uploads no build artifacts and installs no dependencies.

Before enabling, check GitHub account Settings → Billing and licensing → Budgets and alerts. Set an Actions budget of $0 with **Stop usage when budget limit is reached** enabled where available. Do not enable paid overages or larger runners. Check shared usage periodically. Free-tier limits and platform policies may change; free hosting is not an unlimited-service guarantee. Supabase may pause low-activity Free projects; resume in its dashboard if needed. Monitor database space as records accumulate.

References checked October 4, 2026:
- https://docs.github.com/en/billing/reference/product-usage-included
- https://docs.github.com/en/billing/how-tos/set-up-budgets
- https://supabase.com/pricing
- https://supabase.com/docs/guides/platform/free-project-pausing
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

## Step 5 — test and enable

The schedule becomes active once daily.yml is on the repository's default branch and Actions is enabled.

1. Open GitHub repository → Actions → Cruising free daily checker → Run workflow.
2. Open the run. Both the tests and checker should pass.
3. In Supabase Table Editor, open `bursary_discoveries` to inspect saved links. Open `bursary_free_runs` for check results.
4. Run again if needed: existing links should produce zero new inserts. This is normal.

A warning/failed source makes the workflow fail visibly, while successful sources can still save their links. A database HTTP 401/403 suggests the key/permissions need checking; 404 often means the SQL tables were not created in the configured project. Never paste secrets into logs or support messages.

To stop: GitHub → Actions → this workflow → menu → Disable workflow.

## Stop the old paid agent

This checker does not invoke the old Supabase `bursary-agent` function. Do not continue testing that old function or enable its previous SQL schedule. If you already enabled a Cron job for the old function, disable only that bursary job in Supabase Cron. You may remove OPENAI_API_KEY from Supabase Edge Function secrets if no other function needs it; that makes the old worker refuse paid searches. Existing saved data can stay.

## Optional local test

Python is already installed on the GitHub runner; you do not need to install it on Windows for the hosted setup. With Python 3.11+ locally:

```powershell
python -m unittest -v
python checker.py --dry-run
```

Dry run makes public website requests but needs no database key and writes no data. No Supabase production write has been tested by the package author because your private backend key is not available.
