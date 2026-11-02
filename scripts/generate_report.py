#!/usr/bin/env python3
"""
Generates the Storm Creek daily OCR accuracy/error report from a CSV export
of the "Live Orders" sheet in the tracker spreadsheet:
https://docs.google.com/spreadsheets/d/1SGFQmGZ59tKD4tdWKG3o1acZsZtZM85kN3sbUKUSGH4

Usage:
    python3 generate_report.py <live_orders.csv> <output_report.md>

The CSV must have the header:
Sr No,Date,Week#,Allotment,Processed By,Message ID,Order Status,PO Number,
Line,Product ID,Distributor,AX Comments,Issue related,TID
"""
import csv
import re
import sys
import datetime
from collections import Counter, defaultdict

ISSUE_CATEGORIES = ("OCR Issue", "PO Issue", "Storm Creek Issue", "OCR / Email Format")

THEME_BUCKETS = {
    "STC (State To Credit)": r"\bSTC\b|state to credit",
    "Reporting Group / AIM / Facilis": r"reporting group|\bRG:?\b|\bAIM\b|facilis",
    "Ship To / Address": r"ship ?to|shipping address|secondline|second line",
    "Account Number / Shipping Acct ID": r"account number|acct|account id",
    "PO Number": r"po number|po#|po #",
    "PO Contact Email/Mail": r"po contact|po mail|contact email",
    "Quantity/Qty": r"\bqty\b|quantity",
    "Color/Size": r"\bcolor\b|\bsize\b",
    "Ship Method": r"ship method|shipping method|carrier",
    "Company Name": r"company name",
    "Product ID / Part ID / SKU": r"product id|part id|\bsku\b",
    "Ship Date": r"ship date",
    "Order Type (blank/sample/etc.)": r"order type",
    "PSST": r"\bpsst\b",
    "FF / PO Total / Pricing": r"\bFF\b|po total|pricing",
}


def parse_date(s):
    m, d, y = s.strip().split("/")
    return datetime.date(int(y), int(m), int(d))


def load_rows(csv_path):
    rows = [r for r in csv.DictReader(open(csv_path, newline="", encoding="utf-8"))]
    rows = [r for r in rows if r["Date"].strip()]
    for r in rows:
        r["_date"] = parse_date(r["Date"])
    return rows


def theme_breakdown(issue_rows):
    counts = Counter()
    for r in issue_rows:
        c = r["AX Comments"]
        for name, pat in THEME_BUCKETS.items():
            if re.search(pat, c, re.IGNORECASE):
                counts[name] += 1
    return counts


def daily_trend(rows):
    by_date = defaultdict(list)
    for r in rows:
        by_date[r["_date"]].append(r)
    out = []
    for d in sorted(by_date):
        recs = by_date[d]
        total = len(recs)
        acc = sum(1 for r in recs if r["Issue related"] == "Accurate Orders")
        ocr = sum(1 for r in recs if r["Issue related"] == "OCR Issue")
        po = sum(1 for r in recs if r["Issue related"] == "PO Issue")
        sc = sum(1 for r in recs if r["Issue related"] == "Storm Creek Issue")
        out.append(
            dict(date=d, total=total, accurate=acc, ocr=ocr, po=po, sc=sc,
                 accuracy_pct=(acc / total * 100 if total else 0))
        )
    return out


def distributor_breakdown(rows, min_orders=30):
    by_dist = defaultdict(list)
    for r in rows:
        if r["Distributor"].strip():
            by_dist[r["Distributor"]].append(r)
    out = []
    for dist, recs in by_dist.items():
        if len(recs) < min_orders:
            continue
        total = len(recs)
        acc = sum(1 for r in recs if r["Issue related"] == "Accurate Orders")
        out.append(dict(distributor=dist, total=total, accurate=acc,
                         accuracy_pct=acc / total * 100))
    out.sort(key=lambda x: x["accuracy_pct"])
    return out


def associate_breakdown(rows):
    by_assoc = defaultdict(list)
    for r in rows:
        if r["Processed By"].strip():
            by_assoc[r["Processed By"]].append(r)
    out = []
    for assoc, recs in by_assoc.items():
        total = len(recs)
        acc = sum(1 for r in recs if r["Issue related"] == "Accurate Orders")
        out.append(dict(associate=assoc, total=total, accurate=acc,
                         accuracy_pct=acc / total * 100))
    out.sort(key=lambda x: -x["total"])
    return out


def weekly_trend(rows):
    by_wk = defaultdict(list)
    for r in rows:
        by_wk[r["_date"].isocalendar()[:2]].append(r)
    out = []
    for wk in sorted(by_wk):
        recs = by_wk[wk]
        lab = [r for r in recs if r["Issue related"]]
        acc = sum(1 for r in recs if r["Issue related"] == "Accurate Orders")
        out.append(dict(week=f"{wk[0]}-W{wk[1]:02d}", start=min(r["_date"] for r in recs),
                        total=len(recs), labeled=len(lab), accurate=acc,
                        pct=acc / len(lab) * 100 if lab else 0))
    return out


def window_section(title, rows_w, rows_prev, lines):
    """Themes + distributors for a window, with comparison to the window before it."""
    iss = [r for r in rows_w if r["Issue related"] in ISSUE_CATEGORIES]
    iss_prev = [r for r in rows_prev if r["Issue related"] in ISSUE_CATEGORIES]
    t, tp = theme_breakdown(iss), theme_breakdown(iss_prev)
    lines.append(f"## {title}")
    lines.append("")
    lines.append(f"{len(iss)} flagged of {len(rows_w)} orders (prior window: {len(iss_prev)} of {len(rows_prev)}).")
    lines.append("")
    lines.append("| Theme | Count | % of flagged | Prior window % | Change (pts) |")
    lines.append("|---|---|---|---|---|")
    for name, c in t.most_common():
        pct = c / len(iss) * 100 if iss else 0
        pp = tp[name] / len(iss_prev) * 100 if iss_prev else 0
        lines.append(f"| {name} | {c} | {pct:.1f}% | {pp:.1f}% | {pct-pp:+.1f} |")
    lines.append("")
    d = distributor_breakdown(rows_w, min_orders=8)
    lines.append("Worst accounts in window (8+ orders):")
    lines.append("")
    lines.append("| Distributor | Orders | Accuracy % |")
    lines.append("|---|---|---|")
    for x in d[:8]:
        lines.append(f"| {x['distributor']} | {x['total']} | {x['accuracy_pct']:.1f}% |")
    lines.append("")


def render_report(rows, report_date):
    trend = daily_trend(rows)
    issue_rows = [r for r in rows if r["Issue related"] in ISSUE_CATEGORIES]
    themes = theme_breakdown(issue_rows)
    dists = distributor_breakdown(rows)
    assocs = associate_breakdown(rows)

    total = len(rows)
    acc_total = sum(1 for r in rows if r["Issue related"] == "Accurate Orders")
    overall_pct = acc_total / total * 100 if total else 0

    recent = trend[-3:] if len(trend) >= 3 else trend
    recent_total = sum(d["total"] for d in recent)
    recent_acc = sum(d["accurate"] for d in recent)
    recent_pct = recent_acc / recent_total * 100 if recent_total else 0

    first = trend[:3] if len(trend) >= 3 else trend
    first_total = sum(d["total"] for d in first)
    first_acc = sum(d["accurate"] for d in first)
    first_pct = first_acc / first_total * 100 if first_total else 0

    lines = []
    lines.append(f"# Storm Creek OCR Daily Report — {report_date}")
    lines.append("")
    lines.append(f"Data source: Live Orders sheet, {total} orders logged, "
                 f"{trend[0]['date']} to {trend[-1]['date']}.")
    lines.append("")
    lines.append("## Headline")
    lines.append(f"- Overall accuracy (all logged orders): **{overall_pct:.1f}%** "
                 f"({acc_total}/{total})")
    lines.append(f"- Last 3 logged days: **{recent_pct:.1f}%** ({recent_acc}/{recent_total})")
    lines.append(f"- First 3 logged days: **{first_pct:.1f}%** ({first_acc}/{first_total})")
    trend_word = "improved" if recent_pct > first_pct else "declined"
    lines.append(f"- Trend: accuracy has **{trend_word}** by "
                 f"{abs(recent_pct - first_pct):.1f} points since the start of this window.")
    lines.append("")

    lines.append("## Daily trend")
    lines.append("")
    lines.append("| Date | Orders | Accurate | Accuracy % | OCR Issue | PO Issue | Storm Creek Issue |")
    lines.append("|---|---|---|---|---|---|---|")
    for d in trend:
        lines.append(f"| {d['date']} | {d['total']} | {d['accurate']} | "
                     f"{d['accuracy_pct']:.1f}% | {d['ocr']} | {d['po']} | {d['sc']} |")
    lines.append("")

    wk = weekly_trend(rows)
    lines.append("## Weekly trend (accuracy on labeled orders)")
    lines.append("")
    lines.append("| ISO week | Starts | Orders | Labeled | Accuracy % |")
    lines.append("|---|---|---|---|---|")
    for w in wk:
        lines.append(f"| {w['week']} | {w['start']} | {w['total']} | {w['labeled']} | {w['pct']:.1f}% |")
    lines.append("")
    unl = [r for r in rows if not r["Issue related"]]
    lines.append(f"Note: {len(unl)} orders have no 'Issue related' label "
                 f"(mostly rejected/duplicate files: {Counter(r['Order Status'] for r in unl).most_common(3)}). "
                 "Daily accuracy % below counts them in the denominator, as in earlier reports.")
    lines.append("")
    last_day = trend[-1]["date"]
    days = sorted({r["_date"] for r in rows})
    w7, p7 = days[-7:], days[-14:-7]
    window_section(f"Last 7 logged days ({w7[0]} to {w7[-1]}) vs prior 7",
                   [r for r in rows if r["_date"] in w7], [r for r in rows if r["_date"] in p7], lines)
    day_rows = [r for r in rows if r["_date"] == last_day]
    di = [r for r in day_rows if r["Issue related"] in ISSUE_CATEGORIES]
    lines.append(f"## Latest logged day: {last_day}")
    lines.append("")
    lines.append(f"{len(day_rows)} orders, {trend[-1]['accuracy_pct']:.1f}% accurate, {len(di)} flagged.")
    lines.append("")
    for r in di[:25]:
        lines.append(f"- {r['Distributor']} / PO {r['PO Number']} ({r['Issue related']}, {r['Processed By']}): {r['AX Comments'][:140]}")
    lines.append("")
    lines.append("## Error categorization (recurring themes in flagged orders)")
    lines.append("")
    lines.append(f"Out of {len(issue_rows)} flagged orders, comment themes break down as "
                 "(a single order can carry more than one theme):")
    lines.append("")
    lines.append("| Theme | Count | % of flagged orders |")
    lines.append("|---|---|---|")
    for name, count in themes.most_common():
        lines.append(f"| {name} | {count} | {count/len(issue_rows)*100:.1f}% |")
    lines.append("")

    lines.append("## Accounts/distributors needing the most attention")
    lines.append("")
    lines.append("(Accounts with 30+ orders in the logged window, sorted worst first)")
    lines.append("")
    lines.append("| Distributor | Orders | Accuracy % |")
    lines.append("|---|---|---|")
    for d in dists[:10]:
        lines.append(f"| {d['distributor']} | {d['total']} | {d['accuracy_pct']:.1f}% |")
    lines.append("")

    lines.append("## Associate accuracy (orders processed)")
    lines.append("")
    lines.append("| Processed By | Orders | Accuracy % |")
    lines.append("|---|---|---|")
    for a in assocs:
        lines.append(f"| {a['associate']} | {a['total']} | {a['accuracy_pct']:.1f}% |")
    lines.append("")

    return "\n".join(lines)


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    csv_path, out_path = sys.argv[1], sys.argv[2]
    rows = load_rows(csv_path)
    report_date = datetime.date.today().isoformat()
    report = render_report(rows, report_date)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"Wrote report to {out_path}")


if __name__ == "__main__":
    main()
