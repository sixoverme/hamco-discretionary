"""
Build the 1200x630 link-preview image (site/og-image.png) from real ledger data.

Writes an HTML card, then screenshots it with headless Chrome.

Usage: python3 -I scripts/og/make_og_image.py [fiscal_year]
"""

import csv
import html
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "site" / "data" / "ledger.csv"
OUT = ROOT / "site" / "og-image.png"
CHROME = "/usr/bin/google-chrome"

FY = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
NOW_PER_SEAT = 17500
PROPOSED_PER_SEAT = 100000

SEGMENTS = [
    ("gift", "#3987e5", "Gifts to organizations"),
    ("travel_office", "#e0622b", "Travel and office"),
    ("community_purchase", "#1fae7b", "Purchases for schools, staff and events"),
]


def spending_by_commissioner(fy):
    """Spending per commissioner, counting commitments in the year they were made."""
    people = defaultdict(lambda: defaultdict(float))
    with LEDGER.open() as f:
        for r in csv.DictReader(f):
            if int(r["fiscal_year"]) != fy:
                continue
            key = (int(r["district"]), r["commissioner"])
            amt = -float(r["amount"])
            if r["line_type"] == "payment" and r["category"] in ("gift", "travel_office", "community_purchase"):
                people[key][r["category"]] += amt
            elif r["line_type"] == "committed":
                people[key]["gift"] += amt
            elif r["line_type"] == "budget":
                people[key]["budget"] += -amt
    return sorted(people.items())


def card_html(rows):
    scale = max(NOW_PER_SEAT, *(sum(v[k] for k, *_ in SEGMENTS) for _, v in rows))
    bars = []
    for (district, name), v in rows:
        segs = "".join(
            f'<span style="flex:{v[k]:.2f} 0 0;background:{color}"></span>'
            for k, color, _ in SEGMENTS if v[k] > 0.5
        )
        spent = sum(v[k] for k, *_ in SEGMENTS)
        width = spent / scale * 100
        bars.append(
            f'<div class="row"><div class="who"><b>{district}</b> {html.escape(name)}</div>'
            f'<div class="track"><div class="fill" style="width:{width:.1f}%">{segs}</div></div></div>'
        )
    legend = "".join(
        f'<span><i style="background:{color}"></i>{label}</span>'
        for _, color, label in SEGMENTS if label
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  * {{ box-sizing: border-box; margin: 0; }}
  html, body {{ width: 1200px; height: 630px; background: #111318; }}
  body {{
    font-family: Inter, Lato, sans-serif; color: #f0f0f0;
    padding: 56px 60px 0; position: relative; overflow: hidden;
  }}
  .grid {{ display: grid; grid-template-columns: 560px 1fr; gap: 56px; }}
  .eyebrow {{ color: #3fcf8e; font-weight: 700; font-size: 19px; letter-spacing: .12em; text-transform: uppercase; }}
  h1 {{ font-size: 58px; line-height: 1.06; font-weight: 800; letter-spacing: -.02em; margin-top: 16px; }}
  .sub {{ color: #a7abc0; font-size: 22px; line-height: 1.4; margin-top: 20px; }}
  .stakes {{ display: flex; gap: 14px; margin-top: 30px; }}
  .stake {{ background: #1e2028; border: 1px solid #2d3040; border-radius: 12px; padding: 14px 18px; }}
  .stake .n {{ font-size: 34px; font-weight: 800; letter-spacing: -.01em; }}
  .stake .l {{ color: #a7abc0; font-size: 16px; margin-top: 2px; }}
  .stake.next .n {{ color: #3fcf8e; }}
  .chart {{ background: #1a1c23; border: 1px solid #2d3040; border-radius: 14px; padding: 20px 22px 18px; }}
  .chart h2 {{ font-size: 17px; font-weight: 600; color: #c9ccdb; margin-bottom: 12px; }}
  .row {{ display: grid; grid-template-columns: 132px 1fr; align-items: center; height: 33px; }}
  .who {{ font-size: 15px; color: #c9ccdb; white-space: nowrap; overflow: hidden; }}
  .who b {{ display: inline-block; width: 22px; color: #8a8fa8; font-weight: 600; }}
  .track {{ height: 14px; background: #262934; border-radius: 4px; overflow: hidden; }}
  .fill {{ display: flex; gap: 2px; height: 100%; }}
  .fill span:last-child {{ border-radius: 0 4px 4px 0; }}
  .legend {{ display: flex; flex-wrap: wrap; gap: 6px 16px; margin-top: 12px; font-size: 14px; color: #a7abc0; }}
  .legend i {{ display: inline-block; width: 11px; height: 11px; border-radius: 3px; margin-right: 6px; vertical-align: -1px; }}
  footer {{
    position: absolute; left: 0; right: 0; bottom: 0; height: 74px;
    display: flex; align-items: center; justify-content: space-between;
    padding: 0 60px; background: #0b0c10; border-top: 1px solid #2d3040;
  }}
  .url {{ font-size: 25px; font-weight: 700; }}
  .brand {{ font-size: 19px; color: #a7abc0; font-weight: 600; }}
  .brand i {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: #3fcf8e; margin-right: 9px; }}
</style></head>
<body>
  <div class="grid">
    <div>
      <div class="eyebrow">Hamilton County Commission</div>
      <h1>See where your commissioner's discretionary dollars went</h1>
      <p class="sub">Every line of the county's own spending reports, FY2017 to today. Updated daily.</p>
      <div class="stakes">
        <div class="stake"><div class="n">${NOW_PER_SEAT:,}</div><div class="l">per commissioner now</div></div>
        <div class="stake next"><div class="n">${PROPOSED_PER_SEAT:,}</div><div class="l">per commissioner, proposed</div></div>
      </div>
    </div>
    <div class="chart">
      <h2>FY{FY} spending by commissioner</h2>
      {''.join(bars)}
      <div class="legend">{legend}</div>
    </div>
  </div>
  <footer>
    <div class="url">commission.chattanoogamapped.com</div>
    <div class="brand"><i></i>Chattanooga Mapped</div>
  </footer>
</body></html>"""


def main():
    rows = spending_by_commissioner(FY)
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "og.html"
        page.write_text(card_html(rows))
        shot = Path(tmp) / "shot.png"
        subprocess.run([
            CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
            "--force-device-scale-factor=1", "--virtual-time-budget=6000",
            "--window-size=1200,800", f"--screenshot={shot}", page.as_uri(),
        ], check=True, capture_output=True, timeout=120)
        Image.open(shot).crop((0, 0, 1200, 630)).convert("RGB").save(OUT, optimize=True)
    print(f"{OUT} ({OUT.stat().st_size // 1024} KB) from FY{FY}, {len(rows)} commissioners")


if __name__ == "__main__":
    main()
