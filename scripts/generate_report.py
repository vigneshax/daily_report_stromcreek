#!/usr/bin/env python3
"""
Generates the Storm Creek daily OCR accuracy/error report from a CSV export
of the "Live Orders" sheet in the tracker spreadsheet:
https://docs.google.com/spreadsheets/d/1SGFQmGZ59tKD4tdWKG3o1acZsZtZM85kN3sbUKUSGH4

Usage:
    python3 generate_report.py <live_orders.csv> <output_report.md> [YYYY-MM-DD]

The optional date is the "report day" to focus on; it defaults to the latest
date present in the sheet.

Required CSV columns: Date, Processed By, PO Number, Distributor, AX Comments,
Issue related. Optional (used when present): Secondary Cat for OCR Issue,
"Distributor wise ", Order Status.

Definitions
-----------
- Labeled order: a row whose "Issue related" is not blank. Rows with a blank
  label are reported as "unlabeled" and excluded from accuracy denominators.
- Overall accuracy: Accurate Orders / labeled orders.
- OCR accuracy: labeled orders WITHOUT an OCR-attributable issue
  ("OCR Issue" or "OCR / Email Format") / labeled orders. This is the number
  the dev team can move; PO Issue and Storm Creek Issue are client/data side.
"""
import csv
import re
import sys
import datetime
from collections import Counter, defaultdict

ACCURATE = "Accurate Orders"
OCR_LABELS = ("OCR Issue", "OCR / Email Format")
PO_LABEL = "PO Issue"
SC_LABEL = "Storm Creek Issue"

# Recurring themes in the reviewers' "AX Comments". A comment can hit several.
THEME_BUCKETS = {
    "STC (State To Credit)": r"\bSTC\b|state to credit",
    "Reporting Group / AIM / Facilis": r"reporting group|\bRG\b|\bAIM\b|facilis",
    "Ship To / Address": r"ship ?to|shipping address|ship address|secondline|second line|address",
    "Account Number": r"account number|acc(oun)?t\.? ?(no|#|id)|\bacct\b",
    "Part ID / Product code / Line": r"part ?id|product id|product code|\bsku\b|item code|\bline\b",
    "Color": r"colou?r|navy|gr[ae]y|black|charcoal",
    "Size / Quantity": r"\bsize\b|\bqty\b|quantity|\b[2-5]?xl\b",
    "Ship Method / Carrier": r"ship(ping)? ?method|ship via|carrier|will call|\bups\b|fedex",
    "PO Number": r"po number|po ?#|po no",
    "PO Contact / Email": r"po contact|po mail|contact email|email",
    "Company Name": r"company name",
    "Order Type": r"order type",
    "PO Total / Price": r"po total|price|amount",
    "In-hand / Ship date": r"in ?hand|ship date|due date",
}


def parse_date(s):
    m, d, y = s.strip().split("/")
    return datetime.date(int(y), int(m), int(d))


def load_rows(csv_path):
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if not r.get("Date", "").strip():
                continue
            try:
                r["_date"] = parse_date(r["Date"])
            except ValueError:
                continue
            r["_label"] = (r.get("Issue related") or "").strip()
            r["_dist"] = (r.get("Distributor") or "").strip()
            r["_comment"] = (r.get("AX Comments") or "").strip()
            r["_sec"] = (r.get("Secondary Cat for OCR Issue") or "").strip()
            rows.append(r)
    return rows


# ---------- stats helpers ----------

def stats(recs):
    labeled = [r for r in recs if r["_label"]]
    n = len(labeled)
    acc = sum(1 for r in labeled if r["_label"] == ACCURATE)
    ocr = sum(1 for r in labeled if r["_label"] in OCR_LABELS)
    po = sum(1 for r in labeled if r["_label"] == PO_LABEL)
    sc = sum(1 for r in labeled if r["_label"] == SC_LABEL)
    return dict(
        total=len(recs), labeled=n, unlabeled=len(recs) - n,
        accurate=acc, ocr=ocr, po=po, sc=sc,
        acc_pct=(acc / n * 100) if n else None,
        ocr_acc_pct=((n - ocr) / n * 100) if n else None,
    )


def pct(v):
    return "n/a" if v is None else f"{v:.1f}%"


def delta(a, b):
    if a is None or b is None:
        return "n/a"
    d = a - b
    arrow = "▲" if d > 0.05 else ("▼" if d < -0.05 else "▬")
    return f"{arrow} {d:+.1f} pts"


def themes_of(comment):
    return [name for name, pat in THEME_BUCKETS.items()
            if re.search(pat, comment, re.IGNORECASE)]


def theme_counts(recs):
    c = Counter()
    for r in recs:
        hits = themes_of(r["_comment"])
        if not hits:
            c["Other / uncategorized"] += 1
        for h in hits:
            c[h] += 1
    return c


def norm_sec(s):
    s = re.sub(r"\s+", " ", s.strip())
    return s[:1].upper() + s[1:].lower() if s else s


# ---------- report ----------

def md_escape(s):
    return s.replace("|", "/").replace("\n", " ").strip()


def render_report(rows, report_day, generated_on):
    dates = sorted({r["_date"] for r in rows})
    by_date = defaultdict(list)
    for r in rows:
        by_date[r["_date"]].append(r)

    day_recs = by_date.get(report_day, [])
    prior_days = [d for d in dates if d < report_day]
    last5 = prior_days[-5:]
    last20 = prior_days[-20:]
    win7 = [d for d in dates if d <= report_day][-7:]       # incl. report day
    prev7_28 = [d for d in dates if d < (win7[0] if win7 else report_day)][-21:]

    def recs_for(ds):
        out = []
        for d in ds:
            out.extend(by_date[d])
        return out

    s_day = stats(day_recs)
    s_5 = stats(recs_for(last5))
    s_20 = stats(recs_for(last20))
    s_all = stats(rows)
    s_win7 = stats(recs_for(win7))
    s_prev = stats(recs_for(prev7_28))

    L = []
    L.append(f"# Storm Creek OCR Daily Report — {report_day}")
    L.append("")
    L.append(f"_Generated {generated_on}. Source: Live Orders sheet "
             f"({len(rows)} logged orders, {dates[0]} → {dates[-1]}). "
             f"Report day = latest logged working day._")
    L.append("")

    # ---- Headline
    L.append("## Headline")
    L.append("")
    if not day_recs:
        L.append(f"- **No orders logged for {report_day}.** Latest data is {dates[-1]}.")
    else:
        L.append(f"- **{report_day}: {pct(s_day['acc_pct'])} overall accuracy** "
                 f"({s_day['accurate']}/{s_day['labeled']} labeled orders) — "
                 f"{delta(s_day['acc_pct'], s_5['acc_pct'])} vs prior 5-day avg "
                 f"({pct(s_5['acc_pct'])}), {delta(s_day['acc_pct'], s_20['acc_pct'])} "
                 f"vs prior 20-day avg ({pct(s_20['acc_pct'])}).")
        L.append(f"- **OCR accuracy (dev-fixable): {pct(s_day['ocr_acc_pct'])}** — "
                 f"{s_day['ocr']} OCR-attributable errors; "
                 f"{delta(s_day['ocr_acc_pct'], s_5['ocr_acc_pct'])} vs prior 5 days "
                 f"({pct(s_5['ocr_acc_pct'])}).")
        L.append(f"- Error mix today: {s_day['ocr']} OCR, {s_day['po']} PO (client-side), "
                 f"{s_day['sc']} Storm Creek; {s_day['unlabeled']} rows not yet labeled.")
    L.append(f"- Last 7 working days: {pct(s_win7['acc_pct'])} overall / "
             f"{pct(s_win7['ocr_acc_pct'])} OCR, vs {pct(s_prev['acc_pct'])} / "
             f"{pct(s_prev['ocr_acc_pct'])} in the 21 working days before "
             f"({delta(s_win7['acc_pct'], s_prev['acc_pct'])} overall).")
    L.append(f"- All-time (since {dates[0]}): {pct(s_all['acc_pct'])} overall / "
             f"{pct(s_all['ocr_acc_pct'])} OCR.")
    L.append("")

    # ---- Fix-first list
    win_ocr = [r for r in recs_for(win7) if r["_label"] in OCR_LABELS]
    prev_ocr = [r for r in recs_for(prev7_28) if r["_label"] in OCR_LABELS]
    t_win = theme_counts(win_ocr)
    t_prev = theme_counts(prev_ocr)
    n_win7_lab = s_win7["labeled"] or 1
    n_prev_lab = s_prev["labeled"] or 1

    L.append("## Where improvement is needed (OCR errors, last 7 working days)")
    L.append("")
    L.append("Rate = OCR errors with this theme per 100 labeled orders. "
             "Change compares against the 21 working days before.")
    L.append("")
    L.append("| # | Theme | Errors (7d) | Rate /100 orders | Prior rate | Change |")
    L.append("|---|---|---|---|---|---|")
    for i, (name, cnt) in enumerate(t_win.most_common(10), 1):
        rate = cnt / n_win7_lab * 100
        prate = t_prev.get(name, 0) / n_prev_lab * 100
        trend = "worse" if rate > prate * 1.15 + 0.05 else (
            "better" if rate < prate * 0.85 - 0.05 else "flat")
        L.append(f"| {i} | {name} | {cnt} | {rate:.2f} | {prate:.2f} | {trend} |")
    L.append("")

    # Secondary category (reviewer-assigned) if present
    sec = Counter(norm_sec(r["_sec"]) for r in recs_for(win7)
                  if r["_label"] in OCR_LABELS and r["_sec"])
    if sec:
        L.append("Reviewer-assigned secondary category for OCR issues (last 7 days): " +
                 ", ".join(f"{k} ({v})" for k, v in sec.most_common(8)) + ".")
        L.append("")

    # ---- Today's error categorization
    if day_recs:
        L.append(f"## Error categorization — {report_day}")
        L.append("")
        flagged = [r for r in day_recs if r["_label"] and r["_label"] != ACCURATE]
        L.append("| Theme | OCR | PO | Storm Creek |")
        L.append("|---|---|---|---|")
        tc = defaultdict(Counter)
        for r in flagged:
            hits = themes_of(r["_comment"]) or ["Other / uncategorized"]
            bucket = ("OCR" if r["_label"] in OCR_LABELS else
                      "PO" if r["_label"] == PO_LABEL else "SC")
            for h in hits:
                tc[h][bucket] += 1
        for name, c in sorted(tc.items(), key=lambda kv: -sum(kv[1].values())):
            L.append(f"| {name} | {c['OCR']} | {c['PO']} | {c['SC']} |")
        L.append("")

        L.append(f"### OCR issues to action ({report_day})")
        L.append("")
        ocr_today = [r for r in day_recs if r["_label"] in OCR_LABELS]
        if ocr_today:
            L.append("| Distributor | PO Number | Reviewer comment |")
            L.append("|---|---|---|")
            for r in sorted(ocr_today, key=lambda r: r["_dist"]):
                L.append(f"| {md_escape(r['_dist'])} | {md_escape(r.get('PO Number', ''))} | "
                         f"{md_escape(r['_comment'])} |")
        else:
            L.append("None logged.")
        L.append("")

        po_today = [r for r in day_recs if r["_label"] == PO_LABEL]
        if po_today:
            L.append(f"### PO / client-side issues ({report_day}) — FYI, not OCR")
            L.append("")
            for r in sorted(po_today, key=lambda r: r["_dist"]):
                L.append(f"- **{md_escape(r['_dist'])}**: {md_escape(r['_comment'])[:220]}")
            L.append("")

        unl = [r for r in day_recs if not r["_label"]]
        if unl:
            L.append(f"_Unlabeled rows on {report_day}: " +
                     ", ".join(f"{md_escape(r['_dist'])}"
                               + (f" (“{md_escape(r['_comment'])[:60]}”)" if r["_comment"] else "")
                               for r in unl) + "._")
            L.append("")

    # ---- Daily trend
    L.append("## Daily trend (last 15 working days)")
    L.append("")
    L.append("| Date | Orders | Overall acc. | OCR acc. | OCR | PO | Storm Creek |")
    L.append("|---|---|---|---|---|---|---|")
    for d in [d for d in dates if d <= report_day][-15:]:
        s = stats(by_date[d])
        mark = " ◀" if d == report_day else ""
        L.append(f"| {d}{mark} | {s['total']} | {pct(s['acc_pct'])} | {pct(s['ocr_acc_pct'])} | "
                 f"{s['ocr']} | {s['po']} | {s['sc']} |")
    L.append("")

    # ---- Weekly trend
    L.append("## Weekly trend")
    L.append("")
    L.append("| Week of (Mon) | Orders | Overall acc. | OCR acc. | OCR errors | PO issues |")
    L.append("|---|---|---|---|---|---|")
    weeks = defaultdict(list)
    for r in rows:
        if r["_date"] <= report_day:
            wk = r["_date"] - datetime.timedelta(days=r["_date"].weekday())
            weeks[wk].append(r)
    for wk in sorted(weeks):
        s = stats(weeks[wk])
        L.append(f"| {wk} | {s['total']} | {pct(s['acc_pct'])} | {pct(s['ocr_acc_pct'])} | "
                 f"{s['ocr']} | {s['po']} |")
    L.append("")

    # ---- Distributor trends
    def dist_stats(recs):
        g = defaultdict(list)
        for r in recs:
            if r["_dist"]:
                g[r["_dist"]].append(r)
        return {k: stats(v) for k, v in g.items()}

    d_win = dist_stats(recs_for(win7))
    d_prev = dist_stats(recs_for(prev7_28))

    L.append("## Accounts / distributors — trend")
    L.append("")
    L.append("### Most OCR errors in the last 7 working days")
    L.append("")
    L.append("| Distributor | Orders (7d) | OCR errors | OCR acc. (7d) | OCR acc. (prior 21d) | Change | Top themes |")
    L.append("|---|---|---|---|---|---|---|")
    win_by_dist = defaultdict(list)
    for r in win_ocr:
        win_by_dist[r["_dist"]].append(r)
    top = sorted(((k, v) for k, v in d_win.items() if v["ocr"] > 0),
                 key=lambda kv: (-kv[1]["ocr"], kv[1]["ocr_acc_pct"] or 0))[:12]
    for k, v in top:
        p = d_prev.get(k)
        tt = theme_counts(win_by_dist[k]).most_common(2)
        L.append(f"| {md_escape(k)} | {v['labeled']} | {v['ocr']} | {pct(v['ocr_acc_pct'])} | "
                 f"{pct(p['ocr_acc_pct']) if p else 'new'} | "
                 f"{delta(v['ocr_acc_pct'], p['ocr_acc_pct']) if p else '—'} | "
                 f"{', '.join(n for n, _ in tt)} |")
    L.append("")

    L.append("### Worsening accounts (≥5 orders in both windows, OCR accuracy down ≥10 pts)")
    L.append("")
    worse = []
    better = []
    for k, v in d_win.items():
        p = d_prev.get(k)
        if not p or v["labeled"] < 5 or p["labeled"] < 5:
            continue
        dlt = v["ocr_acc_pct"] - p["ocr_acc_pct"]
        if dlt <= -10:
            worse.append((dlt, k, v, p))
        elif dlt >= 10:
            better.append((dlt, k, v, p))
    if worse:
        for dlt, k, v, p in sorted(worse):
            L.append(f"- **{k}**: {pct(p['ocr_acc_pct'])} → {pct(v['ocr_acc_pct'])} "
                     f"({v['ocr']} OCR errors in {v['labeled']} orders)")
    else:
        L.append("- None.")
    L.append("")
    if better:
        L.append("### Improving accounts (OCR accuracy up ≥10 pts)")
        L.append("")
        for dlt, k, v, p in sorted(better, reverse=True):
            L.append(f"- **{k}**: {pct(p['ocr_acc_pct'])} → {pct(v['ocr_acc_pct'])}")
        L.append("")

    # Chronic offenders over whole history
    d_all = dist_stats(rows)
    chronic = sorted(((k, v) for k, v in d_all.items() if v["labeled"] >= 40),
                     key=lambda kv: kv[1]["ocr_acc_pct"])[:8]
    L.append("### Chronic low-accuracy accounts (all-time, ≥40 orders)")
    L.append("")
    L.append("| Distributor | Orders | Overall acc. | OCR acc. | PO issues |")
    L.append("|---|---|---|---|---|")
    for k, v in chronic:
        L.append(f"| {md_escape(k)} | {v['labeled']} | {pct(v['acc_pct'])} | "
                 f"{pct(v['ocr_acc_pct'])} | {v['po']} |")
    L.append("")

    # ---- Associates
    L.append("## Reviewer / associate volume (last 7 working days)")
    L.append("")
    L.append("| Processed By | Orders | Overall acc. | OCR errors flagged |")
    L.append("|---|---|---|---|")
    g = defaultdict(list)
    for r in recs_for(win7):
        if (r.get("Processed By") or "").strip():
            g[r["Processed By"].strip()].append(r)
    for k, recs in sorted(g.items(), key=lambda kv: -len(kv[1])):
        s = stats(recs)
        L.append(f"| {k} | {s['total']} | {pct(s['acc_pct'])} | {s['ocr']} |")
    L.append("")

    return "\n".join(L)


def main():
    if len(sys.argv) not in (3, 4):
        print(__doc__)
        sys.exit(1)
    csv_path, out_path = sys.argv[1], sys.argv[2]
    rows = load_rows(csv_path)
    if not rows:
        sys.exit("No dated rows found in CSV")
    if len(sys.argv) == 4:
        report_day = datetime.date.fromisoformat(sys.argv[3])
    else:
        report_day = max(r["_date"] for r in rows)
    generated_on = datetime.date.today().isoformat()
    report = render_report(rows, report_day, generated_on)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"Wrote report for {report_day} to {out_path}")


if __name__ == "__main__":
    main()
