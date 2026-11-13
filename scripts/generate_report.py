#!/usr/bin/env python3
"""
Generates the Storm Creek daily OCR accuracy/error report from a CSV export
of the "Live Orders" tab of the tracker spreadsheet:
https://docs.google.com/spreadsheets/d/1SGFQmGZ59tKD4tdWKG3o1acZsZtZM85kN3sbUKUSGH4

Usage:
    python3 generate_report.py <live_orders.csv> <output_report.md> [YYYY-MM-DD]

The optional date is the "focus day"; it defaults to the latest date in the sheet.

Required columns (others are ignored, extra columns are fine):
    Date, Processed By, Order Status, PO Number, Distributor, AX Comments,
    Issue related
Optional columns used when present:
    Secondary Cat for OCR Issue, Dev Notes, Status
"""
import csv
import re
import sys
import datetime
from collections import Counter, defaultdict

ACCURATE = "Accurate Orders"
# Errors attributable to our OCR/logic (what we fix).
OCR_CATS = ("OCR Issue", "OCR / Email Format")
# Errors on the customer's PO itself / on Storm Creek side.
OTHER_CATS = ("PO Issue", "Storm Creek Issue")
ALL_CATS = (ACCURATE,) + OCR_CATS + OTHER_CATS

THEME_BUCKETS = {
    "STC (State To Credit)": r"\bSTC\b|state to credit",
    "Reporting Group / AIM / Facilis": r"reporting group|\bRG\b|\bAIM\b|facilis",
    "Account Number / Shipping Acct": r"account (number|no|id|#)|\bacct\b|8318",
    "Ship To / Address": r"ship ?to|shipping address|address|secondline|second line|drop ?ship",
    "Ship Method / Expedite": r"ship(ping)? method|carrier|expedite|overnight|ground|\bUPS\b|fedex",
    "Ship Date / In-hands Date": r"ship date|in.?hands|due date|need by",
    "Order Type": r"order type",
    "PSST (new details)": r"\bPSST\b",
    "Line / Part ID / Product Code": r"part ?id|product ?(id|code)|item code|\bsku\b|line record|line was not|line item",
    "Color / Size": r"\bcolou?r\b|\bsize\b",
    "Quantity": r"\bqty\b|quantity",
    "PO Number": r"po ?(number|#|no\b)",
    "PO Contact / Email": r"po contact|po mail|contact (email|name)|e-?mail",
    "Company Name": r"company name",
    "Proof / PPC": r"\bproof\b|\bPPC\b",
    "Pricing / PO Total": r"price|pricing|po total|amount",
    "Decoration / Imprint": r"decorat|imprint|embroider|logo",
}


def parse_date(s):
    try:
        return datetime.datetime.strptime(s.strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def norm(s):
    return (s or "").strip()


def load_rows(csv_path):
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            d = parse_date(r.get("Date", ""))
            if not d:
                continue
            r = {k.strip() if k else k: v for k, v in r.items()}
            r["_date"] = d
            r["_cat"] = norm(r.get("Issue related"))
            r["_dist"] = norm(r.get("Distributor"))
            r["_comment"] = re.sub(r"\s+", " ", norm(r.get("AX Comments")).strip('"'))
            rows.append(r)
    return rows


def scored(rows):
    """Rows that carry a reviewer verdict (blank verdict = rejected/unscored)."""
    return [r for r in rows if r["_cat"] in ALL_CATS]


def stats(rows):
    s = scored(rows)
    n = len(s)
    c = Counter(r["_cat"] for r in s)
    acc = c[ACCURATE]
    ocr = sum(c[k] for k in OCR_CATS)
    return dict(
        n=n, acc=acc, ocr=ocr, po=c["PO Issue"], sc=c["Storm Creek Issue"],
        email=c["OCR / Email Format"], unscored=len(rows) - n,
        acc_pct=(acc / n * 100) if n else None,
        # OCR accuracy: share of orders our pipeline did not get wrong.
        ocr_pct=((n - ocr) / n * 100) if n else None,
    )


def pct(x):
    return "n/a" if x is None else f"{x:.1f}%"


def delta(a, b):
    if a is None or b is None:
        return "n/a"
    d = a - b
    arrow = "▲" if d > 0.05 else ("▼" if d < -0.05 else "■")
    return f"{arrow} {d:+.1f} pts"


def themes_for(comment):
    return [n for n, p in THEME_BUCKETS.items() if re.search(p, comment, re.IGNORECASE)] or ["Other / Unclassified"]


def theme_counts(rows):
    c = Counter()
    for r in rows:
        for t in themes_for(r["_comment"]):
            c[t] += 1
    return c


def comment_signature(c):
    """Normalise a comment so near-identical reviewer notes group together."""
    c = c.lower()
    c = re.sub(r"\d+\)", " ", c)
    c = re.sub(r"[\"'“”]", "", c)
    c = re.sub(r"\s+", " ", c).strip(" .")
    return c[:90]


def render(rows, focus):
    days = sorted({r["_date"] for r in rows if r["_date"] <= focus})
    if focus not in days:
        raise SystemExit(f"No rows for focus day {focus}")
    by_day = defaultdict(list)
    for r in rows:
        by_day[r["_date"]].append(r)

    idx = days.index(focus)
    prev_day = days[idx - 1] if idx else None
    last7 = days[max(0, idx - 6): idx + 1]
    prior7 = days[max(0, idx - 13): max(0, idx - 6)]
    last14 = days[max(0, idx - 13): idx + 1]
    last30 = days[max(0, idx - 29): idx + 1]

    def rows_in(ds):
        ds = set(ds)
        return [r for r in rows if r["_date"] in ds]

    today = by_day[focus]
    st_today = stats(today)
    st_prev = stats(by_day[prev_day]) if prev_day else stats([])
    st_7 = stats(rows_in(last7))
    st_p7 = stats(rows_in(prior7))
    st_30 = stats(rows_in(last30))
    st_all = stats(rows)

    # Is the focus day still being logged?
    vols = [len(scored(by_day[d])) for d in last7[:-1]]
    avg_vol = sum(vols) / len(vols) if vols else 0
    partial = avg_vol and st_today["n"] < 0.6 * avg_vol

    L = []
    L.append(f"# Storm Creek OCR Daily Report — {focus}")
    L.append("")
    L.append(f"_Source: “Live Orders” tab ({len(rows)} logged rows, {days[0]} → {days[-1]}). "
             f"Generated {datetime.date.today()}._")
    L.append("")
    if partial:
        L.append(f"> ⚠️ **{focus} looks partially logged** — {st_today['n']} reviewed orders vs a "
                 f"{avg_vol:.0f}/day average over the previous 6 days. Treat today's numbers as provisional; "
                 f"the 7-day figures are the more reliable signal.")
        L.append("")

    L.append("__FOCUS__")
    L.append("## 1. Headline")
    L.append("")
    L.append("**Overall accuracy** = orders marked “Accurate Orders” ÷ reviewed orders. "
             "**OCR accuracy** = orders *not* flagged as an OCR-side error (OCR Issue + OCR / Email Format) — "
             "this is the number our fixes move; PO Issues and Storm Creek Issues are customer/client-side.")
    L.append("")
    L.append("| Window | Reviewed | Overall accuracy | OCR accuracy | OCR errors | PO issues | Storm Creek |")
    L.append("|---|---|---|---|---|---|---|")
    for label, s in [(f"**{focus}** (focus day)", st_today),
                     (f"{prev_day} (previous day)", st_prev),
                     (f"Last 7 logged days", st_7),
                     (f"Prior 7 logged days", st_p7),
                     (f"Last 30 logged days", st_30),
                     (f"All time ({days[0]} →)", st_all)]:
        L.append(f"| {label} | {s['n']} | {pct(s['acc_pct'])} | {pct(s['ocr_pct'])} | "
                 f"{s['ocr']} | {s['po']} | {s['sc']} |")
    L.append("")
    L.append(f"- Focus day vs previous day — overall {delta(st_today['acc_pct'], st_prev['acc_pct'])}, "
             f"OCR {delta(st_today['ocr_pct'], st_prev['ocr_pct'])}")
    L.append(f"- Last 7 vs prior 7 days — overall {delta(st_7['acc_pct'], st_p7['acc_pct'])}, "
             f"OCR {delta(st_7['ocr_pct'], st_p7['ocr_pct'])}")
    L.append("")

    # ---- Error categorization
    ocr7 = [r for r in rows_in(last7) if r["_cat"] in OCR_CATS]
    ocrp7 = [r for r in rows_in(prior7) if r["_cat"] in OCR_CATS]
    ocr_today = [r for r in today if r["_cat"] in OCR_CATS]
    t7, tp7, tt = theme_counts(ocr7), theme_counts(ocrp7), theme_counts(ocr_today)
    L.append("## 2. OCR error categories (what to fix)")
    L.append("")
    L.append("Themes are derived from reviewer “AX Comments” on OCR-side errors; one order can hit several themes.")
    L.append("")
    L.append(f"| Theme | Focus day | Last 7 days | Prior 7 days | Trend |")
    L.append("|---|---|---|---|---|")
    for name in sorted(set(t7) | set(tp7) | set(tt), key=lambda k: (-t7[k], -tt[k], k)):
        tr = "▲ worse" if t7[name] > tp7[name] else ("▼ better" if t7[name] < tp7[name] else "■ flat")
        L.append(f"| {name} | {tt[name]} | {t7[name]} | {tp7[name]} | {tr} |")
    L.append("")
    if any(norm(r.get("Secondary Cat for OCR Issue")) for r in rows_in(last30)):
        sec = Counter(norm(r.get("Secondary Cat for OCR Issue")).lower()
                      for r in rows_in(last30) if norm(r.get("Secondary Cat for OCR Issue")))
        L.append("Reviewer-assigned “Secondary Cat for OCR Issue” (last 30 days, where filled in): " +
                 ", ".join(f"{k} ({v})" for k, v in sec.most_common(10)) + ".")
        L.append("")

    # ---- Systemic / repeated errors
    sig = defaultdict(list)
    for r in rows_in(last7):
        if r["_cat"] in OCR_CATS and r["_comment"]:
            sig[comment_signature(r["_comment"])].append(r)
    rep = sorted([(k, v) for k, v in sig.items() if len(v) >= 2], key=lambda kv: -len(kv[1]))
    L.append("## 3. Repeated OCR errors in the last 7 days (likely systemic)")
    L.append("")
    if rep:
        L.append("Same reviewer comment on 2+ orders — usually one logic bug, so highest leverage to fix.")
        L.append("")
        L.append("| Comment | Orders | Distinct accounts | Accounts |")
        L.append("|---|---|---|---|")
        for k, v in rep[:12]:
            ds = Counter(r["_dist"] or "(blank)" for r in v)
            L.append(f"| {v[0]['_comment'][:110]} | {len(v)} | {len(ds)} | "
                     f"{', '.join(f'{d} ({n})' for d, n in ds.most_common(4))} |")
    else:
        L.append("None — no OCR comment repeated on 2+ orders.")
    L.append("")

    # ---- Accounts
    def dist_stats(rs):
        g = defaultdict(list)
        for r in scored(rs):
            if r["_dist"]:
                g[r["_dist"]].append(r)
        return {d: stats(v) for d, v in g.items()}

    d14 = dist_stats(rows_in(last14))
    d7 = dist_stats(rows_in(last7))
    dp7 = dist_stats(rows_in(prior7))
    L.append("## 4. Accounts needing attention (last 14 logged days)")
    L.append("")
    L.append("Accounts with ≥2 OCR errors in the window, sorted by OCR error count.")
    L.append("")
    L.append("| Distributor | Orders | OCR errors | OCR accuracy | Overall acc. | Last 7 OCR acc. | Prior 7 OCR acc. | Top themes |")
    L.append("|---|---|---|---|---|---|---|---|")
    bad = sorted([(d, s) for d, s in d14.items() if s["ocr"] >= 2], key=lambda x: (-x[1]["ocr"], x[1]["ocr_pct"]))
    for d, s in bad[:15]:
        th = theme_counts([r for r in rows_in(last14) if r["_dist"] == d and r["_cat"] in OCR_CATS])
        L.append(f"| {d} | {s['n']} | {s['ocr']} | {pct(s['ocr_pct'])} | {pct(s['acc_pct'])} | "
                 f"{pct(d7[d]['ocr_pct']) if d in d7 else '—'} | {pct(dp7[d]['ocr_pct']) if d in dp7 else '—'} | "
                 f"{', '.join(k for k, _ in th.most_common(2))} |")
    if not bad:
        L.append("| — | | | | | | | |")
    L.append("")

    movers = []
    for d in set(d7) & set(dp7):
        a, b = d7[d], dp7[d]
        if a["n"] >= 5 and b["n"] >= 5:
            movers.append((a["ocr_pct"] - b["ocr_pct"], d, a, b))
    movers.sort()
    worse = [m for m in movers if m[0] <= -5][:8]
    better = [m for m in reversed(movers) if m[0] >= 5][:8]
    L.append("### Account trend: last 7 vs prior 7 logged days (≥5 orders in each)")
    L.append("")
    L.append("| Distributor | Prior 7 OCR acc. | Last 7 OCR acc. | Change |")
    L.append("|---|---|---|---|")
    for dlt, d, a, b in worse:
        L.append(f"| 🔻 {d} | {pct(b['ocr_pct'])} ({b['n']}) | {pct(a['ocr_pct'])} ({a['n']}) | {dlt:+.1f} pts |")
    for dlt, d, a, b in better:
        L.append(f"| 🔺 {d} | {pct(b['ocr_pct'])} ({b['n']}) | {pct(a['ocr_pct'])} ({a['n']}) | {dlt:+.1f} pts |")
    if not worse and not better:
        L.append("| No account moved by ≥5 pts | | | |")
    L.append("")

    # ---- PO-side
    po7 = [r for r in rows_in(last7) if r["_cat"] in OTHER_CATS]
    if po7:
        pc = Counter(r["_dist"] or "(blank)" for r in po7)
        L.append("## 5. PO / Storm Creek-side issues (last 7 days, not OCR)")
        L.append("")
        L.append(f"{len(po7)} orders. Themes: " +
                 ", ".join(f"{k} ({v})" for k, v in theme_counts(po7).most_common(6)) + ".")
        L.append(f"Most frequent accounts: " + ", ".join(f"{k} ({v})" for k, v in pc.most_common(6)) + ".")
        L.append("")

    # ---- Daily trend
    L.append("## 6. Daily trend (last 14 logged days)")
    L.append("")
    L.append("| Date | Reviewed | Overall acc. | OCR acc. | OCR errors | PO | Storm Creek | Unscored/rejected |")
    L.append("|---|---|---|---|---|---|---|---|")
    for d in last14:
        s = stats(by_day[d])
        L.append(f"| {d} | {s['n']} | {pct(s['acc_pct'])} | {pct(s['ocr_pct'])} | {s['ocr']} | "
                 f"{s['po']} | {s['sc']} | {s['unscored']} |")
    L.append("")
    weeks = defaultdict(list)
    for r in rows:
        y, w, _ = r["_date"].isocalendar()
        weeks[(y, w)].append(r)
    L.append("### Weekly trend")
    L.append("")
    L.append("| ISO week (starting) | Reviewed | Overall acc. | OCR acc. |")
    L.append("|---|---|---|---|")
    for (y, w) in sorted(weeks):
        s = stats(weeks[(y, w)])
        L.append(f"| {datetime.date.fromisocalendar(y, w, 1)} | {s['n']} | {pct(s['acc_pct'])} | {pct(s['ocr_pct'])} |")
    L.append("")

    # ---- Today's flagged orders
    flagged = [r for r in today if r["_cat"] in OCR_CATS + OTHER_CATS]
    L.append(f"## 7. Every flagged order on {focus} ({len(flagged)})")
    L.append("")
    if flagged:
        L.append("| Category | Distributor | PO # | Processed by | Reviewer comment |")
        L.append("|---|---|---|---|---|")
        for r in sorted(flagged, key=lambda r: (r["_cat"] not in OCR_CATS, r["_cat"], r["_dist"])):
            c = r["_comment"].replace("|", "/")
            L.append(f"| {r['_cat']} | {r['_dist']} | {norm(r.get('PO Number'))} | "
                     f"{norm(r.get('Processed By'))} | {c[:220]} |")
    L.append("")

    # ---- Associates
    ga = defaultdict(list)
    for r in rows_in(last7):
        if norm(r.get("Processed By")):
            ga[norm(r.get("Processed By"))].append(r)
    L.append("## 8. Reviewer volume & flag rate (last 7 days)")
    L.append("")
    L.append("Not a quality score for reviewers — a big gap in flag rate can mean inconsistent review standards.")
    L.append("")
    L.append("| Processed by | Reviewed | OCR errors flagged | Flag rate |")
    L.append("|---|---|---|---|")
    for a, rs in sorted(ga.items(), key=lambda kv: -len(scored(kv[1]))):
        s = stats(rs)
        if s["n"]:
            L.append(f"| {a} | {s['n']} | {s['ocr']} | {s['ocr']/s['n']*100:.1f}% |")
    L.append("")
    # ---- "Where to focus" summary, placed at the top
    F = ["## Where to focus today", ""]
    F.append(f"- **Accuracy:** last 7 days {pct(st_7['acc_pct'])} overall / {pct(st_7['ocr_pct'])} OCR "
             f"({delta(st_7['ocr_pct'], st_p7['ocr_pct'])} OCR vs prior 7 days); "
             f"{focus}: {pct(st_today['acc_pct'])} / {pct(st_today['ocr_pct'])}"
             f"{' (partial day)' if partial else ''}.")
    rising = sorted([k for k in t7 if k != "Other / Unclassified" and t7[k] - tp7[k] >= 3],
                    key=lambda k: -(t7[k] - tp7[k]))
    if rising:
        F.append("- **Rising error themes:** " + "; ".join(
            f"{k} {tp7[k]}→{t7[k]}" for k in rising[:4]) + ".")
    top = [k for k, _ in t7.most_common(3)]
    if top:
        F.append("- **Biggest OCR error buckets (7d):** " + ", ".join(f"{k} ({t7[k]})" for k in top) + ".")
    if rep:
        F.append("- **Likely systemic bugs:** " + "; ".join(
            f"“{v[0]['_comment'][:80]}” ×{len(v)}" for _, v in rep[:3]) + ".")
    captured = Counter()
    for r in rows_in(last30):
        if r["_cat"] in OCR_CATS:
            if re.search(r"captur", r["_comment"], re.I):
                for tok in set(re.findall(r"(?<![\w-])(\d{4,})(?![\w-])", r["_comment"])):
                    captured[tok] += 1
    stuck = [(v, n) for v, n in captured.most_common(3) if n >= 3]
    if stuck:
        F.append("- **Same code/value recurring in OCR error comments (30d):** " + ", ".join(
            f"`{v}` ×{n}" for v, n in stuck) + " — usually a product-code mapping (e.g. look-alike SKUs) or default-value bug; grep the comments for these codes.")
    if worse:
        F.append("- **Accounts slipping (7d vs prior 7d):** " + ", ".join(
            f"{d} {pct(b['ocr_pct'])}→{pct(a['ocr_pct'])}" for _, d, a, b in worse[:4]) + ".")
    F.append("")
    out = "\n".join(L).replace("__FOCUS__", "\n".join(F))
    return out, dict(today=st_today, prev=st_prev, last7=st_7, prior7=st_p7,
                              partial=bool(partial), repeated=rep[:3], themes7=t7, bad=bad[:3],
                              worse=worse[:3], focus=focus)


def main():
    if len(sys.argv) not in (3, 4):
        print(__doc__)
        sys.exit(1)
    rows = load_rows(sys.argv[1])
    focus = (datetime.date.fromisoformat(sys.argv[3]) if len(sys.argv) == 4
             else max(r["_date"] for r in rows))
    report, _ = render(rows, focus)
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print(f"Wrote report for {focus} to {sys.argv[2]}")


if __name__ == "__main__":
    main()
