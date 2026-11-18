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

Columns used: `Date, Processed By, Distributor, PO Number, AX Comments, Issue related`
(plus `Secondary Cat for OCR Issue` when present). Extra columns are ignored.

Accuracy = Accurate Orders ÷ reviewed orders (blank *Issue related* = not yet
reviewed, excluded). The OCR error rate counts `OCR Issue` + `OCR / Email Format`.
Each report compares the latest logged day against the last 7 and prior 7 logged
days, breaks errors into comment-derived themes, and flags recurring accounts.
A hand-written "Where improvement is needed" section is added per run.

## Known limitation

The Google Drive export used to pull the CSV only returns the sheet's default
tab ("Live Orders") at full row fidelity. The spreadsheet's other tabs
("Errors Encountered", "External Errors - Client", "Action Tracker",
"Distributor Wise issues") are read at sample fidelity only and are folded
into the report as qualitative context, not full row-level stats.
