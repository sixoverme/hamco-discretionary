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


def org(s):
    """norm(), spelling out VFD and dropping the company words norm() leaves in."""
    s = re.sub(r"\bvfd\b", "volunteer fire department", norm(s))
    return re.sub(r"\b(corporation|company|co)\b", " ", s)


def compact(s):
    return org(s).replace(" ", "")


GENERIC = {"school", "schools", "elementary", "middle", "high", "academy", "association", "club", "clubs", "county",
           "hamilton", "chattanooga", "department", "center", "community", "fund", "of", "and", "for", "a"}


def distinctive(s):
    return "".join(w for w in org(s).split() if w not in GENERIC)


def likeness(a, b):
    """How alike two organization names are, ignoring case, spacing and punctuation.
    The distinctive words must match too, so "Apison Elementary" is not "Harrison Elementary"."""
    full = SequenceMatcher(None, compact(a), compact(b)).ratio() if compact(a) and compact(b) else 0.0
    da, db = distinctive(a), distinctive(b)
    if not da or not db:
        return full
    # Same distinctive words, and one name only adds generic ones: "Red Bank Band Boosters"
    # and "Red Bank High School Band Boosters". "Hixson High" and "Hixson Middle" stay apart.
    ga, gb = ({w for w in org(x).split() if w in GENERIC} for x in (a, b))
    if da == db and (ga <= gb or gb <= ga):
        return max(full, 0.9)
    return min(full, SequenceMatcher(None, da, db).ratio())


def match_audit(gift, exhibit, loose=False):
    """Same organization and amount, approved in the payment's fiscal year or the one before.
    The loose pass also accepts one name inside the other, such as "S.T.A.R.S." and "Hamilton County STARS"."""
    for e in exhibit:
        if e["used"] or abs(e["amount"] - gift["_out"]) > 1:
            continue
        if gift["fiscal_year"] not in (e["fy"], e["fy"] + 1):
            continue
        a, b = compact(e["org"]), compact(gift["recipient"])
        if likeness(e["org"], gift["recipient"]) >= 0.85 or (loose and a and b and (a in b or b in a)):
            e["used"] = True
            return e
    return None


NUMBER_WORDS = {w: i for i, w in enumerate(
    "ZERO ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE TEN ELEVEN".split())}

# A recipient follows "TO" and ends where the amount, fund or purpose begins.
RECIPIENT = re.compile(r"\bTO (?:THE )?([A-Z0-9][A-Z0-9 .,'’&()/-]*?)"
                       r"(?=,? (?:IN THE|IN AN|FROM|FOR|AS ALLOTTED|TO ASSIST|TO PURCHASE|AND \$)|[.;]|$)")


def dollars(text):
    out = set()
    for m in re.findall(r"\$\s*(\d[\d,. ]*\d|\d)", text):
        m = m.replace(" ", "").replace(",", "")
        cents = re.search(r"\.(\d\d)$", m)
        whole = (m[:cents.start()] if cents else m).replace(".", "")
        out.add(float(whole + ("." + cents.group(1) if cents else "")))
    return out


# One recipient's share of a resolution that pays several: "TO X IN THE AMOUNT OF ... ($n)",
# "; X IN AN AMOUNT TOTALING ... ($n)" or "AGENCIES: X - ... ($n) AND ... ($m)". The share runs to the next ";".
SHARE = re.compile(r"(?:\bTO (?:THE )?|;\s*(?:AND )?(?:TO )?(?:THE )?|:\s*)([A-Z0-9](?:(?! TO )[A-Z0-9 .,'’&()/-])*?),?\s+"
                   r"(?:IN (?:THE|AN) (?:TOTAL )?AMOUNT (?:OF|TOTALING)|-)((?:(?!\bTO [A-Z])[^;])*)")


def shares_in(text):
    """Each recipient named with an amount, and every amount it gets (one per district when several pay)."""
    out = {}
    for name, rest in SHARE.findall(text):
        name = name.strip(" ,;")
        amount = sum(dollars(rest.split(" FROM ")[0]))
        if amount and not name.startswith("DISTRICT"):
            out.setdefault(name, []).append(amount)
    return list(out.items())


def districts_in(text):
    found = set()
    for m in re.finditer(r"DISTRICTS?\b(?=(.{0,90}))", text):
        seg = re.split(r"\b(?:EXPENSE|DISCRETIONARY|GENERAL|TRAVEL|FUNDS?|MONIES|TO|FOR|IN|FROM|AS)\b|[.;]",
                       m.group(1).replace("'S", " ").replace("’S", " "))[0]
        for w in re.findall(r"\b(1O|\d+|[A-Z]+)\b", seg):
            d = 10 if w == "1O" else int(w) if w.isdigit() else NUMBER_WORDS.get(w)
            if d and 1 <= d <= 11:
                found.add(d)
    return found


def parse_resolutions():
    """Adopted resolutions that spend a district's money, with what was said about each in committee."""
    path = DATA / "resolutions.csv"
    if not path.exists():
        return []
    with path.open() as f:
        rows = list(csv.DictReader(f))

    # A discussion entry often covers several resolutions. Only one about a single resolution is used.
    talk = defaultdict(list)
    for r in rows:
        nums = set(re.findall(r"\b\d{3,4}-\d{1,3}[A-Z]?\b", r["text"]))
        if r["kind"] == "discussion" and len(nums) == 1:
            talk[nums.pop()].append(r["text"])

    out, seen = [], set()
    for r in rows:
        # Some listings drop "RESOLUTION NO." from the title; the index number is the same.
        res_no = r["resolution_no"] or r["index_no"].upper()
        if r["kind"] != "resolution" or not r["action"].startswith("ADOPTED") or res_no in seen:
            continue
        seen.add(res_no)
        text = r["text"]
        said = " ".join(dict.fromkeys(talk[res_no]))
        # Some titles leave out the district; the committee discussion names it.
        districts = districts_in(text) or districts_in(said)
        amounts = dollars(text) or dollars(said)
        if not amounts:
            continue
        names = []
        for n in RECIPIENT.findall(text):
            n = n.strip(" ,")
            if n.startswith("DISTRICT"):
                n = n.split(" TO ", 1)[1] if " TO " in n else ""
            if len(n) > 3 and not any(likeness(n, m) >= 0.85 for m in names):
                names.append(n)
        out.append({
            "res": res_no, "date": r["date"], "pdf": r["pdf_url"],
            "districts": districts, "amounts": amounts, "names": names,
            "shares": shares_in(text),
            "total": bool(re.search(r"TOTAL|UP TO|NOT TO EXCEED", text)),
            "compact": compact(text), "words": set(norm(text + " " + said).split()),
            "purpose": stated_purpose(said),
        })
    return out


def stated_purpose(said):
    """The sentences from committee discussion that say what the money is for."""
    keep = []
    for s in re.split(r"(?<=\.)\s+", said):
        if re.search(r"SPOKE REGARDING|WHICH APPROPRIATES|WHICH APPROVES|WHICH ALLOCATES|NO QUESTIONS|^DISCUSSION|RESOLUTION NO\.", s):
            continue
        if re.search(r"\b(FUNDS?|MONEY|ASSIST|HELP|PURCHASE|USED|SUPPORT|PROGRAM)\b", s):
            keep.append(s.strip())
    return " ".join(dict.fromkeys(keep))[:600]


def fuzzy_in(name, text):
    """Best likeness between a compact name and any stretch of compact text the same length."""
    if not name or not text:
        return 0.0
    if name in text:
        return 1.0
    # A close match shares at least one 4-letter run with the text; skip the slow scan otherwise.
    if not any(name[i:i + 4] in text for i in range(0, max(1, len(name) - 3), 2)):
        return 0.0
    n, best = len(name), 0.0
    for i in range(max(1, len(text) - n + 1)):
        sm = SequenceMatcher(None, name, text[i:i + n])
        if sm.real_quick_ratio() > best and sm.quick_ratio() > best:
            best = max(best, sm.ratio())
    return best


def name_fit(g, r):
    """How well a gift's recipient fits a resolution, and which share of it."""
    if len(r["shares"]) > 1:
        share = max(r["shares"], key=lambda sh: likeness(g["recipient"], sh[0]))
        return likeness(g["recipient"], share[0]), share
    name = max([likeness(g["recipient"], n) for n in r["names"]] + [0.0])
    inside = fuzzy_in(compact(g["recipient"]), r["compact"]) if name < 0.85 else 0.0
    if name < 0.85 and (inside >= 0.97 or fuzzy_in(distinctive(g["recipient"]), r["compact"]) >= 0.85):
        # Titles that name the recipient mid-sentence or list several schools without separate amounts.
        name = 0.95 if inside >= 0.97 else 0.9 if inside >= 0.9 else 0.0
    return name, None


def match_resolutions(gifts, resolutions):
    """Pair gifts with the resolutions that approved them, in passes from surest to loosest.

    Every pass needs a close name, a resolution for the gift's district (or one naming no district),
    passed from two and a half years before the fiscal year ends to three months after.
      1. One gift, one resolution, same amount.
      2. Several report lines that add up to one resolution's amount, or fit under its total.
      3. One gift paid from two resolutions that add up to it.
      4. A partial payment, 50 to 100 percent of the amount approved.
    """
    by_id = {g["gift_id"]: g for g in gifts}
    cands = defaultdict(list)
    for g in gifts:
        fy, d = int(g["fiscal_year"]), int(g["district"])
        lo, start, hi = f"{fy - 2}-01-01", f"{fy - 1}-07-01", f"{fy}-09-30"
        what = {w for w in norm(g["project"]).split() if len(w) > 2 and w not in ("for", "and", "with")}
        for r in resolutions:
            if (r["districts"] and d not in r["districts"]) or not lo <= r["date"] <= hi:
                continue
            name, share = name_fit(g, r)
            if name < (0.85 if r["districts"] else 0.95):
                continue
            project = sum(any(w in x for x in r["words"]) for w in what) / len(what) if what else 0.0
            amounts = set(share[1]) | {sum(share[1])} if share else r["amounts"]
            slot = (r["res"],) + ((share[0],) if share else (d,) if len(r["districts"]) > 1 and not r["total"] else ())
            rank = (name >= 0.95, start <= r["date"] <= f"{fy}-06-30", project, round(name, 2), r["date"])
            cands[g["gift_id"]].append({"r": r, "amounts": amounts, "slot": slot, "rank": rank})
    for c in cands.values():
        c.sort(key=lambda x: x["rank"], reverse=True)

    found, used = {}, defaultdict(float)
    cap = lambda c: max(c["amounts"])  # a share's largest amount is the sum of its parts
    room = lambda c: cap(c) - used[c["slot"]]

    def take(gid, picks, how):
        for c in picks:
            used[c["slot"]] += float(by_id[gid]["amount_approved"]) if len(picks) == 1 else cap(c)
        found[gid] = ([c["r"] for c in picks], how)

    # 1. Exact amount.
    order = sorted(((c["rank"], gid, c) for gid, cs in cands.items() for c in cs), key=lambda x: x[0], reverse=True)
    for _, gid, c in order:
        amt = float(by_id[gid]["amount_approved"])
        if gid not in found and room(c) >= amt - 1 and any(abs(a - amt) < 1 for a in c["amounts"]):
            take(gid, [c], "exact")

    # 2. Several lines filling one resolution: same recipient, adding up exactly, or under a stated total.
    from itertools import combinations
    slots = {}
    for gid, cs in cands.items():
        for c in cs:
            slots.setdefault(c["slot"], c)
    for slot, c in slots.items():
        if used[slot]:
            continue
        pool = [gid for gid in cands if gid not in found and any(x["slot"] == slot for x in cands[gid])]
        best = None
        for k in range(min(len(pool), 6), 1, -1):
            for combo in combinations(pool, k):
                total = sum(float(by_id[g]["amount_approved"]) for g in combo)
                if abs(total - cap(c)) < 1 or (c["r"]["total"] and 0.5 * cap(c) <= total <= cap(c) + 1):
                    best = combo
                    break
            if best:
                break
        for gid in best or ():
            used[slot] += float(by_id[gid]["amount_approved"])
            found[gid] = ([c["r"]], "part of a larger approval")

    # 3. Two resolutions for one gift.
    for gid, cs in cands.items():
        if gid in found:
            continue
        amt = float(by_id[gid]["amount_approved"])
        free = [c for c in cs if not used[c["slot"]] and c["rank"][0]]
        for a, b in combinations(free, 2):
            if a["slot"] != b["slot"] and abs(cap(a) + cap(b) - amt) < 1:
                take(gid, [a, b], "two resolutions")
                break

    # 4. Partial payment of one approval.
    for gid, cs in cands.items():
        if gid in found:
            continue
        amt = float(by_id[gid]["amount_approved"])
        for c in cs:
            if c["rank"][0] and not used[c["slot"]] and any(0.5 * a <= amt < a for a in c["amounts"]):
                take(gid, [c], "partial")
                break
    return found


GIFT_COLUMNS = [
    # Set when the commission approves the gift
    "gift_id", "fiscal_year", "district", "commissioner",
    "recipient", "recipient_ein", "recipient_address", "recipient_in_district",
    "project", "amount_approved", "resolution_no", "resolution_date", "resolution_url",
    "stated_purpose", "goal", "report_due",
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

    resolutions = parse_resolutions()
    found = match_resolutions(gifts, resolutions)
    for g in gifts:
        hit = found.get(g["gift_id"])
        if not hit:
            continue
        rs, how = hit
        g["resolution_no"] = "; ".join(r["res"] for r in rs)
        g["resolution_date"] = "; ".join(r["date"] for r in rs)
        g["resolution_url"] = "; ".join(r["pdf"] for r in rs)
        g["stated_purpose"] = " ".join(r["purpose"] for r in rs if r["purpose"])
        g["record_source"] += "; commission resolution"
        approved = ", ".join(f"${a:,.2f}" for r in rs for a in sorted(r["amounts"]))
        if how == "partial":
            g["notes"] = (g["notes"] + f" Resolution {rs[0]['res']} approved {approved}.").strip()
        elif how == "two resolutions":
            g["notes"] = (g["notes"] + f" Paid under two resolutions, {approved}.").strip()
        elif how == "part of a larger approval":
            g["notes"] = (g["notes"] + f" One of several payments under resolution {rs[0]['res']}.").strip()

    hand = DATA / "resolution_matches.csv"
    if hand.exists():
        with hand.open() as f:
            for h in csv.DictReader(f):
                for g in gifts:
                    if (not g["resolution_no"] and str(g["fiscal_year"]) == h["fiscal_year"]
                            and str(g["district"]) == h["district"] and g["recipient"] == h["recipient"]
                            and abs(float(g["amount_approved"]) - float(h["amount"])) < 0.01):
                        g["resolution_no"], g["resolution_date"] = h["resolution_no"], h["resolution_date"]
                        g["resolution_url"] = h["resolution_url"]
                        g["record_source"] += "; commission resolution, matched by hand"
                        g["notes"] = (g["notes"] + " " + h["why"]).strip()

    exhibit = parse_audit_exhibit()
    audit = {}
    for loose in (False, True):
        for g in gifts:
            if g["gift_id"] not in audit:
                e = match_audit(g, exhibit, loose)
                if e:
                    audit[g["gift_id"]] = e
    matched, disagree = 0, []
    for g in gifts:
        e = audit.get(g["gift_id"])
        if not e:
            continue
        matched += 1
        if g["resolution_no"] and g["resolution_no"] != e["res"]:
            disagree.append((g["gift_id"], g["recipient"], g["resolution_no"], e["res"]))
        g["resolution_no"] = g["resolution_no"] or e["res"]
        g["resolution_date"] = g["resolution_date"] or e["date"]
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
    print(f"gifts matched to a resolution: {len(found)} of {len(gifts)}")
    for d in disagree:
        print("  resolution differs from the audit:", *d)
    if disagree:
        raise SystemExit("Resolution matches disagree with the 2025 audit.")


if __name__ == "__main__":
    main()
