#!/usr/bin/env python3
"""
Generates the Storm Creek daily OCR accuracy/error report from a CSV export
of the "Live Orders" sheet in the tracker spreadsheet:
https://docs.google.com/spreadsheets/d/1SGFQmGZ59tKD4tdWKG3o1acZsZtZM85kN3sbUKUSGH4

Usage:
    python3 generate_report.py <live_orders.csv> <output_report.md> [YYYY-MM-DD]

The optional date picks the "focus day" (defaults to the latest date in the
sheet). Required columns: Date, Week#, Processed By, PO Number, Distributor,
AX Comments, Issue related. Optional: Order Status, Secondary Cat for OCR Issue.

Metric definitions:
- Reviewed order: a row whose "Issue related" is filled in. Rows left blank
  (file rejected, duplicates, pending) are excluded from accuracy and reported
  separately.
- Overall accuracy = Accurate Orders / reviewed orders.
- OCR accuracy = 1 - (OCR Issue + OCR / Email Format) / reviewed orders. This is
  the number the OCR/logic team owns; PO Issue and Storm Creek Issue are
  upstream/client problems.
"""
import csv
import re
import sys
import datetime
from collections import Counter, defaultdict

ACCURATE = "Accurate Orders"
OCR_CATS = ("OCR Issue", "OCR / Email Format")
EXTERNAL_CATS = ("PO Issue", "Storm Creek Issue")
CAT_ORDER = ("OCR Issue", "OCR / Email Format", "PO Issue", "Storm Creek Issue")

# First matching theme wins for the "primary theme"; all matches are counted
# for theme frequency. Order matters: more specific patterns first.
THEME_BUCKETS = [
    ("Name in both Ship To & Company", r"both ship ?to and company|captured in both"),
    ("STC (State To Credit)", r"\bSTC\b|state to credit"),
    ("Reporting Group / AIM / Facilis", r"reporting group|\bRG\b|\bAIM\b|facilis"),
    ("Account Number", r"account (number|no|#|id)|acct|shipping acct"),
    ("Ship To / Address", r"ship ?to|address|secondline|second line|dropship|zip|\bstate\b|\bcity\b"),
    ("Ship Method / Carrier", r"ship(ping)? method|carrier|\bups\b|fedex|ground|pickup"),
    ("Ship / In-hands Date & Time", r"ship date|in.?hands|due date|\bdate\b|\b\d{1,2} ?(am|pm)\b|next day"),
    ("Part ID / Line not captured", r"part ?id|line record|product id|\bsku\b|item .*not captured|line .*not captured|product code"),
    ("Color / Size", r"\bcolou?r\b|\bsize\b|\bnavy\b|\bgr[ae]y\b|heather|\bblack\b|\bwhite\b"),
    ("Quantity", r"\bqty\b|quantity"),
    ("PO Number", r"po ?(number|no|#)"),
    ("PO Contact / Email", r"po contact|po mail|contact email|email"),
    ("Order Type / PSST / Sample", r"order type|psst|sample|blank order"),
    ("PO Total / Freight / Pricing", r"po total|freight|\bFF\b|price|pricing"),
    ("Company Name", r"company name"),
]
FALSE_FLAG_RE = re.compile(r"\ball ?(ok|okay)\b|unnecessar(y|ily) flag", re.I)


def parse_date(s):
    m, d, y = s.strip().split("/")
    return datetime.date(int(y), int(m), int(d))


def load_rows(csv_path):
    rows = []
    for r in csv.DictReader(open(csv_path, newline="", encoding="utf-8")):
        r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
        if not r.get("Date"):
            continue
        try:
            r["_date"] = parse_date(r["Date"])
        except ValueError:
            continue
        r["_cat"] = r.get("Issue related", "")
        r["_dist"] = re.sub(r"\s+", " ", r.get("Distributor", "")).strip() or "(blank)"
        rows.append(r)
    return rows


def themes_of(comment):
    found = [name for name, pat in THEME_BUCKETS if re.search(pat, comment, re.I)]
    if "Name in both Ship To & Company" in found:
        # Same root cause; only count Ship To / Company Name if raised separately.
        rest = re.sub(r"[^.;\n]*captured in both[^.;\n]*", " ", comment, flags=re.I)
        for t in ("Ship To / Address", "Company Name"):
            if t in found and not re.search(dict(THEME_BUCKETS)[t], rest, re.I):
                found.remove(t)
    return found


def stats(recs):
    reviewed = [r for r in recs if r["_cat"]]
    n = len(reviewed)
    cats = Counter(r["_cat"] for r in reviewed)
    acc = cats.get(ACCURATE, 0)
    ocr = sum(cats.get(c, 0) for c in OCR_CATS)
    return dict(
        total=len(recs), reviewed=n, unreviewed=len(recs) - n, accurate=acc,
        ocr=ocr, cats=cats,
        acc_pct=(acc / n * 100) if n else None,
        ocr_acc_pct=((n - ocr) / n * 100) if n else None,
    )


def pct(x):
    return "n/a" if x is None else f"{x:.1f}%"


def delta(a, b):
    if a is None or b is None:
        return "n/a"
    d = a - b
    arrow = "▲" if d > 0.05 else ("▼" if d < -0.05 else "■")
    return f"{arrow} {d:+.1f} pts"


def theme_counts(recs):
    c = Counter()
    for r in recs:
        for t in set(themes_of(r.get("AX Comments", ""))):
            c[t] += 1
        if r.get("AX Comments") and not themes_of(r["AX Comments"]):
            c["Other / uncategorized"] += 1
    return c


def md_escape(s):
    return s.replace("|", "\\|").replace("\n", " ")


def render_report(rows, focus):
    by_date = defaultdict(list)
    for r in rows:
        by_date[r["_date"]].append(r)
    dates = sorted(by_date)
    if focus not in by_date:
        raise SystemExit(f"No rows for focus date {focus}; latest is {dates[-1]}")
    idx = dates.index(focus)
    prev7_dates = dates[max(0, idx - 7):idx]           # 7 working days before focus
    last7_dates = dates[max(0, idx - 6):idx + 1]       # focus + 6 before
    prior7_dates = dates[max(0, idx - 13):max(0, idx - 6)]
    last14_dates = dates[max(0, idx - 13):idx + 1]
    window = [r for d in dates[:idx + 1] for r in by_date[d]]

    def collect(ds):
        return [r for d in ds for r in by_date[d]]

    day = by_date[focus]
    s_day, s_prev7 = stats(day), stats(collect(prev7_dates))
    s_last7, s_prior7 = stats(collect(last7_dates)), stats(collect(prior7_dates))
    s_all = stats(window)
    same_wd = [d for d in dates[:idx] if d.weekday() == focus.weekday()]
    s_wd = stats(by_date[same_wd[-1]]) if same_wd else None

    L = []
    L.append(f"# Storm Creek OCR Daily Report — {focus:%a %d %b %Y}")
    L.append("")
    L.append(f"_Generated {datetime.date.today().isoformat()} from the Live Orders sheet "
             f"({len(window)} orders logged, {dates[0]} → {focus}). "
             "Accuracy counts only reviewed orders (\"Issue related\" filled in)._")
    L.append("")

    # ---------------- Headline ----------------
    L.append("## 1. Headline")
    L.append("")
    L.append("| Metric | Focus day | Prev 7 working days | Change | Since start |")
    L.append("|---|---|---|---|---|")
    L.append(f"| Orders logged | {s_day['total']} | {s_prev7['total']/max(1,len(prev7_dates)):.0f}/day | | {s_all['total']} |")
    L.append(f"| Reviewed orders | {s_day['reviewed']} | | | {s_all['reviewed']} |")
    L.append(f"| **Overall accuracy** | **{pct(s_day['acc_pct'])}** | {pct(s_prev7['acc_pct'])} | {delta(s_day['acc_pct'], s_prev7['acc_pct'])} | {pct(s_all['acc_pct'])} |")
    L.append(f"| **OCR accuracy** (excl. PO/client issues) | **{pct(s_day['ocr_acc_pct'])}** | {pct(s_prev7['ocr_acc_pct'])} | {delta(s_day['ocr_acc_pct'], s_prev7['ocr_acc_pct'])} | {pct(s_all['ocr_acc_pct'])} |")
    for c in CAT_ORDER:
        L.append(f"| {c} | {s_day['cats'].get(c,0)} | {s_prev7['cats'].get(c,0)/max(1,len(prev7_dates)):.1f}/day | | {s_all['cats'].get(c,0)} |")
    L.append(f"| Not categorized (rejected/duplicate/pending) | {s_day['unreviewed']} | | | {s_all['unreviewed']} |")
    L.append("")
    if s_wd:
        L.append(f"- Same weekday last week ({same_wd[-1]}): overall {pct(s_wd['acc_pct'])}, "
                 f"OCR {pct(s_wd['ocr_acc_pct'])}.")
    L.append(f"- Last 7 working days vs the 7 before: overall {pct(s_last7['acc_pct'])} vs "
             f"{pct(s_prior7['acc_pct'])} ({delta(s_last7['acc_pct'], s_prior7['acc_pct'])}); "
             f"OCR {pct(s_last7['ocr_acc_pct'])} vs {pct(s_prior7['ocr_acc_pct'])} "
             f"({delta(s_last7['ocr_acc_pct'], s_prior7['ocr_acc_pct'])}).")
    L.append("")

    # ---------------- Where to act ----------------
    ocr_day = [r for r in day if r["_cat"] in OCR_CATS]
    ocr_last7 = [r for r in collect(last7_dates) if r["_cat"] in OCR_CATS]
    ocr_prior7 = [r for r in collect(prior7_dates) if r["_cat"] in OCR_CATS]
    t_day, t7, tp7 = theme_counts(ocr_day), theme_counts(ocr_last7), theme_counts(ocr_prior7)

    L.append("## 2. Where improvement is needed")
    L.append("")
    acts = []
    for t, n in t7.most_common(4):
        acts.append(f"**{t}** — {n} OCR errors in the last 7 working days "
                    f"(prior 7: {tp7.get(t,0)}; focus day: {t_day.get(t,0)}).")
    rising = sorted(((t7[t] - tp7.get(t, 0), t) for t in t7 if t7[t] - tp7.get(t, 0) >= 3), reverse=True)
    added = 0
    for d, t in rising:
        if added < 2 and not any(f"**{t}**" in a for a in acts):
            added += 1
            acts.append(f"**{t}** is rising: {tp7.get(t,0)} → {t7[t]} week over week.")
    for i, a in enumerate(acts, 1):
        L.append(f"{i}. {a}")
    L.append("")

    # ---------------- Focus day details ----------------
    L.append(f"## 3. Focus day error list ({focus}) — OCR-attributable")
    L.append("")
    if ocr_day:
        L.append("| # | Distributor | PO | Theme(s) | Reviewer comment |")
        L.append("|---|---|---|---|---|")
        for i, r in enumerate(sorted(ocr_day, key=lambda r: r["_dist"].lower()), 1):
            th = ", ".join(themes_of(r.get("AX Comments", ""))) or "Other"
            flag = " ⚠️ possible false flag" if FALSE_FLAG_RE.search(r.get("AX Comments", "")) else ""
            L.append(f"| {i} | {md_escape(r['_dist'])} | {md_escape(r.get('PO Number',''))} | {th} | "
                     f"{md_escape(r.get('AX Comments',''))[:220]}{flag} |")
    else:
        L.append("No OCR-attributable errors logged on this day.")
    L.append("")
    ext_day = [r for r in day if r["_cat"] in EXTERNAL_CATS]
    if ext_day:
        L.append(f"<details><summary>PO / client issues on {focus} ({len(ext_day)}) — not OCR, for context</summary>")
        L.append("")
        for r in ext_day:
            L.append(f"- {md_escape(r['_dist'])} (PO {md_escape(r.get('PO Number',''))}): {md_escape(r.get('AX Comments',''))[:200]}")
        L.append("")
        L.append("</details>")
        L.append("")

    # ---------------- Error categorization ----------------
    L.append("## 4. Error categorization — OCR error themes")
    L.append("")
    L.append("Themes are derived from reviewer comments; one order can carry several themes.")
    L.append("")
    ocr_all = [r for r in window if r["_cat"] in OCR_CATS]
    t_all = theme_counts(ocr_all)
    L.append("| Theme | Focus day | Last 7 days | Prior 7 days | WoW | Since start |")
    L.append("|---|---|---|---|---|---|")
    for t, n in t_all.most_common():
        d = t7.get(t, 0) - tp7.get(t, 0)
        L.append(f"| {t} | {t_day.get(t,0)} | {t7.get(t,0)} | {tp7.get(t,0)} | {d:+d} | {n} |")
    L.append("")

    # ---------------- Trend ----------------
    L.append("## 5. Accuracy trend")
    L.append("")
    L.append("### Weekly")
    L.append("")
    L.append("| Week # | Days | Reviewed | Overall acc. | OCR acc. | OCR errors | PO issues | SC issues |")
    L.append("|---|---|---|---|---|---|---|---|")
    by_week = defaultdict(list)
    for r in window:
        by_week[r["_date"].isocalendar()[:2]].append(r)
    for wk in sorted(by_week):
        recs = by_week[wk]
        s = stats(recs)
        ndays = len({r["_date"] for r in recs})
        start = min(r["_date"] for r in recs)
        L.append(f"| W{wk[1]} ({start:%d %b}) | {ndays} | {s['reviewed']} | {pct(s['acc_pct'])} | "
                 f"{pct(s['ocr_acc_pct'])} | {s['ocr']} | {s['cats'].get('PO Issue',0)} | "
                 f"{s['cats'].get('Storm Creek Issue',0)} |")
    L.append("")
    L.append("### Last 14 working days")
    L.append("")
    L.append("| Date | Reviewed | Overall acc. | OCR acc. | OCR errors | PO issues |")
    L.append("|---|---|---|---|---|---|")
    for d in last14_dates:
        s = stats(by_date[d])
        L.append(f"| {d:%a %d %b} | {s['reviewed']} | {pct(s['acc_pct'])} | {pct(s['ocr_acc_pct'])} | "
                 f"{s['ocr']} | {s['cats'].get('PO Issue',0)} |")
    L.append("")

    # ---------------- Accounts ----------------
    L.append("## 6. Account (distributor) trends")
    L.append("")
    last14 = collect(last14_dates)
    before14 = [r for d in dates[:max(0, idx - 13)] for r in by_date[d]]
    d14, dbefore = defaultdict(list), defaultdict(list)
    for r in last14:
        d14[r["_dist"]].append(r)
    for r in before14:
        dbefore[r["_dist"]].append(r)

    rows_acc = []
    for dist, recs in d14.items():
        s = stats(recs)
        if s["reviewed"] < 8 or dist == "(blank)":
            continue
        sb = stats(dbefore.get(dist, []))
        rows_acc.append((s["ocr_acc_pct"], dist, s, sb))
    rows_acc.sort()
    L.append("### Lowest OCR accuracy, last 14 working days (≥8 reviewed orders)")
    L.append("")
    L.append("| Distributor | Reviewed | OCR acc. (14d) | OCR acc. (before) | Trend | Top themes (14d) |")
    L.append("|---|---|---|---|---|---|")
    for ocr_pct, dist, s, sb in rows_acc[:12]:
        if ocr_pct is not None and ocr_pct >= 95:
            break
        th = theme_counts([r for r in d14[dist] if r["_cat"] in OCR_CATS]).most_common(2)
        L.append(f"| {md_escape(dist)} | {s['reviewed']} | {pct(ocr_pct)} | {pct(sb['ocr_acc_pct'])} | "
                 f"{delta(ocr_pct, sb['ocr_acc_pct'])} | {', '.join(f'{t} ({n})' for t, n in th)} |")
    L.append("")

    # repeat offenders: OCR errors on >=3 distinct days in last 14
    rep = []
    for dist, recs in d14.items():
        errdays = {r["_date"] for r in recs if r["_cat"] in OCR_CATS}
        if len(errdays) >= 3 and dist != "(blank)":
            rep.append((len(errdays), sum(1 for r in recs if r["_cat"] in OCR_CATS), dist))
    rep.sort(reverse=True)
    L.append("### Repeat offenders — OCR errors on 3+ separate days in the last 14")
    L.append("")
    if rep:
        L.append("| Distributor | Days with errors | OCR errors | Most common theme |")
        L.append("|---|---|---|---|")
        for nd, ne, dist in rep[:10]:
            th = theme_counts([r for r in d14[dist] if r["_cat"] in OCR_CATS]).most_common(1)
            L.append(f"| {md_escape(dist)} | {nd} | {ne} | {th[0][0] if th else ''} |")
    else:
        L.append("None.")
    L.append("")

    # improved accounts
    imp = [(ocr - sb["ocr_acc_pct"], dist, ocr, sb) for ocr, dist, s, sb in rows_acc
           if ocr is not None and sb["ocr_acc_pct"] is not None and sb["reviewed"] >= 8]
    imp.sort(reverse=True)
    good = [x for x in imp if x[0] >= 10][:5]
    if good:
        L.append("### Most improved accounts (14d vs before)")
        L.append("")
        for d, dist, ocr, sb in good:
            L.append(f"- {dist}: {pct(sb['ocr_acc_pct'])} → {pct(ocr)} ({d:+.1f} pts)")
        L.append("")

    # ---------------- Reviewers ----------------
    L.append("## 7. Volume and error rate by reviewer")
    L.append("")
    L.append("_Errors are attributed to the order the reviewer processed, not to the reviewer._")
    L.append("")
    L.append("| Processed By | Focus day orders | Focus day OCR acc. | Last 7d orders | Last 7d OCR acc. |")
    L.append("|---|---|---|---|---|")
    pa_day, pa7 = defaultdict(list), defaultdict(list)
    for r in day:
        pa_day[r.get("Processed By") or "(blank)"].append(r)
    for r in collect(last7_dates):
        pa7[r.get("Processed By") or "(blank)"].append(r)
    for p in sorted(pa7, key=lambda p: -len(pa7[p])):
        sd, s7 = stats(pa_day.get(p, [])), stats(pa7[p])
        L.append(f"| {p} | {sd['total']} | {pct(sd['ocr_acc_pct'])} | {s7['total']} | {pct(s7['ocr_acc_pct'])} |")
    L.append("")

    # ---------------- Data quality ----------------
    L.append("## 8. Data quality notes")
    L.append("")
    ff = [r for r in collect(last7_dates) if r["_cat"] in OCR_CATS and FALSE_FLAG_RE.search(r.get("AX Comments", ""))]
    L.append(f"- {len(ff)} OCR-tagged orders in the last 7 days say \"All OK\" / \"unnecessarily flagged\" "
             "in the comment. Some may be false flags (the order was right but the UI flagged it), or the "
             "order had several errors and only one was a false flag. Worth checking whether they should "
             "count as errors.")
    nocat = [r for r in collect(last7_dates) if not r["_cat"]]
    if nocat:
        why = Counter((r.get("Order Status") or "?").title() for r in nocat)
        L.append(f"- {len(nocat)} orders in the last 7 days have no \"Issue related\" value "
                 f"({', '.join(f'{k}: {v}' for k, v in why.most_common())}). These are excluded from accuracy.")
    sec = sum(1 for r in collect(last7_dates) if r.get("Secondary Cat for OCR Issue"))
    L.append(f"- \"Secondary Cat for OCR Issue\" is filled in for {sec} of {len(ocr_last7)} OCR errors "
             "in the last 7 days, so themes are inferred from the AX Comments text instead.")
    L.append("")
    return "\n".join(L)


def main():
    if len(sys.argv) not in (3, 4):
        print(__doc__)
        sys.exit(1)
    rows = load_rows(sys.argv[1])
    focus = (datetime.date.fromisoformat(sys.argv[3]) if len(sys.argv) == 4
             else max(r["_date"] for r in rows))
    report = render_report(rows, focus)
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print(f"Wrote report for {focus} to {sys.argv[2]}")


if __name__ == "__main__":
    main()
