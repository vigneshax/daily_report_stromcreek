# Daily OCR Accuracy Report — Storm Creek

Generates a daily report from the "Live Orders" tab of the tracker sheet:
https://docs.google.com/spreadsheets/d/1SGFQmGZ59tKD4tdWKG3o1acZsZtZM85kN3sbUKUSGH4

Each daily run:
1. Pulls the "Live Orders" tab as CSV (Google Drive connector export).
2. Runs `scripts/generate_report.py` to produce `reports/YYYY-MM-DD.md`.
3. Commits the report and sends a short summary notification.

## What the report contains

The report focuses on the **latest logged review day** on or before the run
date and compares it with the previous day, the trailing 7 review days and
the 7 before that.

1. **Headline** — order accuracy and **OCR accuracy** (orders with no
   OCR-attributable error; PO Issues and Storm Creek Issues are excluded
   because they are PO/SC-data problems, not model defects).
2. **Error categorisation for the day** — every OCR error of the day with
   the reviewer comment, classified into themes (RG, STC, account/shipper
   number, ship-to, ship method, part ID, colour/size, order type, …), with
   7-day vs prior-7-day trend per theme. PO/SC issues listed separately.
3. **Weekly theme trend** — errors per 100 reviewed orders, last 6 weeks.
4. **Daily trend** — last 15 review days.
5. **Account trends** — recurring problem distributors (2+ OCR errors in 7
   days), distributors getting worse/better week over week, and worst
   high-volume distributors all-time.
6. **Reviewer coverage** — where findings come from.
7. **Where improvement is needed** — auto-generated action list.

Rows with a blank / duplicate / rejected "Issue related" value are excluded.

## Regenerating a report manually

```
python3 scripts/generate_report.py path/to/live_orders.csv reports/YYYY-MM-DD.md [YYYY-MM-DD]
```

Required columns: `Date, Week#, Processed By, PO Number, Distributor, AX Comments, Issue related`
(extra columns are ignored).

Theme rules live in `THEMES` at the top of the script — add a regex there when
reviewers start describing a new failure mode (the report lists unclassified
comments so they are easy to spot).

## Known limitation

The Drive CSV export only returns the sheet's default tab ("Live Orders") at
full fidelity. Other tabs (Action Tracker, Errors Encountered, External
Errors - Client, Shopify / BrandBook / Manual Review orders) are not part of
the stats.
