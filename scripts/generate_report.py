#!/usr/bin/env python3
"""
Generates the Storm Creek daily OCR accuracy/error report from a CSV export
of the "Live Orders" sheet in the tracker spreadsheet:
https://docs.google.com/spreadsheets/d/1SGFQmGZ59tKD4tdWKG3o1acZsZtZM85kN3sbUKUSGH4

Usage:
    python3 generate_report.py <live_orders.csv> <output_report.md> [YYYY-MM-DD]

The optional date is the report date (defaults to today). The report focuses on
the latest logged day on or before the report date, and compares it with the
trailing 7 logged days and the 7 before that.

Required CSV columns (extra columns are ignored):
  Date, Processed By, Distributor, AX Comments, Issue related
Optional columns used when present:
  Secondary Cat for OCR Issue, Order Status, PO Number, Dev Notes, Status

Accuracy = "Accurate Orders" / reviewed orders, where reviewed means
"Issue related" is filled in. Rows with a blank "Issue related" are counted
as not-yet-reviewed and left out of the accuracy denominator.
"""
import csv
import datetime
import re
import sys
from collections import Counter, defaultdict

ACCURATE = "Accurate Orders"
OCR_CATS = ("OCR Issue", "OCR / Email Format")
ISSUE_CATS = ("OCR Issue", "OCR / Email Format", "PO Issue", "Storm Creek Issue")

# Error themes, matched on the reviewer comment (AX Comments). An order can
# carry more than one theme. Order matters only for display.
THEMES = {
    "Account Number / Shipping Acct ID": r"account numb|acc(?:oun)?t\.? ?(?:no|#|id)|\bacct\b|shipper number|shipping account",
    "STC (Ship To Credit)": r"\bSTC\b|state to credit|ship(?:ping)? to credit",
    "Reporting Group (RG / AIM / Facilis)": r"reporting group|\bRG\b|\bAIM\b|facilis",
    "Ship To / Address": r"ship ?to\b|shipping addr|address|secondline|second line|addr\b",
    "Name in both Ship To & Company Name": r"both ship to and company|ship to and company name",
    "Ship Method / Carrier": r"ship(?:ping)? method|carrier|\busps\b|\bups\b|fedex",
    "Part ID / Line not captured": r"part ?id|line record|did not capture line|line (?:was )?not captured|\bsku\b|product id|product code|incorrect product",
    "Quantity": r"\bqty\b|quantity",
    "Color / Size (incl. not in PPC)": r"\bcolou?r\b|\bsize\b|not available in ppc|navy|gray|grey|heather",
    "PO Number": r"po ?number|po ?#|po no\b",
    "PO Contact / Email": r"po contact|contact email|po mail|email",
    "Order Type / PSST": r"order type|psst",
    "Ship Date / In-hands Date": r"ship date|in.?hands|requested next day|\b\d{1,2} ?(?:am|pm)\b|delivery date",
    "Company Name": r"(?<!ship to and )company name",
    "PO Total / FF / Pricing": r"po total|\bFF\b|price|pricing",
}

SECONDARY_ALIASES = {
    "line / part id issue": "line/part id issue",
    "account numbe (not listed)": "account number",
    "qty": "quantity",
    "shipping address": "shipping details",
}


def parse_date(s):
    try:
        m, d, y = s.strip().split("/")
        return datetime.date(int(y), int(m), int(d))
    except (ValueError, AttributeError):
        return None


def clean(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def load_rows(csv_path):
    with open(csv_path, newline="", encoding="utf-8") as f:
        raw = list(csv.DictReader(f))
    rows = []
    for r in raw:
        r = {clean(k): v for k, v in r.items() if k is not None}
        d = parse_date(r.get("Date", ""))
        if not d:
            continue
        r["_date"] = d
        r["_dist"] = clean(r.get("Distributor"))
        r["_cat"] = clean(r.get("Issue related"))
        r["_comment"] = clean(r.get("AX Comments"))
        sec = clean(r.get("Secondary Cat for OCR Issue")).lower()
        r["_sec"] = SECONDARY_ALIASES.get(sec, sec)
        rows.append(r)
    return rows


def themes_of(comment):
    return [n for n, p in THEMES.items() if re.search(p, comment, re.IGNORECASE)]


def stats(recs):
    reviewed = [r for r in recs if r["_cat"]]
    c = Counter(r["_cat"] for r in reviewed)
    n = len(reviewed)
    acc = c[ACCURATE]
    ocr = sum(c[k] for k in OCR_CATS)
    return dict(logged=len(recs), reviewed=n, accurate=acc, ocr=ocr,
                po=c["PO Issue"], sc=c["Storm Creek Issue"],
                pending=len(recs) - n,
                acc_pct=acc / n * 100 if n else 0.0,
                ocr_pct=ocr / n * 100 if n else 0.0)


def pct(x):
    return f"{x:.1f}%"


def delta(a, b):
    d = a - b
    arrow = "▲" if d > 0.05 else ("▼" if d < -0.05 else "▬")
    return f"{arrow} {d:+.1f} pts"


def theme_counts(recs):
    c = Counter()
    for r in recs:
        for t in themes_of(r["_comment"]):
            c[t] += 1
    return c


def render(rows, report_date):
    rows = [r for r in rows if r["_date"] <= report_date]
    days = sorted({r["_date"] for r in rows})
    if not days:
        return f"# Storm Creek OCR Daily Report — {report_date}\n\nNo logged orders found.\n"
    by_day = defaultdict(list)
    for r in rows:
        by_day[r["_date"]].append(r)

    latest = days[-1]
    last7_days = days[-7:]
    prev7_days = days[-14:-7]
    last7 = [r for d in last7_days for r in by_day[d]]
    prev7 = [r for d in prev7_days for r in by_day[d]]
    s_day = stats(by_day[latest])
    s_7 = stats(last7)
    s_p7 = stats(prev7)
    s_all = stats(rows)
    first7 = stats([r for d in days[:7] for r in by_day[d]])

    L = []
    L.append(f"# Storm Creek OCR Daily Report — {report_date}")
    L.append("")
    L.append(f"Source: *Live Orders* tab · {s_all['logged']:,} orders logged {days[0]} → {latest} "
             f"({len(days)} working days). Latest logged day: **{latest}**.")
    L.append("")
    L.append("Accuracy = Accurate Orders ÷ reviewed orders (rows with a blank *Issue related* are "
             "treated as not yet reviewed). **OCR error rate** = OCR Issue + OCR / Email Format ÷ reviewed — "
             "this is the part the OCR pipeline owns; PO Issue and Storm Creek Issue are upstream/data problems.")
    L.append("")

    # ---- Headline
    L.append("## Headline")
    L.append("")
    L.append("| Window | Reviewed | Accuracy | OCR error rate | OCR | PO | Storm Creek |")
    L.append("|---|---|---|---|---|---|---|")
    for label, s in ((f"Latest day ({latest})", s_day),
                     (f"Last 7 days ({last7_days[0]} → {last7_days[-1]})", s_7),
                     (f"Prior 7 days ({prev7_days[0]} → {prev7_days[-1]})" if prev7_days else "Prior 7 days", s_p7),
                     (f"First 7 days ({days[0]} → {days[min(6, len(days)-1)]})", first7),
                     ("All time", s_all)):
        L.append(f"| {label} | {s['reviewed']} | **{pct(s['acc_pct'])}** | {pct(s['ocr_pct'])} | "
                 f"{s['ocr']} | {s['po']} | {s['sc']} |")
    L.append("")
    L.append(f"- Latest day vs last-7 average: accuracy {delta(s_day['acc_pct'], s_7['acc_pct'])}, "
             f"OCR error rate {delta(s_day['ocr_pct'], s_7['ocr_pct'])}.")
    if prev7_days:
        L.append(f"- Last 7 vs prior 7: accuracy {delta(s_7['acc_pct'], s_p7['acc_pct'])}, "
                 f"OCR error rate {delta(s_7['ocr_pct'], s_p7['ocr_pct'])}.")
    L.append(f"- Since the first week: accuracy {delta(s_7['acc_pct'], first7['acc_pct'])}, "
             f"OCR error rate {delta(s_7['ocr_pct'], first7['ocr_pct'])}.")
    if s_day["pending"]:
        L.append(f"- {s_day['pending']} order(s) on {latest} have no *Issue related* value yet (not reviewed).")
    L.append("")

    # ---- Weekly trend
    L.append("## Weekly trend")
    L.append("")
    L.append("| Week of | Days | Reviewed | Accuracy | OCR error rate | OCR | PO | Storm Creek |")
    L.append("|---|---|---|---|---|---|---|---|")
    weeks = defaultdict(list)
    for d in days:
        weeks[d - datetime.timedelta(days=d.weekday())].append(d)
    for wk in sorted(weeks):
        s = stats([r for d in weeks[wk] for r in by_day[d]])
        L.append(f"| {wk} | {len(weeks[wk])} | {s['reviewed']} | {pct(s['acc_pct'])} | "
                 f"{pct(s['ocr_pct'])} | {s['ocr']} | {s['po']} | {s['sc']} |")
    L.append("")

    # ---- Daily trend (last 10)
    L.append("## Daily trend (last 10 logged days)")
    L.append("")
    L.append("| Date | Reviewed | Accuracy | OCR error rate | OCR | PO | Storm Creek | Not reviewed |")
    L.append("|---|---|---|---|---|---|---|---|")
    for d in days[-10:]:
        s = stats(by_day[d])
        L.append(f"| {d} | {s['reviewed']} | {pct(s['acc_pct'])} | {pct(s['ocr_pct'])} | "
                 f"{s['ocr']} | {s['po']} | {s['sc']} | {s['pending']} |")
    L.append("")

    # ---- Error categorization
    ocr_day = [r for r in by_day[latest] if r["_cat"] in OCR_CATS]
    ocr_7 = [r for r in last7 if r["_cat"] in OCR_CATS]
    ocr_p7 = [r for r in prev7 if r["_cat"] in OCR_CATS]
    ocr_all = [r for r in rows if r["_cat"] in OCR_CATS]
    t_day, t_7, t_p7, t_all = (theme_counts(x) for x in (ocr_day, ocr_7, ocr_p7, ocr_all))
    L.append("## OCR error categories")
    L.append("")
    L.append("Themes are matched from the reviewer comment on OCR-flagged orders; one order can hit "
             "several themes. Sorted by last-7-day count.")
    L.append("")
    L.append(f"| Theme | {latest} | Last 7 days | Prior 7 days | Change | All time |")
    L.append("|---|---|---|---|---|---|")
    names = sorted(THEMES, key=lambda n: (-t_7[n], -t_all[n]))
    for n in names:
        if not (t_7[n] or t_p7[n] or t_all[n]):
            continue
        ch = t_7[n] - t_p7[n]
        L.append(f"| {n} | {t_day[n]} | {t_7[n]} | {t_p7[n]} | {ch:+d} | {t_all[n]} |")
    unthemed = [r for r in ocr_7 if not themes_of(r["_comment"])]
    L.append(f"| *(no theme matched)* | {sum(1 for r in ocr_day if not themes_of(r['_comment']))} | "
             f"{len(unthemed)} | {sum(1 for r in ocr_p7 if not themes_of(r['_comment']))} | | "
             f"{sum(1 for r in ocr_all if not themes_of(r['_comment']))} |")
    L.append("")

    sec = Counter(r["_sec"] for r in rows if r["_sec"])
    if sec:
        L.append("Reviewer-assigned *Secondary Cat for OCR Issue* (all time, only filled on some rows): " +
                 ", ".join(f"{k} ({v})" for k, v in sec.most_common(10)) + ".")
        L.append("")

    po_7 = [r for r in last7 if r["_cat"] == "PO Issue"]
    if po_7:
        po_themes = theme_counts(po_7)
        L.append(f"PO Issue themes, last 7 days ({len(po_7)} orders): " +
                 ", ".join(f"{k} ({v})" for k, v in po_themes.most_common(6)) + ".")
        L.append("")

    # ---- Accounts
    def dist_stats(recs):
        g = defaultdict(list)
        for r in recs:
            if r["_dist"]:
                g[r["_dist"]].append(r)
        return {k: stats(v) for k, v in g.items()}

    d7 = dist_stats(last7)
    dp7 = dist_stats(prev7)
    dall = dist_stats(rows)
    L.append("## Accounts / distributors")
    L.append("")
    L.append("### Most OCR errors in the last 7 days")
    L.append("")
    L.append("| Distributor | OCR errors (7d) | Reviewed (7d) | Accuracy (7d) | Accuracy (prior 7d) | Accuracy (all time) | Top themes (7d) |")
    L.append("|---|---|---|---|---|---|---|")
    top = sorted((k for k in d7 if d7[k]["ocr"]), key=lambda k: (-d7[k]["ocr"], d7[k]["acc_pct"]))[:12]
    for k in top:
        th = theme_counts([r for r in ocr_7 if r["_dist"] == k]).most_common(3)
        prior = pct(dp7[k]["acc_pct"]) if k in dp7 and dp7[k]["reviewed"] else "–"
        L.append(f"| {k} | {d7[k]['ocr']} | {d7[k]['reviewed']} | {pct(d7[k]['acc_pct'])} | {prior} | "
                 f"{pct(dall[k]['acc_pct'])} ({dall[k]['reviewed']}) | {', '.join(t for t, _ in th) or '–'} |")
    L.append("")

    # recurring offenders: OCR error on >=3 distinct days in last 14 logged days
    win14 = days[-14:]
    hits = defaultdict(set)
    for d in win14:
        for r in by_day[d]:
            if r["_cat"] in OCR_CATS and r["_dist"]:
                hits[r["_dist"]].add(d)
    recurring = sorted(((k, v) for k, v in hits.items() if len(v) >= 3), key=lambda kv: -len(kv[1]))
    L.append("### Recurring accounts (OCR error on 3+ of the last 14 logged days)")
    L.append("")
    if recurring:
        L.append("| Distributor | Days with OCR errors | Most common themes (14d) |")
        L.append("|---|---|---|")
        recs14 = [r for d in win14 for r in by_day[d] if r["_cat"] in OCR_CATS]
        for k, v in recurring:
            th = theme_counts([r for r in recs14 if r["_dist"] == k]).most_common(3)
            L.append(f"| {k} | {len(v)} | {', '.join(f'{t} ({c})' for t, c in th) or '–'} |")
    else:
        L.append("None.")
    L.append("")

    L.append("### Lowest accuracy, all time (accounts with 30+ reviewed orders)")
    L.append("")
    L.append("| Distributor | Reviewed | Accuracy (all time) | Accuracy (last 7d) |")
    L.append("|---|---|---|---|")
    worst = sorted((k for k in dall if dall[k]["reviewed"] >= 30), key=lambda k: dall[k]["acc_pct"])[:10]
    for k in worst:
        last = f"{pct(d7[k]['acc_pct'])} ({d7[k]['reviewed']})" if k in d7 and d7[k]["reviewed"] else "–"
        L.append(f"| {k} | {dall[k]['reviewed']} | {pct(dall[k]['acc_pct'])} | {last} |")
    L.append("")

    # ---- Latest-day detail
    flagged = [r for r in by_day[latest] if r["_cat"] in ISSUE_CATS]
    L.append(f"## Flagged orders on {latest} ({len(flagged)})")
    L.append("")
    L.append("| Category | Distributor | PO | Themes | Reviewer comment |")
    L.append("|---|---|---|---|---|")
    order = {c: i for i, c in enumerate(ISSUE_CATS)}
    for r in sorted(flagged, key=lambda r: (order.get(r["_cat"], 9), r["_dist"])):
        c = r["_comment"].replace("|", "/")
        if len(c) > 220:
            c = c[:217] + "…"
        L.append(f"| {r['_cat']} | {r['_dist']} | {clean(r.get('PO Number'))} | "
                 f"{', '.join(themes_of(r['_comment'])) or '–'} | {c} |")
    L.append("")

    # ---- Associates
    L.append("## Reviewer volume (last 7 days)")
    L.append("")
    L.append("| Processed By | Reviewed | Accuracy | OCR flagged |")
    L.append("|---|---|---|---|")
    g = defaultdict(list)
    for r in last7:
        if clean(r.get("Processed By")):
            g[clean(r["Processed By"])].append(r)
    for k in sorted(g, key=lambda k: -len(g[k])):
        s = stats(g[k])
        L.append(f"| {k} | {s['reviewed']} | {pct(s['acc_pct'])} | {s['ocr']} |")
    L.append("")
    L.append("Differences between reviewers mostly reflect which accounts they were allotted, not reviewer quality.")
    L.append("")
    return "\n".join(L)


def main():
    if len(sys.argv) not in (3, 4):
        print(__doc__)
        sys.exit(1)
    csv_path, out_path = sys.argv[1], sys.argv[2]
    report_date = (datetime.date.fromisoformat(sys.argv[3]) if len(sys.argv) == 4
                   else datetime.date.today())
    rows = load_rows(csv_path)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(render(rows, report_date))
    print(f"Wrote report to {out_path}")


if __name__ == "__main__":
    main()
