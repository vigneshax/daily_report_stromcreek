# Daily OCR Accuracy Report — Storm Creek

Generates a daily report from the "Live Orders" tab of the tracker sheet:
https://docs.google.com/spreadsheets/d/1SGFQmGZ59tKD4tdWKG3o1acZsZtZM85kN3sbUKUSGH4

Each run:
1. Pulls the "Live Orders" sheet (CSV export via the Google Drive connector).
2. Runs `scripts/generate_report.py` on that CSV. The report focuses on the
   latest logged day (the "focus day") and compares it with the previous 7
   working days and the whole history:
   - overall accuracy and OCR accuracy (PO/client issues excluded)
   - where improvement is needed (top and rising OCR error themes)
   - the focus day's OCR error list, one row per order
   - error themes taken from "AX Comments", with week-over-week change
   - weekly and daily accuracy trend
   - account trends: lowest accuracy, repeat offenders, most improved
   - volume by reviewer, plus data-quality notes
3. Writes the result to `reports/YYYY-MM-DD.md`, named after the focus day.

## Regenerating a report manually

```
python3 scripts/generate_report.py path/to/live_orders.csv reports/YYYY-MM-DD.md [YYYY-MM-DD]
```

The optional third argument picks the focus day; by default it is the latest date in the sheet.
Required columns: `Date, Processed By, PO Number, Distributor, AX Comments, Issue related`.
Extra columns are ignored.

## Known limitation

The Google Drive export used to pull the CSV only returns the sheet's default
tab ("Live Orders") at full row fidelity. The spreadsheet's other tabs
("Errors Encountered", "External Errors - Client", "Action Tracker",
"Distributor Wise issues") are read at sample fidelity only and are folded
into the report as qualitative context, not full row-level stats.
