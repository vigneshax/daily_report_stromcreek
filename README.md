# Daily OCR Accuracy Report — Storm Creek

Generates a daily report from the "Live Orders" tab of the tracker sheet:
https://docs.google.com/spreadsheets/d/1SGFQmGZ59tKD4tdWKG3o1acZsZtZM85kN3sbUKUSGH4

Each run:
1. Pulls the "Live Orders" sheet (CSV export via the Google Drive connector).
2. Runs `scripts/generate_report.py` on that CSV. The report covers:
   - Latest logged day vs the prior 7 logged days, month-to-date and all-time
     (overall accuracy and OCR-only accuracy, which leaves out PO-side issues)
   - Weekly and last-10-day trend
   - OCR error themes from reviewer comments, with 7-day vs 28-day trend
   - An action list of every OCR issue on the latest day
   - Distributors with the lowest OCR accuracy over the last 14 days, the biggest
     movers, and the accounts with the most issues over time
   - Customer-side (PO Issue) themes and each reviewer's flag rate
3. Writes the result to `reports/YYYY-MM-DD.md`.

## Regenerating a report manually

```
python3 scripts/generate_report.py path/to/live_orders.csv reports/YYYY-MM-DD.md [YYYY-MM-DD]
```

Needed columns: `Date, Processed By, PO Number, Distributor, AX Comments, Issue related`
(optional: `Dev Notes`, `Status`). Rows with a blank "Issue related" are left out
(duplicates, rejected files, or orders not yet reviewed).

## Known limitation

The Google Drive export used to pull the CSV only returns the sheet's default
tab ("Live Orders") at full row fidelity. The spreadsheet's other tabs
("Errors Encountered", "External Errors - Client", "Action Tracker",
"Distributor Wise issues") are read at sample fidelity only and are folded
into the report as qualitative context, not full row-level stats.
