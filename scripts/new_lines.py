"""
List spending lines that are new since the last published data, with the category
each was given, so a person can catch any that were sorted wrong.

Prints Markdown, or nothing when there are no new lines.

Usage: python3 -I scripts/new_lines.py OLD_LEDGER.csv NEW_LEDGER.csv
"""

import csv
import sys
from collections import Counter

KEY = ("fiscal_year", "district", "commissioner", "fund", "line_type", "description", "amount")
SPENDING = {"payment", "committed", "commitment_paid"}

LABELS = {
    "gift": "Gift",
    "travel_office": "Travel and office",
    "community_purchase": "Purchase for others",
    "transfer": "Transfer",
}


def load(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def main(old_path, new_path):
    old = Counter(tuple(r[k] for k in KEY) for r in load(old_path))
    fresh = []
    for r in load(new_path):
        key = tuple(r[k] for k in KEY)
        if old[key] > 0:
            old[key] -= 1
        elif r["line_type"] in SPENDING:
            fresh.append(r)

    if not fresh:
        return

    print(f"## {len(fresh)} new spending {'line' if len(fresh) == 1 else 'lines'}\n")
    print("Check the category. Fix a wrong one by adding a pattern to `scripts/category_overrides.csv`.\n")
    print("| FY | District | Commissioner | Line | Amount | Category |")
    print("|---|---|---|---|---:|---|")
    for r in fresh:
        line = r["description"].replace("|", "/")
        amount = -float(r["amount"])
        print(f"| {r['fiscal_year']} | {r['district']} | {r['commissioner']} | {line} | "
              f"${amount:,.2f} | {LABELS.get(r['category'], r['category'])} |")


if __name__ == "__main__":
    main(*sys.argv[1:3])
