#!/usr/bin/env python3
"""
Storm Creek daily OCR accuracy report.

Reads the full tracker workbook (xlsx export of
https://docs.google.com/spreadsheets/d/1SGFQmGZ59tKD4tdWKG3o1acZsZtZM85kN3sbUKUSGH4)
and writes a Markdown report focused on the most recent review day, with
trends across days, error categories, and accounts (distributors).

Usage:
    python3 generate_report.py <workbook.xlsx> <output_report.md> [--summary <summary.txt>]

Requires: pandas, openpyxl
"""
import re
import sys
import datetime as dt

import pandas as pd

ACC = "Accurate Orders"
OCR_LABELS = {"OCR Issue", "OCR / Email Format"}
PO_LABELS = {"PO Issue"}
SC_LABELS = {"Storm Creek Issue"}

# Field-level error categories, matched against the reviewer's AX Comments.
# Order matters only for display; one order can hit several categories.
CATEGORIES = [
    ("Contact name copied into Company Name",
     r"captured in both ship to and company name"),
    ("Account number / Shipper acct ID",
     r"account|acct|shipper (number|no)|shipping id|ups shipper"),
    ("Ship method / Carrier",
     r"ship(ping)? method|ship carrier|shipping carrier|\bground\b|next day|2nd day|"
     r"overnight|\busps\b|\b(8|10) ?am\b|3 day"),
    ("Part ID / Line record",
     r"part ?id|product id|line record|\bline\b.*(not|creat)|incorrect line|"
     r"system captures? [0-9]|item [0-9]+ was not|product code|\bmto\b"),
    ("Quantity", r"\bqty\b|quantity|quanity"),
    ("Color / Size", r"colou?r|\bsize\b|\bjt\b|\bbk\b"),
    ("STC (state to credit)", r"\bstc\b|state to credit"),
    ("Reporting Group", r"reporting group|\brg\b"),
    ("PO number", r"po ?(number|no|#)"),
    ("PO total / Freight (FF)", r"po ?total|\bff\b|freight|pricing|unit cost"),
    ("Order type / PSST",
     r"order type|psst|preferred ship date|sample order|blank order"),
    ("Ship-to address / Company name",
     r"ship ?to|address|company name|\bto:"),
    ("Product proof", r"proof"),
    ("PO contact / Email", r"po contact|contact email|po mail"),
]


ERR_RE = (r"incorrect|wrong|not captured|did not capture|didn't capture|"
          r"failed|was captured as|captured in both|unnecessary(?! ?flag)|"
          r"not created|missing")


def categorize(comment):
    c = str(comment or "")
    hits = [name for name, pat in CATEGORIES if re.search(pat, c, re.I)]
    # The contact-name pattern also mentions "ship to"/"company name"; keep it
    # in its own bucket only.
    if "Contact name copied into Company Name" in hits and \
            "Ship-to address / Company name" in hits:
        hits.remove("Ship-to address / Company name")
    return hits or ["Other / unclassified"]


def pct(a, b):
    return a / b * 100 if b else 0.0


def load(path):
    lo = pd.read_excel(path, sheet_name="Live Orders")
    lo = lo[lo["Date"].notna()].copy()
    lo["Date"] = pd.to_datetime(lo["Date"], errors="coerce").dt.normalize()
    lo = lo[lo["Date"].notna()]
    lo["Issue related"] = lo["Issue related"].astype("string").str.strip()
    lo["Distributor"] = lo["Distributor"].astype("string").str.strip()
    # Only orders a reviewer actually classified count toward accuracy
    # (excludes duplicates / file-rejected / pending rows).
    rev = lo[lo["Issue related"].notna()].copy()
    rev["is_acc"] = rev["Issue related"] == ACC
    rev["is_ocr"] = rev["Issue related"].isin(OCR_LABELS)
    rev["is_po"] = rev["Issue related"].isin(PO_LABELS)
    rev["is_sc"] = rev["Issue related"].isin(SC_LABELS)
    com = rev["AX Comments"].astype("string").fillna("").str.strip()
    allok = com.str.match(r'^"?\s*all\s*ok', case=False)
    # "Accurate" orders whose comment still describes an extraction miss
    # (not prefixed "All Ok"): accuracy is overstated by these.
    rev["hidden_err"] = rev.is_acc & ~allok & com.str.contains(
        ERR_RE, case=False, regex=True)
    # Validation flags the reviewer had to clear although the field was right.
    rev["false_flag"] = com.str.contains(r"unnecess?ary flag|unnessary flag|"
                                         r"unnecessary\s+flagged|flagged for .* correct",
                                         case=False, regex=True)
    rev["ff_field"] = com.str.extract(
        r"flagged\s+(?:for\s+)?(?:the\s+)?([a-z #/]+?)\s+(?:which|was|is|field)",
        flags=re.I)[0].str.lower().str.strip()
    rev["cats"] = [categorize(c) if (o or h) else [] for c, o, h in
                   zip(rev["AX Comments"], rev["is_ocr"], rev["hidden_err"])]
    others = {}
    for name in ("External Errors - Client", "Action Tracker",
                 "Fully Automated Order"):
        try:
            others[name] = pd.read_excel(path, sheet_name=name)
        except ValueError:
            others[name] = None
    return rev, others


def day_stats(df):
    n = len(df)
    return dict(n=n, acc=int(df.is_acc.sum()), ocr=int(df.is_ocr.sum()),
                po=int(df.is_po.sum()), sc=int(df.is_sc.sum()),
                acc_pct=pct(df.is_acc.sum(), n),
                ocr_acc_pct=100 - pct(df.is_ocr.sum(), n))


def cat_counts(df):
    s = df[df.is_ocr]["cats"].explode()
    return s.value_counts()


def fmt_delta(x, unit="pts"):
    return f"{'+' if x >= 0 else ''}{x:.1f} {unit}"


def build(rev, others):
    days = sorted(rev["Date"].unique())
    today = pd.Timestamp(days[-1])
    last5 = [pd.Timestamp(d) for d in days[-5:]]
    prev5 = [pd.Timestamp(d) for d in days[-10:-5]]
    last10 = [pd.Timestamp(d) for d in days[-10:]]
    base20 = [pd.Timestamp(d) for d in days[-30:-10]]

    T = rev[rev.Date == today]
    L5 = rev[rev.Date.isin(last5)]
    P5 = rev[rev.Date.isin(prev5)]
    L10 = rev[rev.Date.isin(last10)]
    B20 = rev[rev.Date.isin(base20)]

    st, s5, p5 = day_stats(T), day_stats(L5), day_stats(P5)
    s30 = day_stats(rev[rev.Date.isin([pd.Timestamp(d) for d in days[-30:]])])
    allst = day_stats(rev)

    out = []
    w = out.append
    w(f"# Storm Creek OCR Daily Report — review day {today:%Y-%m-%d} ({today:%a})")
    w("")
    w(f"Source: \"Live Orders\" tab, {allst['n']:,} reviewer-classified orders, "
      f"{pd.Timestamp(days[0]):%Y-%m-%d} to {today:%Y-%m-%d} ({len(days)} working days). "
      f"Accuracy = Accurate Orders / classified orders. OCR accuracy = 1 − OCR-attributable "
      f"issues / classified orders (PO issues are customer-side and Storm Creek issues are "
      f"setup-side, so they are left out of OCR accuracy).")
    w("")

    # ---------------- Headline
    w("## Headline")
    w("")
    w("| Metric | Latest day | Last 5 days | Prior 5 days | Change | Last 30 days |")
    w("|---|---|---|---|---|---|")
    w(f"| Orders reviewed | {st['n']} | {s5['n']} | {p5['n']} | | {s30['n']} |")
    w(f"| Overall accuracy | **{st['acc_pct']:.1f}%** | {s5['acc_pct']:.1f}% | "
      f"{p5['acc_pct']:.1f}% | {fmt_delta(s5['acc_pct']-p5['acc_pct'])} | {s30['acc_pct']:.1f}% |")
    w(f"| OCR accuracy | **{st['ocr_acc_pct']:.1f}%** | {s5['ocr_acc_pct']:.1f}% | "
      f"{p5['ocr_acc_pct']:.1f}% | {fmt_delta(s5['ocr_acc_pct']-p5['ocr_acc_pct'])} | "
      f"{s30['ocr_acc_pct']:.1f}% |")
    w(f"| OCR issues | {st['ocr']} | {s5['ocr']} | {p5['ocr']} | | {s30['ocr']} |")
    w(f"| PO issues | {st['po']} | {s5['po']} | {p5['po']} | | {s30['po']} |")
    w(f"| Storm Creek issues | {st['sc']} | {s5['sc']} | {p5['sc']} | | {s30['sc']} |")
    w("")

    # ---------------- Daily trend
    w("## Daily trend (last 15 working days)")
    w("")
    w("| Date | Orders | Accuracy | OCR accuracy | OCR | PO | SC |")
    w("|---|---|---|---|---|---|---|")
    for d in days[-15:]:
        s = day_stats(rev[rev.Date == pd.Timestamp(d)])
        w(f"| {pd.Timestamp(d):%m-%d %a} | {s['n']} | {s['acc_pct']:.1f}% | "
          f"{s['ocr_acc_pct']:.1f}% | {s['ocr']} | {s['po']} | {s['sc']} |")
    w("")
    w("Monthly: " + "; ".join(
        f"{m}: {day_stats(g)['acc_pct']:.1f}% overall / {day_stats(g)['ocr_acc_pct']:.1f}% OCR "
        f"({len(g):,} orders)"
        for m, g in rev.groupby(rev.Date.dt.strftime('%b'), sort=False)))
    w("")

    # ---------------- Categories
    ct, c5, cp, c20 = cat_counts(T), cat_counts(L5), cat_counts(P5), cat_counts(B20)
    names = list(dict.fromkeys(list(c5.index) + list(ct.index) + list(cp.index)))
    rows = []
    for nme in names:
        r5 = pct(c5.get(nme, 0), s5["n"])
        rp = pct(cp.get(nme, 0), p5["n"])
        rows.append((nme, int(ct.get(nme, 0)), int(c5.get(nme, 0)),
                     int(cp.get(nme, 0)), r5 - rp, int(c20.get(nme, 0))))
    rows.sort(key=lambda r: (-r[2], -r[1]))
    w("## OCR error categories")
    w("")
    w("From the reviewer's AX Comments on OCR-attributable orders (one order can hit "
      "more than one category). Change = per-100-orders rate, last 5 days vs prior 5.")
    w("")
    w("| Category | Latest day | Last 5 days | Prior 5 days | Rate change | Days 11–30 back |")
    w("|---|---|---|---|---|---|")
    for nme, a, b, c, dlt, e in rows:
        arrow = "▲" if dlt > 0.25 else ("▼" if dlt < -0.25 else "–")
        w(f"| {nme} | {a} | {b} | {c} | {arrow} {dlt:+.2f} | {e} |")
    w("")

    # New/emerging: categories seen in last 5 days but not in the 20 days before that
    hist = cat_counts(rev[rev.Date < last5[0]])
    first_seen = {}
    ocr_rows = rev[rev.is_ocr].explode("cats")
    for nme, g in ocr_rows.groupby("cats"):
        first_seen[nme] = g.Date.min()
    emerging = [n for n in names if c5.get(n, 0) >= 2 and
                (first_seen.get(n, today) >= last10[0] or
                 c5.get(n, 0) >= 2 * max(cp.get(n, 0), 1))]

    # ---------------- Latest day detail
    w(f"## Flagged orders on {today:%Y-%m-%d}")
    w("")
    w("| Type | Distributor | Reviewer | Category | Comment |")
    w("|---|---|---|---|---|")
    flagged = T[~T.is_acc].sort_values(["is_ocr", "Distributor"], ascending=[False, True])
    for _, r in flagged.iterrows():
        typ = "OCR" if r.is_ocr else ("PO" if r.is_po else ("SC" if r.is_sc else r["Issue related"]))
        cat = ", ".join(r.cats) if r.is_ocr else "—"
        com = re.sub(r"\s+", " ", str(r["AX Comments"])).replace("|", "/")[:160]
        w(f"| {typ} | {r.Distributor if pd.notna(r.Distributor) else '—'} | "
          f"{r['Processed By']} | {cat} | {com} |")
    w("")

    # ---------------- Accounts
    def acct_table(df):
        g = df.groupby("Distributor").agg(n=("is_acc", "size"), acc=("is_acc", "sum"),
                                          ocr=("is_ocr", "sum"), po=("is_po", "sum"))
        g["acc_pct"] = g.acc / g.n * 100
        g["ocr_rate"] = g.ocr / g.n * 100
        return g

    a10, ab = acct_table(L10), acct_table(B20)
    j = a10.join(ab.add_suffix("_b"), how="left")
    w("## Accounts needing attention (last 10 working days)")
    w("")
    w("Accounts with at least 2 OCR issues in the last 10 working days, worst OCR-issue rate first. "
      "\"Before\" = the 20 working days before that.")
    w("")
    w("| Distributor | Orders | OCR issues | OCR-issue rate | Accuracy | Accuracy before | Main categories |")
    w("|---|---|---|---|---|---|---|")
    hot = j[j.ocr >= 2].sort_values(["ocr_rate", "ocr"], ascending=False).head(15)
    for dname, r in hot.iterrows():
        cats = cat_counts(L10[L10.Distributor == dname]).head(3)
        catstr = ", ".join(f"{k} ({v})" for k, v in cats.items())
        before = f"{r.acc_pct_b:.0f}% ({int(r.n_b)})" if pd.notna(r.n_b) else "new"
        w(f"| {dname} | {int(r.n)} | {int(r.ocr)} | {r.ocr_rate:.0f}% | {r.acc_pct:.0f}% | "
          f"{before} | {catstr} |")
    w("")

    big = j[(j.n >= 15) & (j.n_b >= 15)].copy()
    big["chg"] = big.acc_pct - big.acc_pct_b
    w("### Biggest movers (≥15 orders in both windows)")
    w("")
    w("| Distributor | Accuracy before → now | Change | Orders now |")
    w("|---|---|---|---|")
    movers = pd.concat([big.sort_values("chg").head(5),
                        big.sort_values("chg", ascending=False).head(3)])
    for dname, r in movers.iterrows():
        w(f"| {dname} | {r.acc_pct_b:.0f}% → {r.acc_pct:.0f}% | {r.chg:+.0f} pts | {int(r.n)} |")
    w("")

    # PO-issue accounts (customer side)
    po_acc = L10[L10.is_po].Distributor.value_counts().head(5)
    if len(po_acc):
        w("PO-side (customer) issues concentrate in: " +
          ", ".join(f"{k} ({v})" for k, v in po_acc.items()) + ".")
        w("")

    # ---------------- Labelling gaps
    def hidden_tbl(df):
        return df[df.hidden_err].explode("cats")["cats"].value_counts()
    h5, hp = hidden_tbl(L5), hidden_tbl(P5)
    nh5, nhp = int(L5.hidden_err.sum()), int(P5.hidden_err.sum())
    w("## Errors hidden inside \"Accurate Orders\"")
    w("")
    w(f"Orders labelled Accurate whose comment describes an extraction miss and is not "
      f"prefixed \"All Ok\": **{nh5}** in the last 5 days vs {nhp} in the prior 5. "
      f"Counting them as OCR issues, last-5-day OCR accuracy would be "
      f"**{100-pct(s5['ocr']+nh5, s5['n']):.1f}%** instead of {s5['ocr_acc_pct']:.1f}%.")
    w("")
    if nh5:
        w("| Category | Last 5 days | Prior 5 days | Example |")
        w("|---|---|---|---|")
        ex = L5[L5.hidden_err].explode("cats")
        for nme, v in h5.items():
            e = re.sub(r"\s+", " ", str(ex[ex.cats == nme]["AX Comments"].iloc[0]))[:110]
            w(f"| {nme} | {v} | {int(hp.get(nme, 0))} | {e.replace('|', '/')} |")
        w("")
    ff5 = L5[L5.false_flag]["ff_field"].fillna("other").value_counts()
    ffp = int(P5.false_flag.sum())
    w("## False-positive validation flags")
    w("")
    w(f"Comments saying a field was flagged although it was correct: **{int(L5.false_flag.sum())}** "
      f"in the last 5 days vs {ffp} in the prior 5. Each one costs reviewer time without "
      f"catching an error.")
    if len(ff5):
        w("")
        w("By field (last 5 days): " + ", ".join(f"{k} ({v})" for k, v in ff5.head(8).items()) + ".")
    w("")

    # ---------------- Reviewers
    w("## By reviewer (last 5 days)")
    w("")
    w("| Reviewer | Orders | Flag rate | OCR flags |")
    w("|---|---|---|---|")
    g = L5.groupby("Processed By").agg(n=("is_acc", "size"), acc=("is_acc", "sum"),
                                         ocr=("is_ocr", "sum"))
    for nme, r in g.sort_values("n", ascending=False).iterrows():
        w(f"| {nme} | {int(r.n)} | {100-pct(r.acc, r.n):.1f}% | {int(r.ocr)} |")
    w("")
    w("A big spread in flag rate between reviewers on the same mix of POs can mean they "
      "apply different standards, not just that the OCR quality differs.")
    w("")

    # ---------------- Client escapes
    ee = others.get("External Errors - Client")
    recent_ee = None
    if ee is not None and "Date" in ee:
        ee = ee[ee["Date"].notna()].copy()
        ee["Date"] = pd.to_datetime(ee["Date"], errors="coerce")
        recent_ee = ee[ee["Date"] >= today - pd.Timedelta(days=7)]
        w("## Client-reported errors, last 7 days (\"External Errors - Client\")")
        w("")
        if len(recent_ee):
            for _, r in recent_ee.iterrows():
                txt = re.sub(r"\s+", " ", str(r["Issues / Errors"]))[:220]
                w(f"- {r['Date']:%m-%d} — TID {r.get('TID', '')}: {txt}")
        else:
            w("- None logged.")
        w("")

    # ---------------- Action tracker
    at = others.get("Action Tracker")
    if at is not None and "Status" in at:
        open_items = at[at["Status"].astype(str).str.lower() != "completed"]
        w("## Open Action Tracker items")
        w("")
        for _, r in open_items.iterrows():
            w(f"- **{r['Task']}** ({r.get('Priority', '')}, {r.get('Owner', '')}) — "
              f"{r['Status']}{' / ' + str(r['Code Status']) if pd.notna(r.get('Code Status')) else ''}")
        w("")

    return out, dict(today=today, st=st, s5=s5, p5=p5, s30=s30, rows=rows,
                     hot=hot, emerging=emerging, hidden5=int(L5.hidden_err.sum()), ff5=int(L5.false_flag.sum()), recent_ee=recent_ee, movers=big)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    rev, others = load(sys.argv[1])
    lines, ctx = build(rev, others)
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    # A machine-readable summary to stdout to help write the action section
    st, s5, p5 = ctx["st"], ctx["s5"], ctx["p5"]
    print(f"day={ctx['today']:%Y-%m-%d} acc={st['acc_pct']:.1f} ocr_acc={st['ocr_acc_pct']:.1f} "
          f"n={st['n']} ocr={st['ocr']} po={st['po']}")
    print(f"last5 acc={s5['acc_pct']:.1f} ocr_acc={s5['ocr_acc_pct']:.1f}; "
          f"prev5 acc={p5['acc_pct']:.1f} ocr_acc={p5['ocr_acc_pct']:.1f}")
    print("emerging:", ctx["emerging"])
    print("hidden errors last5:", ctx["hidden5"], " false flags last5:", ctx["ff5"])


if __name__ == "__main__":
    main()
