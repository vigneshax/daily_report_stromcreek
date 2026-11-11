#!/usr/bin/env python3
"""
Storm Creek daily OCR accuracy/error report.

Reads a CSV export of the "Live Orders" tab of the tracker spreadsheet:
https://docs.google.com/spreadsheets/d/1SGFQmGZ59tKD4tdWKG3o1acZsZtZM85kN3sbUKUSGH4

Usage:
    python3 generate_report.py <live_orders.csv> <output_report.md> [YYYY-MM-DD]

The optional date is the "run date". The report focuses on the most recent
logged review day on or before that date (default: today), and compares it
with the previous day, the trailing 7 logged days and the 7 before that.

Required CSV columns (extra columns are ignored):
Date, Week#, Processed By, PO Number, Distributor, AX Comments, Issue related
Optional: Secondary Cat for OCR Issue
"""
import csv
import datetime
import re
import sys
from collections import Counter, defaultdict

# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------
ACCURATE = "Accurate Orders"
# Errors the OCR/extraction pipeline owns (what we can fix).
OCR_LABELS = {"OCR Issue", "OCR / Email Format"}
# Errors caused by the PO itself or by Storm Creek data (not an OCR defect).
PO_LABELS = {"PO Issue"}
SC_LABELS = {"Storm Creek Issue"}

# Ordered: first match is the order's *primary* theme; all matches are counted
# as secondary themes. Patterns are matched case-insensitively on AX Comments.
THEMES = [
    ("Reporting Group (RG) wrong/unnecessary",
     r"reporting group|\bRG\b|\bAIM\b|facilis|\bASB\b|deluxe|\bAIA\b"),
    ("STC (State To Credit) not captured", r"\bSTC\b|state to credit"),
    ("Account / Shipper number",
     r"account (number|numbe|id)|acct|\baccount\b(?! of)|shipper number|shipping id|shipping account"),
    ("Contact name in Ship To + Company Name",
     r"captured in both ship to and company name"),
    ("Ship To / Address lines",
     r"ship ?to|shipping address|address line|dropship|second ?line|secondline"),
    ("Ship method / carrier",
     r"ship(ping)? method|carrier|\bups\b|fedex|ground method|2nd day|overnight"),
    ("Part ID / Product ID / line record",
     r"part ?id|product id|product details|product number|item \d{4}.*not captured|"
     r"line record|incorrect line|captures \d{4}|\d{4}s?\b was captured|product code"),
    ("Color / Size", r"\bcolou?r\b|\bsize\b|\bgr[ae]y\b|navy|black|heather"),
    ("Quantity", r"\bqty\b|quantity"),
    ("Order type (Blank/Sample/PSST)", r"order type|blank order|sample order"),
    ("Preferred ship date", r"ship date"),
    ("PO number", r"po ?number|po ?#"),
    ("PO total / Freight (FF)", r"po total|\bFF\b|unit (cost|price)"),
    ("PO contact / email", r"po contact|po mail|contact email|\bemail\b"),
    ("Company name", r"company name"),
]
THEME_RE = [(n, re.compile(p, re.IGNORECASE)) for n, p in THEMES]
THEMES_DICT = dict(THEMES)
OTHER = "Other / unclassified"

# Comments that say a field was flagged but was actually correct — a
# confidence/flagging problem rather than an extraction error.
FALSE_FLAG_RE = re.compile(r"unnecess?ar(y|ily)\s+flagged|flagged for", re.IGNORECASE)


# A theme that, when present, explains the listed broader themes on its own.
SUBSUMES = {
    "Contact name in Ship To + Company Name": {"Ship To / Address lines", "Company name"},
}


def themes_for(comment):
    hits = [n for n, rx in THEME_RE if rx.search(comment)]
    drop = set().union(*(SUBSUMES.get(h, set()) for h in hits)) if hits else set()
    # Only drop a broader theme if the comment has no other reason to carry it,
    # i.e. it is mentioned once (inside the "both ship to and company name" phrase).
    if drop:
        rest = re.sub(THEMES_DICT["Contact name in Ship To + Company Name"], "", comment, flags=re.I)
        hits = [h for h in hits if h not in drop or re.search(THEMES_DICT[h], rest, re.I)]
    return hits or [OTHER]


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
def parse_date(s):
    s = s.strip()
    if not s:
        return None
    try:
        m, d, y = s.split("/")
        y = int(y)
        if y < 100:
            y += 2000
        return datetime.date(y, int(m), int(d))
    except ValueError:
        return None


def label_of(r):
    lab = r.get("Issue related", "").strip()
    if lab == ACCURATE:
        return "accurate"
    if lab in OCR_LABELS:
        return "ocr"
    if lab in PO_LABELS:
        return "po"
    if lab in SC_LABELS:
        return "sc"
    return None  # blank / duplicate / rejected / unreviewed -> excluded


def load_rows(csv_path):
    with open(csv_path, newline="", encoding="utf-8") as f:
        raw = list(csv.DictReader(f))
    rows, skipped = [], 0
    for r in raw:
        r = {k.strip(): (v or "") for k, v in r.items() if k}
        d = parse_date(r.get("Date", ""))
        lab = label_of(r)
        if d is None or lab is None:
            skipped += 1
            continue
        r["_date"] = d
        r["_label"] = lab
        r["_dist"] = r.get("Distributor", "").strip() or "(blank)"
        r["_comment"] = " ".join(r.get("AX Comments", "").split())
        r["_themes"] = themes_for(r["_comment"]) if lab == "ocr" else []
        rows.append(r)
    return rows, skipped


# --------------------------------------------------------------------------
# Stats helpers
# --------------------------------------------------------------------------
def stats(recs):
    n = len(recs)
    c = Counter(r["_label"] for r in recs)
    return dict(
        n=n, acc=c["accurate"], ocr=c["ocr"], po=c["po"], sc=c["sc"],
        acc_pct=(c["accurate"] / n * 100) if n else 0.0,
        # OCR accuracy: share of orders with no OCR-attributable error.
        ocr_pct=((n - c["ocr"]) / n * 100) if n else 0.0,
    )


def pct(x):
    return f"{x:.1f}%"


def delta(a, b):
    d = a - b
    arrow = "▲" if d > 0.05 else ("▼" if d < -0.05 else "■")
    return f"{arrow} {d:+.1f} pts"


def theme_counts(recs, primary_only=False):
    c = Counter()
    for r in recs:
        if r["_label"] != "ocr":
            continue
        if primary_only:
            c[r["_themes"][0]] += 1
        else:
            c.update(r["_themes"])
    return c


def md_table(header, body):
    out = ["| " + " | ".join(header) + " |",
           "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(x) for x in row) + " |" for row in body]
    return out


def esc(s, n=140):
    s = s.replace("|", "/")
    return s if len(s) <= n else s[: n - 1] + "…"


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
def render_report(rows, skipped, run_date):
    by_date = defaultdict(list)
    for r in rows:
        by_date[r["_date"]].append(r)
    days = sorted(d for d in by_date if d <= run_date)
    if not days:
        return f"# Storm Creek OCR Daily Report — {run_date}\n\nNo reviewed orders found.\n"

    day = days[-1]
    prev_day = days[-2] if len(days) > 1 else None
    last7_days = days[-7:]
    prior7_days = days[-14:-7]
    last7 = [r for d in last7_days for r in by_date[d]]
    prior7 = [r for d in prior7_days for r in by_date[d]]
    today = by_date[day]
    prev = by_date[prev_day] if prev_day else []

    s_day, s_prev = stats(today), stats(prev)
    s_7, s_p7 = stats(last7), stats(prior7)
    s_all = stats([r for d in days for r in by_date[d]])

    L = []
    L.append(f"# Storm Creek OCR Daily Report — {run_date}")
    L.append("")
    stale = (run_date - day).days
    L.append(f"**Review day covered: {day:%a %d %b %Y}** "
             f"({s_day['n']} reviewed orders). "
             f"Data: Live Orders tab, {s_all['n']} reviewed orders "
             f"{days[0]} → {days[-1]}"
             + (f"; {skipped} rows excluded (blank/duplicate/rejected/unreviewed)." if skipped else "."))
    if stale > 4:
        L.append("")
        L.append(f"> ⚠️ Latest logged review day is {stale} days before the run date — "
                 "the sheet may not have been updated.")
    L.append("")
    L.append("**Definitions** — *Order accuracy* = orders marked “Accurate Orders” ÷ reviewed orders. "
             "*OCR accuracy* = reviewed orders with **no OCR-attributable error** (OCR Issue / OCR-Email Format) ÷ "
             "reviewed orders; PO Issues and Storm Creek Issues are problems in the PO or SC data, not the model.")
    L.append("")

    # ---- Headline -------------------------------------------------------
    L.append("## 1. Headline")
    L.append("")
    hdr = ["Metric", f"{day:%m/%d}", f"vs {prev_day:%m/%d}" if prev_day else "vs prev",
           "Last 7 days", "vs prior 7", "All-time"]
    body = [
        ["Orders reviewed", s_day["n"], s_prev["n"], s_7["n"], s_p7["n"], s_all["n"]],
        ["Order accuracy", pct(s_day["acc_pct"]), delta(s_day["acc_pct"], s_prev["acc_pct"]),
         pct(s_7["acc_pct"]), delta(s_7["acc_pct"], s_p7["acc_pct"]), pct(s_all["acc_pct"])],
        ["**OCR accuracy**", f"**{pct(s_day['ocr_pct'])}**", delta(s_day["ocr_pct"], s_prev["ocr_pct"]),
         f"**{pct(s_7['ocr_pct'])}**", delta(s_7["ocr_pct"], s_p7["ocr_pct"]), pct(s_all["ocr_pct"])],
        ["OCR issues", s_day["ocr"], s_prev["ocr"], s_7["ocr"], s_p7["ocr"], s_all["ocr"]],
        ["PO issues", s_day["po"], s_prev["po"], s_7["po"], s_p7["po"], s_all["po"]],
        ["Storm Creek issues", s_day["sc"], s_prev["sc"], s_7["sc"], s_p7["sc"], s_all["sc"]],
    ]
    L += md_table(hdr, body)
    L.append("")

    # ---- Error categorisation for the day -------------------------------
    L.append(f"## 2. Error categorisation — {day:%m/%d}")
    L.append("")
    day_ocr = [r for r in today if r["_label"] == "ocr"]
    tc_day = theme_counts(today)
    tc_7 = theme_counts(last7)
    tc_p7 = theme_counts(prior7)
    if day_ocr:
        L.append(f"{len(day_ocr)} OCR-attributable orders (one order can hit several themes):")
        L.append("")
        body = []
        for name, c in tc_day.most_common():
            body.append([name, c, tc_7.get(name, 0), tc_p7.get(name, 0),
                         delta_count(tc_7.get(name, 0), tc_p7.get(name, 0))])
        L += md_table(["Theme", f"{day:%m/%d}", "Last 7d", "Prior 7d", "7d trend"], body)
    else:
        L.append("No OCR-attributable errors logged on this day. 🎉")
    L.append("")

    L.append(f"### OCR errors logged on {day:%m/%d}")
    L.append("")
    if day_ocr:
        body = [[esc(r["_dist"], 40), esc(r.get("PO Number", ""), 20), esc(r["_comment"]),
                 ", ".join(r["_themes"])] for r in day_ocr]
        L += md_table(["Distributor", "PO", "Reviewer comment", "Theme(s)"], body)
    else:
        L.append("_None._")
    L.append("")

    day_other = [r for r in today if r["_label"] in ("po", "sc")]
    if day_other:
        L.append(f"<details><summary>PO / Storm Creek issues on {day:%m/%d} "
                 f"({len(day_other)}) — not OCR defects, shown for context</summary>")
        L.append("")
        body = [[{"po": "PO", "sc": "Storm Creek"}[r["_label"]], esc(r["_dist"], 40), esc(r["_comment"])]
                for r in day_other]
        L += md_table(["Type", "Distributor", "Reviewer comment"], body)
        L.append("")
        L.append("</details>")
        L.append("")

    false_flags = [r for r in last7 if FALSE_FLAG_RE.search(r["_comment"])]
    if false_flags:
        L.append(f"_Over-flagging:_ {len(false_flags)} orders in the last 7 days note a field was "
                 "flagged for review even though it was captured correctly (adds reviewer effort, "
                 "not an accuracy loss).")
        L.append("")

    # ---- Theme trend over weeks -----------------------------------------
    L.append("## 3. Error-theme trend by week (OCR issues)")
    L.append("")
    weeks = defaultdict(list)
    for r in rows:
        if r["_date"] <= run_date:
            weeks[week_key(r)].append(r)
    wk = sorted(weeks)[-6:]
    wk_tc = {w: theme_counts(weeks[w]) for w in wk}
    wk_st = {w: stats(weeks[w]) for w in wk}
    names = [n for n, _ in THEMES] + [OTHER]
    names = [n for n in names if any(wk_tc[w].get(n) for w in wk)]
    names.sort(key=lambda n: -sum(wk_tc[w].get(n, 0) for w in wk))
    hdr = ["Theme"] + [week_label(w, weeks[w]) for w in wk]
    body = [[n] + [rate_cell(wk_tc[w].get(n, 0), wk_st[w]["n"]) for w in wk] for n in names]
    body.append(["**Orders reviewed**"] + [wk_st[w]["n"] for w in wk])
    body.append(["**OCR accuracy**"] + [f"**{pct(wk_st[w]['ocr_pct'])}**" for w in wk])
    body.append(["Order accuracy"] + [pct(wk_st[w]["acc_pct"]) for w in wk])
    L += md_table(hdr, body)
    L.append("")
    L.append("_Cells: count (errors per 100 reviewed orders). Last column may be a partial week._")
    L.append("")

    # ---- Daily trend ----------------------------------------------------
    L.append("## 4. Daily trend (last 15 review days)")
    L.append("")
    body = []
    for d in days[-15:]:
        s = stats(by_date[d])
        body.append([f"{d:%a %m/%d}", s["n"], pct(s["acc_pct"]), pct(s["ocr_pct"]),
                     s["ocr"], s["po"], s["sc"], spark(s["ocr_pct"])])
    L += md_table(["Date", "Orders", "Order acc.", "OCR acc.", "OCR", "PO", "SC", ""], body)
    L.append("")

    # ---- Accounts -------------------------------------------------------
    L.append("## 5. Account (distributor) trends")
    L.append("")
    acc_today = Counter(r["_dist"] for r in day_ocr)
    d7 = defaultdict(list)
    for r in last7:
        d7[r["_dist"]].append(r)
    dp7 = defaultdict(list)
    for r in prior7:
        dp7[r["_dist"]].append(r)

    L.append("### Recurring problem accounts — last 7 review days")
    L.append("")
    rec = []
    for dist, recs in d7.items():
        s = stats(recs)
        if s["ocr"] >= 2:
            sp = stats(dp7.get(dist, []))
            top = theme_counts(recs).most_common(2)
            rec.append((s["ocr"], dist, s, sp, top))
    rec.sort(key=lambda x: (-x[0], x[2]["ocr_pct"]))
    if rec:
        body = []
        for _, dist, s, sp, top in rec[:12]:
            prior = f"{pct(sp['ocr_pct'])} ({sp['n']})" if sp["n"] else "—"
            body.append([esc(dist, 45), s["n"], s["ocr"], pct(s["ocr_pct"]), prior,
                         "; ".join(f"{n} ×{c}" for n, c in top),
                         "yes" if dist in acc_today else ""])
        L += md_table(["Distributor", "Orders 7d", "OCR errs 7d", "OCR acc. 7d",
                       "OCR acc. prior 7d (orders)", "Main themes", f"Hit on {day:%m/%d}"], body)
    else:
        L.append("_No account had 2+ OCR errors in the last 7 review days._")
    L.append("")

    L.append("### Accounts getting worse / better (≥5 orders in both 7-day windows)")
    L.append("")
    mv = []
    for dist in set(d7) & set(dp7):
        a, b = stats(d7[dist]), stats(dp7[dist])
        if a["n"] >= 5 and b["n"] >= 5:
            mv.append((a["ocr_pct"] - b["ocr_pct"], dist, a, b))
    mv.sort()
    worse = [m for m in mv if m[0] <= -10][:6]
    better = [m for m in reversed(mv) if m[0] >= 10][:6]
    if worse or better:
        body = [["▼ worse", esc(d, 45), f"{pct(b['ocr_pct'])} → {pct(a['ocr_pct'])}", f"{x:+.1f}",
                 f"{b['n']} → {a['n']}"] for x, d, a, b in worse]
        body += [["▲ better", esc(d, 45), f"{pct(b['ocr_pct'])} → {pct(a['ocr_pct'])}", f"{x:+.1f}",
                  f"{b['n']} → {a['n']}"] for x, d, a, b in better]
        L += md_table(["", "Distributor", "OCR acc. prior → last 7d", "Δ pts", "Orders"], body)
    else:
        L.append("_No account moved by 10+ points between the two 7-day windows._")
    L.append("")

    L.append("### High-volume accounts — all time (≥40 orders, worst OCR accuracy first)")
    L.append("")
    dall = defaultdict(list)
    for d in days:
        for r in by_date[d]:
            dall[r["_dist"]].append(r)
    hv = [(stats(v), k) for k, v in dall.items() if len(v) >= 40 and k != "(blank)"]
    hv.sort(key=lambda x: x[0]["ocr_pct"])
    body = []
    for s, k in hv[:10]:
        s7 = stats(d7.get(k, []))
        body.append([esc(k, 45), s["n"], pct(s["ocr_pct"]), pct(s["acc_pct"]),
                     f"{pct(s7['ocr_pct'])} ({s7['n']})" if s7["n"] else "—",
                     ", ".join(n for n, _ in theme_counts(dall[k]).most_common(2))])
    L += md_table(["Distributor", "Orders", "OCR acc.", "Order acc.", "OCR acc. last 7d (orders)",
                   "Top themes"], body)
    L.append("")

    # ---- Reviewers ------------------------------------------------------
    L.append("## 6. Reviewer coverage")
    L.append("")
    L.append("Errors are logged by reviewers, so this shows where findings come from — "
             "large gaps between reviewers can mean different review strictness, not different OCR quality.")
    L.append("")
    rv7 = defaultdict(list)
    for r in last7:
        rv7[r.get("Processed By", "").strip() or "(blank)"].append(r)
    rvd = Counter(r.get("Processed By", "").strip() or "(blank)" for r in today)
    body = []
    for k, v in sorted(rv7.items(), key=lambda x: -len(x[1])):
        s = stats(v)
        body.append([k, rvd.get(k, 0), s["n"], s["ocr"], pct(s["ocr_pct"]), pct(s["acc_pct"])])
    L += md_table(["Reviewer", f"Orders {day:%m/%d}", "Orders 7d", "OCR errs 7d", "OCR acc. 7d",
                   "Order acc. 7d"], body)
    L.append("")

    # ---- Where to act ---------------------------------------------------
    L.append("## 7. Where improvement is needed (auto-generated)")
    L.append("")
    for i, b in enumerate(action_items(s_day, s_7, s_p7, tc_7, tc_p7, rec, worse, last7), 1):
        L.append(f"{i}. {b}")
    L.append("")
    return "\n".join(L)


# --------------------------------------------------------------------------
def delta_count(a, b):
    if b == 0:
        return "new" if a else "—"
    ch = (a - b) / b * 100
    arrow = "▲" if ch > 0 else ("▼" if ch < 0 else "■")
    return f"{arrow} {ch:+.0f}%"


def week_key(r):
    d = r["_date"]
    iso = d.isocalendar()
    return (iso[0], iso[1])


def week_label(w, recs):
    ds = sorted(r["_date"] for r in recs)
    return f"Wk {w[1]} ({ds[0]:%m/%d}–{ds[-1]:%m/%d})"


def rate_cell(c, n):
    if not c:
        return "·"
    return f"{c} ({c / n * 100:.1f})" if n else str(c)


def spark(p):
    # 80% → 0 blocks, 100% → 10 blocks
    k = max(0, min(10, round((p - 80) / 2)))
    return "█" * k + "░" * (10 - k)


def action_items(s_day, s_7, s_p7, tc_7, tc_p7, rec, worse, last7):
    out = []
    direction = "up" if s_7["ocr_pct"] > s_p7["ocr_pct"] else "down"
    out.append(
        f"**OCR accuracy is {pct(s_7['ocr_pct'])} over the last 7 review days "
        f"({direction} {abs(s_7['ocr_pct'] - s_p7['ocr_pct']):.1f} pts vs the prior 7).** "
        f"{s_7['ocr']} OCR-attributable errors across {s_7['n']} orders.")
    top = [(n, c) for n, c in tc_7.most_common() if n != OTHER][:3]
    if top:
        share = sum(c for _, c in top) / max(1, s_7["ocr"]) * 100
        out.append(
            "**Biggest fix opportunities (last 7d):** "
            + "; ".join(f"{n} — {c} orders ({delta_count(c, tc_p7.get(n, 0))} vs prior 7d)" for n, c in top)
            + f". Fixing these three would address up to ~{share:.0f}% of OCR-error orders.")
    rising = [(n, c, tc_p7.get(n, 0)) for n, c in tc_7.items()
              if n != OTHER and c >= 3 and c >= 1.5 * max(1, tc_p7.get(n, 0))]
    rising.sort(key=lambda x: -(x[1] - x[2]))
    if rising:
        out.append("**Rising themes (possible regression or new PO pattern):** "
                   + "; ".join(f"{n} {p} → {c}" for n, c, p in rising[:4]) + ".")
    if rec:
        out.append("**Accounts to target with distributor-specific rules:** "
                   + "; ".join(f"{d} ({s['ocr']} errs / {s['n']} orders, mostly {t[0][0] if t else '—'})"
                               for _, d, s, _, t in rec[:4]) + ".")
    if worse:
        out.append("**Accounts deteriorating week over week:** "
                   + "; ".join(f"{d} ({pct(b['ocr_pct'])} → {pct(a['ocr_pct'])})" for _, d, a, b in worse[:4])
                   + ".")
    oth = [r for r in last7 if r["_label"] == "ocr" and r["_themes"] == [OTHER]]
    if oth:
        out.append(f"{len(oth)} OCR errors in the last 7 days did not match any known theme — "
                   "review them for new failure modes (e.g. “" + esc(oth[0]["_comment"], 90) + "”).")
    if s_day["n"] and s_day["ocr_pct"] < s_7["ocr_pct"] - 3:
        out.append(f"Today's OCR accuracy ({pct(s_day['ocr_pct'])}) is notably below the 7-day level — "
                   "check the error table in §2 for a single account or PO template driving it.")
    return out


def main():
    if len(sys.argv) not in (3, 4):
        print(__doc__)
        sys.exit(1)
    csv_path, out_path = sys.argv[1], sys.argv[2]
    run_date = (datetime.date.fromisoformat(sys.argv[3]) if len(sys.argv) == 4
                else datetime.date.today())
    rows, skipped = load_rows(csv_path)
    report = render_report(rows, skipped, run_date)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"Wrote report to {out_path}")


if __name__ == "__main__":
    main()
