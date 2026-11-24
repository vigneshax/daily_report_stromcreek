# Daily OCR Accuracy Report — Storm Creek

Generates a daily report from the "Live Orders" tab of the tracker sheet:
https://docs.google.com/spreadsheets/d/1SGFQmGZ59tKD4tdWKG3o1acZsZtZM85kN3sbUKUSGH4

Each run:
1. Pulls the "Live Orders" sheet (CSV export via the Google Drive connector).
2. Runs `scripts/generate_report.py` on that CSV. The report focuses on the
   latest logged working day and covers: overall vs OCR (dev-fixable) accuracy
   compared with the prior 5 and 20 days; error themes from "AX Comments" with
   the 7-day rate vs the prior 21 days; that day's OCR issues to action;
   daily and weekly trends; worsening, improving and chronic distributors; and
   associate volume.
3. Writes the result to `reports/<run-date>.md` with analyst notes at the top.

## Regenerating a report manually

```
python3 scripts/generate_report.py path/to/live_orders.csv reports/YYYY-MM-DD.md [report-day YYYY-MM-DD]
```

Required columns: `Date, Processed By, PO Number, Distributor, AX Comments, Issue related`.
Optional columns: `Secondary Cat for OCR Issue`.
Rows with a blank "Issue related" are counted as unlabeled and left out of accuracy figures.

## Known limitation

The Google Drive export used to pull the CSV only returns the sheet's default
tab ("Live Orders") at full row fidelity. The spreadsheet's other tabs
("Errors Encountered", "External Errors - Client", "Action Tracker",
"Distributor Wise issues") are read at sample fidelity only and are folded
into the report as qualitative context, not full row-level stats.
