"""
Download commission resolutions and committee discussions that may spend a district's
discretionary money, from the county's resolution search.

Writes  data/resolutions.csv   one row per search result

Usage: python3 -I scripts/fetch_resolutions.py [first_date]   (default 2015-01-01)
"""

import csv
import html
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "resolutions.csv"
SEARCH = "http://resolutions.hamiltontn.gov/ResolutionSearch/ResolutionSearch.aspx"
# The search matches keywords, so one term misses resolutions worded another way.
SUBJECTS = ["DISCRETIONARY", "APPROPRIATION", "EXPENSE FUND"]
COLUMNS = ["date", "index_no", "resolution_no", "kind", "action", "meeting_type", "pdf_url", "text"]

opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
opener.addheaders = [("User-Agent", "Mozilla/5.0 (resolution archive reader)")]


def fetch(data=None):
    body = urllib.parse.urlencode(data).encode() if data else None
    for attempt in range(4):
        try:
            return opener.open(SEARCH, body, timeout=90).read().decode("utf-8", "ignore")
        except OSError:
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))


def form_state(page):
    def val(name):
        m = re.search(r'name="%s"[^>]*value="([^"]*)"' % re.escape(name), page)
        return html.unescape(m.group(1)) if m else ""
    keys = ["__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION",
            "ctl00$MainContent$hdnCurrentPage", "ctl00$MainContent$NoticeVal"]
    return {k: val(k) for k in keys}


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def search(subject, start, end):
    """All results for one subject and date window. The site returns at most 200 per search."""
    page = fetch()
    data = form_state(page)
    data.update({
        "ctl00$MainContent$txtSubject": subject,
        "ctl00$MainContent$ddlAction": "999",
        "ctl00$MainContent$ddlMeetingType": "0",
        "ctl00$MainContent$txtFromDate": start.strftime("%m/%d/%Y"),
        # The site leaves out the "to" date itself, so search through the day after.
        "ctl00$MainContent$txtToDate": (end + timedelta(days=1)).strftime("%m/%d/%Y"),
        "ctl00$MainContent$btnSubject": "Search",
    })
    out = fetch(data)
    total = re.search(r"of (\d+) results found", clean(out))
    rows = []
    # Each result starts at its Date label.
    for block in re.split(r'<span id="ctl00_MainContent_dgrResults_ctl\d+_Label14"', out)[1:]:
        text = clean(block)
        m = re.match(r'[^>]*>\s*Date:\s*(\d+)/(\d+)/(\d{4})\s*Action:\s*(.*?)\s*Meeting Type:\s*(.*?)\s*'
                     r'Index Number:\s*(.+?)\s*Links:', text)
        if not m:
            continue
        mo, dy, yr, action, meeting, index = m.groups()
        body = text[m.end():]
        body = re.sub(r"^(Resolution|Minutes|Audio|Discussion|\s)+", "", body)
        body = body.split(" Back To Search")[0].strip()
        pdf = re.search(r'ShowAEPopup\("([^"]+?/\d+-\d+[A-Za-z]?\.pdf)"', block)
        res = re.search(r"RESOLUTION NO\.\s*(\d{3,4}-\d+[A-Z]?)", body)
        rows.append({
            "date": f"{yr}-{int(mo):02d}-{int(dy):02d}",
            "index_no": index.replace(" ", "").lower(),
            "resolution_no": res.group(1) if res else ("" if index.lower().endswith("x") else index.replace(" ", "").upper()),
            "kind": "discussion" if index.lower().endswith("x") else "resolution",
            "action": action,
            "meeting_type": meeting,
            "pdf_url": pdf.group(1) if pdf else "",
            "text": body,
        })
    return rows, int(total.group(1)) if total else 0


def search_all(subject, start, end):
    """Like search, but splits the date range until each part fits under the site's 200-result cap."""
    rows, total = search(subject, start, end)
    if total <= len(rows):
        return rows
    if start == end:
        raise RuntimeError(f"{start} {subject}: {total} results in one day, only {len(rows)} readable")
    mid = start + (end - start) // 2
    return search_all(subject, start, mid) + search_all(subject, mid + timedelta(days=1), end)


def windows(first):
    d = first
    while d <= date.today():
        nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        yield d, nxt - timedelta(days=1)
        d = nxt


def main():
    first = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2015, 1, 1)
    seen, rows = set(), []
    for start, end in windows(first):
        for subject in SUBJECTS:
            for r in search_all(subject, start, end):
                key = (r["date"], r["index_no"])
                if key not in seen:
                    seen.add(key)
                    rows.append(r)
            time.sleep(1)
        print(f"{start:%Y-%m}: {len(rows)} so far", flush=True)

    if first > date(2015, 1, 1) and OUT.exists():
        with OUT.open() as f:
            rows = [r for r in csv.DictReader(f) if r["date"] < first.isoformat()] + rows
    rows.sort(key=lambda r: (r["date"], r["index_no"]))
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"{OUT} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
