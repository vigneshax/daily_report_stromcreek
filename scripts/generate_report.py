#!/usr/bin/env python3
"""
Generates the Storm Creek daily OCR accuracy/error report from a CSV export
of the "Live Orders" sheet in the tracker spreadsheet:
https://docs.google.com/spreadsheets/d/1SGFQmGZ59tKD4tdWKG3o1acZsZtZM85kN3sbUKUSGH4

Usage:
    python3 generate_report.py <live_orders.csv> <output_report.md> [YYYY-MM-DD]

The optional third argument is the report (run) date; defaults to today.
The report focuses on the most recent logged day on or before that date and
compares it against the previous 5 logged days and the full history.

Required CSV columns (extra columns are ignored):
Date, Processed By, PO Number, Distributor, AX Comments, Issue related
Optional: Secondary Cat for OCR Issue
"""
import csv
import re
import sys
import datetime
from collections import Counter, defaultdict

ACCURATE = "Accurate Orders"
ERROR_CATS = ("OCR Issue", "PO Issue", "Storm Creek Issue", "OCR / Email Format")

# Ordered: first match is the "primary" theme, but every match is counted.
THEME_BUCKETS = {
    "Account Number / Shipping Acct": r"account number|\bacct\b|account id|wrong account|account (?:was )?captured|shipper number",
    "Reporting Group / STC": r"\bSTC\b|state to credit|reporting group|\bRG\b|\bAIM\b|facilis",
    "Ship To / Address": r"ship ?to|shipping address|address|secondline|second line|dropship",
    "Ship Method": r"ship(?:ping)? method|carrier|fedex|\bups\b|2nd day|overnight|expedite",
    "Preferred Ship Date / PSST": r"ship date|\bPSST\b|in.?hands",
    "Order Type (Sample/Blank/etc.)": r"order type|\bsample\b|\bblank\b",
    "Line Record / Part ID / Item Code": r"part ?id|line record|item (?:code|number)|product id|\bsku\b|product code",
    "Color / Size": r"\bcolou?r\b|\bsize\b|\bnavy\b|\bblack\b|\bgr[ae]y\b",
    "Quantity": r"\bqty\b|quantity",
    "PO Number": r"po number|po#|po #",
    "PO Total / Price": r"po total|price",
    "PO Contact / Email": r"po contact|po mail|contact email|email",
    "Company Name": r"company name",
    "Product not in PPC / Proof": r"\bPPC\b|proof|not available",
}


def parse_date(s):
    m, d, y = s.strip().split("/")
    return datetime.date(int(y), int(m), int(d))


def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def load_rows(csv_path):
    out = []
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not r.get("Date", "").strip():
                continue
            try:
                r["_date"] = parse_date(r["Date"])
            except ValueError:
                continue
            r["_cat"] = norm(r.get("Issue related"))
            r["_dist"] = norm(r.get("Distributor"))
            r["_assoc"] = norm(r.get("Processed By"))
            r["_comment"] = norm(r.get("AX Comments"))
            out.append(r)
    return out


def scored(rows):
    """Rows that carry an Issue-related classification (blank rows excluded)."""
    return [r for r in rows if r["_cat"]]


def acc(rows):
    s = scored(rows)
    a = sum(1 for r in s if r["_cat"] == ACCURATE)
    return a, len(s), (a / len(s) * 100 if s else 0.0)


def themes_of(r):
    return [n for n, p in THEME_BUCKETS.items() if re.search(p, r["_comment"], re.I)]


def theme_counts(rows):
    c = Counter()
    for r in rows:
        t = themes_of(r)
        for n in t:
            c[n] += 1
        if not t:
            c["Other / uncategorized"] += 1
    return c


def is_error(r):
    return r["_cat"] in ERROR_CATS


def pct(n, d):
    return n / d * 100 if d else 0.0


def arrow(delta, good_up=True, tol=0.5):
    if abs(delta) < tol:
        return "→"
    up = delta > 0
    return "▲" if up else "▼"


def fmt_delta(delta):
    return f"{delta:+.1f}"


def render_report(rows, run_date):
    rows = [r for r in rows if r["_date"] <= run_date]
    days = sorted({r["_date"] for r in rows})
    if not days:
        return f"# Storm Creek OCR Daily Report — {run_date}\n\nNo logged orders found.\n"
    by_day = defaultdict(list)
    for r in rows:
        by_day[r["_date"]].append(r)

    today = days[-1]
    prev5 = days[-6:-1]
    last10 = days[-10:]
    t_rows = by_day[today]
    p_rows = [r for d in prev5 for r in by_day[d]]

    ta, tn, tp = acc(t_rows)
    pa, pn, pp = acc(p_rows)
    aa, an, ap = acc(rows)

    t_err = [r for r in t_rows if is_error(r)]
    p_err = [r for r in p_rows if is_error(r)]
    t_ocr = [r for r in t_rows if r["_cat"] == "OCR Issue"]
    unclassified_today = sum(1 for r in t_rows if not r["_cat"])

    L = []
    L.append(f"# Storm Creek OCR Daily Report — {run_date}")
    L.append("")
    stale = (run_date - today).days
    note = "" if stale <= 1 else f" (latest logged day; sheet has no entries for the {stale - 1} day(s) since)"
    L.append(f"**Report day: {today:%a %Y-%m-%d}**{note}  ")
    L.append(f"Source: *Live Orders* tab — {len(rows)} orders logged {days[0]} → {today}, {len(days)} working days.")
    L.append("")

    # ---------- Headline ----------
    L.append("## 1. Headline")
    L.append("")
    L.append("| Metric | Report day | Prev 5 days | All-time |")
    L.append("|---|---|---|---|")
    L.append(f"| Orders reviewed | {len(t_rows)} | {len(p_rows)} ({len(p_rows)/max(len(prev5),1):.0f}/day) | {len(rows)} |")
    L.append(f"| **Accuracy** | **{tp:.1f}%** ({ta}/{tn}) | {pp:.1f}% | {ap:.1f}% |")
    t_ocr_p = pct(len(t_ocr), tn)
    p_ocr_p = pct(sum(1 for r in p_rows if r['_cat'] == 'OCR Issue'), pn)
    a_ocr_p = pct(sum(1 for r in rows if r['_cat'] == 'OCR Issue'), an)
    L.append(f"| OCR-issue rate (yours to fix) | {t_ocr_p:.1f}% ({len(t_ocr)}) | {p_ocr_p:.1f}% | {a_ocr_p:.1f}% |")
    t_po = sum(1 for r in t_rows if r['_cat'] == 'PO Issue')
    L.append(f"| PO-issue rate (source PO problem) | {pct(t_po, tn):.1f}% ({t_po}) | "
             f"{pct(sum(1 for r in p_rows if r['_cat']=='PO Issue'), pn):.1f}% | "
             f"{pct(sum(1 for r in rows if r['_cat']=='PO Issue'), an):.1f}% |")
    L.append("")
    d = tp - pp
    L.append(f"- Accuracy vs previous 5 days: **{arrow(d)} {fmt_delta(d)} pts**.")
    if unclassified_today:
        L.append(f"- {unclassified_today} order(s) on the report day have a blank *Issue related* "
                 "and are excluded from accuracy — reviewers should fill these in.")
    L.append("")

    # ---------- Today's error categorization ----------
    L.append("## 2. Error categorization — report day")
    L.append("")
    L.append("| Category (Issue related) | Count |")
    L.append("|---|---|")
    for c, n in Counter(r["_cat"] or "(blank)" for r in t_rows).most_common():
        L.append(f"| {c} | {n} |")
    L.append("")
    tt = theme_counts(t_err)
    pt = theme_counts(p_err)
    L.append(f"Root-cause themes from reviewer comments on the {len(t_err)} flagged orders "
             "(an order can hit several themes; prev-5-day column is a daily average for comparison):")
    L.append("")
    L.append("| Theme | Report day | % of flagged | Prev 5d avg/day | Trend |")
    L.append("|---|---|---|---|---|")
    names = sorted(set(tt) | set(pt), key=lambda k: (-tt.get(k, 0), -pt.get(k, 0)))
    for n in names:
        cur = tt.get(n, 0)
        avg = pt.get(n, 0) / max(len(prev5), 1)
        if cur == 0 and avg < 0.5:
            continue
        tr = "▲ rising" if cur >= avg + 1.5 and cur >= 2 * max(avg, 0.5) else ("▼ falling" if cur + 1.5 <= avg else "→")
        L.append(f"| {n} | {cur} | {pct(cur, len(t_err)):.0f}% | {avg:.1f} | {tr} |")
    L.append("")

    # ---------- Account (distributor) view ----------
    L.append("## 3. Accounts (distributors) — where errors are concentrated")
    L.append("")
    L.append("### Report day: accounts with errors")
    L.append("")
    L.append("| Distributor | Orders today | Errors today | Error types | Recurring? (errors in prev 10 days) |")
    L.append("|---|---|---|---|---|")
    hist_days = set(days[-11:-1])
    hist_err = Counter(r["_dist"] for r in rows if r["_date"] in hist_days and is_error(r))
    td = defaultdict(list)
    for r in t_rows:
        td[r["_dist"]].append(r)
    dist_today = []
    for dist, rs in td.items():
        e = [r for r in rs if is_error(r)]
        if e:
            th = Counter(t for r in e for t in (themes_of(r) or ["Other"]))
            dist_today.append((len(e), dist, len(rs), ", ".join(k for k, _ in th.most_common(3)), hist_err.get(dist, 0)))
    dist_today.sort(key=lambda x: (-x[0], -x[4]))
    for ne, dist, no, th, h in dist_today:
        flag = f"**yes — {h}**" if h >= 3 else (str(h) if h else "new")
        L.append(f"| {dist} | {no} | {ne} | {th} | {flag} |")
    L.append("")

    # trend across days for accounts: last 10 days vs the 10 before
    L.append("### Account trend: last 10 days vs the 10 days before (accounts with ≥10 orders in last 10 days)")
    L.append("")
    win_a = set(days[-10:])
    win_b = set(days[-20:-10])
    ga, gb = defaultdict(list), defaultdict(list)
    for r in rows:
        if r["_date"] in win_a:
            ga[r["_dist"]].append(r)
        elif r["_date"] in win_b:
            gb[r["_dist"]].append(r)
    trows = []
    for dist, rs in ga.items():
        a1, n1, p1 = acc(rs)
        if n1 < 10 or not dist:
            continue
        a0, n0, p0 = acc(gb.get(dist, []))
        trows.append((p1, dist, n1, p0 if n0 else None, n0))
    worst = sorted(trows)[:12]
    L.append("| Distributor | Orders (last 10d) | Accuracy last 10d | Accuracy prior 10d | Change |")
    L.append("|---|---|---|---|---|")
    for p1, dist, n1, p0, n0 in worst:
        ch = f"{arrow(p1 - p0)} {fmt_delta(p1 - p0)}" if p0 is not None and n0 >= 5 else "n/a"
        p0s = f"{p0:.1f}% ({n0})" if p0 is not None else "—"
        L.append(f"| {dist} | {n1} | {p1:.1f}% | {p0s} | {ch} |")
    L.append("")
    improved = sorted([t for t in trows if t[3] is not None and t[4] >= 10], key=lambda t: -(t[0] - t[3]))[:5]
    if improved and improved[0][0] - improved[0][3] > 3:
        L.append("Most improved accounts: " + "; ".join(
            f"{t[1]} ({t[3]:.0f}% → {t[0]:.0f}%)" for t in improved if t[0] - t[3] > 3) + ".")
        L.append("")

    # ---------- Daily trend ----------
    L.append("## 4. Daily trend (last 10 logged days)")
    L.append("")
    L.append("| Date | Orders | Accuracy | OCR | PO | SC | Top OCR theme |")
    L.append("|---|---|---|---|---|---|---|")
    for dday in last10:
        rs = by_day[dday]
        a, n, p = acc(rs)
        c = Counter(r["_cat"] for r in rs)
        top = theme_counts([r for r in rs if r["_cat"] == "OCR Issue"]).most_common(1)
        tops = f"{top[0][0]} ({top[0][1]})" if top else "—"
        L.append(f"| {dday:%a %m-%d} | {len(rs)} | {p:.1f}% | {c.get('OCR Issue',0)} | "
                 f"{c.get('PO Issue',0)} | {c.get('Storm Creek Issue',0)} | {tops} |")
    L.append("")

    # ---------- Weekly ----------
    L.append("## 5. Weekly accuracy trend")
    L.append("")
    wk = defaultdict(list)
    for r in rows:
        y, w, _ = r["_date"].isocalendar()
        wk[(y, w)].append(r)
    L.append("| ISO week (starting) | Orders | Accuracy | OCR-issue rate |")
    L.append("|---|---|---|---|")
    for k in sorted(wk):
        rs = wk[k]
        a, n, p = acc(rs)
        start = datetime.date.fromisocalendar(k[0], k[1], 1)
        o = sum(1 for r in rs if r["_cat"] == "OCR Issue")
        L.append(f"| W{k[1]} ({start:%m-%d}) | {len(rs)} | {p:.1f}% | {pct(o, n):.1f}% |")
    L.append("")

    # ---------- Associates ----------
    L.append("## 6. Reviewer view — report day")
    L.append("")
    L.append("Flag rate = share of a reviewer's orders they flagged; large gaps can mean inconsistent review standards rather than model quality.")
    L.append("")
    L.append("| Reviewer | Orders today | Flagged | Flag rate | Prev 5d flag rate |")
    L.append("|---|---|---|---|---|")
    ta_ = defaultdict(list)
    pa_ = defaultdict(list)
    for r in t_rows:
        ta_[r["_assoc"]].append(r)
    for r in p_rows:
        pa_[r["_assoc"]].append(r)
    for who, rs in sorted(ta_.items(), key=lambda x: -len(x[1])):
        a, n, p = acc(rs)
        a2, n2, p2 = acc(pa_.get(who, []))
        L.append(f"| {who or '(blank)'} | {len(rs)} | {n - a} | {100 - p:.1f}% | "
                 f"{(100 - p2):.1f}%" + (" |" if n2 else " (no data) |"))
    L.append("")

    # ---------- Detail ----------
    L.append("## 7. Report-day OCR issues (full list — your fix queue)")
    L.append("")
    L.append("| # | Distributor | PO | Theme(s) | Reviewer comment |")
    L.append("|---|---|---|---|---|")
    for i, r in enumerate(sorted(t_ocr, key=lambda r: (themes_of(r) or ["~"])[0]), 1):
        cm = r["_comment"].replace("|", "/")
        if len(cm) > 180:
            cm = cm[:177] + "…"
        L.append(f"| {i} | {r['_dist']} | {norm(r.get('PO Number'))} | {', '.join(themes_of(r)) or 'Other'} | {cm} |")
    L.append("")
    return "\n".join(L), dict(today=today, tp=tp, pp=pp, ap=ap, n=len(t_rows), ocr=len(t_ocr),
                              themes=tt, dist_today=dist_today, worst=worst)


def main():
    if len(sys.argv) not in (3, 4):
        print(__doc__)
        sys.exit(1)
    csv_path, out_path = sys.argv[1], sys.argv[2]
    run_date = (datetime.date.fromisoformat(sys.argv[3]) if len(sys.argv) == 4
                else datetime.date.today())
    rows = load_rows(csv_path)
    report, _ = render_report(rows, run_date)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"Wrote report to {out_path}")


if __name__ == "__main__":
    main()
