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
}


UNSCORED = 0


def parse_date(s):
    m, d, y = s.strip().split("/")
    return datetime.date(int(y), int(m), int(d))


def load_rows(csv_path):
    rows = [r for r in csv.DictReader(open(csv_path, newline="", encoding="utf-8"))]
    rows = [r for r in rows if r["Date"].strip()]
    # Only orders a reviewer classified count toward accuracy. Blank "Issue related"
    # rows are duplicates / rejected files / no-PO and are excluded from the denominator.
    global UNSCORED
    UNSCORED = sum(1 for r in rows if not r["Issue related"].strip())
    rows = [r for r in rows if r["Issue related"].strip()]
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
        po = sum(1 for r in recs if r["Issue related"] in ("PO Issue", "OCR / Email Format"))
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

    # ---- Week-over-week and window comparison ----
    by_week = defaultdict(list)
    for r in rows:
        by_week[r["Week#"]].append(r)
    lines.append("## Weekly trend")
    lines.append("")
    lines.append("| Week# | Orders | Accuracy % | OCR | PO/Email | SC |")
    lines.append("|---|---|---|---|---|---|")
    for w in sorted(by_week, key=lambda x: int(x) if x.isdigit() else 99):
        recs = by_week[w]; n = len(recs)
        a = sum(1 for r in recs if r["Issue related"] == "Accurate Orders")
        lines.append(f"| {w} | {n} | {a/n*100:.1f}% | "
                     f"{sum(1 for r in recs if r['Issue related']=='OCR Issue')} | "
                     f"{sum(1 for r in recs if r['Issue related'] in ('PO Issue','OCR / Email Format'))} | "
                     f"{sum(1 for r in recs if r['Issue related']=='Storm Creek Issue')} |")
    lines.append("")

    last_day = trend[-1]["date"]
    days = [d["date"] for d in trend]
    l7 = set(days[-7:]); p7 = set(days[-14:-7])
    r_l7 = [r for r in rows if r["_date"] in l7]
    r_p7 = [r for r in rows if r["_date"] in p7]
    def pct(rs):
        return sum(1 for r in rs if r["Issue related"] == "Accurate Orders") / len(rs) * 100 if rs else 0
    lines.append(f"## Latest day ({last_day}) vs recent windows")
    lines.append("")
    lines.append(f"- Latest day: **{trend[-1]['accuracy_pct']:.1f}%** ({trend[-1]['accurate']}/{trend[-1]['total']})")
    lines.append(f"- Last 7 logged days: **{pct(r_l7):.1f}%** ({len(r_l7)} orders)")
    lines.append(f"- Previous 7 logged days: **{pct(r_p7):.1f}%** ({len(r_p7)} orders) -> change {pct(r_l7)-pct(r_p7):+.1f} pts")
    lines.append(f"- Excluded from scoring (duplicates / rejected / no PO, blank Issue): {UNSCORED} rows")
    lines.append("")
    lines.append("### Theme movement (flagged orders, last 7 days vs previous 7 days)")
    lines.append("")
    t_l = theme_breakdown([r for r in r_l7 if r["Issue related"] in ISSUE_CATEGORIES])
    t_p = theme_breakdown([r for r in r_p7 if r["Issue related"] in ISSUE_CATEGORIES])
    lines.append("| Theme | Last 7d | Prev 7d | Change |")
    lines.append("|---|---|---|---|")
    for name in sorted(THEME_BUCKETS, key=lambda n: -t_l[n]):
        lines.append(f"| {name} | {t_l[name]} | {t_p[name]} | {t_l[name]-t_p[name]:+d} |")
    lines.append("")
    lines.append("### Distributor movement (30+ orders overall; last 7d vs previous 7d)")
    lines.append("")
    lines.append("| Distributor | Last 7d orders | Last 7d acc | Prev 7d acc | Change |")
    lines.append("|---|---|---|---|---|")
    mv = []
    for dn in {d["distributor"] for d in dists}:
        a = [r for r in r_l7 if r["Distributor"] == dn]; b = [r for r in r_p7 if r["Distributor"] == dn]
        if len(a) >= 8 and len(b) >= 8:
            mv.append((pct(a)-pct(b), dn, len(a), pct(a), pct(b)))
    mv.sort()
    for ch, dn, n, pa, pb in mv[:6] + mv[-3:]:
        lines.append(f"| {dn} | {n} | {pa:.1f}% | {pb:.1f}% | {ch:+.1f} |")
    lines.append("")
    sec = Counter(r["Secondary Cat for OCR Issue"].strip().lower() for r in rows if r["Secondary Cat for OCR Issue"].strip())
    if sec:
        lines.append("### Reviewer secondary categories (OCR issues, where filled in)")
        lines.append("")
        for k, v in sec.most_common(8):
            lines.append(f"- {k}: {v}")
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
