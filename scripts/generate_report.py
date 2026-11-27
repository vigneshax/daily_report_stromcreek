#!/usr/bin/env python3
"""
Generates the Storm Creek daily OCR accuracy/error report from a CSV export
of the "Live Orders" sheet in the tracker spreadsheet:
https://docs.google.com/spreadsheets/d/1SGFQmGZ59tKD4tdWKG3o1acZsZtZM85kN3sbUKUSGH4

Usage:
    python3 generate_report.py <live_orders.csv> <output_report.md> [report_date]

Required columns: Date, Processed By, Order Status, PO Number, Distributor,
AX Comments, Issue related. Optional: Secondary Cat for OCR Issue, Dev Notes, Status.

Definitions
- Reviewed order: a dated row whose "Issue related" is filled in (blank rows are
  duplicates / rejected files / not yet reviewed and are excluded).
- Accuracy: Accurate Orders / reviewed orders.
- OCR accuracy: 1 - (OCR-side issues / reviewed orders). OCR-side = "OCR Issue"
  and "OCR / Email Format". PO Issue (bad/missing info on the customer PO) and
  Storm Creek Issue are not counted against the OCR engine.
- "Latest day" = most recent date in the sheet. Comparison baseline = the 7
  logged days before it.
"""
import csv
import datetime
import re
import sys
from collections import Counter, defaultdict

ACCURATE = "Accurate Orders"
OCR_CATS = ("OCR Issue", "OCR / Email Format")
ISSUE_CATS = ("OCR Issue", "OCR / Email Format", "PO Issue", "Storm Creek Issue")

# Ordered: first match is the "primary" theme, but an order can carry several.
THEME_BUCKETS = [
    ("Ship Method / Carrier", r"ship(ping)? ?method|carrier|\bFF\b|freight"),
    ("Account / Shipper Number", r"account|acct|shipper number|shipper no"),
    ("STC / Reporting Group (AIM)", r"\bSTC\b|state to credit|reporting group|\bRG\b|\bAIM\b|facilis"),
    ("Order Type / PSST", r"order type|psst"),
    ("Ship To / Address", r"ship ?to|shipping address|address|secondline|second line|dropship|split ship"),
    ("Product Color", r"colou?r|\bnavy\b|\bblack\b|\bblue\b|\bgr[ae]y\b|\bred\b|\bwhite\b|\bshade"),
    ("Product Size", r"\bsize\b|\b[2-5]?xl\b|\bS/M\b|\bM/L\b|\bL/XL\b"),
    ("Product / Part ID / Line", r"product ?id|part ?id|product code|\bsku\b|\bline\b|item (number|#|no)"),
    ("Quantity / PO Total / Price", r"\bqty\b|quantity|po total|price|amount"),
    ("PO Number", r"po ?number|po ?#|po no"),
    ("PO Contact / Email", r"po contact|contact|e-?mail|po mail"),
    ("Company Name", r"company name"),
    ("In-Hands / Ship Date", r"in.?hands|ship date|due date|\bIHD\b"),
]


def parse_date(s):
    m, d, y = s.strip().split("/")
    return datetime.date(int(y), int(m), int(d))


def load_rows(path):
    rows = []
    for r in csv.DictReader(open(path, newline="", encoding="utf-8")):
        if not (r.get("Date") or "").strip():
            continue
        try:
            r["_date"] = parse_date(r["Date"])
        except ValueError:
            continue
        r["_cat"] = (r.get("Issue related") or "").strip()
        r["_dist"] = (r.get("Distributor") or "").strip() or "(blank)"
        r["_comment"] = re.sub(r"\s+", " ", (r.get("AX Comments") or "").strip())
        rows.append(r)
    return rows


def themes_of(comment):
    out = [name for name, pat in THEME_BUCKETS if re.search(pat, comment, re.I)]
    return out or ["Other / Unclassified"]


def stats(rows):
    rev = [r for r in rows if r["_cat"]]
    n = len(rev)
    acc = sum(r["_cat"] == ACCURATE for r in rev)
    ocr = sum(r["_cat"] in OCR_CATS for r in rev)
    po = sum(r["_cat"] == "PO Issue" for r in rev)
    sc = sum(r["_cat"] == "Storm Creek Issue" for r in rev)
    return dict(n=n, acc=acc, ocr=ocr, po=po, sc=sc,
                acc_pct=acc / n * 100 if n else 0.0,
                ocr_acc_pct=(1 - ocr / n) * 100 if n else 0.0,
                ocr_rate=ocr / n * 100 if n else 0.0)


def theme_counts(rows, cats):
    c = Counter()
    for r in rows:
        if r["_cat"] in cats:
            for t in themes_of(r["_comment"]):
                c[t] += 1
    return c


def pct(x):
    return f"{x:.1f}%"


def delta(a, b):
    d = a - b
    arrow = "▲" if d > 0.05 else ("▼" if d < -0.05 else "▬")
    return f"{arrow} {d:+.1f} pts"


def render(rows, report_date):
    dates = sorted({r["_date"] for r in rows})
    latest = dates[-1]
    prev7 = dates[-8:-1]
    prev28 = dates[-29:-1]
    by_date = defaultdict(list)
    for r in rows:
        by_date[r["_date"]].append(r)

    L_rows = by_date[latest]
    P7_rows = [r for d in prev7 for r in by_date[d]]
    P28_rows = [r for d in prev28 for r in by_date[d]]
    month_rows = [r for r in rows if (r["_date"].year, r["_date"].month) == (latest.year, latest.month)]
    S_L, S_7, S_28, S_M, S_all = map(stats, (L_rows, P7_rows, P28_rows, month_rows, rows))

    out = []
    w = out.append
    w(f"# Storm Creek OCR Daily Report — {report_date}")
    w("")
    w(f"Source: \"Live Orders\" tab · {len(rows)} logged rows · {dates[0]} → {latest} · "
      f"latest day in sheet: **{latest} ({latest:%A})**")
    if (report_date - latest).days > 1:
        w("")
        w(f"> Note: no rows logged after {latest}. The report covers {latest} as the latest day.")
    w("")

    # ---------------- Headline
    w("## 1. Headline")
    w("")
    w("| Metric | Latest day | Prior 7 days | Change | Month-to-date | All-time |")
    w("|---|---|---|---|---|---|")
    w(f"| Reviewed orders | {S_L['n']} | {S_7['n']} | | {S_M['n']} | {S_all['n']} |")
    w(f"| Overall accuracy | **{pct(S_L['acc_pct'])}** | {pct(S_7['acc_pct'])} | "
      f"{delta(S_L['acc_pct'], S_7['acc_pct'])} | {pct(S_M['acc_pct'])} | {pct(S_all['acc_pct'])} |")
    w(f"| OCR accuracy (excl. PO-side issues) | **{pct(S_L['ocr_acc_pct'])}** | {pct(S_7['ocr_acc_pct'])} | "
      f"{delta(S_L['ocr_acc_pct'], S_7['ocr_acc_pct'])} | {pct(S_M['ocr_acc_pct'])} | {pct(S_all['ocr_acc_pct'])} |")
    w(f"| OCR issues | {S_L['ocr']} | {S_7['ocr']} ({S_7['ocr']/max(len(prev7),1):.1f}/day) | | {S_M['ocr']} | {S_all['ocr']} |")
    w(f"| PO issues (customer-side) | {S_L['po']} | {S_7['po']} | | {S_M['po']} | {S_all['po']} |")
    w(f"| Storm Creek issues | {S_L['sc']} | {S_7['sc']} | | {S_M['sc']} | {S_all['sc']} |")
    w("")

    # Top call-outs
    tL = theme_counts(L_rows, OCR_CATS)
    t7 = theme_counts(P7_rows, OCR_CATS)
    t28 = theme_counts(P28_rows, OCR_CATS)
    dist_L = Counter(r["_dist"] for r in L_rows if r["_cat"] in OCR_CATS)
    callouts = []
    if tL:
        top, cnt = tL.most_common(1)[0]
        base = t7.get(top, 0) / max(len(prev7), 1)
        callouts.append(f"Top OCR error theme on {latest}: **{top}** ({cnt} orders vs {base:.1f}/day avg prior week).")
    if dist_L:
        d, c = dist_L.most_common(1)[0]
        if c >= 3:
            callouts.append(f"**{d}** alone produced {c} of {S_L['ocr']} OCR issues on {latest} — likely one template/format problem.")
    spikes = []
    for t, c in tL.items():
        base = t7.get(t, 0) / max(len(prev7), 1)
        if c >= 3 and c >= 2 * max(base, 0.5):
            spikes.append(f"{t} ({c} vs {base:.1f}/day)")
    if spikes:
        callouts.append("Spikes vs prior-week daily average: " + "; ".join(spikes) + ".")
    if callouts:
        w("**Call-outs**")
        w("")
        for c in callouts:
            w(f"- {c}")
        w("")

    # ---------------- Weekly trend
    w("## 2. Trend")
    w("")
    w("### Weekly")
    w("")
    w("| Week starting | Days | Reviewed | Accuracy | OCR accuracy | OCR issues | PO issues |")
    w("|---|---|---|---|---|---|---|")
    weeks = defaultdict(list)
    for r in rows:
        ws = r["_date"] - datetime.timedelta(days=r["_date"].weekday())
        weeks[ws].append(r)
    for ws in sorted(weeks):
        s = stats(weeks[ws])
        nd = len({r["_date"] for r in weeks[ws]})
        w(f"| {ws} | {nd} | {s['n']} | {pct(s['acc_pct'])} | {pct(s['ocr_acc_pct'])} | {s['ocr']} | {s['po']} |")
    w("")
    w("### Last 10 logged days")
    w("")
    w("| Date | Reviewed | Accuracy | OCR accuracy | OCR | PO | Storm Creek |")
    w("|---|---|---|---|---|---|---|")
    for d in dates[-10:]:
        s = stats(by_date[d])
        w(f"| {d} ({d:%a}) | {s['n']} | {pct(s['acc_pct'])} | {pct(s['ocr_acc_pct'])} | {s['ocr']} | {s['po']} | {s['sc']} |")
    w("")

    # ---------------- Error categorization
    w("## 3. OCR error categories (what to fix)")
    w("")
    w("Themes are classified from reviewer \"AX Comments\" on OCR-side issues; one order can carry several.")
    w("")
    w(f"| Theme | Latest day | Prior 7 days | Prior 28 days | 7-day share | Trend (7d vs 28d rate) |")
    w("|---|---|---|---|---|---|")
    tot7 = max(sum(1 for r in P7_rows if r["_cat"] in OCR_CATS), 1)
    names = sorted(set(tL) | set(t7) | set(t28), key=lambda t: (-t7.get(t, 0), -tL.get(t, 0)))
    for t in names:
        r7 = t7.get(t, 0) / max(len(prev7), 1)
        r28 = t28.get(t, 0) / max(len(prev28), 1)
        if r28 == 0 and r7 == 0:
            tr = "new" if tL.get(t) else "—"
        elif r28 == 0:
            tr = "new ▲"
        else:
            ch = (r7 - r28) / r28 * 100
            tr = ("▲ " if ch > 15 else "▼ " if ch < -15 else "▬ ") + f"{ch:+.0f}%"
        w(f"| {t} | {tL.get(t, 0)} | {t7.get(t, 0)} | {t28.get(t, 0)} | {t7.get(t, 0)/tot7*100:.0f}% | {tr} |")
    w("")

    # ---------------- Latest-day OCR issues
    w(f"## 4. OCR issues logged on {latest} (action list)")
    w("")
    ocr_L = [r for r in L_rows if r["_cat"] in OCR_CATS]
    if not ocr_L:
        w("None.")
    else:
        w("| # | Distributor | PO Number | Theme | Reviewer comment |")
        w("|---|---|---|---|---|")
        ocr_L.sort(key=lambda r: (-dist_L[r["_dist"]], r["_dist"]))
        for i, r in enumerate(ocr_L, 1):
            c = r["_comment"].replace("|", "/")
            w(f"| {i} | {r['_dist']} | {r.get('PO Number','').strip()} | {', '.join(themes_of(r['_comment']))} | {c[:220]} |")
    w("")

    # ---------------- Accounts / distributors
    w("## 5. Accounts / distributors")
    w("")
    last14 = dates[-14:]
    prior_win = dates[-42:-14]
    R14 = [r for d in last14 for r in by_date[d]]
    RP = [r for d in prior_win for r in by_date[d]]
    g14, gP = defaultdict(list), defaultdict(list)
    for r in R14:
        g14[r["_dist"]].append(r)
    for r in RP:
        gP[r["_dist"]].append(r)
    rowsD = []
    for dname, rs in g14.items():
        s = stats(rs)
        if s["n"] < 8 or dname == "(blank)":
            continue
        sp = stats(gP.get(dname, []))
        top = theme_counts(rs, OCR_CATS).most_common(2)
        rowsD.append((s, sp, dname, top))
    rowsD.sort(key=lambda x: (x[0]["ocr_acc_pct"], -x[0]["ocr"]))
    w(f"### Lowest OCR accuracy — last 14 logged days ({last14[0]} → {latest}, accounts with ≥8 orders)")
    w("")
    w("| Distributor | Orders | OCR issues | OCR accuracy | Prior 4 wks OCR acc. | Change | Main OCR themes |")
    w("|---|---|---|---|---|---|---|")
    for s, sp, dname, top in rowsD[:12]:
        if s["ocr"] == 0:
            continue
        prior = pct(sp["ocr_acc_pct"]) if sp["n"] >= 5 else "n/a"
        ch = delta(s["ocr_acc_pct"], sp["ocr_acc_pct"]) if sp["n"] >= 5 else ""
        w(f"| {dname} | {s['n']} | {s['ocr']} | {pct(s['ocr_acc_pct'])} | {prior} | {ch} | "
          f"{', '.join(f'{t} ({c})' for t, c in top)} |")
    w("")

    # improved / regressed
    movers = []
    for dname in set(g14) | set(gP):
        s, sp = stats(g14.get(dname, [])), stats(gP.get(dname, []))
        if s["n"] >= 8 and sp["n"] >= 8 and dname != "(blank)":
            movers.append((s["ocr_acc_pct"] - sp["ocr_acc_pct"], dname, s, sp))
    movers.sort()
    worse = [m for m in movers if m[0] <= -5][:6]
    better = [m for m in reversed(movers) if m[0] >= 5][:6]
    w("### Biggest movers (last 14 days vs the 4 weeks before)")
    w("")
    if worse:
        w("Regressed: " + "; ".join(f"**{d}** {pct(sp['ocr_acc_pct'])} → {pct(s['ocr_acc_pct'])}" for _, d, s, sp in worse))
        w("")
    if better:
        w("Improved: " + "; ".join(f"**{d}** {pct(sp['ocr_acc_pct'])} → {pct(s['ocr_acc_pct'])}" for _, d, s, sp in better))
        w("")
    if not worse and not better:
        w("No account moved ≥5 pts.")
        w("")

    # Recurring offenders all-time
    gall = defaultdict(list)
    for r in rows:
        gall[r["_dist"]].append(r)
    rec = []
    for dname, rs in gall.items():
        s = stats(rs)
        if dname == "(blank)" or s["ocr"] < 10:
            continue
        days_hit = len({r["_date"] for r in rs if r["_cat"] in OCR_CATS})
        rec.append((s["ocr"], dname, s, days_hit, theme_counts(rs, OCR_CATS).most_common(2)))
    rec.sort(reverse=True)
    w("### Chronic accounts (most OCR issues since tracking began)")
    w("")
    w("| Distributor | Orders | OCR issues | OCR accuracy | Days with an OCR issue | Main themes |")
    w("|---|---|---|---|---|---|")
    for o, dname, s, dh, top in rec[:10]:
        w(f"| {dname} | {s['n']} | {o} | {pct(s['ocr_acc_pct'])} | {dh} | {', '.join(f'{t} ({c})' for t, c in top)} |")
    w("")

    # ---------------- PO-side issues
    w("## 6. Customer-side (PO Issue) themes — not OCR defects, but drive manual work")
    w("")
    pL = theme_counts(L_rows, ("PO Issue",))
    p7 = theme_counts(P7_rows, ("PO Issue",))
    w("| Theme | Latest day | Prior 7 days |")
    w("|---|---|---|")
    for t in sorted(set(pL) | set(p7), key=lambda t: -p7.get(t, 0) - pL.get(t, 0))[:8]:
        w(f"| {t} | {pL.get(t, 0)} | {p7.get(t, 0)} |")
    w("")

    # ---------------- Associates
    w("## 7. Reviewer volume & flag rate (last 7 logged days incl. latest)")
    w("")
    w("| Processed By | Reviewed | Accurate | OCR flagged | PO flagged |")
    w("|---|---|---|---|---|")
    ga = defaultdict(list)
    for d in dates[-7:]:
        for r in by_date[d]:
            if (r.get("Processed By") or "").strip():
                ga[r["Processed By"].strip()].append(r)
    for a, rs in sorted(ga.items(), key=lambda x: -len(x[1])):
        s = stats(rs)
        w(f"| {a} | {s['n']} | {pct(s['acc_pct'])} | {s['ocr']} ({pct(s['ocr_rate'])}) | {s['po']} |")
    w("")
    w("_Large gaps in OCR-flag rate between reviewers can point to inconsistent review standards rather than OCR quality._")
    w("")

    # ---------------- Dev notes
    notes = [r for r in rows if (r.get("Dev Notes") or "").strip() or (r.get("Status") or "").strip()]
    if notes:
        st = Counter((r.get("Status") or "").strip() or "(no status)" for r in notes)
        w("## 8. Dev notes / fix status in sheet")
        w("")
        w(f"{len(notes)} rows carry Dev Notes or a Status: " + ", ".join(f"{k}: {v}" for k, v in st.most_common()) + ".")
        recent_notes = [r for r in notes if r["_date"] >= dates[-14] and (r.get("Dev Notes") or "").strip()]
        for r in recent_notes[:10]:
            w(f"- {r['_date']} · {r['_dist']} · {r['Dev Notes'].strip()[:200]} ({(r.get('Status') or '').strip() or 'no status'})")
        w("")

    return "\n".join(out)


def main():
    if len(sys.argv) not in (3, 4):
        print(__doc__)
        sys.exit(1)
    rows = load_rows(sys.argv[1])
    report_date = (datetime.date.fromisoformat(sys.argv[3]) if len(sys.argv) == 4
                   else datetime.date.today())
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        f.write(render(rows, report_date) + "\n")
    print(f"Wrote report to {sys.argv[2]}")


if __name__ == "__main__":
    main()
