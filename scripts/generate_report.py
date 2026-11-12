#!/usr/bin/env python3
"""
Generates the Storm Creek daily OCR accuracy/error report from a CSV export
of the "Live Orders" sheet in the tracker spreadsheet:
https://docs.google.com/spreadsheets/d/1SGFQmGZ59tKD4tdWKG3o1acZsZtZM85kN3sbUKUSGH4

Usage:
    python3 generate_report.py <live_orders.csv> <output_report.md> [YYYY-MM-DD]

The optional date is the "report day"; it defaults to the latest date logged
in the sheet. Required columns: Date, Week#, Processed By, PO Number,
Distributor, AX Comments, Issue related. "Secondary Cat for OCR Issue" and
"Order Status" are used when present.
"""
import csv
import re
import sys
import datetime
from collections import Counter, defaultdict

ACCURATE = "Accurate Orders"
OCR_CATS = ("OCR Issue", "OCR / Email Format")   # errors owned by the OCR/logic layer
OTHER_CATS = ("PO Issue", "Storm Creek Issue")    # source-document / client-side
SCORED = (ACCURATE,) + OCR_CATS + OTHER_CATS

# Ordered: first match wins for the "primary theme"; all matches are counted
# for the multi-theme table.
THEME_BUCKETS = [
    ("Contact name put in Ship-to + Company", r"both ship ?to and company"),
    ("PSST / Preferred ship date", r"\bpsst\b|preferred ship|ship date|in.?hands"),
    ("Order type (sample/regular)", r"order type|\bsample\b"),
    ("Account number / Shipping ID", r"account number|acct|account id|shipping id|shipper number|\bFF\b"),
    ("STC / Reporting Group (AIM)", r"\bSTC\b|state to credit|reporting group|\bRG\b|\bAIM\b|facilis"),
    ("Ship-to / Address", r"ship ?to|shipping address|address|secondline|second line|drop ?ship"),
    ("Ship method / Carrier", r"ship(ping)? method|carrier|\bups\b|fedex"),
    ("Product color", r"\bcolou?r\b"),
    ("Product size", r"\bsize\b|\b(xs|s|m|l|xl|2xl|3xl)\b\s*(was|is)"),
    ("Part ID / Product code / Lines", r"part ?id|product id|product code|\bsku\b|\bitem\b|\bline(s)?\b"),
    ("Quantity", r"\bqty\b|quantit"),
    ("Company name", r"company name"),
    ("PO number / PO contact", r"po number|po#|po #|po contact|po mail|contact email"),
    ("PPC / Proof / Unavailable product", r"\bppc\b|proof|not available|unavailable|invalid"),
    ("PO total / Price", r"po total|price|amount"),
]

SECONDARY_NORMALIZE = [
    (r"line\s*/?\s*part", "Line/Part ID"),
    (r"product colou?r", "Product color"),
    (r"product size", "Product size"),
    (r"product code", "Product code"),
    (r"account num", "Account number"),
    (r"shipping details", "Shipping details"),
    (r"shipping address|split ship", "Shipping address"),
    (r"order type", "Order type"),
]


def parse_date(s):
    s = s.strip()
    m, d, y = s.split("/")
    y = int(y)
    if y < 100:
        y += 2000
    return datetime.date(y, int(m), int(d))


def load_rows(csv_path):
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not r.get("Date", "").strip():
                continue
            try:
                r["_date"] = parse_date(r["Date"])
            except ValueError:
                continue
            r["Issue related"] = r.get("Issue related", "").strip()
            r["Distributor"] = r.get("Distributor", "").strip()
            r["AX Comments"] = (r.get("AX Comments") or "").strip()
            rows.append(r)
    return rows


def pct(n, d):
    return n / d * 100 if d else 0.0


def stats(recs):
    scored = [r for r in recs if r["Issue related"] in SCORED]
    n = len(scored)
    acc = sum(1 for r in scored if r["Issue related"] == ACCURATE)
    ocr = sum(1 for r in scored if r["Issue related"] in OCR_CATS)
    po = sum(1 for r in scored if r["Issue related"] == "PO Issue")
    sc = sum(1 for r in scored if r["Issue related"] == "Storm Creek Issue")
    return dict(n=n, acc=acc, ocr=ocr, po=po, sc=sc,
                acc_pct=pct(acc, n), ocr_acc_pct=pct(n - ocr, n),
                unscored=len(recs) - n)


def themes_for(comment):
    return [name for name, pat in THEME_BUCKETS if re.search(pat, comment, re.I)]


def norm_secondary(s):
    s = s.strip()
    if not s:
        return ""
    for pat, name in SECONDARY_NORMALIZE:
        if re.search(pat, s, re.I):
            return name
    return s[:1].upper() + s[1:]


def fmt_delta(x):
    return f"{x:+.1f} pts"


def window(rows, end, days):
    """Rows within the `days` logged dates ending at `end` (inclusive)."""
    dates = sorted({r["_date"] for r in rows if r["_date"] <= end})[-days:]
    ds = set(dates)
    return [r for r in rows if r["_date"] in ds], dates


def render_report(rows, report_day, generated_on):
    by_date = defaultdict(list)
    for r in rows:
        by_date[r["_date"]].append(r)
    all_dates = sorted(by_date)
    if report_day not in by_date:
        report_day = max(d for d in all_dates if d <= report_day)
    prev_dates = [d for d in all_dates if d < report_day]
    prev_day = prev_dates[-1] if prev_dates else None

    today = by_date[report_day]
    t = stats(today)
    p = stats(by_date[prev_day]) if prev_day else None

    last7, last7_dates = window(rows, report_day, 7)
    prior7, prior7_dates = window(rows, last7_dates[0] - datetime.timedelta(days=1), 7) if len(last7_dates) == 7 else ([], [])
    last30, _ = window(rows, report_day, 22)  # ~ one month of business days
    s7, sp7, s30 = stats(last7), stats(prior7), stats(last30)
    s_all = stats(rows)

    L = []
    L.append(f"# Storm Creek OCR Daily Report — {report_day.isoformat()}")
    L.append("")
    L.append(f"_Generated {generated_on.isoformat()} from the **Live Orders** tab "
             f"({len(rows)} logged orders, {all_dates[0]} → {all_dates[-1]}). "
             "Accuracy = Accurate Orders ÷ orders with an `Issue related` value "
             "(blank rows — duplicates, rejected files, no-PO — are excluded). "
             "**OCR accuracy** counts only `OCR Issue` + `OCR / Email Format` as errors, "
             "i.e. the errors that are ours to fix._")
    L.append("")

    # ---------------- Headline ----------------
    L.append("## Headline")
    L.append("")
    L.append("| Metric | Report day | Prev. day | Last 7 days | Prior 7 days | Last ~month | All-time |")
    L.append("|---|---|---|---|---|---|---|")
    def cell(s, key):
        return f"{s[key]:.1f}%" if s and s["n"] else "—"
    L.append(f"| Overall accuracy | **{cell(t,'acc_pct')}** | {cell(p,'acc_pct')} | {cell(s7,'acc_pct')} | "
             f"{cell(sp7,'acc_pct')} | {cell(s30,'acc_pct')} | {cell(s_all,'acc_pct')} |")
    L.append(f"| OCR accuracy | **{cell(t,'ocr_acc_pct')}** | {cell(p,'ocr_acc_pct')} | {cell(s7,'ocr_acc_pct')} | "
             f"{cell(sp7,'ocr_acc_pct')} | {cell(s30,'ocr_acc_pct')} | {cell(s_all,'ocr_acc_pct')} |")
    L.append(f"| Orders scored | {t['n']} | {p['n'] if p else '—'} | {s7['n']} | {sp7['n']} | {s30['n']} | {s_all['n']} |")
    L.append(f"| OCR errors | {t['ocr']} | {p['ocr'] if p else '—'} | {s7['ocr']} | {sp7['ocr']} | {s30['ocr']} | {s_all['ocr']} |")
    L.append(f"| PO / Storm Creek issues | {t['po']+t['sc']} | {(p['po']+p['sc']) if p else '—'} | "
             f"{s7['po']+s7['sc']} | {sp7['po']+sp7['sc']} | {s30['po']+s30['sc']} | {s_all['po']+s_all['sc']} |")
    L.append("")
    bullets = []
    if p:
        bullets.append(f"Report day OCR accuracy {t['ocr_acc_pct']:.1f}% vs {p['ocr_acc_pct']:.1f}% the previous "
                       f"logged day ({fmt_delta(t['ocr_acc_pct'] - p['ocr_acc_pct'])}).")
    if sp7["n"]:
        bullets.append(f"Week-over-week OCR accuracy: {s7['ocr_acc_pct']:.1f}% vs {sp7['ocr_acc_pct']:.1f}% "
                       f"({fmt_delta(s7['ocr_acc_pct'] - sp7['ocr_acc_pct'])}); "
                       f"overall accuracy {fmt_delta(s7['acc_pct'] - sp7['acc_pct'])}.")
    bullets.append(f"Daily volume on report day: {len(today)} orders logged "
                   f"({t['unscored']} without an `Issue related` value).")
    for b in bullets:
        L.append(f"- {b}")
    L.append("")

    # ---------------- Report-day flagged orders ----------------
    flagged = [r for r in today if r["Issue related"] not in (ACCURATE, "")]
    L.append(f"## Flagged orders on {report_day.isoformat()} ({len(flagged)})")
    L.append("")
    if flagged:
        L.append("| Category | Theme | Distributor | PO # | Reviewer comment |")
        L.append("|---|---|---|---|---|")
        flagged.sort(key=lambda r: (r["Issue related"] not in OCR_CATS, r["Issue related"], r["Distributor"]))
        for r in flagged:
            th = ", ".join(themes_for(r["AX Comments"])) or "Uncategorized"
            c = re.sub(r"\s+", " ", r["AX Comments"]).replace("|", "/")
            L.append(f"| {r['Issue related']} | {th} | {r['Distributor'] or '—'} | {r.get('PO Number','').strip()} | {c} |")
    else:
        L.append("No flagged orders.")
    L.append("")

    # ---------------- Theme categorization + trend ----------------
    def theme_counts(recs, cats):
        c = Counter()
        for r in recs:
            if r["Issue related"] in cats:
                for th in themes_for(r["AX Comments"]) or ["Uncategorized"]:
                    c[th] += 1
        return c

    L.append("## OCR error themes — trend")
    L.append("")
    L.append("Themes are derived from reviewer comments on `OCR Issue` / `OCR / Email Format` rows "
             "(one order can hit several themes). Trend compares the last 7 logged days with the prior 7.")
    L.append("")
    ct, c7, cp7, c30 = (theme_counts(today, OCR_CATS), theme_counts(last7, OCR_CATS),
                        theme_counts(prior7, OCR_CATS), theme_counts(last30, OCR_CATS))
    names = sorted(set(c7) | set(cp7) | set(c30), key=lambda k: (-c7[k], -c30[k]))
    L.append("| Theme | Report day | Last 7d | Prior 7d | Δ | Last ~month | Signal |")
    L.append("|---|---|---|---|---|---|---|")
    for k in names:
        d = c7[k] - cp7[k]
        if c7[k] >= 3 and d >= 2:
            sig = "🔺 rising"
        elif cp7[k] >= 3 and c7[k] == 0:
            sig = "✅ cleared"
        elif d <= -2:
            sig = "🔻 falling"
        else:
            sig = ""
        L.append(f"| {k} | {ct[k]} | {c7[k]} | {cp7[k]} | {d:+d} | {c30[k]} | {sig} |")
    L.append("")

    po7, pop7 = theme_counts(last7, OTHER_CATS), theme_counts(prior7, OTHER_CATS)
    if po7 or pop7:
        L.append("**PO / Storm Creek issues (source-document problems, not OCR)** — last 7d vs prior 7d: " +
                 ", ".join(f"{k} {po7[k]} (prev {pop7[k]})"
                           for k in sorted(set(po7) | set(pop7), key=lambda k: -po7[k])[:8]) + ".")
        L.append("")

    sec = Counter(norm_secondary(r.get("Secondary Cat for OCR Issue", "")) for r in last30)
    sec.pop("", None)
    if sec:
        L.append("**Reviewer-tagged secondary category (last ~month):** " +
                 ", ".join(f"{k} {v}" for k, v in sec.most_common(10)) + ".")
        L.append("")

    # ---------------- Daily trend ----------------
    L.append("## Daily trend (last 15 logged days)")
    L.append("")
    L.append("| Date | Scored | Accuracy % | OCR accuracy % | OCR errors | PO issues | SC issues |")
    L.append("|---|---|---|---|---|---|---|")
    for d in [x for x in all_dates if x <= report_day][-15:]:
        s = stats(by_date[d])
        mark = " ◀" if d == report_day else ""
        L.append(f"| {d}{mark} | {s['n']} | {s['acc_pct']:.1f}% | {s['ocr_acc_pct']:.1f}% | "
                 f"{s['ocr']} | {s['po']} | {s['sc']} |")
    L.append("")

    # ---------------- Weekly trend ----------------
    by_week = defaultdict(list)
    for r in rows:
        if r["_date"] <= report_day:
            iso = r["_date"].isocalendar()
            by_week[(iso[0], iso[1])].append(r)
    L.append("## Weekly trend")
    L.append("")
    L.append("| ISO week | Week of | Scored | Accuracy % | OCR accuracy % | OCR errors |")
    L.append("|---|---|---|---|---|---|")
    for wk in sorted(by_week)[-10:]:
        s = stats(by_week[wk])
        start = datetime.date.fromisocalendar(wk[0], wk[1], 1)
        L.append(f"| {wk[1]} | {start} | {s['n']} | {s['acc_pct']:.1f}% | {s['ocr_acc_pct']:.1f}% | {s['ocr']} |")
    L.append("")

    # ---------------- Accounts / distributors ----------------
    def by_dist(recs):
        g = defaultdict(list)
        for r in recs:
            if r["Distributor"]:
                g[r["Distributor"].strip().lower()].append(r)
        return g

    g14, _ = window(rows, report_day, 14)
    d14 = by_dist(g14)
    d30 = by_dist(last30)
    display = {}
    for r in rows:
        if r["Distributor"]:
            display.setdefault(r["Distributor"].strip().lower(), r["Distributor"].strip())

    L.append("## Accounts needing attention")
    L.append("")
    L.append("### Repeat OCR offenders (last 14 logged days)")
    L.append("")
    L.append("Accounts with OCR errors on 2+ different days, or 3+ OCR errors — likely a template/layout "
             "the model hasn't learned yet.")
    L.append("")
    rep = []
    for k, recs in d14.items():
        o = [r for r in recs if r["Issue related"] in OCR_CATS]
        days = {r["_date"] for r in o}
        if len(days) >= 2 or len(o) >= 3:
            th = Counter(t for r in o for t in (themes_for(r["AX Comments"]) or ["Uncategorized"]))
            s = stats(recs)
            rep.append((len(o), len(days), display[k], s, th))
    rep.sort(key=lambda x: (-x[0], -x[1]))
    if rep:
        L.append("| Distributor | OCR errors | Days hit | Orders | OCR accuracy % | Main themes |")
        L.append("|---|---|---|---|---|---|")
        for n_o, n_d, name, s, th in rep[:15]:
            L.append(f"| {name} | {n_o} | {n_d} | {s['n']} | {s['ocr_acc_pct']:.1f}% | "
                     f"{', '.join(f'{a} ({b})' for a, b in th.most_common(3))} |")
    else:
        L.append("None.")
    L.append("")

    L.append("### Lowest OCR accuracy, high-volume accounts (last ~month, 10+ scored orders)")
    L.append("")
    lows = []
    for k, recs in d30.items():
        s = stats(recs)
        if s["n"] >= 10:
            lows.append((s["ocr_acc_pct"], display[k], s))
    lows.sort()
    L.append("| Distributor | Orders | OCR accuracy % | OCR errors | Overall accuracy % |")
    L.append("|---|---|---|---|---|")
    for a, name, s in lows[:10]:
        L.append(f"| {name} | {s['n']} | {a:.1f}% | {s['ocr']} | {s['acc_pct']:.1f}% |")
    L.append("")

    # ---------------- Improvement priorities ----------------
    L.append("## Where improvement is needed (auto-ranked)")
    L.append("")
    pri = []
    for k in names:
        if k == "Uncategorized":
            continue
        score = c7[k] * 2 + c30[k] * 0.5 + max(0, c7[k] - cp7[k]) * 2
        if score > 0:
            pri.append((score, k))
    pri.sort(reverse=True)
    for i, (_, k) in enumerate(pri[:5], 1):
        accts = Counter(display[r["Distributor"].strip().lower()] for r in last7
                        if r["Distributor"] and r["Issue related"] in OCR_CATS and k in themes_for(r["AX Comments"]))
        ex = ", ".join(a for a, _ in accts.most_common(3))
        trend = "rising" if c7[k] > cp7[k] else ("falling" if c7[k] < cp7[k] else "flat")
        L.append(f"{i}. **{k}** — {c7[k]} errors in last 7d ({trend} vs {cp7[k]}), {c30[k]} in last ~month."
                 + (f" Accounts: {ex}." if ex else ""))
    L.append("")

    # ---------------- Data hygiene ----------------
    unscored_recent = [r for r in last7 if r["Issue related"] == ""]
    if unscored_recent:
        why = Counter((r["AX Comments"] or "(no comment)")[:40] for r in unscored_recent)
        L.append("## Data notes")
        L.append("")
        L.append(f"- {len(unscored_recent)} orders in the last 7 logged days have no `Issue related` value "
                 f"and are excluded from accuracy: " + ", ".join(f"{k} ({v})" for k, v in why.most_common(5)) + ".")
        L.append("")

    return "\n".join(L)


def main():
    if len(sys.argv) not in (3, 4):
        print(__doc__)
        sys.exit(1)
    csv_path, out_path = sys.argv[1], sys.argv[2]
    rows = load_rows(csv_path)
    if len(sys.argv) == 4:
        report_day = datetime.date.fromisoformat(sys.argv[3])
    else:
        report_day = max(r["_date"] for r in rows)
    report = render_report(rows, report_day, datetime.date.today())
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"Wrote report to {out_path}")


if __name__ == "__main__":
    main()
