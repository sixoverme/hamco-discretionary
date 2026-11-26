/*
  Commissioner discretionary spending dashboard.

  Reads three CSV files named in config.json and renders everything from them.
  To update the page, replace the CSV files. No code changes are needed.
*/

(function () {
  "use strict";

  const CATEGORIES = [
    { key: "gift", label: "Gifts to organizations", swatch: "s-gift", color: "--series-1" },
    { key: "travel_office", label: "Travel and office", swatch: "s-travel_office", color: "--series-2" },
    { key: "community_purchase", label: "Purchases for schools, staff and events", swatch: "s-community_purchase", color: "--series-3" },
  ];

  const FUND_LABELS = {
    travel_discretionary: "travel and discretionary account",
    general_fund_discretionary: "general fund discretionary account",
    bond_fund: "2015 bond fund",
  };

  const STATUS = {
    met: { label: "Met", icon: "✓" },
    not_met: { label: "Not met", icon: "✕" },
    no_report: { label: "No report", icon: "!" },
    overdue: { label: "Report overdue", icon: "!" },
    due: { label: "Report due", icon: "…" },
    voided: { label: "Voided", icon: "–" },
    untracked: { label: "Not tracked", icon: "" },
  };

  const PAGE_SIZE = 50;

  const COMMITTED_LABEL = "Gifts committed for later payment";

  const state = {
    year: "",
    district: "",
    search: "",
    sort: { key: "amount", dir: "descending" },
    expanded: new Set(),
    limit: PAGE_SIZE,
    showHistoryTable: false,
    modal: null,
    modalSort: "report",
  };

  let DB = null;

  // ---------- Loading ----------

  async function load() {
    const cfg = await (await fetch("config.json", { cache: "no-cache" })).json();
    const get = async (path) => parseCSV(await (await fetch(path, { cache: "no-cache" })).text());
    const [ledger, gifts, reports] = await Promise.all([
      get(cfg.data.ledger), get(cfg.data.gifts), get(cfg.data.reports),
    ]);

    ledger.forEach((r) => {
      r.fiscal_year = +r.fiscal_year;
      r.district = +r.district;
      r.amount = toNumber(r.amount);
    });
    gifts.forEach((g) => {
      g.fiscal_year = +g.fiscal_year;
      g.district = +g.district;
      g.amount_approved = toNumber(g.amount_approved);
      g.outcome = normalizeOutcome(g.outcome);
    });
    reports.forEach((r) => { r.fiscal_year = +r.fiscal_year; });
    reports.sort((a, b) => b.fiscal_year - a.fiscal_year);

    const paymentsByGift = new Map();
    ledger.forEach((r) => {
      if (!r.gift_id) return;
      if (!paymentsByGift.has(r.gift_id)) paymentsByGift.set(r.gift_id, []);
      paymentsByGift.get(r.gift_id).push(r);
    });

    DB = { cfg, ledger, gifts, reports, paymentsByGift };
  }

  // RFC 4180 CSV, as written by Excel, CentralSquare or any spreadsheet export.
  function parseCSV(text) {
    text = text.replace(/^﻿/, "");
    const rows = [];
    let row = [], field = "", quoted = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (quoted) {
        if (c === '"' && text[i + 1] === '"') { field += '"'; i++; }
        else if (c === '"') quoted = false;
        else field += c;
      } else if (c === '"') quoted = true;
      else if (c === ",") { row.push(field); field = ""; }
      else if (c === "\n") { row.push(field); rows.push(row); row = []; field = ""; }
      else if (c !== "\r") field += c;
    }
    if (field !== "" || row.length) { row.push(field); rows.push(row); }
    const [head, ...body] = rows;
    const keys = head.map((h) => h.trim().toLowerCase());
    return body
      .filter((r) => r.some((v) => v.trim() !== ""))
      .map((r) => Object.fromEntries(keys.map((k, j) => [k, (r[j] ?? "").trim()])));
  }

  function toNumber(v) {
    if (v === "" || v == null) return 0;
    const s = String(v).replace(/[$,\s]/g, "");
    const neg = /^\(.*\)$/.test(s);
    const n = parseFloat(s.replace(/[()]/g, ""));
    return isNaN(n) ? 0 : neg ? -n : n;
  }

  function normalizeOutcome(v) {
    const s = String(v || "").trim().toLowerCase().replace(/[\s-]+/g, "_");
    return STATUS[s] && !["due", "overdue", "untracked"].includes(s) ? s : "";
  }

  // Accepts 2024-06-26, 6/26/2024 or 6/26/24.
  function parseDate(v) {
    if (!v) return null;
    let m = /^(\d{4})-(\d{1,2})-(\d{1,2})/.exec(v);
    if (m) return new Date(+m[1], m[2] - 1, +m[3]);
    m = /^(\d{1,2})\/(\d{1,2})\/(\d{2,4})$/.exec(v);
    if (m) return new Date(m[3].length === 2 ? 2000 + +m[3] : +m[3], m[1] - 1, +m[2]);
    return null;
  }

  // ---------- Formatting ----------

  const dollars = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
  const cents = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });
  const fmtDate = (d) => d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

  function compact(n) {
    if (Math.abs(n) >= 1e6) return "$" + (n / 1e6).toFixed(n % 1e6 === 0 ? 0 : 1) + "M";
    if (Math.abs(n) >= 1e3) return "$" + Math.round(n / 1e3) + "K";
    return "$" + Math.round(n);
  }

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "style") node.style.cssText = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat(Infinity)) {
      if (c == null || c === false) continue;
      node.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return node;
  }

  function svg(tag, attrs, ...children) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v);
    }
    children.flat(Infinity).forEach((c) => c != null && node.append(c instanceof Node ? c : document.createTextNode(String(c))));
    return node;
  }

  const css = (name) => getComputedStyle(document.querySelector(".viz-root")).getPropertyValue(name).trim();

  // ---------- Selection ----------

  function inScope(r, ignoreYear) {
    if (!ignoreYear && state.year && r.fiscal_year !== +state.year) return false;
    if (state.district && r.district !== +state.district) return false;
    return true;
  }

  function currentReport() {
    return state.year ? DB.reports.find((r) => r.fiscal_year === +state.year) : null;
  }

  function inProgress(report) {
    return report && !/^June 30/.test(report.as_of);
  }

  // Money available, spent and left for each commissioner, from the report's own lines.
  function commissionerRows() {
    const blocks = new Map();
    DB.ledger.filter((r) => inScope(r)).forEach((r) => {
      const key = [r.fiscal_year, r.district, r.commissioner, r.fund].join("|");
      if (!blocks.has(key)) blocks.set(key, []);
      blocks.get(key).push(r);
    });

    const people = new Map();
    for (const rows of blocks.values()) {
      const first = rows[0];
      const key = `${first.district}|${first.commissioner}`;
      if (!people.has(key)) {
        people.set(key, {
          district: first.district, commissioner: first.commissioner, years: new Set(),
          available: 0, remaining: 0, committed: 0, gift: 0, travel_office: 0, community_purchase: 0, lines: [],
        });
      }
      const p = people.get(key);
      p.years.add(first.fiscal_year);

      // The county counts committed money as spent in the year it is committed.
      // A later payment of that commitment is left out of both available and spent.
      const bi = rows.findIndex((r) => r.line_type === "beginning_balance");
      const after = bi >= 0 ? rows.slice(bi + 1) : rows;
      const sum = (rs, types) => rs.filter((r) => types.includes(r.line_type)).reduce((a, r) => a + r.amount, 0);
      const available = (bi >= 0 ? rows[bi].amount : 0)
        + sum(after, ["budget", "carryover", "transfer"])
        + sum(rows, ["commitment_paid"]);

      rows.filter((r) => r.line_type === "payment" && r.category in p).forEach((r) => {
        p[r.category] -= r.amount;
      });
      p.committed -= sum(rows, ["committed"]);

      const endings = rows.filter((r) => r.line_type === "ending_balance");
      if (endings.length) p.remaining += endings[endings.length - 1].amount;
      p.available += available;
      p.lines.push(...rows);
    }

    return [...people.values()].sort((a, b) => a.district - b.district || a.commissioner.localeCompare(b.commissioner));
  }

  function selectedGifts() {
    const q = state.search.trim().toLowerCase();
    return DB.gifts.filter((g) => inScope(g) && (!q || `${g.recipient} ${g.project}`.toLowerCase().includes(q)));
  }

  function giftStatus(g) {
    if (g.outcome) return g.outcome;
    const due = parseDate(g.report_due);
    if (due) return due < new Date() ? "overdue" : "due";
    return "untracked";
  }

  function paidFor(g) {
    const lines = (DB.paymentsByGift.get(g.gift_id) || []).filter((r) => r.line_type === "payment");
    return { lines, total: -lines.reduce((a, r) => a + r.amount, 0) };
  }

  // ---------- Rendering ----------

  function render() {
    renderTiles();
    renderCommissioners();
    renderGifts();
    renderHistory();
    if (state.modal && document.getElementById("detail").open) renderDetail();
  }

  function renderTiles() {
    const report = currentReport();
    const people = commissionerRows();
    const total = (k) => people.reduce((a, p) => a + p[k], 0);
    const spent = total("gift") + total("travel_office") + total("community_purchase") + total("committed");
    const available = total("available");

    const gifts = DB.gifts.filter((g) => inScope(g) && g.outcome !== "voided");
    const giftDollars = gifts.reduce((a, g) => a + paidFor(g).total, 0);
    const orgs = new Set(gifts.map((g) => g.recipient.toLowerCase())).size;
    const withRes = gifts.filter((g) => g.resolution_no).length;
    const withOutcome = gifts.filter((g) => ["met", "not_met", "no_report"].includes(g.outcome));
    const count = (o) => withOutcome.filter((g) => g.outcome === o).length;

    const scope = report ? (inProgress(report) ? `as of ${report.as_of}` : `FY${report.fiscal_year}`) : "FY2017 to now";

    const tiles = [
      { label: "Spent", value: dollars.format(spent), sub: report ? `of ${dollars.format(available)} available, ${scope}` : scope },
      { label: "Gifts to organizations", value: gifts.length.toLocaleString(), sub: `${dollars.format(giftDollars)} paid to ${orgs} recipients` },
      {
        label: "Gifts with a resolution on record", value: `${withRes} of ${gifts.length}`,
        sub: "County policy requires a commission resolution for every gift",
      },
      {
        label: "Gifts with a reported outcome", value: `${withOutcome.length} of ${gifts.length}`,
        sub: withOutcome.length
          ? `${count("met")} met, ${count("not_met")} not met, ${count("no_report")} with no report`
          : "Outcomes are not yet recorded",
      },
    ];

    document.getElementById("tiles").replaceChildren(...tiles.map((t) =>
      el("div", { class: "tile" },
        el("div", { class: "label" }, t.label),
        el("div", { class: "value" }, t.value),
        el("div", { class: "sub" }, t.sub))));
  }

  function legendItems(includeExtras, people) {
    const items = CATEGORIES.map((c) => el("li", {}, el("span", { class: `swatch ${c.swatch}` }), c.label));
    if (includeExtras) {
      if (people.some((p) => p.committed > 0.5)) {
        items.push(el("li", {}, el("span", { class: "swatch s-gift", style: "opacity:.4" }), COMMITTED_LABEL));
      }
      if (state.year) items.push(el("li", {}, el("span", { class: "swatch s-remaining" }), "Unspent"));
    }
    return items;
  }

  function renderCommissioners() {
    const people = commissionerRows();
    document.getElementById("legend").replaceChildren(...legendItems(true, people));
    // Balances carry from year to year, so the all-years view sums spending only.
    const allYears = !state.year;
    const spentOf = (p) => p.gift + p.travel_office + p.community_purchase + p.committed;
    const max = Math.max(1, ...people.map((p) => allYears ? spentOf(p) : Math.max(p.available, spentOf(p))));

    const head = el("thead", {}, el("tr", {},
      el("th", {}, "District"),
      el("th", {}, "Commissioner"),
      allYears ? null : el("th", { class: "num" }, "Available"),
      el("th", { class: "num" }, "Spent"),
      el("th", { class: "bar-cell" }, "Where it went"),
      allYears ? null : el("th", { class: "num" }, "Left")));

    const body = el("tbody", {}, people.map((p) => {
      const spent = spentOf(p);
      const parts = [
        ...CATEGORIES.map((c) => ({ label: c.label, value: p[c.key], cls: c.swatch, style: "" })),
        { label: COMMITTED_LABEL, value: p.committed, cls: "s-gift", style: "opacity:.4" },
        ...(allYears ? [] : [{ label: "Unspent", value: Math.max(0, p.remaining), cls: "s-remaining", style: "" }]),
      ].filter((x) => x.value > 0.5);
      const width = ((allYears ? spent : Math.max(p.available, spent)) / max) * 100;
      const who = `District ${p.district}, Commissioner ${p.commissioner}`;

      const open = () => openCommissioner(p.district, p.commissioner);
      return el("tr", { class: "row", onclick: (e) => { if (!e.target.closest("button, .bar span")) open(); } },
        el("td", {}, p.district),
        el("td", {},
          el("button", { type: "button", class: "expand", "aria-haspopup": "dialog", onclick: open }, p.commissioner),
          allYears ? el("div", { class: "muted small" }, yearSpan(p.years)) : null),
        allYears ? null : el("td", { class: "num" }, dollars.format(p.available)),
        el("td", { class: "num" }, dollars.format(spent)),
        el("td", { class: "bar-cell" },
          el("div", { class: "bar", style: `width:${width}%`, role: "img", "aria-label": `${who}: ` + parts.map((x) => `${x.label} ${dollars.format(x.value)}`).join(", ") },
            parts.map((x) => el("span", {
              class: x.cls,
              style: `flex:${x.value} 1 0;${x.style}`,
              tabindex: "0",
              onpointermove: (e) => showTip(e, who, [{ name: x.label, value: x.value, cls: x.cls, style: x.style }]),
              onpointerleave: hideTip,
              onfocus: (e) => showTip(e, who, [{ name: x.label, value: x.value, cls: x.cls, style: x.style }]),
              onblur: hideTip,
            })))),
        allYears ? null : el("td", { class: "num" }, dollars.format(p.remaining)));
    }));

    document.getElementById("commissioners").replaceChildren(head, body);
  }

  function yearSpan(years) {
    const ys = [...years].sort();
    return ys.length === 1 ? `FY${ys[0]}` : `FY${ys[0]} to FY${ys[ys.length - 1]}`;
  }

  function statusChip(g) {
    const s = giftStatus(g);
    const info = STATUS[s];
    const label = s === "due" ? `Report due ${fmtDate(parseDate(g.report_due))}` : info.label;
    return el("span", { class: `status ${s}` }, el("span", { class: "dot", "aria-hidden": "true" }, info.icon), label);
  }

  function renderGifts() {
    const all = selectedGifts();
    const { key, dir } = state.sort;
    const sign = dir === "ascending" ? 1 : -1;
    const value = (g) => key === "amount" ? paidFor(g).total || g.amount_approved
      : key === "recipient" ? g.recipient.toLowerCase()
      : key === "district" ? g.district * 10000 + g.fiscal_year
      : giftStatus(g);
    all.sort((a, b) => (value(a) > value(b) ? 1 : value(a) < value(b) ? -1 : 0) * sign);
    const shown = all.slice(0, state.limit);

    const sortButton = (k, label, defaultDir) => {
      const active = state.sort.key === k;
      return el("button", {
        type: "button", class: "sort", "aria-sort": active ? state.sort.dir : null,
        onclick: () => {
          state.sort = { key: k, dir: active ? (state.sort.dir === "ascending" ? "descending" : "ascending") : defaultDir };
          renderGifts();
        },
      }, label);
    };

    const head = el("thead", {}, el("tr", {},
      el("th", {}, sortButton("recipient", "Recipient and project", "ascending")),
      el("th", {}, sortButton("district", "District", "ascending")),
      el("th", { class: "num" }, sortButton("amount", "Amount", "descending")),
      el("th", {}, "Resolution"),
      el("th", {}, sortButton("status", "Outcome", "ascending"))));

    const rows = [];
    shown.forEach((g) => {
      const open = state.expanded.has(g.gift_id);
      const paid = paidFor(g).total;
      const toggle = () => {
        open ? state.expanded.delete(g.gift_id) : state.expanded.add(g.gift_id);
        syncURL();
        renderGifts();
      };
      const res = g.resolution_no
        ? el("span", {}, g.resolution_no, g.resolution_date ? el("div", { class: "muted small" }, fmtDate(parseDate(g.resolution_date))) : null)
        : el("span", { class: "muted small" }, "Not on record");

      rows.push(el("tr", { class: "row", "aria-expanded": String(open), onclick: (e) => { if (!e.target.closest("button")) toggle(); } },
        el("td", {},
          el("button", { type: "button", class: "expand", "aria-expanded": String(open), "aria-controls": `rec-${g.gift_id}`, onclick: toggle },
            el("span", { class: "chevron", "aria-hidden": "true" }, "›"), g.recipient),
          g.project ? el("div", { class: "muted small" }, g.project) : null),
        el("td", { class: "small" }, `District ${g.district}`, el("div", { class: "muted" }, `${g.commissioner}, FY${g.fiscal_year}`)),
        el("td", { class: "num" }, dollars.format(paid || g.amount_approved)),
        el("td", { class: "small" }, res),
        el("td", {}, statusChip(g))));

      if (open) rows.push(el("tr", { class: "record", id: `rec-${g.gift_id}` }, el("td", { colspan: "5" }, giftRecord(g))));
    });

    const table = document.getElementById("gifts");
    table.replaceChildren(head, el("tbody", {}, rows));
    document.getElementById("gifts-empty").hidden = all.length > 0;

    const old = table.parentElement.querySelector(".more");
    if (old) old.remove();
    if (all.length > shown.length) {
      table.after(el("button", {
        type: "button", class: "more",
        onclick: () => { state.limit += PAGE_SIZE; renderGifts(); },
      }, `Show more (${all.length - shown.length} left)`));
    }
  }

  function field(label, value, opts = {}) {
    const empty = value == null || value === "";
    let content;
    if (empty) content = el("span", { class: "missing" }, "Not recorded");
    else if (opts.link && /^https?:\/\//.test(value)) content = el("a", { href: value, target: "_blank", rel: "noopener" }, opts.linkText || value);
    else content = value;
    return [el("dt", {}, label), el("dd", {}, content)];
  }

  function giftRecord(g) {
    const { lines, total } = paidFor(g);
    const report = (fy) => DB.reports.find((r) => r.fiscal_year === fy);
    const paidText = lines.length
      ? `${cents.format(total)}` + (lines.length > 1 ? ` in ${lines.length} payments` : "")
      : "";
    const paidFrom = [...new Set(lines.map((r) => `FY${r.fiscal_year}, ${FUND_LABELS[r.fund] || r.fund}`))].join("; ");
    const date = (v) => { const d = parseDate(v); return d ? fmtDate(d) : v; };
    const status = giftStatus(g);

    const source = (() => {
      const m = /^FY(\d{4})\.pdf line (\d+)/.exec(g.record_source || "");
      const r = m && report(+m[1]);
      return r ? el("a", { href: r.source_url, target: "_blank", rel: "noopener" }, `FY${m[1]} spending report`) : g.record_source;
    })();

    return el("div", {},
      el("div", { class: "record-grid" },
        el("div", {},
          el("h3", {}, "Set when the commission approves it"),
          el("dl", {},
            field("Recipient", g.recipient),
            field("Tax ID (EIN)", g.recipient_ein),
            field("Address", g.recipient_address),
            field("In the district", g.recipient_in_district),
            field("Project", g.project),
            field("Amount approved", g.amount_approved ? cents.format(g.amount_approved) : ""),
            field("Resolution", g.resolution_no),
            field("Approved on", date(g.resolution_date)),
            field("Goal", g.goal),
            field("Report due", date(g.report_due)))),
        el("div", {},
          el("h3", {}, "Filled in after the money goes out"),
          el("dl", {},
            field("Paid", paidText),
            field("Paid from", paidFrom),
            field("Report received", date(g.report_received)),
            field("Evidence", g.evidence_url, { link: true, linkText: "View evidence" }),
            [el("dt", {}, "Outcome"), el("dd", {}, status === "untracked" ? el("span", { class: "missing" }, "Not recorded") : statusChip(g))],
            field("Checked by", g.verified_by),
            field("Checked on", date(g.verified_date))))),
      g.notes ? el("p", { class: "note" }, g.notes) : null,
      el("p", { class: "note" }, "Gift ", g.gift_id, ". Source: ", source,
        /audit/.test(g.record_source) ? ", 2025 county audit" : "", "."));
  }

  // ---------- History chart ----------

  function historyData() {
    const years = [...new Set(DB.ledger.map((r) => r.fiscal_year))].sort();
    return years.map((fy) => {
      const row = { fy };
      CATEGORIES.forEach((c) => { row[c.key] = 0; });
      DB.ledger.forEach((r) => {
        if (r.fiscal_year !== fy || !inScope(r, true) || !(r.category in row)) return;
        if (r.line_type === "payment" || r.line_type === "committed") row[r.category] -= r.amount;
      });
      row.total = CATEGORIES.reduce((a, c) => a + Math.max(0, row[c.key]), 0);
      return row;
    });
  }

  function niceMax(v) {
    if (v <= 0) return 1000;
    const p = Math.pow(10, Math.floor(Math.log10(v)));
    for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
    return 10 * p;
  }

  function renderHistory() {
    const data = historyData();
    const wrap = document.getElementById("history-chart");
    const table = document.getElementById("history-table");
    wrap.hidden = state.showHistoryTable;
    table.hidden = !state.showHistoryTable;
    document.getElementById("history-toggle").textContent = state.showHistoryTable ? "Show as chart" : "Show as table";
    document.getElementById("history-toggle").setAttribute("aria-pressed", String(state.showHistoryTable));

    table.replaceChildren(
      el("thead", {}, el("tr", {}, el("th", {}, "Fiscal year"), CATEGORIES.map((c) => el("th", { class: "num" }, c.label)), el("th", { class: "num" }, "Total"))),
      el("tbody", {}, data.map((d) => el("tr", {},
        el("td", {}, `FY${d.fy}`),
        CATEGORIES.map((c) => el("td", { class: "num" }, dollars.format(d[c.key]))),
        el("td", { class: "num" }, dollars.format(d.total))))));

    // Drawn at the container's real width so text stays at its set size.
    const W = Math.max(300, wrap.clientWidth || 1040), H = 280, padL = 52, padR = 8, padT = 22, padB = 30;
    const max = niceMax(Math.max(...data.map((d) => d.total)));
    const plotW = W - padL - padR, plotH = H - padT - padB;
    const band = plotW / data.length;
    const colW = Math.min(24, band * 0.6);
    const y = (v) => padT + plotH - (v / max) * plotH;

    const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => t * max);
    const g = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": "Spending by fiscal year and type. A table version is available." });

    ticks.forEach((t) => {
      g.append(svg("line", { class: t === 0 ? "baseline" : "gridline", x1: padL, x2: W - padR, y1: y(t), y2: y(t) }));
      g.append(svg("text", { class: "tick", x: padL - 8, y: y(t) + 4, "text-anchor": "end" }, compact(t)));
    });

    data.forEach((d, i) => {
      const cx = padL + band * i + band / 2;
      const x = cx - colW / 2;
      const selected = state.year && +state.year === d.fy;
      const group = svg("g", { class: "col" });
      let base = 0;
      const segs = CATEGORIES.filter((c) => d[c.key] > 0);
      segs.forEach((c, j) => {
        const top = y(base + d[c.key]);
        const bottom = y(base);
        const gap = j > 0 ? 2 : 0;
        const h = Math.max(0, bottom - top - gap);
        const isTop = j === segs.length - 1;
        const r = isTop ? Math.min(4, h) : 0;
        const path = isTop
          ? `M${x},${top + h} V${top + r} Q${x},${top} ${x + r},${top} H${x + colW - r} Q${x + colW},${top} ${x + colW},${top + r} V${top + h} Z`
          : `M${x},${top} H${x + colW} V${top + h} H${x} Z`;
        group.append(svg("path", { d: path, fill: css(c.color) }));
        base += d[c.key];
      });

      const rows = CATEGORIES.map((c) => ({ name: c.label, value: d[c.key], cls: c.swatch }));
      const hit = svg("rect", {
        class: "col-hit", x: padL + band * i, y: padT, width: band, height: plotH, tabindex: "0",
        "aria-label": `FY${d.fy}: ` + rows.map((r) => `${r.name} ${dollars.format(r.value)}`).join(", "),
        onpointermove: (e) => { group.classList.add("active"); showTip(e, `FY${d.fy}, total ${dollars.format(d.total)}`, rows); },
        onpointerleave: () => { group.classList.remove("active"); hideTip(); },
        onfocus: (e) => { group.classList.add("active"); showTip(e, `FY${d.fy}, total ${dollars.format(d.total)}`, rows); },
        onblur: () => { group.classList.remove("active"); hideTip(); },
        onclick: () => setYear(String(d.fy)),
      });
      g.append(hit, group);

      const yearLabel = band >= 44 ? `FY${String(d.fy).slice(2)}` : `’${String(d.fy).slice(2)}`;
      g.append(svg("text", { class: `tick${selected ? " selected-year" : ""}`, x: cx, y: H - 8, "text-anchor": "middle" }, yearLabel));
      if (selected) {
        g.append(svg("text", { class: "total-label", x: cx, y: y(d.total) - 6, "text-anchor": "middle" }, compact(d.total)));
      }
    });

    wrap.replaceChildren(el("ul", { class: "legend", style: "margin-bottom:8px" }, legendItems(false)), g);
  }

  // ---------- Commissioner breakdown ----------

  function openCommissioner(district, commissioner) {
    state.modal = { district, commissioner };
    syncURL();
    renderDetail();
    const dlg = document.getElementById("detail");
    if (!dlg.open) dlg.showModal();
    dlg.querySelector(".detail-body").scrollTop = 0;
  }

  function closeDetail() {
    const dlg = document.getElementById("detail");
    if (dlg.open) dlg.close();
  }

  function openGiftFromDetail(giftId) {
    const g = DB.gifts.find((x) => x.gift_id === giftId);
    if (!g) return;
    closeDetail();
    state.year = String(g.fiscal_year);
    state.district = String(g.district);
    state.search = "";
    document.getElementById("f-year").value = state.year;
    document.getElementById("f-district").value = state.district;
    document.getElementById("f-search").value = "";
    state.expanded = new Set([g.gift_id]);
    state.sort = { key: "district", dir: "ascending" };
    state.limit = 1000;
    syncURL();
    render();
    const rec = document.getElementById(`rec-${g.gift_id}`);
    if (rec) {
      rec.previousElementSibling.scrollIntoView({ block: "center" });
      rec.previousElementSibling.querySelector("button.expand").focus({ preventScroll: true });
    }
  }

  const LINE_NOTES = {
    committed: "Committed, counted this year",
    commitment_paid: "Paid from an earlier year's commitment",
  };

  function renderDetail() {
    const dlg = document.getElementById("detail");
    const m = state.modal;
    if (!m) return;
    const person = commissionerRows().find((p) => p.district === m.district && p.commissioner === m.commissioner);
    if (!person) { closeDetail(); return; }

    const allYears = !state.year;
    const report = currentReport();
    const scope = report ? (inProgress(report) ? `FY${report.fiscal_year}, through ${report.as_of}` : `FY${report.fiscal_year}`) : yearSpan(person.years);
    const lines = person.lines.slice().sort((a, b) => a.fiscal_year - b.fiscal_year);
    const spent = person.gift + person.travel_office + person.community_purchase + person.committed;

    // Summary figures
    const stats = allYears
      ? [["Spent", spent], ["Gifts", person.gift + person.committed], ["Travel and office", person.travel_office]]
      : [["Available", person.available], ["Spent", spent], ["Left", person.remaining]];

    // Spending lines by category, in report order or largest first
    const spendTypes = ["payment", "committed"];
    const groups = CATEGORIES.map((c) => {
      const rs = lines.filter((r) => spendTypes.includes(r.line_type) && r.category === c.key);
      if (state.modalSort === "amount") rs.sort((a, b) => a.amount - b.amount);
      return { ...c, rows: rs, total: -rs.reduce((a, r) => a + r.amount, 0) };
    }).filter((g) => g.rows.length);

    const other = lines.filter((r) => !spendTypes.includes(r.line_type) || !(r.category in person));
    const showFY = allYears;

    const lineRow = (r) => {
      const credit = r.amount > 0 && spendTypes.includes(r.line_type);
      const fund = r.fund !== "travel_discretionary" ? FUND_LABELS[r.fund] : null;
      const note = LINE_NOTES[r.line_type];
      return el("tr", {},
        showFY ? el("td", { class: "small muted" }, `FY${r.fiscal_year}`) : null,
        el("td", {},
          r.description,
          (fund || note || credit) ? el("div", { class: "muted small" },
            [credit ? "Refund, void or credit" : null, note, fund ? `From the ${fund}` : null].filter(Boolean).join(". ")) : null,
          r.gift_id && r.category === "gift"
            ? el("div", {}, el("button", { type: "button", class: "link small", onclick: () => openGiftFromDetail(r.gift_id) }, "View gift record"))
            : null),
        el("td", { class: "num" }, cents.format(-r.amount)));
    };

    const table = (rows, mapper) => el("table", { class: "lines" }, el("tbody", {}, rows.map(mapper)));

    const sortSel = el("select", {
      "aria-label": "Order of lines",
      onchange: (e) => { state.modalSort = e.target.value; renderDetail(); },
    },
      el("option", { value: "report" }, "Report order"),
      el("option", { value: "amount" }, "Largest first"));
    sortSel.value = state.modalSort;

    const download = el("button", {
      type: "button", class: "link",
      onclick: () => downloadLines(person, lines, scope),
    }, "Download these lines (CSV)");

    const years = [...person.years].sort();
    const sources = DB.reports.filter((r) => years.includes(r.fiscal_year)).sort((a, b) => a.fiscal_year - b.fiscal_year);

    dlg.replaceChildren(
      el("div", { class: "detail-head" },
        el("div", {},
          el("p", { class: "eyebrow" }, `District ${person.district}, ${scope}`),
          el("h2", { id: "detail-title" }, `Commissioner ${person.commissioner}`)),
        el("button", { type: "button", class: "close", "aria-label": "Close", onclick: closeDetail }, "×")),
      el("div", { class: "detail-body" },
        el("div", { class: "mini-tiles" }, stats.map(([label, v]) =>
          el("div", { class: "tile" }, el("div", { class: "label" }, label), el("div", { class: "value" }, dollars.format(v))))),

        el("h3", {}, "Where it went"),
        el("table", { class: "split" }, el("tbody", {},
          [...CATEGORIES.map((c) => ({ label: c.label, value: person[c.key], cls: c.swatch, style: "" })),
            { label: COMMITTED_LABEL, value: person.committed, cls: "s-gift", style: "opacity:.4" }]
            .filter((x) => Math.abs(x.value) > 0.5)
            .map((x) => el("tr", {},
              el("td", {}, el("span", { class: `swatch ${x.cls}`, style: x.style }), " ", x.label),
              el("td", { class: "num" }, dollars.format(x.value)),
              el("td", { class: "num muted" }, spent > 0 ? `${Math.round((x.value / spent) * 100)}%` : ""),
              el("td", { class: "split-bar" }, el("span", { class: x.cls, style: `width:${spent > 0 ? Math.max(0, (x.value / spent) * 100) : 0}%;${x.style}` })))))),

        el("div", { class: "section-head" },
          el("h3", {}, "Every line"),
          el("label", { class: "small muted" }, "Order ", sortSel)),
        groups.map((g) => el("details", { open: true, class: "group" },
          el("summary", {},
            el("span", { class: `swatch ${g.swatch}` }), " ",
            el("span", { class: "group-name" }, g.label),
            el("span", { class: "muted small" }, ` ${g.rows.length} ${g.rows.length === 1 ? "line" : "lines"}`),
            el("span", { class: "num group-total" }, dollars.format(g.total))),
          table(g.rows, lineRow))),
        other.length ? el("details", { class: "group" },
          el("summary", {}, el("span", { class: "group-name" }, "Budget, balances and transfers"),
            el("span", { class: "muted small" }, ` ${other.length} lines`)),
          el("table", { class: "lines" }, el("tbody", {}, other.map((r) => el("tr", {},
            showFY ? el("td", { class: "small muted" }, `FY${r.fiscal_year}`) : null,
            el("td", {}, r.description,
              el("div", { class: "muted small" }, [LINE_NOTES[r.line_type], r.fund !== "travel_discretionary" ? `From the ${FUND_LABELS[r.fund]}` : null].filter(Boolean).join(". "))),
            el("td", { class: "num" }, cents.format(r.amount))))))) : null,

        el("p", { class: "note small muted" },
          "Amounts are spending, so refunds and voids show as negative. Lines appear as the county printed them. Source: ",
          sources.map((r, i) => [i ? ", " : "", el("a", { href: r.source_url, target: "_blank", rel: "noopener" }, `FY${r.fiscal_year} report`)]),
          ". "),
        el("p", {}, download)));
  }

  function downloadLines(person, lines, scope) {
    const cols = ["fiscal_year", "district", "commissioner", "fund", "line_type", "category", "gift_id", "description", "amount", "source", "source_line"];
    const esc = (v) => /[",\n]/.test(String(v ?? "")) ? `"${String(v).replace(/"/g, '""')}"` : String(v ?? "");
    const text = [cols.join(","), ...lines.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
    const url = URL.createObjectURL(new Blob(["﻿" + text], { type: "text/csv" }));
    const name = `district-${person.district}-${person.commissioner}-${scope}`.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/-+$/, "");
    const a = el("a", { href: url, download: `${name}.csv` });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // ---------- Theme ----------

  // Follows the system setting until the viewer picks one, then remembers it.
  function setupTheme() {
    const root = document.documentElement;
    const media = matchMedia("(prefers-color-scheme: dark)");
    const buttons = document.querySelectorAll("[data-set-theme]");
    const current = () => root.getAttribute("data-theme") || (media.matches ? "dark" : "light");
    const sync = () => buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.setTheme === current())));
    const redraw = () => { if (DB) renderHistory(); };

    buttons.forEach((b) => b.addEventListener("click", () => {
      root.setAttribute("data-theme", b.dataset.setTheme);
      try { localStorage.setItem("theme", b.dataset.setTheme); } catch (e) { /* private mode */ }
      sync();
      redraw();
    }));
    media.addEventListener("change", () => { sync(); redraw(); });
    sync();
  }

  // ---------- Tooltip ----------

  const tip = () => document.getElementById("tooltip");

  function showTip(e, title, rows) {
    const t = tip();
    t.replaceChildren(
      el("div", { class: "t-title" }, title),
      ...rows.map((r) => el("div", { class: "t-row" },
        el("span", { class: `t-key ${r.cls}`, style: r.style || "" }),
        el("span", { class: "t-val" }, dollars.format(r.value)),
        el("span", { class: "t-name" }, r.name))));
    t.hidden = false;
    let x, y;
    if (e.clientX || e.clientY) { x = e.clientX; y = e.clientY; }
    else { const b = e.target.getBoundingClientRect(); x = b.left + b.width / 2; y = b.top; }
    const w = t.offsetWidth, h = t.offsetHeight;
    t.style.left = Math.min(window.innerWidth - w - 8, Math.max(8, x + 14)) + "px";
    t.style.top = (y - h - 12 < 8 ? y + 16 : y - h - 12) + "px";
  }

  function hideTip() { tip().hidden = true; }

  // ---------- Filters and URL ----------

  function setYear(v) {
    state.year = v;
    document.getElementById("f-year").value = v;
    resetPaging();
    syncURL();
    render();
  }

  function resetPaging() {
    state.limit = PAGE_SIZE;
    state.expanded.clear();
  }

  function syncURL() {
    const p = new URLSearchParams();
    if (state.year) p.set("year", state.year);
    if (state.district) p.set("district", state.district);
    if (state.search) p.set("q", state.search);
    if (state.expanded.size === 1) p.set("gift", [...state.expanded][0]);
    if (state.modal) p.set("cm", `${state.modal.district}:${state.modal.commissioner}`);
    history.replaceState(null, "", p.toString() ? `?${p}` : location.pathname);
  }

  function setupFilters() {
    const { cfg, reports } = DB;
    document.getElementById("title").textContent = cfg.title;
    document.title = `${cfg.title}, ${cfg.jurisdiction}`;
    document.getElementById("jurisdiction").textContent = cfg.jurisdiction;
    const notice = document.getElementById("notice");
    notice.textContent = cfg.notice || "";
    notice.hidden = !cfg.notice;

    // Optional credit line and link to related tools, both set in config.json.
    const credit = document.getElementById("credit");
    const link = (o) => el("a", { href: o.url, target: "_blank", rel: "noopener" }, o.link_text || o.url);
    const parts = [];
    if (cfg.credit && cfg.credit.text) parts.push([cfg.credit.text, cfg.credit.url ? [" · ", link(cfg.credit)] : []]);
    if (cfg.more && cfg.more.url) parts.push([cfg.more.text ? `${cfg.more.text} ` : "", link(cfg.more)]);
    if (parts.length) {
      credit.replaceChildren(...parts.flatMap((part, i) => [i ? " · " : "", ...part.flat()]));
      credit.hidden = false;
    }

    const latest = reports[0];
    document.getElementById("lede").textContent =
      `How much each county commissioner has to spend at their discretion, where it went, and whether each gift did what it was given for. ` +
      `Reports run from FY${reports[reports.length - 1].fiscal_year} through FY${latest.fiscal_year}, updated ${latest.as_of}.`;

    const yearSel = document.getElementById("f-year");
    yearSel.replaceChildren(
      ...reports.map((r) => el("option", { value: r.fiscal_year }, inProgress(r) ? `FY${r.fiscal_year} (to ${r.as_of})` : `FY${r.fiscal_year}`)),
      el("option", { value: "" }, "All years"));

    const districts = [...new Set(DB.ledger.map((r) => r.district))].sort((a, b) => a - b);
    const distSel = document.getElementById("f-district");
    distSel.replaceChildren(el("option", { value: "" }, "All districts"), ...districts.map((d) => el("option", { value: d }, `District ${d}`)));

    const p = new URLSearchParams(location.search);
    state.year = p.has("year") ? p.get("year") : String(latest.fiscal_year);
    state.district = p.get("district") || "";
    state.search = p.get("q") || "";
    const linked = p.get("gift") && DB.gifts.find((g) => g.gift_id === p.get("gift"));
    if (linked) {
      state.year = String(linked.fiscal_year);
      state.district = String(linked.district);
      state.expanded.add(linked.gift_id);
      state.sort = { key: "district", dir: "ascending" };
    }
    yearSel.value = state.year;
    distSel.value = state.district;
    document.getElementById("f-search").value = state.search;

    yearSel.addEventListener("change", (e) => setYear(e.target.value));
    distSel.addEventListener("change", (e) => { state.district = e.target.value; resetPaging(); syncURL(); render(); });
    let timer;
    document.getElementById("f-search").addEventListener("input", (e) => {
      clearTimeout(timer);
      timer = setTimeout(() => { state.search = e.target.value; resetPaging(); syncURL(); renderGifts(); }, 150);
    });
    document.getElementById("filters").addEventListener("submit", (e) => e.preventDefault());
    let resizeTimer, lastWidth = window.innerWidth;
    window.addEventListener("resize", () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        if (window.innerWidth !== lastWidth) { lastWidth = window.innerWidth; renderHistory(); }
      }, 150);
    });
    const dlg = document.getElementById("detail");
    dlg.addEventListener("close", () => { state.modal = null; syncURL(); });
    dlg.addEventListener("click", (e) => { if (e.target === dlg) closeDetail(); });
    document.getElementById("history-toggle").addEventListener("click", () => {
      state.showHistoryTable = !state.showHistoryTable;
      renderHistory();
    });

    document.getElementById("sources").replaceChildren(
      ...[...reports].reverse().map((r) => el("li", {}, el("a", { href: r.source_url, target: "_blank", rel: "noopener" }, `FY${r.fiscal_year} spending report`), ` (as of ${r.as_of})`)),
      ...(cfg.sources || []).map((s) => el("li", {}, el("a", { href: s.url, target: "_blank", rel: "noopener" }, s.label))));
    document.getElementById("downloads").replaceChildren(
      el("li", {}, el("a", { href: cfg.data.gifts, download: "" }, "Gift register (CSV)"), ", one row per gift"),
      el("li", {}, el("a", { href: cfg.data.ledger, download: "" }, "Spending ledger (CSV)"), ", every line of every report"));
  }

  setupTheme();

  load()
    .then(() => {
      setupFilters();
      render();
      const cm = new URLSearchParams(location.search).get("cm");
      const hit = cm && /^(\d+):(.+)$/.exec(cm);
      if (hit) openCommissioner(+hit[1], hit[2]);
      const open = document.querySelector(".record");
      if (open) open.previousElementSibling.scrollIntoView({ block: "center" });
    })
    .catch((err) => {
      document.querySelector(".page").append(el("p", { class: "notice" }, "The data files could not be loaded. ", String(err)));
      console.error(err);
    });
})();
