#!/usr/bin/env python3
"""
Generates the Storm Creek daily OCR accuracy/error report from a CSV export
of the "Live Orders" sheet in the tracker spreadsheet:
https://docs.google.com/spreadsheets/d/1SGFQmGZ59tKD4tdWKG3o1acZsZtZM85kN3sbUKUSGH4

Usage:
    python3 generate_report.py <live_orders.csv> <output_report.md> [YYYY-MM-DD]

The optional date is the day to report on; it defaults to the latest date
logged in the sheet. Required columns: Date, Processed By, Order Status,
PO Number, Distributor, AX Comments, Issue related.

Definitions
- Reviewed order: a row whose "Issue related" is filled in.
- Overall accuracy: Accurate Orders / reviewed orders.
- OCR accuracy: 1 - (OCR Issue + OCR / Email Format) / reviewed orders.
  This is the number engineering owns; PO Issue (bad/ambiguous customer PO)
  and Storm Creek Issue (catalog/website) are tracked but are not OCR misses.
"""
import csv
import re
import sys
import datetime
from collections import Counter, defaultdict

OCR_CATS = ("OCR Issue", "OCR / Email Format")
NON_OCR_CATS = ("PO Issue", "Storm Creek Issue")
ACCURATE = "Accurate Orders"

# Field-level error themes, matched against "AX Comments". Order matters only
# for display; one order can hit several themes.
THEMES = [
    ("Account / shipper number", r"account|acct|shipper number|shipping id"),
    ("Ship method / carrier", r"ship(ping)? method|carrier|fedex|ups|2nd day|ground|overnight"),
    ("Part ID / product ID", r"part ?id|product id|product code|product details|\bsku\b|-mto"),
    ("Reporting group (RG/AIM/ASB/Facilis/Deluxe)", r"\brg\b|reporting group|\baim\b|\basb\b|\baia\b|facilis|deluxe"),
    ("STC (state to credit)", r"\bstc\b|state to credit"),
    ("Order type (blank/sample/PSST)", r"order type|sample|blank order|psst"),
    ("PO total / freight (FF) / unit cost", r"po total|\bff\b|freight|unit (cost|price)|extended price"),
    ("PO number", r"po number|po#|po #"),
    ("Ship-to address", r"ship ?to|shipping address|address|second ?line|line 2"),
    ("Quantity", r"\bqty\b|quantity"),
    ("Color / size", r"colou?r|\bsize\b|navy|black|blue|gray|grey|heather|\b(xs|s|m|l|xl|2xl|3xl)\b"),
    ("Company name", r"company name"),
    ("Ship / in-hands date", r"ship date|in.?hands|due date"),
]


def parse_date(s):
    return datetime.datetime.strptime(s.strip(), "%m/%d/%Y").date()


def load_rows(csv_path):
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if not (r.get("Date") or "").strip():
                continue
            try:
                r["_date"] = parse_date(r["Date"])
            except ValueError:
                continue
            r["_cat"] = (r.get("Issue related") or "").strip()
            r["_dist"] = (r.get("Distributor") or "").strip() or "(blank)"
            r["_comment"] = (r.get("AX Comments") or "").strip()
            rows.append(r)
    return rows


def themes_for(comment):
    c = comment.lower()
    hits = [name for name, pat in THEMES if re.search(pat, c)]
    return hits or ["Other / unclassified"]


def stats(rows):
    reviewed = [r for r in rows if r["_cat"]]
    n = len(reviewed)
    acc = sum(r["_cat"] == ACCURATE for r in reviewed)
    ocr = sum(r["_cat"] in OCR_CATS for r in reviewed)
    po = sum(r["_cat"] == "PO Issue" for r in reviewed)
    sc = sum(r["_cat"] == "Storm Creek Issue" for r in reviewed)
    return dict(
        logged=len(rows), reviewed=n, accurate=acc, ocr=ocr, po=po, sc=sc,
        unreviewed=len(rows) - n,
        acc_pct=acc / n * 100 if n else 0.0,
        ocr_pct=(1 - ocr / n) * 100 if n else 0.0,
    )


def pct(x):
    return f"{x:.1f}%"


def delta(a, b):
    d = a - b
    arrow = "▲" if d > 0.05 else ("▼" if d < -0.05 else "■")
    return f"{arrow} {d:+.1f} pts"


def theme_counts(rows):
    c = Counter()
    for r in rows:
        if r["_cat"] in OCR_CATS:
            for t in themes_for(r["_comment"]):
                c[t] += 1
    return c


def render_report(rows, day):
    dates = sorted({r["_date"] for r in rows})
    prior_dates = [d for d in dates if d < day]
    last7 = prior_dates[-7:]
    last30_start = day - datetime.timedelta(days=30)

    today = [r for r in rows if r["_date"] == day]
    p7 = [r for r in rows if r["_date"] in set(last7)]
    p30 = [r for r in rows if last30_start <= r["_date"] < day]
    s_today, s7, s30, s_all = stats(today), stats(p7), stats(p30), stats(rows)

    L = []
    L.append(f"# Storm Creek OCR Daily Report — {day.isoformat()}")
    L.append("")
    L.append(f"Source: \"Live Orders\" tab, {s_all['logged']:,} orders logged "
             f"{dates[0].isoformat()} → {dates[-1].isoformat()}. "
             f"Report day = {day.isoformat()} (latest logged day). "
             f"Baselines: previous 7 logged days ({last7[0].isoformat()} → {last7[-1].isoformat()}) "
             f"and previous 30 calendar days.")
    L.append("")

    # ---- Headline
    L.append("## 1. Headline")
    L.append("")
    L.append("| Metric | Report day | Prev 7 days | Δ vs 7d | Prev 30 days | All-time |")
    L.append("|---|---|---|---|---|---|")
    L.append(f"| Orders reviewed | {s_today['reviewed']} | {s7['reviewed']} | | {s30['reviewed']} | {s_all['reviewed']:,} |")
    L.append(f"| **OCR accuracy** (excl. PO/Storm Creek issues) | **{pct(s_today['ocr_pct'])}** | {pct(s7['ocr_pct'])} | {delta(s_today['ocr_pct'], s7['ocr_pct'])} | {pct(s30['ocr_pct'])} | {pct(s_all['ocr_pct'])} |")
    L.append(f"| Overall accuracy (all-OK orders) | {pct(s_today['acc_pct'])} | {pct(s7['acc_pct'])} | {delta(s_today['acc_pct'], s7['acc_pct'])} | {pct(s30['acc_pct'])} | {pct(s_all['acc_pct'])} |")
    L.append(f"| OCR issues | {s_today['ocr']} | {s7['ocr']} | | {s30['ocr']} | {s_all['ocr']} |")
    L.append(f"| PO issues (customer PO) | {s_today['po']} | {s7['po']} | | {s30['po']} | {s_all['po']} |")
    L.append(f"| Storm Creek issues | {s_today['sc']} | {s7['sc']} | | {s30['sc']} | {s_all['sc']} |")
    L.append("")
    if s_today["unreviewed"]:
        L.append(f"_{s_today['unreviewed']} order(s) on {day.isoformat()} have no \"Issue related\" value yet "
                 "and are excluded from accuracy._")
        L.append("")

    # ---- Error categorization for the day
    L.append("## 2. Today's errors, categorized")
    L.append("")
    tc_today = theme_counts(today)
    tc7 = theme_counts(p7)
    tc30 = theme_counts(p30)
    if tc_today:
        L.append("OCR error themes (an order can hit more than one):")
        L.append("")
        L.append("| Theme | Today | Prev 7 days (avg/day) | Prev 30 days |")
        L.append("|---|---|---|---|")
        for t, n in tc_today.most_common():
            avg = tc7[t] / len(last7) if last7 else 0
            L.append(f"| {t} | {n} | {tc7[t]} ({avg:.1f}) | {tc30[t]} |")
        L.append("")
    flagged = [r for r in today if r["_cat"] and r["_cat"] != ACCURATE]
    flagged.sort(key=lambda r: (r["_cat"] not in OCR_CATS, r["_cat"], r["_dist"]))
    if flagged:
        L.append("<details><summary>All flagged orders today</summary>")
        L.append("")
        L.append("| Category | Distributor | PO | Theme(s) | Reviewer comment |")
        L.append("|---|---|---|---|---|")
        for r in flagged:
            th = ", ".join(themes_for(r["_comment"])) if r["_cat"] in OCR_CATS else "—"
            com = r["_comment"].replace("|", "/").replace("\n", " ")
            L.append(f"| {r['_cat']} | {r['_dist']} | {r.get('PO Number','').strip()} | {th} | {com} |")
        L.append("")
        L.append("</details>")
        L.append("")

    # ---- Theme trend
    L.append("## 3. OCR error theme trend (weekly)")
    L.append("")
    weeks = []
    w_end = day
    for _ in range(4):
        w_start = w_end - datetime.timedelta(days=6)
        weeks.append((w_start, w_end))
        w_end = w_start - datetime.timedelta(days=1)
    weeks.reverse()
    wk_rows = [[r for r in rows if a <= r["_date"] <= b] for a, b in weeks]
    wk_tc = [theme_counts(w) for w in wk_rows]
    wk_st = [stats(w) for w in wk_rows]
    hdr = " | ".join(f"{a.strftime('%m/%d')}–{b.strftime('%m/%d')}" for a, b in weeks)
    L.append(f"| Theme | {hdr} | Direction |")
    L.append("|---|" + "---|" * len(weeks) + "---|")
    all_t = Counter()
    for c in wk_tc:
        all_t.update(c)
    for t, _ in all_t.most_common():
        vals = [c[t] for c in wk_tc]
        direction = "rising" if vals[-1] > vals[-2] and vals[-1] >= 3 else (
            "falling" if vals[-1] < vals[-2] else "flat")
        L.append(f"| {t} | " + " | ".join(str(v) for v in vals) + f" | {direction} |")
    L.append("| _OCR accuracy_ | " + " | ".join(pct(s["ocr_pct"]) for s in wk_st) + " | |")
    L.append("| _Orders reviewed_ | " + " | ".join(str(s["reviewed"]) for s in wk_st) + " | |")
    L.append("")

    # ---- Accounts
    L.append("## 4. Accounts (distributors)")
    L.append("")
    by_dist_today = defaultdict(list)
    for r in today:
        if r["_cat"] in OCR_CATS:
            by_dist_today[r["_dist"]].append(r)
    by_dist30 = defaultdict(list)
    for r in p30:
        by_dist30[r["_dist"]].append(r)
    if by_dist_today:
        L.append("### Accounts with OCR issues today, with their 30-day history")
        L.append("")
        L.append("| Distributor | OCR issues today | Orders (30d) | OCR issues (30d) | OCR acc. (30d) | Repeat? |")
        L.append("|---|---|---|---|---|---|")
        for dname, recs in sorted(by_dist_today.items(), key=lambda kv: -len(kv[1])):
            s = stats(by_dist30.get(dname, []))
            repeat = "**yes**" if s["ocr"] >= 2 else ("once before" if s["ocr"] == 1 else "new")
            L.append(f"| {dname} | {len(recs)} | {s['reviewed']} | {s['ocr']} | "
                     f"{pct(s['ocr_pct']) if s['reviewed'] else '—'} | {repeat} |")
        L.append("")

    L.append("### Recurring problem accounts — last 30 days (≥10 orders, worst OCR accuracy)")
    L.append("")
    ranked = []
    for dname, recs in by_dist30.items():
        s = stats(recs)
        if s["reviewed"] >= 10 and s["ocr"] > 0:
            top = theme_counts(recs).most_common(2)
            ranked.append((s["ocr_pct"], dname, s, top))
    ranked.sort(key=lambda x: (x[0], -x[2]["ocr"]))
    L.append("| Distributor | Orders | OCR issues | OCR acc. | Main themes |")
    L.append("|---|---|---|---|---|")
    for _, dname, s, top in ranked[:12]:
        th = "; ".join(f"{t} ({n})" for t, n in top)
        L.append(f"| {dname} | {s['reviewed']} | {s['ocr']} | {pct(s['ocr_pct'])} | {th} |")
    L.append("")

    # ---- Reviewers
    L.append("## 5. Reviewer view (today)")
    L.append("")
    by_rev = defaultdict(list)
    for r in today:
        by_rev[(r.get("Processed By") or "").strip() or "(blank)"].append(r)
    L.append("| Processed by | Orders | OCR issues flagged | PO issues flagged | Overall acc. |")
    L.append("|---|---|---|---|---|")
    for rv, recs in sorted(by_rev.items(), key=lambda kv: -len(kv[1])):
        s = stats(recs)
        if not s["reviewed"]:
            continue
        L.append(f"| {rv} | {s['reviewed']} | {s['ocr']} | {s['po']} | {pct(s['acc_pct'])} |")
    L.append("")
    L.append("_Large gaps in flag rate between reviewers on similar volume can mean inconsistent "
             "categorization rather than real accuracy differences._")
    L.append("")

    # ---- Where to improve
    L.append("## 6. Where improvement is needed (prioritized)")
    L.append("")
    scored = []
    for t in set(tc7) | set(tc_today):
        if t == "Other / unclassified":
            continue
        w_last, w_prev = wk_tc[-1][t], wk_tc[-2][t]
        scored.append((tc7[t] + 2 * tc_today[t] + max(0, w_last - w_prev), t, w_last, w_prev))
    scored.sort(reverse=True)
    for i, (_, t, w_last, w_prev) in enumerate(scored[:5], 1):
        dists = Counter(r["_dist"] for r in p7 + today
                        if r["_cat"] in OCR_CATS and t in themes_for(r["_comment"]))
        top_d = ", ".join(f"{d} ({n})" for d, n in dists.most_common(3))
        trend = "up" if w_last > w_prev else ("down" if w_last < w_prev else "flat")
        L.append(f"{i}. **{t}**: {tc_today[t]} today, {tc7[t]} in prev 7 days, "
                 f"week-over-week {w_prev}→{w_last} ({trend}). Most affected: {top_d}.")
    L.append("")
    non_ocr = s_today["po"] + s_today["sc"]
    if non_ocr:
        L.append(f"Non-OCR: {s_today['po']} PO issue(s) and {s_today['sc']} Storm Creek issue(s) today "
                 "— mostly unavailable colors/sizes, wrong part IDs on the customer PO, or missing "
                 "ship-to. These need customer/catalog follow-up, not model changes.")
        L.append("")

    return "\n".join(L), s_today, s7, scored


def main():
    if len(sys.argv) not in (3, 4):
        print(__doc__)
        sys.exit(1)
    rows = load_rows(sys.argv[1])
    if not rows:
        sys.exit("No dated rows found in CSV.")
    day = (datetime.date.fromisoformat(sys.argv[3]) if len(sys.argv) == 4
           else max(r["_date"] for r in rows))
    report, s_today, s7, scored = render_report(rows, day)
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print(f"day={day} ocr_acc={s_today['ocr_pct']:.1f} (7d {s7['ocr_pct']:.1f}) "
          f"overall={s_today['acc_pct']:.1f} (7d {s7['acc_pct']:.1f}) "
          f"ocr_issues={s_today['ocr']} po={s_today['po']} sc={s_today['sc']} "
          f"top={[t for _, t, *_ in scored[:3]]}")
    print(f"Wrote report to {sys.argv[2]}")


if __name__ == "__main__":
    main()
