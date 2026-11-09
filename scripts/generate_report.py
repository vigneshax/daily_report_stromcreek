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

ISSUE_CATEGORIES = ("OCR Issue", "OCR / Email Format", "PO Issue", "Storm Creek Issue")

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


def pct(a, b):
    return a / b * 100 if b else 0.0


def acc_of(recs):
    return sum(1 for r in recs if r["Issue related"] == "Accurate Orders")


def week_trend(rows):
    by = defaultdict(list)
    for r in rows:
        by[r["_date"].isocalendar()[:2]].append(r)
    return [(k, v) for k, v in sorted(by.items())]


def render_report(rows, report_date):
    trend = daily_trend(rows)
    issue_rows = [r for r in rows if r["Issue related"] in ISSUE_CATEGORIES]
    dates = sorted({r["_date"] for r in rows})
    latest = dates[-1]
    last7 = set(dates[-7:])
    prev7 = set(dates[-14:-7])
    last14 = set(dates[-14:])
    total = len(rows)
    acc_total = acc_of(rows)
    unlabeled = [r for r in rows if not r["Issue related"].strip()]
    labeled = [r for r in rows if r["Issue related"].strip()]

    def window(ds):
        recs = [r for r in labeled if r["_date"] in ds]
        return acc_of(recs), len(recs)

    la, ln = window({latest})
    a7, n7 = window(last7)
    p7, pn7 = window(prev7)
    lines = [f"# Storm Creek OCR Daily Report — {report_date}", ""]
    lines.append(f"Data source: Live Orders sheet, {total} orders logged "
                 f"({len(unlabeled)} not yet labelled by reviewers and excluded from "
                 f"accuracy), {dates[0]} to {latest}. Accuracy = Accurate Orders / labelled orders.")
    lines.append("")
    lines.append("## Headline")
    lines.append(f"- Latest logged day ({latest}): **{pct(la, ln):.1f}%** ({la}/{ln})")
    lines.append(f"- Last 7 logged days: **{pct(a7, n7):.1f}%** ({a7}/{n7}); "
                 f"previous 7: {pct(p7, pn7):.1f}% ({p7}/{pn7}) -> "
                 f"{'up' if pct(a7, n7) >= pct(p7, pn7) else 'DOWN'} "
                 f"{abs(pct(a7, n7) - pct(p7, pn7)):.1f} pts")
    lines.append(f"- Overall since {dates[0]}: **{pct(acc_of(labeled), len(labeled)):.1f}%** "
                 f"({acc_of(labeled)}/{len(labeled)})")
    lines.append("")

    lines.append("## Weekly trend")
    lines.append("")
    lines.append("| ISO week (starts) | Orders | Accuracy % | OCR | OCR/Email Format | PO | Storm Creek |")
    lines.append("|---|---|---|---|---|---|---|")
    for (y, w), recs in week_trend(labeled):
        c = Counter(r["Issue related"] for r in recs)
        start = min(r["_date"] for r in recs)
        lines.append(f"| {y}-W{w:02d} ({start}) | {len(recs)} | {pct(acc_of(recs), len(recs)):.1f}% | "
                     f"{c['OCR Issue']} | {c['OCR / Email Format']} | {c['PO Issue']} | {c['Storm Creek Issue']} |")
    lines.append("")

    lines.append("## Daily trend (last 14 logged days)")
    lines.append("")
    lines.append("| Date | Labelled | Accurate | Accuracy % | OCR | OCR/Email Format | PO | Storm Creek |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for d in sorted(last14):
        recs = [r for r in labeled if r["_date"] == d]
        c = Counter(r["Issue related"] for r in recs)
        lines.append(f"| {d} | {len(recs)} | {acc_of(recs)} | {pct(acc_of(recs), len(recs)):.1f}% | "
                     f"{c['OCR Issue']} | {c['OCR / Email Format']} | {c['PO Issue']} | {c['Storm Creek Issue']} |")
    lines.append("")

    lines.append("## Error categories (issue type, all-time vs last 14 days)")
    lines.append("")
    recent_issue = [r for r in issue_rows if r["_date"] in last14]
    lines.append("| Category | All-time | Last 14d | Share of last-14d orders |")
    lines.append("|---|---|---|---|")
    rl = [r for r in labeled if r["_date"] in last14]
    for cat in ISSUE_CATEGORIES:
        ac = sum(1 for r in issue_rows if r["Issue related"] == cat)
        rc = sum(1 for r in recent_issue if r["Issue related"] == cat)
        lines.append(f"| {cat} | {ac} | {rc} | {pct(rc, len(rl)):.1f}% |")
    lines.append("")

    lines.append("## Error themes from reviewer comments (last 14 days vs. before)")
    lines.append("")
    older_issue = [r for r in issue_rows if r["_date"] not in last14]
    tr, to = theme_breakdown(recent_issue), theme_breakdown(older_issue)
    lines.append(f"Flagged orders: {len(recent_issue)} in last 14d, {len(older_issue)} earlier "
                 "(one order can carry several themes).")
    lines.append("")
    lines.append("| Theme | Last 14d | % of flagged | Earlier % of flagged |")
    lines.append("|---|---|---|---|")
    for name, count in tr.most_common():
        lines.append(f"| {name} | {count} | {pct(count, len(recent_issue)):.1f}% | "
                     f"{pct(to[name], len(older_issue)):.1f}% |")
    lines.append("")

    sec = Counter(r["Secondary Cat for OCR Issue"].strip().lower().replace(" / ", "/")
                  for r in issue_rows if r["Secondary Cat for OCR Issue"].strip())
    if sec:
        lines.append("## Secondary OCR category (where reviewers filled it in)")
        lines.append("")
        lines.append("| Category | Count |")
        lines.append("|---|---|")
        for k, v in sec.most_common(10):
            lines.append(f"| {k} | {v} |")
        lines.append("")

    lines.append("## Accounts/distributors needing attention (last 14 logged days, 10+ orders)")
    lines.append("")
    lines.append("| Distributor | Orders | Accuracy % | All-time % | Top issue comments |")
    lines.append("|---|---|---|---|---|")
    by = defaultdict(list)
    allby = defaultdict(list)
    for r in labeled:
        if r["Distributor"].strip():
            allby[r["Distributor"]].append(r)
            if r["_date"] in last14:
                by[r["Distributor"]].append(r)
    ranked = sorted(((d, v) for d, v in by.items() if len(v) >= 10),
                    key=lambda x: pct(acc_of(x[1]), len(x[1])))
    for d, v in ranked[:10]:
        th = theme_breakdown([r for r in v if r["Issue related"] in ISSUE_CATEGORIES])
        top = ", ".join(f"{k} ({c})" for k, c in th.most_common(2)) or "-"
        lines.append(f"| {d} | {len(v)} | {pct(acc_of(v), len(v)):.1f}% | "
                     f"{pct(acc_of(allby[d]), len(allby[d])):.1f}% | {top} |")
    lines.append("")

    lines.append("## Associate accuracy (last 14 logged days)")
    lines.append("")
    lines.append("| Processed By | Orders | Accuracy % |")
    lines.append("|---|---|---|")
    ab = defaultdict(list)
    for r in rl:
        if r["Processed By"].strip():
            ab[r["Processed By"]].append(r)
    for a, v in sorted(ab.items(), key=lambda x: -len(x[1])):
        lines.append(f"| {a} | {len(v)} | {pct(acc_of(v), len(v)):.1f}% |")
    lines.append("")

    lines.append(f"## Flagged orders on {latest} (for follow-up)")
    lines.append("")
    lines.append("| Msg ID | PO | Distributor | Type | Comment |")
    lines.append("|---|---|---|---|---|")
    for r in issue_rows:
        if r["_date"] == latest:
            cm = r["AX Comments"].replace("|", "/").replace("\n", " ")[:140]
            lines.append(f"| {r['Message ID']} | {r['PO Number']} | {r['Distributor']} | "
                         f"{r['Issue related']} | {cm} |")
    lines.append("")
    return "\n".join(lines)


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    csv.field_size_limit(10**9)
    csv_path, out_path = sys.argv[1], sys.argv[2]
    rows = load_rows(csv_path)
    report_date = datetime.date.today().isoformat()
    report = render_report(rows, report_date)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"Wrote report to {out_path}")


if __name__ == "__main__":
    main()
