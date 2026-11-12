# Daily OCR Accuracy Report — Storm Creek

Generates a daily report from the "Live Orders" tab of the tracker sheet:
https://docs.google.com/spreadsheets/d/1SGFQmGZ59tKD4tdWKG3o1acZsZtZM85kN3sbUKUSGH4

Each run:
1. Pulls the "Live Orders" sheet (CSV export via the Google Drive connector).
2. Runs `scripts/generate_report.py` on that CSV to categorize errors ("Issue
   related" + recurring themes in "AX Comments"), compute per-day/per-distributor/
   per-associate accuracy, and flag where accuracy is weakest.
3. Writes the result to `reports/YYYY-MM-DD.md`.

## Regenerating a report manually

```
python3 scripts/generate_report.py path/to/live_orders.csv reports/YYYY-MM-DD.md [REPORT_DAY]
```

`REPORT_DAY` (YYYY-MM-DD) defaults to the latest date logged in the sheet.
The report covers: report-day vs previous day / last 7 / prior 7 / ~month
accuracy (overall and OCR-only), every flagged order that day, OCR error
themes with week-over-week trend, daily and weekly trend tables, repeat-offender
accounts, low-accuracy accounts, and an auto-ranked improvement list.

Rows with a blank `Issue related` (duplicates, rejected files, no PO) are
excluded from accuracy. "OCR accuracy" treats only `OCR Issue` and
`OCR / Email Format` as errors; `PO Issue` and `Storm Creek Issue` are
source-document problems tracked separately.

## Known limitation

Only the sheet's default tab ("Live Orders") is exported at full row fidelity.
Other tabs (Shopify / BrandBook / Fully Automated / Manual Review orders,
Action Tracker, Errors Encountered, External Errors - Client) are not yet
part of the stats.
