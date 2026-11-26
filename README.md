# Daily OCR Accuracy Report — Storm Creek

Generates a daily report from the "Live Orders" tab of the tracker sheet:
https://docs.google.com/spreadsheets/d/1SGFQmGZ59tKD4tdWKG3o1acZsZtZM85kN3sbUKUSGH4

Each run:
1. Pulls the "Live Orders" sheet (CSV export via the Google Drive connector).
2. Runs `scripts/generate_report.py` on that CSV. The report covers the latest
   logged day and compares it with the previous 7 logged days and the previous 30 days:
   - OCR accuracy (excludes PO and Storm Creek issues) and overall accuracy
   - that day's OCR errors, grouped into field-level themes from "AX Comments"
     (account number, ship method, part ID, RG, STC, order type, ...)
   - a weekly theme trend over 4 weeks
   - distributors with errors that day plus their 30-day history, and the
     accounts with recurring problems
   - each reviewer's flag rates
   - a ranked list of what to fix next
3. Writes the result to `reports/<report-day>.md`.

## Regenerating a report manually

```
python3 scripts/generate_report.py path/to/live_orders.csv reports/YYYY-MM-DD.md [YYYY-MM-DD]
```

The CSV must have the header:
`Sr No,Date,Week#,Allotment,Processed By,Message ID,Order Status,PO Number,Line,Product ID,Distributor,AX Comments,Issue related,TID`

## Known limitation

The Google Drive export used to pull the CSV only returns the sheet's default
tab ("Live Orders") at full row fidelity. The spreadsheet's other tabs
("Errors Encountered", "External Errors - Client", "Action Tracker",
"Distributor Wise issues") are read at sample fidelity only and are folded
into the report as qualitative context, not full row-level stats.
