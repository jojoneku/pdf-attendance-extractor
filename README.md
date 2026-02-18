# PDF Attendance Extractor

A local web tool that extracts student attendance data from batch PDF files and exports to Excel or Google Sheets in a standardised attendance format.

## Features

- **Batch upload** — drag-and-drop multiple PDFs at once
- **Smart column detection** — matches table headers by text, not position
- **Paginated preview** — review extracted data before exporting (100 rows at a time)
- **Full Name concatenation** — auto-builds `Lastname, Firstname Middlename Extension`
- **Optional defaults** — set Email, Beneficiary, Age Range, Affiliation Type, and Affiliation Name for all rows before export
- **Excel export** — download a single `.xlsx` with all aggregated records
- **Google Sheets export** — push directly to a Google Sheet (optional)
- **Error handling** — malformed PDFs are reported without crashing the batch

## Export Output Columns

| Column           | Source                        |
|------------------|-------------------------------|
| Full Name        | Auto-concatenated from PDF    |
| Email            | Optional (user input)         |
| Gender           | Extracted from PDF            |
| Beneficiary      | Dropdown: Youth / Educator / Parent |
| Age Range        | Dropdown: 15-20 / 21-25 / 26-30 / 31-35 / Over 35 |
| Affiliation Type | Dropdown: School / Community / Workplace / University |
| Affiliation Name | Free text input               |

All columns are always present in the output, even when left blank.

## Quick Start

### 1. Clone & install

```bash
cd pdf-attendance-extractor
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

pip install -r backend/requirements.txt
```

### 2. Run the server

```bash
cd backend
uvicorn main:app --reload --port 8000
```

### 3. Open the UI

Navigate to **http://localhost:8000** in your browser.

### 4. Use it

1. Drag-and-drop one or more attendance PDFs into the upload zone.
2. Click **Extract Data** to parse and preview.
3. Optionally fill in the **defaults panel** (Email, Beneficiary, Age Range, etc.).
4. Click **Download Excel** or **Send to Google Sheets** to export.

## Google Sheets Setup (Optional)

To enable the Google Sheets export:

1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project (or use an existing one).
3. Enable the **Google Sheets API** and **Google Drive API**.
4. Create a **Service Account** and download the JSON key.
5. Place the JSON key at `credentials/service_account.json`.
6. Share your target Google Sheet with the service account email.

Alternatively, set the env var:

```bash
export GOOGLE_CREDENTIALS_PATH=/path/to/your/service_account.json
```

## Expected PDF Format

The tool expects PDFs with a table containing these column headers (case-insensitive, flexible matching):

| No | StudentID | Lastname | Firstname | Middlename | Extension | Dept. | Course | Gender | TimeIn |
|----|-----------|----------|-----------|------------|-----------|-------|--------|--------|--------|

Only **Lastname**, **Firstname**, **Middlename**, **Extension**, and **Gender** are extracted.

## Project Structure

```
pdf-attendance-extractor/
├── backend/
│   ├── main.py              # FastAPI app
│   ├── extractor.py         # PDF parsing logic
│   ├── exporter.py          # Excel + Google Sheets export
│   ├── models.py            # Pydantic schemas
│   └── requirements.txt     # Dependencies
├── frontend/
│   ├── index.html           # Web UI
│   ├── style.css            # Styles
│   └── app.js               # Client-side logic
├── tests/                   # Test suite
├── agents/                  # Agent specs (Lead, Dev, QA)
├── credentials/             # Google service account (gitignored)
├── SPECS.md                 # Full project specification
└── README.md                # This file
```

## Tech Stack

- **Python 3.11+** / FastAPI / uvicorn
- **pdfplumber** for PDF table extraction
- **openpyxl** for Excel generation
- **gspread** for Google Sheets integration
- **Vanilla HTML/CSS/JS** frontend

## Running Tests

```bash
python -m pytest tests/ -v
```
