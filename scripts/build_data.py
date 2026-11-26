"""
Build the dashboard's data files from the parsed ledger.

Reads   data/ledger_raw.csv, raw/txt/audit_FY2022-FY2024.txt, scripts/category_overrides.csv
Writes  site/data/ledger.csv    every report line, with category and gift_id
        site/data/gifts.csv     one row per gift: the register the policy would require
        site/data/reports.csv   one row per fiscal-year report

Usage: python3 -I scripts/build_data.py
"""

import csv
import re
from difflib import SequenceMatcher
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "site" / "data"

# Travel, conferences, office costs and the commissioner's own meals.
TRAVEL_OFFICE = re.compile(
    r"\b(mileage|travel (advance|reimbursement)|hotel|inn\b|lodge|suites|marriott|hilton|doubletree"
    r"|sheraton|sheridan|hyatt|embassy|hampton|westin|fairmont|reissued|duplicate charge|overage|airlines?|delta|southwest|flight|air travel|uber|lyft"
    r"|parking|valet|naco|tcsa|tennessee county services|county commissioners association|nobco|ctas|ccfo"
    r"|conference|seminar|registration|orientation|government day|legislative|rent\b|ipad|iphone|ear ?pods"
    r"|verizon|xfinity|comcast|at&t|epb|internet|cell|phone|business cards?|letterhead|note ?cards?|envelopes"
    r"|diversified companies|usps|stamps|postage|office (supplies|expense)|staples|office depot|ink\b"
    r"|printer|binder|folders|totes|paypal|subscription|imazing|dues|membership|legal (notice|ad)"
    r"|times free press|newspaper|printing|meals?\b|district issues|school issues|constituent|amazon"
    r"|best buy|apple)", re.I)

# Stores and restaurants. Buying from one is a purchase, never a gift.
VENDOR = re.compile(
    r"\b(chick.?fil.?a|jack'?s|champy|mcalister|wal.?mart|publix|sam'?s club|kroger|food city|pizza"
    r"|bojangles|cookout|cracker barrel|jimmy johns?|jason'?s deli|deli\b|boathouse|hobby lobby|holbby lobby"
    r"|grill|restaurant|cafe|bbq|diner|bistro|coffee|bakery|trophy shop|el metate|scotties"
    r"|rembrandt|sweet basil|thai smiles"
    r"|walgreens|big lots|lunch\b|breakfast\b)", re.I)

# A purchase made for a school, staff or event, rather than for the commissioner.
FOR_OTHERS = re.compile(
    r"\b(for\b|teachers?|students?|staff|appreciation|school|elementary|middle|high|team|event|ceremony"
    r"|senior|program|recognition|department|maintenance|dispatcher|memorial|faculty|dvds)", re.I)


def norm(s):
    s = s.lower().replace("&", "and").replace(".", "")
    s = re.sub(r"\b(inc|incorporated|the|dba|llc|corp|foundation)\b\.?", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def load_overrides():
    path = ROOT / "scripts" / "category_overrides.csv"
    if not path.exists():
        return []
    with path.open() as f:
        return [(re.compile(r["pattern"], re.I), r["category"]) for r in csv.DictReader(f)]


def categorize(row, overrides):
    if row["line_type"] == "transfer":
        return "transfer"
    if row["line_type"] not in ("payment", "committed"):
        return ""
    text = f"{row['payee']} {row['purpose']} {row['description']}"
    # Bare month lines are the monthly mileage, meals and office allowance.
    if re.fullmatch(r"(January|February|March|April|May|June|July|August|September|October"
                    r"|November|December) \d{4}", row["description"].strip(), re.I):
        return "travel_office"
    for rx, cat in overrides:
        if rx.search(text):
            return cat
    if VENDOR.search(row["payee"]) or VENDOR.match(row["description"]):
        return "community_purchase" if FOR_OTHERS.search(row["purpose"] or row["description"]) else "travel_office"
    if TRAVEL_OFFICE.search(text):
        return "travel_office"
    return "gift"


def parse_audit_exhibit():
    """Exhibit I of the 2025 audit: gifts in FY2023-FY2024 with resolution numbers."""
    path = ROOT / "raw" / "txt" / "audit_FY2022-FY2024.txt"
    out = []
    tail = re.compile(r"(\d\d/\d\d/\d\d)\s+(\d{3,4}-\d+[A-Z]?)\s+([\d,]+)\s*$")
    for line in path.read_text(errors="ignore").splitlines():
        m = tail.search(line)
        if not m:
            continue
        cols = re.split(r"\s{2,}", line[:m.start()].strip())
        if len(cols) < 2:
            continue
        mm, dd, yy = m.group(1).split("/")
        year = 2000 + int(yy)
        out.append({
            "org": cols[0], "purpose": " ".join(cols[1:]),
            "date": f"{year}-{mm}-{dd}", "fy": year + 1 if int(mm) >= 7 else year,
            "res": m.group(2), "amount": float(m.group(3).replace(",", "")), "used": False,
        })
    return out


def match_audit(gift, exhibit):
    """Same organization and amount, approved in the payment's fiscal year or the one before."""
    g = norm(gift["recipient"])
    for e in exhibit:
        if e["used"] or abs(e["amount"] - gift["_out"]) > 1:
            continue
        if gift["fiscal_year"] not in (e["fy"], e["fy"] + 1):
            continue
        o = norm(e["org"])
        close = SequenceMatcher(None, o, g).ratio() > 0.9
        if o and g and (o in g or g in o or o.split()[:2] == g.split()[:2] or close):
            e["used"] = True
            return e
    return None


GIFT_COLUMNS = [
    # Set when the commission approves the gift
    "gift_id", "fiscal_year", "district", "commissioner",
    "recipient", "recipient_ein", "recipient_address", "recipient_in_district",
    "project", "amount_approved", "resolution_no", "resolution_date",
    "goal", "report_due",
    # Filled in after the money goes out
    "report_received", "evidence_url", "outcome", "verified_by", "verified_date",
    "notes", "record_source",
]


def main():
    overrides = load_overrides()
    with (DATA / "ledger_raw.csv").open() as f:
        ledger = list(csv.DictReader(f))

    for r in ledger:
        r["category"] = categorize(r, overrides)
        r["gift_id"] = ""

    # One gift per approval. A gift can span several ledger lines when it is split
    # across funds, committed one year and paid the next, or voided.
    gifts, seq = [], defaultdict(int)
    by_payee = defaultdict(list)
    for r in ledger:
        if r["category"] != "gift":
            continue
        amt = float(r["amount"])
        fy, d = int(r["fiscal_year"]), int(r["district"])
        who, what = norm(r["payee"]), norm(r["purpose"].replace("committed", ""))
        candidates = by_payee[(d, who)]

        if amt > 0:
            match = next((g for g in candidates if g["_fy"] == fy and abs(g["_out"] - amt) < 0.01), None)
            if match:
                r["gift_id"] = match["gift_id"]
                match["_out"] -= amt
                match["_voided"] = match["_out"] < 0.01
            # An unmatched credit reverses a gift from an earlier year; it stays a gift.
            continue

        split = next((g for g in candidates if g["_fy"] == fy and g["_what"] == what
                      and r["fund"] not in g["_funds"]), None)
        later = next((g for g in candidates if g["_fy"] == fy - 1 and g["_what"] == what
                      and g["_committed"] - g["_paid_later"] >= -amt - 0.01), None)

        if split:
            g = split
            g["_out"] += -amt
            g["_funds"].add(r["fund"])
            if r["line_type"] == "committed":
                g["_committed"] += -amt
            g["amount_approved"] = f"{g['_out']:.2f}"
        elif later and r["line_type"] == "payment":
            # The county counts this money in the year it was committed, not this one.
            g = later
            g["_paid_later"] += -amt
            g["_paid_fy"] = fy
            r["line_type"] = "commitment_paid"
        else:
            seq[(fy, d)] += 1
            g = {c: "" for c in GIFT_COLUMNS}
            g.update({
                "gift_id": f"G{fy}-D{d:02d}-{seq[(fy, d)]:03d}",
                "fiscal_year": fy, "district": d, "commissioner": r["commissioner"],
                "recipient": r["payee"], "project": r["purpose"].replace(" committed", "").strip(),
                "amount_approved": f"{-amt:.2f}",
                "record_source": f"{r['source']} line {r['source_line']}",
                "_fy": fy, "_what": what, "_funds": {r["fund"]}, "_out": -amt, "_voided": False,
                "_committed": -amt if r["line_type"] == "committed" else 0.0,
                "_paid_later": 0.0, "_paid_fy": None,
            })
            gifts.append(g)
            candidates.append(g)
        r["gift_id"] = g["gift_id"]

    for g in gifts:
        if g["_committed"] and g["_paid_fy"]:
            g["notes"] = f"Committed in FY{g['_fy']}, paid in FY{g['_paid_fy']}."
        elif g["_committed"]:
            g["notes"] = "Committed in the county report, not yet paid."
        if len(g["_funds"]) > 1:
            g["notes"] = (g["notes"] + f" Paid from {len(g['_funds'])} funds.").strip()

    exhibit = parse_audit_exhibit()
    matched = 0
    for g in gifts:
        e = match_audit(g, exhibit)
        if not e:
            continue
        matched += 1
        g["resolution_no"] = e["res"]
        g["resolution_date"] = e["date"]
        g["project"] = g["project"] or e["purpose"]
        g["record_source"] += "; 2025 audit Exhibit I"
        if "kingship chess" in norm(g["recipient"]):
            g["outcome"] = "no_report"
            g["notes"] = "2025 county audit: the group did not provide documentation despite several requests."
        else:
            g["notes"] = "Tested in the 2025 county audit (deposit and resolution). Use of funds not verified."

    for g in gifts:
        if g["_voided"]:
            g["outcome"] = "voided"
            g["notes"] = (g["notes"] + " Payment voided in the county report.").strip()
        for k in [k for k in g if k.startswith("_")]:
            g.pop(k)

    cols = ["ledger_id", "fiscal_year", "district", "commissioner", "fund", "line_type", "category",
            "gift_id", "payee", "purpose", "description", "amount", "source", "source_line"]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "reports.csv").write_text((DATA / "reports.csv").read_text())
    with (OUT / "ledger.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(ledger)
    with (OUT / "gifts.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=GIFT_COLUMNS)
        w.writeheader()
        w.writerows(gifts)

    cats = defaultdict(float)
    for r in ledger:
        if r["category"]:
            cats[r["category"]] -= float(r["amount"])
    print(f"{len(ledger)} ledger rows, {len(gifts)} gifts")
    print("net outflow by category:", {k: round(v) for k, v in cats.items()})
    print(f"audit exhibit rows {len(exhibit)}, matched {matched}")
    for e in exhibit:
        if not e["used"]:
            print("  unmatched audit row:", e["org"], e["amount"], e["date"], e["res"])


if __name__ == "__main__":
    main()
