# Hamilton County Commissioner Discretionary Spending

Live at https://commission.chattanoogamapped.com

A public dashboard built from the county's yearly commissioner discretionary spending reports and its 2025 audit. Built by Daniel Lambert, [sociomagicka.com](https://sociomagicka.com/).

## How it stays current

A GitHub Actions job runs every morning (`.github/workflows/refresh.yml`).

- It downloads the current and previous fiscal year reports from hamiltontn.gov.
- If no PDF changed, it stops.
- If one changed, it re-reads it, rebuilds `site/data/`, and checks that every fund reconciles. A failed check stops the job before anything is published, and GitHub emails the repo owner.
- When new spending lines appear, it opens an issue listing each one with its category, so a wrong category can be fixed in `scripts/category_overrides.csv`.
- Every version of the PDFs it downloads is kept in `raw/pdf/`, so the git history shows any change the county makes to the current or previous year's report. The "check only" run re-downloads every year.

Run it by hand from the Actions tab. The "check only" option re-reads every PDF and reports any differences without publishing.

## Layout

- `site/` is the page. Its README is written for county IT, Finance and the Finance Committee.
- `scripts/refresh.sh` downloads and re-reads the reports, then rebuilds the data.
- `scripts/parse_reports.py` turns report text into `data/ledger_raw.csv`. It stops if any fund block fails to reconcile.
- `scripts/build_data.py` assigns categories, builds the gift register and matches the audit's resolution numbers.
- `scripts/new_lines.py` lists spending lines that are new since the last publish.

## Preview locally

```bash
cd site && python3 -m http.server 8765
```

Then open http://localhost:8765. Opening `index.html` straight from disk won't load the CSV files.
