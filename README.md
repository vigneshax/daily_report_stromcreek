# Daily OCR Accuracy Report — Storm Creek

Generates a daily report from the tracker workbook:
https://docs.google.com/spreadsheets/d/1SGFQmGZ59tKD4tdWKG3o1acZsZtZM85kN3sbUKUSGH4

Each run:
1. Downloads the full workbook as .xlsx via the Google Drive connector (all tabs at full fidelity).
2. Runs `scripts/generate_report.py` on it. The script:
   - computes overall accuracy and OCR accuracy for the latest review day, the last 5 days and the prior 5 days, plus the daily and monthly trend
   - sorts OCR-issue comments ("AX Comments") into field-level error categories and tracks their week-over-week rate
   - lists every flagged order on the latest day
   - lists accounts (distributors) with the most OCR issues in the last 10 days and the biggest accuracy movers
   - finds errors hidden inside "Accurate Orders" and false-positive validation flags
   - adds client-reported escapes ("External Errors - Client") and open "Action Tracker" items
3. Writes `reports/YYYY-MM-DD.md`, and the run adds a "Where to act today" section by hand.

## Regenerating a report manually

```
pip install pandas openpyxl
python3 scripts/generate_report.py path/to/workbook.xlsx reports/YYYY-MM-DD.md
```
