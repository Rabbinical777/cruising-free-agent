# Cruising checker upgrade — 14 October 2026

This is an upgrade for your existing cruising-free-agent repository, not a new project.
It uses Python's standard library, GitHub Actions and your existing Supabase secrets.
No OpenAI API or paid search API is called. Hosting quotas still apply.

## Install in this order

1. In Supabase SQL Editor, run the complete contents of `02-upgrade.sql`.
   This preserves existing discoveries and review decisions. It adds a restricted
   page-check table and a function callable only by your backend service role.
2. Copy all files from this package into your existing folder, replacing matching files:
   `C:\Users\Rabbinical Kgafela\Downloads\Cruising-Free-Agent (1)\Cruising-Free-Agent`
   Include `.github/workflows/daily.yml`. Keep your existing `.git` folder and `.gitignore`.
3. Open PowerShell in that existing folder, then run these commands one at a time:

```powershell
git add checker.py sources.json test_checker.py test_upgrade.py 02-upgrade.sql START-HERE.md .github/workflows/daily.yml
git commit -m "Monitor bursary page changes and add government sources"
git push origin main
```

4. On GitHub, open Actions → Cruising free daily checker → Run workflow → Run workflow.
   Wait for completion and read the summary. Your existing secrets need no changes.

## What changed

- Existing discovery URLs still deduplicate safely. Review status is never overwritten.
- Six same-host detail pages per directory are checked per run, rotating daily.
  It takes multiple daily runs to revisit all pages; this does not check every listing daily.
- Each successful detail check records a text fingerprint, last-check time, last-change
  time and limited deadline/requirement excerpts in `bursary_page_checks`.
- First checks establish a baseline; they are not counted as changed pages.
- Funza Lushaka and DFFE programme pages are added as two specific government sources.
  These can be saved even if a programme is closed: listings remain pending review.
- The workflow reports new links, detail pages checked, changed pages and failures.
- Robots restrictions, blocked pages and non-HTML documents are not bypassed.
- Checkout uses v7; Ubuntu is pinned to 24.04; each job has an eight-minute limit.

## What this does not claim

This is a rule-based monitor, not a general AI web researcher. It does not guarantee
new bursaries daily. A changed fingerprint can reflect editorial changes, not a new
funding round. Dates and eligibility excerpts need review; no dates are guessed.
PDFs, external-host detail pages and JavaScript-only content need separate support.
Links that disappear from source pages are not automatically marked closed.

Your current app will continue loading discoveries, including new source listings.
The app has NOT been modified by this package: last-check times and evidence are
stored in Supabase but still need frontend integration to appear on cards.
This package does not activate course matching, notifications or applications.

## Inspect results in Supabase

```sql
select d.title, d.source_key, p.last_checked_at, p.last_changed_at,
       p.deadline_evidence, p.requirement_evidence
from public.bursary_page_checks p
join public.bursary_discoveries d on d.url = p.url
order by p.last_checked_at desc;
```

## Troubleshooting

- Database HTTP 404: confirm you ran `02-upgrade.sql` on the same Supabase project.
- Database HTTP 401/403: check the existing GitHub backend secret; never put it in app code.
- Source or robots errors: review the reported source manually. Other sources can still save.
- Zero new saved: discovered URLs already exist. Check detail-page counts separately.
- No page-check rows: read the workflow's individual page error messages.

## Validation

14 offline unit tests cover existing URL safety/deduplication plus evidence extraction,
content-change detection, rotation coverage and excluded external/PDF detail fetches.
Live database writes require your first GitHub run after applying the SQL migration.

## Rollback

Use GitHub to revert the upgrade commit if needed. The extra SQL table/function can
remain: the old checker does not use them. Do not delete existing discoveries.

Live website testing in the build environment did not complete and was stopped.
The first GitHub run must confirm source access and database writes.
