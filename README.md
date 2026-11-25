# Daily OCR Accuracy Report — Storm Creek

Generates a daily report from the "Live Orders" tab of the tracker sheet:
https://docs.google.com/spreadsheets/d/1SGFQmGZ59tKD4tdWKG3o1acZsZtZM85kN3sbUKUSGH4

Each run:
1. Pulls the "Live Orders" sheet (CSV export via the Google Drive connector).
2. Runs `scripts/generate_report.py` on that CSV. The report focuses on the
   latest fully logged day before the run date (normally yesterday) and covers:
   overall vs OCR-only accuracy (day / prev day / 7d / prior 7d / 30d), daily and
   weekly trend, error themes derived from "AX Comments" (week-over-week),
   distributor repeat offenders / biggest movers / lowest accuracy, every flagged
   order of the day, reviewer volume, and a ranked "where to improve" list.
3. Writes the result to `reports/<run-date>.md`.

## Regenerating a report manually

```
python3 scripts/generate_report.py path/to/live_orders.csv reports/YYYY-MM-DD.md [YYYY-MM-DD]
```

The optional third argument is the run date (defaults to today). Required
columns: `Date, Processed By, Distributor, AX Comments, Issue related`
(extra columns such as `Secondary Cat for OCR Issue`, `Dev Notes` are ignored).
Accuracy is computed on reviewed rows only (non-blank `Issue related`);
"OCR accuracy" counts only `OCR Issue` and `OCR / Email Format` as errors.

## Known limitation

The Google Drive export used to pull the CSV only returns the sheet's default
tab ("Live Orders") at full row fidelity. The spreadsheet's other tabs
("Errors Encountered", "External Errors - Client", "Action Tracker",
"Distributor Wise issues") are read at sample fidelity only and are folded
into the report as qualitative context, not full row-level stats.
