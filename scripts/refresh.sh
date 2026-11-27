#!/usr/bin/env bash
# Download the county's yearly reports, re-read any that changed, and rebuild site/data.
#
# By default only the current and previous fiscal years are checked.
# FIRST_FY=2017 checks every year. FORCE=1 re-reads PDFs even when unchanged.

set -euo pipefail
cd "$(dirname "$0")/.."

this_fy=$(( $(date +%Y) + ($(date +%-m) >= 7 ? 1 : 0) ))
first=${FIRST_FY:-$(( this_fy - 1 ))}

mkdir -p raw/pdf raw/txt data

for fy in $(seq "$first" "$this_fy"); do
  pdf="raw/pdf/FY${fy}.pdf"
  tmp="${pdf}.new"

  if ! curl -sfL --retry 3 -o "$tmp" "https://www.hamiltontn.gov/CommissionDSReports/FY${fy}.pdf"; then
    rm -f "$tmp"
    continue
  fi

  # A year the county hasn't posted comes back as a web page, not a 404.
  if [ "$(head -c 4 "$tmp")" != "%PDF" ]; then
    rm -f "$tmp"
    continue
  fi

  if [ -f "$pdf" ] && cmp -s "$tmp" "$pdf" && [ -z "${FORCE:-}" ]; then
    rm -f "$tmp"
    continue
  fi

  mv "$tmp" "$pdf"
  pdftotext -layout "$pdf" "raw/txt/FY${fy}.txt"
  echo "Read FY${fy}"
done

python3 -I scripts/parse_reports.py raw/txt data

# New resolutions from the last year. The saved copy covers earlier ones.
python3 -I scripts/fetch_resolutions.py "$(date -d '-12 months' +%Y-%m-01)" \
  || echo "Resolution search unavailable; using the saved copy"

python3 -I scripts/build_data.py
