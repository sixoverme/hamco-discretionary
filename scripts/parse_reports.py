"""
Parse the county's Commissioner Discretionary Spending PDFs (pdftotext -layout)
into one ledger: data/ledger.csv.

Each output row is one line of a report. Summary lines (budget, balances,
totals) keep line_type so every fund block can be reconciled.

Usage: python3 -I scripts/parse_reports.py raw/txt data
"""

import csv
import re
import sys
from pathlib import Path

AMOUNT = r"\$?\s*(\(?-?[\d,]+\.\d{2}\)?|-)"
AMOUNT_LINE = re.compile(rf"^(?P<desc>.*?\S)?\s{{2,}}{AMOUNT}\s*$|^\s*{AMOUNT}\s*$")
TRAILING_AMOUNT = re.compile(rf"^(?P<desc>.*?\S)\s+{AMOUNT}\s*$")

DISTRICT = re.compile(r"^\s*District\s+(\d+)(\s*-\s*continued)?\s*$", re.I)
COMMISSIONER = re.compile(r"^\s*Commissioner\s+([A-Z][A-Za-z.'\-/ ]+?)\s*$")

# Page furniture repeated on every page.
SKIP = re.compile(
    r"^\s*(Hamilton County Government.*|Commissioner'?s Discretionary Spending.*"
    r"|July 1, \d{4} (thru|through) June 30, \d{4}|As of .*\d{4}|\(continued\)"
    r"|Page \d+.*)\s*$",
    re.I,
)

FUNDS = [
    (re.compile(r"^\s*Travel and Discretionary\s*$", re.I), "travel_discretionary"),
    (re.compile(r"^\s*Current Year Expenses - Travel & Expense\s*$", re.I), "travel_discretionary"),
    (re.compile(r"^\s*(FY \d+\s+)?General Fund Discretionary( Monies)?\s*$", re.I), "general_fund_discretionary"),
    (re.compile(r"^\s*(FY \d+ - )?Bond Funds?( \(\d{4} Bond Fund\))?\s*$", re.I), "bond_fund"),
]

# Summary lines, checked in order. Anything else with an amount is a payment.
SUMMARY = [
    (re.compile(r"^(Balance as of|Rollover from)", re.I), "carryover"),
    (re.compile(r"^(Budget adjustment|Transfer\b)", re.I), "transfer"),
    (re.compile(r"^(New budget|Original Budget|General Fund Discretionary new budget|Budget\b|Allocation of)", re.I), "budget"),
    (re.compile(r"^(Beginning Balance|Balance forward from)", re.I), "beginning_balance"),
    (re.compile(r"^Total Expenses", re.I), "total_expenses"),
    (re.compile(r"^\d?(Ending Balance|Remaining Budget|Balance for FY)", re.I), "ending_balance"),
]

MONTH_LINE = re.compile(
    r"^(January|February|March|April|May|June|July|August|September|October|November|December)\b.*\d{4}$",
    re.I,
)


def to_amount(tok):
    tok = tok.replace("$", "").strip()
    if tok == "-":
        return 0.0
    neg = tok.startswith("(") and tok.endswith(")")
    val = float(tok.strip("()").replace(",", ""))
    return -val if neg else val


def split_payee(desc):
    """'Payee (purpose)' or 'Payee - purpose' -> (payee, purpose)."""
    m = re.match(r"^(?P<payee>[^()]+?)\s*\((?P<purpose>.*)\)\s*(?P<tail>.*)$", desc)
    if m:
        purpose = m["purpose"] + (f" {m['tail']}" if m["tail"] else "")
        return m["payee"].strip(), purpose.strip()
    m = re.match(r"^(?P<payee>.+?)\s+-\s+(?P<purpose>.+)$", desc)
    if m:
        return m["payee"].strip(), m["purpose"].strip()
    return desc.strip(), ""


def parse_file(path):
    fy = int(re.search(r"FY(\d{4})", path.name).group(1))
    rows, unparsed = [], []
    district = commissioner = fund = None
    subhead = ""
    pending_desc = ""
    last_district_line = None
    committed = False

    for n, raw in enumerate(path.read_text(errors="ignore").splitlines(), 1):
        line = raw.rstrip()
        text = line.strip()
        if not text or SKIP.match(line):
            continue

        m = DISTRICT.match(line)
        if m:
            new_d = int(m.group(1))
            if not m.group(2):
                # A fresh district header may start a new commissioner's block.
                last_district_line = n
            district = new_d
            subhead, pending_desc = "", ""
            continue

        m = COMMISSIONER.match(line)
        if m and last_district_line and n - last_district_line <= 3:
            name = m.group(1).strip()
            if name != commissioner:
                commissioner, fund = name, None
            continue

        for rx, name in FUNDS:
            if rx.match(line):
                fund, subhead, pending_desc, committed = name, "", "", False
                break
        else:
            name = None
        if name:
            continue

        m = AMOUNT_LINE.match(line) or TRAILING_AMOUNT.match(line)
        if not m:
            if re.match(r"^Less (Payments|Committed):?$", text, re.I):
                committed = "committed" in text.lower()
                subhead = ""
                continue
            if text.endswith(":"):
                subhead = text.rstrip(":").strip()
            else:
                # Wrapped description; joined to the next amount line.
                pending_desc = f"{pending_desc} {text}".strip()
            continue

        desc = (m.group("desc") or "").strip().strip("$").strip()
        if not desc and "$" in line:
            # A bare "$ amount" line is a running subtotal, even after a wrapped note.
            pending_desc = ""
            continue
        tok = next(g for g in m.groups()[1:] if g)
        amount = to_amount(tok)
        if pending_desc:
            # A summary line never continues a wrapped description.
            if not any(rx.match(desc) for rx, _ in SUMMARY):
                desc = f"{pending_desc} {desc}".strip()
            pending_desc = ""

        # A bare amount with nothing to describe is a running subtotal.
        if not desc:
            continue

        line_type = "payment"
        for rx, kind in SUMMARY:
            if rx.match(desc):
                line_type = kind
                break

        if line_type == "payment" and (committed or re.search(r"\bcommitted\s*$", desc, re.I)):
            line_type = "committed"
        if line_type == "payment" and MONTH_LINE.match(desc) and subhead:
            desc = f"{subhead}, {desc}"
        if line_type != "payment":
            subhead = ""

        if district is None or fund is None:
            unparsed.append((path.name, n, "no district/fund", text))
            continue

        payee, purpose = split_payee(desc) if line_type in ("payment", "committed") else ("", "")
        rows.append({
            "fiscal_year": fy,
            "district": district,
            "commissioner": commissioner,
            "fund": fund,
            "line_type": line_type,
            "description": desc,
            "payee": payee,
            "purpose": purpose,
            "amount": f"{amount:.2f}",
            "source": f"FY{fy}.pdf",
            "source_line": n,
        })

    return rows, unparsed


def reconcile(rows):
    """Opening + budget + payments must equal the stated ending balance."""
    problems = []
    blocks = {}
    for r in rows:
        key = (r["fiscal_year"], r["district"], r["commissioner"], r["fund"])
        blocks.setdefault(key, []).append(r)
    for key, rs in blocks.items():
        amt = lambda t: [float(r["amount"]) for r in rs if r["line_type"] == t]
        begin = amt("beginning_balance")
        # Lines above the beginning balance are already inside it.
        bi = next((i for i, r in enumerate(rs) if r["line_type"] == "beginning_balance"), None)
        after = rs if bi is None else rs[bi + 1:]
        added = sum(float(r["amount"]) for r in after if r["line_type"] in ("budget", "carryover"))
        transfers_before = 0.0 if bi is None else sum(
            float(r["amount"]) for r in rs[:bi] if r["line_type"] == "transfer")
        start = (begin[0] if begin else 0.0) + added - transfers_before
        paid = sum(amt("payment")) + sum(amt("committed")) + sum(amt("transfer"))
        ending = amt("ending_balance")
        if not ending:
            continue
        diff = round(start + paid - ending[-1], 2)
        if abs(diff) > 0.01:
            problems.append((key, round(start, 2), round(paid, 2), ending[-1], diff))
    return problems


def report_meta(path):
    """Fiscal year, period and 'as of' date printed on the report's first page."""
    fy = int(re.search(r"FY(\d{4})", path.name).group(1))
    text = path.read_text(errors="ignore")[:2000]
    m = re.search(r"As of (\w+ \d{1,2}, \d{4})", text)
    as_of = m.group(1) if m else f"June 30, {fy}"
    return {
        "fiscal_year": fy,
        "period": f"July 1, {fy - 1} to June 30, {fy}",
        "as_of": as_of,
        "source_url": f"https://www.hamiltontn.gov/CommissionDSReports/FY{fy}.pdf",
    }


def main(txt_dir, out_dir):
    all_rows, all_unparsed, reports = [], [], []
    for path in sorted(Path(txt_dir).glob("FY20*.txt")):
        rows, unparsed = parse_file(path)
        all_rows += rows
        all_unparsed += unparsed
        reports.append(report_meta(path))

    with (Path(out_dir) / "reports.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(reports[0]))
        w.writeheader()
        w.writerows(reports)

    for i, r in enumerate(all_rows, 1):
        r["ledger_id"] = f"L{r['fiscal_year']}-{i:05d}"

    out = Path(out_dir) / "ledger_raw.csv"
    cols = ["ledger_id", "fiscal_year", "district", "commissioner", "fund", "line_type",
            "payee", "purpose", "description", "amount", "source", "source_line"]
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(all_rows)

    print(f"{len(all_rows)} rows -> {out}")
    print(f"{sum(r['line_type'] == 'payment' for r in all_rows)} payments")
    for u in all_unparsed:
        print("UNPARSED", *u, sep=" | ")
    problems = reconcile(all_rows)
    print(f"{len(problems)} blocks fail reconciliation")
    for p in problems:
        print("RECON", p)
    if problems or all_unparsed:
        sys.exit("Stopped: fix the lines above before publishing.")


if __name__ == "__main__":
    main(*sys.argv[1:3])
