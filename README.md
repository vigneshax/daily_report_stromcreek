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

The optional date is the focus day (defaults to the latest date in the sheet).
Required columns: `Date, Processed By, PO Number, Distributor, AX Comments, Issue related`
(extra columns such as `Secondary Cat for OCR Issue`, `Dev Notes`, `Status` are fine).

## What the report contains
- **Where to focus today** — auto summary: accuracy, rising error themes, likely systemic bugs,
  recurring wrong codes/values, accounts slipping.
- Overall accuracy (Accurate ÷ reviewed) and OCR accuracy (orders not flagged OCR Issue /
  OCR / Email Format) for the focus day, previous day, last/prior 7 days, 30 days, all time.
- OCR error themes (focus day / last 7 / prior 7 with trend).
- Repeated identical reviewer comments (systemic bugs).
- Accounts with the most OCR errors (14d) and biggest 7d-vs-prior-7d movers.
- PO / Storm Creek-side issues, daily + weekly trend, every flagged order on the focus day,
  reviewer flag rates.
- Flags the focus day as partial when it has <60% of the normal daily volume.

## Known limitation

The Google Drive export used to pull the CSV only returns the sheet's default
tab ("Live Orders") at full row fidelity. The spreadsheet's other tabs
("Errors Encountered", "External Errors - Client", "Action Tracker",
"Distributor Wise issues") are read at sample fidelity only and are folded
into the report as qualitative context, not full row-level stats.
