#!/usr/bin/env python3
"""
Generates the Storm Creek daily OCR accuracy/error report from a CSV export
of the "Live Orders" sheet in the tracker spreadsheet:
https://docs.google.com/spreadsheets/d/1SGFQmGZ59tKD4tdWKG3o1acZsZtZM85kN3sbUKUSGH4

Usage:
    python3 generate_report.py <live_orders.csv> <output_report.md> [YYYY-MM-DD]

The optional date is the "report day". It defaults to the latest date logged
in the sheet (reviewers log the previous business day's orders).

Columns used (looked up by name; extra columns are ignored):
Date, Processed By, Order Status, PO Number, Distributor, AX Comments,
Issue related, Secondary Cat for OCR Issue

Accuracy definitions:
- Overall accuracy  = "Accurate Orders" / reviewed orders (rows whose
  "Issue related" is filled in; blank rows are counted as unreviewed).
- OCR accuracy      = orders without an OCR-attributable issue / reviewed
  orders. OCR-attributable = "OCR Issue" + "OCR / Email Format". PO Issue and
  Storm Creek Issue are problems in the PO / client data, not the system.
"""
import csv
import re
import sys
import datetime
from collections import Counter, defaultdict

ACCURATE = "Accurate Orders"
OCR_CATS = ("OCR Issue", "OCR / Email Format")
CATEGORIES = ("OCR Issue", "OCR / Email Format", "PO Issue", "Storm Creek Issue")

THEME_BUCKETS = {
    "Ship To / Address": r"ship ?to|shipping address|address|secondline|second line|attn|attention",
    "Account Number": r"account number|acct|account id|account no",
    "STC (State To Credit)": r"\bSTC\b|state to credit",
    "Reporting Group / AIM": r"reporting group|\bRG\b|\bAIM\b|facilis",
    "Ship Method / Carrier": r"ship(ping)? method|carrier|\bups\b|\busps\b|fedex|shipper|ground",
    "Color": r"colou?r|heather|black|navy|white|gray|grey",
    "Size": r"\bsize|\bXS\b|\bXL\b|\b2XL\b|\b3XL\b",
    "Product / Part ID / SKU": r"product id|part id|part number|\bsku\b|product code|item",
    "PO Number": r"po ?(number|no|#)",
    "PO Contact / Email": r"po contact|po mail|contact|email",
    "Quantity": r"\bqty\b|quantity",
    "PO Total / Price": r"po total|total|price|amount",
    "Order Type / Sample": r"order type|sample",
    "In-hands / Ship Date": r"in ?hands?|ship date|due date|date",
    "Company Name": r"company name",
}


def parse_date(s):
    m, d, y = s.strip().split("/")
    return datetime.date(int(y), int(m), int(d))


def load_rows(csv_path):
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
            if not r.get("Date"):
                continue
            try:
                r["_date"] = parse_date(r["Date"])
            except ValueError:
                continue
            rows.append(r)
    return rows


def reviewed(rows):
    return [r for r in rows if r.get("Issue related")]


def stats(rows):
    rv = reviewed(rows)
    n = len(rv)
    c = Counter(r["Issue related"] for r in rv)
    acc = c[ACCURATE]
    ocr = sum(c[k] for k in OCR_CATS)
    return dict(
        logged=len(rows), n=n, accurate=acc, ocr=ocr,
        ocr_issue=c["OCR Issue"], email_fmt=c["OCR / Email Format"],
        po=c["PO Issue"], sc=c["Storm Creek Issue"],
        acc_pct=acc / n * 100 if n else 0.0,
        ocr_acc_pct=(n - ocr) / n * 100 if n else 0.0,
        rejected=sum(1 for r in rows if "reject" in r.get("Order Status", "").lower()),
    )


def themes(rows):
    counts = Counter()
    for r in rows:
        text = r.get("AX Comments", "") + " " + r.get("Secondary Cat for OCR Issue", "")
        for name, pat in THEME_BUCKETS.items():
            if re.search(pat, text, re.IGNORECASE):
                counts[name] += 1
    return counts


def by_key(rows, key):
    d = defaultdict(list)
    for r in rows:
        if r.get(key):
            d[r[key]].append(r)
    return d


def pct(x):
    return f"{x:.1f}%"


def delta(a, b):
    d = a - b
    arrow = "▲" if d > 0.05 else ("▼" if d < -0.05 else "■")
    return f"{arrow} {d:+.1f} pts"


def render_report(rows, report_day):
    dates = sorted({r["_date"] for r in rows})
    if report_day not in dates:
        raise SystemExit(f"No rows logged for {report_day}")
    idx = dates.index(report_day)
    prev_day = dates[idx - 1] if idx > 0 else None
    wk_days = dates[max(0, idx - 4): idx + 1]            # last 5 logged days incl. today
    prior_wk_days = dates[max(0, idx - 9): max(0, idx - 4)]
    m30_days = dates[max(0, idx - 19): idx + 1]          # ~4 weeks of business days
    prior30_days = dates[max(0, idx - 39): max(0, idx - 19)]

    def sel(ds):
        s = set(ds)
        return [r for r in rows if r["_date"] in s]

    today = sel([report_day])
    prev = sel([prev_day]) if prev_day else []
    wk, prior_wk = sel(wk_days), sel(prior_wk_days)
    m30, prior30 = sel(m30_days), sel(prior30_days)
    upto = [r for r in rows if r["_date"] <= report_day]

    T, P, W, PW, M, PM, ALL = (stats(x) for x in (today, prev, wk, prior_wk, m30, prior30, upto))

    L = []
    a = L.append
    a(f"# Storm Creek OCR Daily Report — {report_day}")
    a("")
    a(f"Source: Live Orders sheet ({ALL['logged']} orders logged {dates[0]} → {report_day}). "
      f"Report day = latest logged day **{report_day}** ({report_day.strftime('%A')}).")
    a("")
    a("## Headline")
    a("")
    a("| Window | Reviewed | Accuracy | OCR accuracy | OCR issues | Email fmt | PO issues | SC issues |")
    a("|---|---|---|---|---|---|---|---|")
    for label, s in ((f"Today ({report_day})", T),
                     (f"Prev day ({prev_day})", P),
                     (f"Last 5 days ({wk_days[0]}→{wk_days[-1]})", W),
                     (f"Prior 5 days", PW),
                     (f"Last 20 days", M),
                     (f"Prior 20 days", PM),
                     ("All time", ALL)):
        if not s["n"]:
            continue
        a(f"| {label} | {s['n']} | {pct(s['acc_pct'])} | {pct(s['ocr_acc_pct'])} | "
          f"{s['ocr_issue']} | {s['email_fmt']} | {s['po']} | {s['sc']} |")
    a("")
    a(f"- Today vs previous day: accuracy {delta(T['acc_pct'], P['acc_pct'])}, "
      f"OCR accuracy {delta(T['ocr_acc_pct'], P['ocr_acc_pct'])}.")
    if PW["n"]:
        a(f"- Week over week (5 logged days): accuracy {delta(W['acc_pct'], PW['acc_pct'])}, "
          f"OCR accuracy {delta(W['ocr_acc_pct'], PW['ocr_acc_pct'])}.")
    if PM["n"]:
        a(f"- Last 20 vs prior 20 logged days: accuracy {delta(M['acc_pct'], PM['acc_pct'])}, "
          f"OCR accuracy {delta(M['ocr_acc_pct'], PM['ocr_acc_pct'])}.")
    unrev = T["logged"] - T["n"]
    if unrev:
        a(f"- {unrev} order(s) logged today have no 'Issue related' value yet (excluded).")
    if T["rejected"]:
        a(f"- {T['rejected']} order(s) today were File Rejected.")
    a("")

    # ---- today's flagged orders
    flagged_today = [r for r in reviewed(today) if r["Issue related"] != ACCURATE]
    a(f"## Today's flagged orders ({len(flagged_today)})")
    a("")
    if flagged_today:
        a("| Category | Distributor | PO # | Processed By | Reviewer comment |")
        a("|---|---|---|---|---|")
        order = {c: i for i, c in enumerate(CATEGORIES)}
        for r in sorted(flagged_today, key=lambda r: (order.get(r["Issue related"], 9), r["Distributor"])):
            cm = r["AX Comments"].replace("|", "/").replace("\n", " ")
            a(f"| {r['Issue related']} | {r['Distributor']} | {r['PO Number']} | "
              f"{r['Processed By']} | {cm} |")
    else:
        a("None — every reviewed order was accurate.")
    a("")

    mislabeled = [r for r in flagged_today
                  if r["Issue related"] not in OCR_CATS
                  and re.search(r"\b(captured|not captured|system)\b", r["AX Comments"], re.I)]
    if mislabeled:
        a("**Check the category:** these are tagged as non-OCR, but the comment describes a capture error: "
          + "; ".join(f"{r['Distributor']} (PO {r['PO Number']})" for r in mislabeled))
        a("")

    # ---- error categories
    ocr_today = [r for r in today if r.get("Issue related") in OCR_CATS]
    ocr_wk = [r for r in wk if r.get("Issue related") in OCR_CATS]
    ocr_pwk = [r for r in prior_wk if r.get("Issue related") in OCR_CATS]
    ocr_m = [r for r in m30 if r.get("Issue related") in OCR_CATS]
    th_t, th_w, th_pw, th_m = themes(ocr_today), themes(ocr_wk), themes(ocr_pwk), themes(ocr_m)
    a("## OCR error categories (what to fix)")
    a("")
    a("Keyword-bucketed from reviewer comments on OCR-attributable orders; one order can hit several buckets.")
    a("")
    a("| Error type | Today | Last 5 days | Prior 5 days | WoW | Last 20 days |")
    a("|---|---|---|---|---|---|")
    for name, _ in th_m.most_common():
        d = th_w[name] - th_pw[name]
        a(f"| {name} | {th_t[name]} | {th_w[name]} | {th_pw[name]} | {d:+d} | {th_m[name]} |")
    a("")
    rising = sorted(((th_w[n] - th_pw[n], n) for n in THEME_BUCKETS if th_w[n] - th_pw[n] >= 2), reverse=True)
    if rising:
        a("**Rising this week:** " + ", ".join(f"{n} ({d:+d})" for d, n in rising))
        a("")

    # ---- PO-side issues
    po_wk = [r for r in wk if r.get("Issue related") in ("PO Issue", "Storm Creek Issue")]
    if po_wk:
        a("## Non-OCR issues, last 5 days (PO / Storm Creek data)")
        a("")
        for name, c in themes(po_wk).most_common(6):
            a(f"- {name}: {c}")
        a("")

    # ---- distributors
    a("## Accounts needing attention")
    a("")
    a("Distributors with the most OCR-attributable issues in the last 20 logged days "
      "(min 5 orders), with the trend vs the prior 20 days.")
    a("")
    a("| Distributor | Orders (20d) | OCR issues (20d) | OCR acc. (20d) | OCR acc. (prior 20d) | Trend | Issues today |")
    a("|---|---|---|---|---|---|---|")
    dm, dpm, dt = by_key(m30, "Distributor"), by_key(prior30, "Distributor"), by_key(today, "Distributor")
    drows = []
    for dist, recs in dm.items():
        s = stats(recs)
        if s["n"] < 5 or s["ocr"] == 0:
            continue
        ps = stats(dpm.get(dist, []))
        drows.append((s["ocr"], s, ps, dist))
    drows.sort(key=lambda x: (-x[0], x[1]["ocr_acc_pct"]))
    for _, s, ps, dist in drows[:15]:
        prior = pct(ps["ocr_acc_pct"]) if ps["n"] else "—"
        trend = delta(s["ocr_acc_pct"], ps["ocr_acc_pct"]) if ps["n"] else "new"
        tdy = stats(dt.get(dist, []))["ocr"]
        a(f"| {dist} | {s['n']} | {s['ocr']} | {pct(s['ocr_acc_pct'])} | {prior} | {trend} | {tdy or ''} |")
    a("")

    # recurring repeat offenders today
    rep = [d for d in {r["Distributor"] for r in ocr_today}
           if stats(dm.get(d, []))["ocr"] >= 3]
    if rep:
        a("**Repeat offenders that failed again today:** " + ", ".join(sorted(rep)))
        a("")

    # ---- daily trend
    a("## Daily trend (last 20 logged days)")
    a("")
    a("| Date | Reviewed | Accuracy | OCR acc. | OCR | Email fmt | PO | SC |")
    a("|---|---|---|---|---|---|---|---|")
    for d in m30_days:
        s = stats(sel([d]))
        a(f"| {d} | {s['n']} | {pct(s['acc_pct'])} | {pct(s['ocr_acc_pct'])} | "
          f"{s['ocr_issue']} | {s['email_fmt']} | {s['po']} | {s['sc']} |")
    a("")

    # ---- associates
    a("## Processed-by breakdown (last 5 days)")
    a("")
    a("| Processed By | Orders | Accuracy | OCR acc. |")
    a("|---|---|---|---|")
    for who, recs in sorted(by_key(wk, "Processed By").items(), key=lambda kv: -len(kv[1])):
        s = stats(recs)
        if s["n"]:
            a(f"| {who} | {s['n']} | {pct(s['acc_pct'])} | {pct(s['ocr_acc_pct'])} |")
    a("")
    return "\n".join(L)


def main():
    if len(sys.argv) not in (3, 4):
        print(__doc__)
        sys.exit(1)
    rows = load_rows(sys.argv[1])
    if len(sys.argv) == 4:
        day = datetime.date.fromisoformat(sys.argv[3])
    else:
        day = max(r["_date"] for r in rows)
    report = render_report(rows, day)
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print(f"Wrote report for {day} to {sys.argv[2]}")


if __name__ == "__main__":
    main()
