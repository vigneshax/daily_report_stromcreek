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
VALID_CATEGORIES = ISSUE_CATEGORIES + ("Accurate Orders",)

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
}


EXCLUDED = Counter()


def parse_date(s):
    m, d, y = s.strip().split("/")
    return datetime.date(int(y), int(m), int(d))


def load_rows(csv_path):
    rows = [r for r in csv.DictReader(open(csv_path, newline="", encoding="utf-8"))]
    rows = [r for r in rows if r["Date"].strip()]
    # Rows with no Issue-related label are duplicates / rejected files / no-PO
    # entries; they are excluded from accuracy so they don't count as accurate or wrong.
    global EXCLUDED
    EXCLUDED = Counter(
        (r["AX Comments"].strip() or r["Order Status"].strip() or "(blank)")[:30]
        for r in rows if r["Issue related"].strip() not in VALID_CATEGORIES)
    rows = [r for r in rows if r["Issue related"].strip() in VALID_CATEGORIES]
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
        ocr = sum(1 for r in recs if r["Issue related"] in ("OCR Issue", "OCR / Email Format"))
        po = sum(1 for r in recs if r["Issue related"] == "PO Issue")
        sc = sum(1 for r in recs if r["Issue related"] == "Storm Creek Issue")
        out.append(
            dict(date=d, total=total, accurate=acc, ocr=ocr, po=po, sc=sc,
                 accuracy_pct=(acc / total * 100 if total else 0))
        )
    return out


def distributor_breakdown(rows, min_orders=15):
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


def pct(recs):
    return sum(1 for r in recs if r["Issue related"] == "Accurate Orders") / len(recs) * 100 if recs else 0


def latest_day_section(rows, trend):
    """Focus of the daily report: the most recent logged day vs. recent baselines."""
    last = trend[-1]["date"]
    day = [r for r in rows if r["_date"] == last]
    prev5 = [r for r in rows if r["_date"] in {d["date"] for d in trend[-6:-1]}]
    wk = [r for r in rows if r["_date"] > last - datetime.timedelta(days=7)]
    pwk = [r for r in rows if last - datetime.timedelta(days=14) < r["_date"] <= last - datetime.timedelta(days=7)]
    flagged = [r for r in day if r["Issue related"] in ISSUE_CATEGORIES]
    L = [f"## Latest day: {last}", ""]
    L.append(f"- Accuracy: **{pct(day):.1f}%** ({sum(1 for r in day if r['Issue related']=='Accurate Orders')}/{len(day)})")
    L.append(f"- Previous 5 logged days: {pct(prev5):.1f}%  (delta {pct(day)-pct(prev5):+.1f} pts)")
    L.append(f"- Last 7 days: {pct(wk):.1f}% vs prior 7 days: {pct(pwk):.1f}%  (delta {pct(wk)-pct(pwk):+.1f} pts)")
    L.append("")
    if flagged:
        L.append("Themes in the day's flagged orders:")
        L.append("")
        for name, c in theme_breakdown(flagged).most_common(6):
            wk_flag = [r for r in wk if r["Issue related"] in ISSUE_CATEGORIES]
            L.append(f"- {name}: {c} (7-day avg/day: {theme_breakdown(wk_flag)[name]/max(1,len({r['_date'] for r in wk})):.1f})")
        L.append("")
        L.append("Distributors with flagged orders that day: " + ", ".join(
            f"{d} ({c})" for d, c in Counter(r["Distributor"] for r in flagged).most_common(8)))
        L.append("")
    L.append("Associates that day: " + ", ".join(
        f"{a} {pct([r for r in day if r['Processed By']==a]):.0f}% ({sum(1 for r in day if r['Processed By']==a)})"
        for a in sorted({r["Processed By"] for r in day if r["Processed By"].strip()})))
    L.append("")
    return L


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
    if EXCLUDED:
        lines.append(f"Excluded from accuracy (no Issue-related label): {sum(EXCLUDED.values())} rows "
                     f"(" + ", ".join(f"{k}: {v}" for k, v in EXCLUDED.most_common(4)) + ").")
        lines.append("")
    lines.extend(latest_day_section(rows, trend))
    lines.append("## Headline")
    lines.append(f"- Overall accuracy (all logged orders): **{overall_pct:.1f}%** "
                 f"({acc_total}/{total})")
    lines.append(f"- Last 3 logged days: **{recent_pct:.1f}%** ({recent_acc}/{recent_total})")
    lines.append(f"- First 3 logged days: **{first_pct:.1f}%** ({first_acc}/{first_total})")
    trend_word = "improved" if recent_pct > first_pct else "declined"
    lines.append(f"- Trend: accuracy has **{trend_word}** by "
                 f"{abs(recent_pct - first_pct):.1f} points since the start of this window.")
    lines.append("")

    lines.append("## Daily trend (last 21 logged days)")
    lines.append("")
    lines.append("| Date | Orders | Accurate | Accuracy % | OCR Issue | PO Issue | Storm Creek Issue |")
    lines.append("|---|---|---|---|---|---|---|")
    for d in trend[-21:]:
        lines.append(f"| {d['date']} | {d['total']} | {d['accurate']} | "
                     f"{d['accuracy_pct']:.1f}% | {d['ocr']} | {d['po']} | {d['sc']} |")
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
    lines.append("(Accounts with 15+ orders in the logged window, sorted worst first)")
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
