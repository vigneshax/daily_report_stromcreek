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
python3 scripts/generate_report.py path/to/live_orders.csv reports/YYYY-MM-DD.md [YYYY-MM-DD]
```

The optional last argument is the report day; it defaults to the latest date
logged in the sheet. Columns are looked up by name (Date, Processed By, Order
Status, PO Number, Distributor, AX Comments, Issue related, Secondary Cat for
OCR Issue), so extra columns in the sheet are fine.

Each report covers: today vs previous day / last 5 / last 20 logged days,
every flagged order for the day, OCR error categories with week-over-week
change, distributors with the most OCR issues and their trend, and a daily
trend table. "OCR accuracy" counts only OCR Issue + OCR / Email Format as
system errors (PO Issue and Storm Creek Issue are data-side).

## Known limitation

The Google Drive export used to pull the CSV only returns the sheet's default
tab ("Live Orders") at full row fidelity. The spreadsheet's other tabs
("Errors Encountered", "External Errors - Client", "Action Tracker",
"Distributor Wise issues") are read at sample fidelity only and are folded
into the report as qualitative context, not full row-level stats.
