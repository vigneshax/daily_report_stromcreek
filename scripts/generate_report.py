#!/usr/bin/env python3
"""
Generates the Storm Creek daily OCR accuracy/error report from a CSV export
of the "Live Orders" tab of the tracker spreadsheet:
https://docs.google.com/spreadsheets/d/1SGFQmGZ59tKD4tdWKG3o1acZsZtZM85kN3sbUKUSGH4

Usage:
    python3 generate_report.py <live_orders.csv> <output_report.md> [YYYY-MM-DD]

The optional date is the "run date". The report focuses on the latest logged
day before the run date that has reviewed orders (normally yesterday), and
compares it with the trailing 7 / 30 logged days.

Required columns (extra columns are ignored):
Date, Week#, Processed By, Distributor, AX Comments, Issue related
Optional: Secondary Cat for OCR Issue, Order Status
"""
import csv
import re
import sys
import datetime
from collections import Counter, defaultdict

ACCURATE = "Accurate Orders"
# Categories that reflect the OCR/automation getting something wrong.
OCR_SIDE = ("OCR Issue", "OCR / Email Format")
# Categories caused by the PO itself / client side.
NON_OCR = ("PO Issue", "Storm Creek Issue")

# Ordered: first match decides the primary theme; all matches are counted.
THEME_BUCKETS = [
    ("STC (State To Credit)", r"\bSTC\b|state to credit"),
    ("Reporting Group / AIM / Facilis", r"reporting group|\bRG\b|\bAIM\b|facilis"),
    ("Account number", r"account (number|no|#)|acc(ount)?\.? ?(no|number|#)|\bacct\b|fedex acc|ups acc"),
    ("Ship-to name duplicated as company name", r"captured in both ship to and company name|both ship ?to and company"),
    ("Order type", r"order type"),
    ("Part ID / Product ID not captured or wrong", r"part ?id|product ?id|product code|\bsku\b|item \d+ (was )?not captured"),
    ("Color not on PO / not in PPC", r"\bcolou?r\b|grey|gray|navy|black|charcoal|not available in ppc"),
    ("Size", r"\bsize\b|\b[2-5]?x+l\b|\bsmall\b|\blarge\b"),
    ("Quantity", r"\bqty\b|quantity"),
    ("Shipping address missing / wrong", r"ship(ping)? ?(to|address)|distributor address|secondline|second line"),
    ("Ship method / carrier", r"ship(ping)? (method|via)|carrier|will call|ground|2nd day|overnight"),
    ("Ship date / PSST / in-hands", r"ship date|psst|in.?hands|due date"),
    ("PO total / freight (FF)", r"po total|\bFF\b|freight"),
    ("PO number", r"po (number|no|#)|po#"),
    ("Contact email / name", r"contact|e-?mail"),
    ("Company name", r"company name"),
    ("Email format / file", r"email format|attachment|file rejected|unreadable|image"),
]

THEME_BUCKETS_D = dict(THEME_BUCKETS)
FALSE_FLAG = re.compile(r"^\s*all ?ok", re.IGNORECASE)


def parse_date(s):
    try:
        m, d, y = s.strip().split("/")
        return datetime.date(int(y), int(m), int(d))
    except ValueError:
        return None


def load_rows(csv_path):
    out = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            d = parse_date(r.get("Date", ""))
            if not d:
                continue
            r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
            r["_date"] = d
            r["_issue"] = r.get("Issue related", "")
            r["_dist"] = r.get("Distributor", "").strip() or "(blank)"
            out.append(r)
    return out


DUP = "Ship-to name duplicated as company name"


def themes_of(comment):
    found = [name for name, pat in THEME_BUCKETS if re.search(pat, comment, re.IGNORECASE)]
    if DUP in found:
        # The duplicate-name pattern mentions "ship to" and "company name";
        # don't double count it as an address or company-name error.
        found = [n for n in found if n not in ("Shipping address missing / wrong", "Company name")
                 or re.search(THEME_BUCKETS_D[n], re.sub(r"captured in both ship ?to and company name", "", comment, flags=re.I), re.I)]
    return found or ["Other / uncategorized"]


def stats(recs):
    reviewed = [r for r in recs if r["_issue"]]
    n = len(reviewed)
    acc = sum(1 for r in reviewed if r["_issue"] == ACCURATE)
    ocr = sum(1 for r in reviewed if r["_issue"] in OCR_SIDE)
    po = sum(1 for r in reviewed if r["_issue"] == "PO Issue")
    sc = sum(1 for r in reviewed if r["_issue"] == "Storm Creek Issue")
    return dict(
        logged=len(recs), reviewed=n, pending=len(recs) - n, accurate=acc,
        ocr=ocr, po=po, sc=sc,
        acc_pct=acc / n * 100 if n else 0.0,
        # OCR accuracy: share of reviewed orders with no OCR-side error.
        ocr_acc_pct=(n - ocr) / n * 100 if n else 0.0,
    )


def pct(x):
    return f"{x:.1f}%"


def delta(a, b):
    d = a - b
    arrow = "▲" if d > 0.05 else ("▼" if d < -0.05 else "■")
    return f"{arrow} {d:+.1f} pts"


def theme_counts(recs, only=None):
    c = Counter()
    for r in recs:
        if r["_issue"] in ("", ACCURATE):
            continue
        if only and r["_issue"] not in only:
            continue
        for t in themes_of(r.get("AX Comments", "")):
            c[t] += 1
    return c


def render_report(rows, run_date):
    by_date = defaultdict(list)
    for r in rows:
        by_date[r["_date"]].append(r)
    days = sorted(d for d in by_date if any(r["_issue"] for r in by_date[d]))
    candidates = [d for d in days if d < run_date] or days
    day = candidates[-1]
    idx = days.index(day)
    prev_day = days[idx - 1] if idx > 0 else None
    last7 = days[max(0, idx - 6): idx + 1]
    prior7 = days[max(0, idx - 13): max(0, idx - 6)]
    last30 = days[max(0, idx - 29): idx + 1]
    last14 = days[max(0, idx - 13): idx + 1]
    prior14 = days[max(0, idx - 27): max(0, idx - 13)]

    def pool(ds):
        return [r for d in ds for r in by_date[d]]

    S_day = stats(by_date[day])
    S_prev = stats(by_date[prev_day]) if prev_day else None
    S_7 = stats(pool(last7))
    S_p7 = stats(pool(prior7)) if prior7 else None
    S_30 = stats(pool(last30))
    S_all = stats(rows)

    L = []
    L.append(f"# Storm Creek OCR Daily Report — {day} (run {run_date})")
    L.append("")
    L.append(f"Source: *Live Orders* tab, {S_all['logged']:,} logged orders "
             f"({days[0]} → {days[-1]}). Accuracy is measured on **reviewed** orders "
             "(rows with an *Issue related* value); unreviewed rows are reported as pending.")
    if run_date in by_date and run_date != day:
        s = stats(by_date[run_date])
        L.append(f"Today ({run_date}) has {s['logged']} rows logged so far, "
                 f"{s['reviewed']} reviewed — not included.")
    L.append("")

    # ---------------- Headline
    L.append("## 1. Headline")
    L.append("")
    L.append("| Metric | Report day | Prev. day | Last 7 days | Prior 7 days | Last 30 days |")
    L.append("|---|---|---|---|---|---|")

    def cell(s, key):
        return pct(s[key]) if s else "—"

    L.append(f"| Overall accuracy (no issue of any kind) | **{pct(S_day['acc_pct'])}** | "
             f"{cell(S_prev, 'acc_pct')} | {pct(S_7['acc_pct'])} | {cell(S_p7, 'acc_pct')} | {pct(S_30['acc_pct'])} |")
    L.append(f"| OCR accuracy (no OCR-side error) | **{pct(S_day['ocr_acc_pct'])}** | "
             f"{cell(S_prev, 'ocr_acc_pct')} | {pct(S_7['ocr_acc_pct'])} | {cell(S_p7, 'ocr_acc_pct')} | {pct(S_30['ocr_acc_pct'])} |")
    L.append(f"| Reviewed orders | {S_day['reviewed']} | {S_prev['reviewed'] if S_prev else '—'} | "
             f"{S_7['reviewed']} | {S_p7['reviewed'] if S_p7 else '—'} | {S_30['reviewed']} |")
    L.append(f"| OCR / PO / Storm Creek issues | {S_day['ocr']} / {S_day['po']} / {S_day['sc']} | "
             f"{(str(S_prev['ocr']) + ' / ' + str(S_prev['po']) + ' / ' + str(S_prev['sc'])) if S_prev else '—'} | "
             f"{S_7['ocr']} / {S_7['po']} / {S_7['sc']} | "
             f"{(str(S_p7['ocr']) + ' / ' + str(S_p7['po']) + ' / ' + str(S_p7['sc'])) if S_p7 else '—'} | "
             f"{S_30['ocr']} / {S_30['po']} / {S_30['sc']} |")
    L.append("")
    if S_prev:
        L.append(f"- Overall accuracy vs previous day: {delta(S_day['acc_pct'], S_prev['acc_pct'])}; "
                 f"vs 7-day average: {delta(S_day['acc_pct'], S_7['acc_pct'])}.")
        L.append(f"- OCR accuracy vs previous day: {delta(S_day['ocr_acc_pct'], S_prev['ocr_acc_pct'])}; "
                 f"vs 7-day average: {delta(S_day['ocr_acc_pct'], S_7['ocr_acc_pct'])}.")
    if S_p7:
        L.append(f"- Week-over-week (last 7 vs prior 7 logged days): overall {delta(S_7['acc_pct'], S_p7['acc_pct'])}, "
                 f"OCR {delta(S_7['ocr_acc_pct'], S_p7['ocr_acc_pct'])}.")
    if S_day["pending"]:
        L.append(f"- {S_day['pending']} order(s) on {day} are logged but not yet reviewed.")
    L.append("")

    # ---------------- Trend
    L.append("## 2. Daily trend (last 15 logged days)")
    L.append("")
    L.append("| Date | Reviewed | Accurate | Overall acc. | OCR acc. | OCR | PO | SC |")
    L.append("|---|---|---|---|---|---|---|---|")
    for d in days[max(0, idx - 14): idx + 1]:
        s = stats(by_date[d])
        mark = " ◀" if d == day else ""
        L.append(f"| {d}{mark} | {s['reviewed']} | {s['accurate']} | {pct(s['acc_pct'])} | "
                 f"{pct(s['ocr_acc_pct'])} | {s['ocr']} | {s['po']} | {s['sc']} |")
    L.append("")

    by_week = defaultdict(list)
    for r in rows:
        iso = r["_date"].isocalendar()
        by_week[(iso[0], iso[1])].append(r)
    L.append("### Weekly trend")
    L.append("")
    L.append("| ISO week | Week of | Reviewed | Overall acc. | OCR acc. | OCR | PO |")
    L.append("|---|---|---|---|---|---|---|")
    for wk in sorted(by_week)[-10:]:
        s = stats(by_week[wk])
        start = min(r["_date"] for r in by_week[wk])
        L.append(f"| {wk[0]}-W{wk[1]:02d} | {start} | {s['reviewed']} | {pct(s['acc_pct'])} | "
                 f"{pct(s['ocr_acc_pct'])} | {s['ocr']} | {s['po']} |")
    L.append("")

    # ---------------- Error categories
    t_day = theme_counts(by_date[day])
    t_7_ocr = theme_counts(pool(last7), OCR_SIDE)
    t_p7_ocr = theme_counts(pool(prior7), OCR_SIDE) if prior7 else Counter()
    t_7_po = theme_counts(pool(last7), NON_OCR)
    L.append("## 3. Error categorization")
    L.append("")
    L.append("Themes are derived from reviewer *AX Comments* (one order can carry several themes).")
    L.append("")
    L.append("### OCR-side errors — last 7 vs prior 7 logged days")
    L.append("")
    L.append(f"| Theme | Report day (all issues) | Last 7 (OCR) | Prior 7 (OCR) | Change |")
    L.append("|---|---|---|---|---|")
    names = sorted(set(t_7_ocr) | set(t_p7_ocr) | set(t_day),
                   key=lambda n: (-t_7_ocr[n], -t_day[n], n))
    for n in names:
        ch = t_7_ocr[n] - t_p7_ocr[n]
        L.append(f"| {n} | {t_day[n]} | {t_7_ocr[n]} | {t_p7_ocr[n]} | {ch:+d} |")
    L.append("")
    if t_7_po:
        L.append("### PO-side / client issues — last 7 logged days")
        L.append("")
        L.append("| Theme | Count |")
        L.append("|---|---|")
        for n, c in t_7_po.most_common(8):
            L.append(f"| {n} | {c} |")
        L.append("")
    ff = [r for r in pool(last7) if r["_issue"] not in ("", ACCURATE) and FALSE_FLAG.search(r.get("AX Comments", ""))]
    if ff:
        L.append(f"- **{len(ff)}** flagged orders in the last 7 days start with *\"All Ok\"* — "
                 "the order was usable but still flagged (unneeded RG/AIM, FF not captured, etc.). "
                 "Worth checking whether these should count as errors.")
        L.append("")

    # ---------------- Accounts
    L.append("## 4. Account (distributor) trends")
    L.append("")
    d7 = defaultdict(list)
    for r in pool(last7):
        d7[r["_dist"]].append(r)
    repeat = []
    for dist, recs in d7.items():
        s = stats(recs)
        if s["ocr"] >= 2 or (s["ocr"] + s["po"] >= 3):
            th = theme_counts(recs, OCR_SIDE)
            repeat.append((s["ocr"], s["po"], dist, s, ", ".join(f"{k} ({v})" for k, v in th.most_common(3))))
    repeat.sort(key=lambda x: (-x[0], -x[1]))
    L.append("### Repeat offenders — last 7 logged days")
    L.append("")
    if repeat:
        L.append("| Distributor | Reviewed | Overall acc. | OCR issues | PO issues | Top OCR themes |")
        L.append("|---|---|---|---|---|---|")
        for ocr, po, dist, s, th in repeat[:15]:
            L.append(f"| {dist} | {s['reviewed']} | {pct(s['acc_pct'])} | {ocr} | {po} | {th or '—'} |")
    else:
        L.append("No distributor had repeated issues in the last 7 days.")
    L.append("")

    a14, b14 = defaultdict(list), defaultdict(list)
    for r in pool(last14):
        a14[r["_dist"]].append(r)
    for r in pool(prior14):
        b14[r["_dist"]].append(r)
    moves = []
    for dist in set(a14) & set(b14):
        sa, sb = stats(a14[dist]), stats(b14[dist])
        if sa["reviewed"] >= 8 and sb["reviewed"] >= 8:
            moves.append((sa["acc_pct"] - sb["acc_pct"], dist, sa, sb))
    moves.sort()
    L.append("### Biggest movers — last 14 vs prior 14 logged days (≥8 reviewed orders in each window)")
    L.append("")
    if moves:
        L.append("| Distributor | Prior 14 acc. | Last 14 acc. | Change |")
        L.append("|---|---|---|---|")
        worse = [m for m in moves if m[0] < 0][:6]
        better = [m for m in reversed(moves) if m[0] > 0][:4]
        for dv, dist, sa, sb in worse + better:
            L.append(f"| {dist} | {pct(sb['acc_pct'])} ({sb['reviewed']}) | {pct(sa['acc_pct'])} ({sa['reviewed']}) | {delta(sa['acc_pct'], sb['acc_pct'])} |")
    else:
        L.append("Not enough overlapping volume to compare.")
    L.append("")

    L.append("### Lowest accuracy accounts — last 30 logged days (≥20 reviewed orders)")
    L.append("")
    d30 = defaultdict(list)
    for r in pool(last30):
        d30[r["_dist"]].append(r)
    low = sorted(((stats(v), k) for k, v in d30.items() if stats(v)["reviewed"] >= 20),
                 key=lambda x: x[0]["acc_pct"])[:10]
    L.append("| Distributor | Reviewed | Overall acc. | OCR acc. | OCR | PO |")
    L.append("|---|---|---|---|---|---|")
    for s, k in low:
        L.append(f"| {k} | {s['reviewed']} | {pct(s['acc_pct'])} | {pct(s['ocr_acc_pct'])} | {s['ocr']} | {s['po']} |")
    L.append("")

    # ---------------- Day detail
    L.append(f"## 5. Every flagged order on {day}")
    L.append("")
    flagged = [r for r in by_date[day] if r["_issue"] not in ("", ACCURATE)]
    flagged.sort(key=lambda r: (r["_issue"] not in OCR_SIDE, r["_issue"], r["_dist"]))
    if flagged:
        L.append("| Category | Distributor | PO # | Theme(s) | Reviewer comment |")
        L.append("|---|---|---|---|---|")
        for r in flagged:
            c = r.get("AX Comments", "").replace("|", "/").replace("\n", " ")
            if len(c) > 220:
                c = c[:217] + "..."
            L.append(f"| {r['_issue']} | {r['_dist']} | {r.get('PO Number', '')} | "
                     f"{', '.join(themes_of(r.get('AX Comments', '')))} | {c} |")
    else:
        L.append("No flagged orders.")
    L.append("")

    # ---------------- Associates
    L.append("## 6. Reviewer volume & accuracy — last 7 logged days")
    L.append("")
    pa = defaultdict(list)
    for r in pool(last7):
        if r.get("Processed By"):
            pa[r["Processed By"]].append(r)
    L.append("| Processed By | Reviewed | Overall acc. | OCR issues | PO issues |")
    L.append("|---|---|---|---|---|")
    for k, v in sorted(pa.items(), key=lambda kv: -stats(kv[1])["reviewed"]):
        s = stats(v)
        L.append(f"| {k} | {s['reviewed']} | {pct(s['acc_pct'])} | {s['ocr']} | {s['po']} |")
    L.append("")
    L.append("_Note: differences between reviewers mostly reflect the order mix they were allotted and how "
             "strictly they flag, not OCR quality._")
    L.append("")

    # ---------------- Where to improve
    L.append("## 7. Where improvement is needed")
    L.append("")
    tips = {
        "STC (State To Credit)": "STC extraction — check the prompt/rule that reads state-to-credit from the PO header/ship-to state.",
        "Reporting Group / AIM / Facilis": "Reporting-group mapping (AIM/Facilis) — both missed and unnecessary RG captures; review the distributor→RG rule table.",
        "Account number": "Shipping account number — wrong/missed carrier account; prefer the explicitly labelled 'Acct #' / FedEx/UPS account field and validate digit length.",
        "Ship-to name duplicated as company name": "Ship-to attention name is being copied into Company Name — add a rule: if no company is on the PO, leave company blank (or use distributor), never the contact name.",
        "Order type": "Order-type classification — add examples of the misclassified cases to the prompt.",
        "Part ID / Product ID not captured or wrong": "Part/Product ID capture — look at multi-line and table-wrapped item codes; add PPC catalog validation for unmatched IDs.",
        "Color not on PO / not in PPC": "Color mapping — add a fuzzy/synonym map (grey/gray, navy/blue, charcoal) against PPC colors and flag ambiguity rather than guess.",
        "Size": "Size parsing — 2X/2XL/XXL normalization and size-per-quantity matrices.",
        "Quantity": "Quantity parsing from size grids / multi-line items.",
        "Shipping address missing / wrong": "Ship-to address extraction (second address line, partial addresses).",
        "Ship method / carrier": "Ship-method mapping (Will Call, Ground, 2-Day) to AX ship-via codes.",
        "Ship date / PSST / in-hands": "Preferred ship date logic — align with the new PSST rules.",
        "PO total / freight (FF)": "PO total / freight-flag capture when totals are present.",
    }
    ranked = [n for n, _ in t_7_ocr.most_common() if n in tips][:5]
    rising = [n for n in names if t_7_ocr[n] - t_p7_ocr[n] >= 2 and n in tips]
    for i, n in enumerate(ranked, 1):
        flag = " **(rising)**" if n in rising else ""
        L.append(f"{i}. **{n}** — {t_7_ocr[n]} OCR errors in last 7 days{flag}. {tips[n]}")
    extra = [n for n in rising if n not in ranked]
    for n in extra:
        L.append(f"- Rising: **{n}** ({t_p7_ocr[n]} → {t_7_ocr[n]}). {tips[n]}")
    if repeat:
        top = ", ".join(x[2] for x in repeat[:5])
        L.append(f"- Accounts to fine-tune first (most repeated OCR errors this week): {top}.")
    if t_7_po:
        po_top = ", ".join(f"{n} ({c})" for n, c in t_7_po.most_common(3))
        L.append(f"- PO-side issues are not OCR bugs but drive overall accuracy; top drivers: {po_top}. "
                 "Consider default rules (e.g. nearest PPC color, distributor address fallback) "
                 "so these stop needing manual review.")
    L.append("")
    return "\n".join(L), day


def main():
    if len(sys.argv) not in (3, 4):
        print(__doc__)
        sys.exit(1)
    csv_path, out_path = sys.argv[1], sys.argv[2]
    run_date = (datetime.date.fromisoformat(sys.argv[3]) if len(sys.argv) == 4
                else datetime.date.today())
    rows = load_rows(csv_path)
    report, day = render_report(rows, run_date)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"Wrote report for {day} to {out_path}")


if __name__ == "__main__":
    main()
