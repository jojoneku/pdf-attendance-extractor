# PDF Attendance Extractor — Project Specs

## Project Overview

A local web tool that accepts batch PDF attendance forms, extracts student data (lastname, firstname, middlename, extension, gender) from embedded tables, and exports aggregated results to Excel or Google Sheets.

---

## Agent Orchestration

See individual agent specs in the [`agents/`](agents/) folder:

| Agent | Model | Spec | Role |
|-------|-------|------|------|
| **Lead / Orchestrator** | Claude Opus 4.6 | [`agents/lead.md`](agents/lead.md) | Project manager, architect, thinker — assigns tasks, reviews code, resolves conflicts |
| **Dev** | Claude Opus 4.6 | [`agents/dev.md`](agents/dev.md) | Full-stack developer — implements backend + frontend, fixes bugs |
| **QA** | Codex | [`agents/qa.md`](agents/qa.md) | Quality assurance — writes tests, validates extraction, reports bugs |

### Workflow

```
Lead (Opus 4.6)
  │
  ├──► Assigns task to Dev ──► Dev (Opus 4.6) builds feature
  │                                     │
  │◄── Dev returns completed code ◄─────┘
  │
  ├──► Lead reviews code
  │
  ├──► Assigns validation to QA ──► QA (Codex) tests feature
  │                                       │
  │◄── QA returns test results ◄──────────┘
  │
  ├──► If bugs: Lead triages, assigns fix back to Dev
  │
  └──► If pass: Lead marks phase complete, moves to next
```

---

## Tech Stack

| Layer           | Choice                        | Rationale                              |
| --------------- | ----------------------------- | -------------------------------------- |
| Backend         | Python 3.11+ / FastAPI        | Best PDF parsing ecosystem             |
| PDF Parsing     | `pdfplumber`                  | Reliable table extraction from text PDFs |
| Excel Export    | `openpyxl`                    | Native `.xlsx` generation              |
| Google Sheets   | `gspread` + service account   | Programmatic Sheets access             |
| Frontend        | Vanilla HTML / CSS / JS       | No framework overhead for a simple UI  |
| Dev Server      | `uvicorn`                     | ASGI server for FastAPI                |

---

## Architecture

```
Browser (drag-and-drop PDF upload)
    │
    ▼
FastAPI Server (localhost:8000)
    ├── POST /api/upload         ← receives batch PDFs, stores temporarily
    ├── POST /api/extract        ← parses PDFs → returns JSON preview
    ├── POST /api/export/excel   ← generates .xlsx download
    └── POST /api/export/gsheet  ← pushes to Google Sheets
    │
    ▼
pdfplumber (per-PDF table extraction)
    │
    ▼
openpyxl / gspread (output)
```

---

## Data Model

### Source PDF Table Columns

| # | Column      | Extract? |
|---|-------------|----------|
| 1 | No          | No       |
| 2 | StudentID   | No       |
| 3 | Lastname    | **Yes**  |
| 4 | Firstname   | **Yes**  |
| 5 | Middlename  | **Yes**  |
| 6 | Extension   | **Yes**  |
| 7 | Dept.       | No       |
| 8 | Course      | No       |
| 9 | Gender      | **Yes**  |
| 10| TimeIn      | No       |

### Output Schema

```json
{
  "source_file": "attendance_2026-02-18.pdf",
  "students": [
    {
      "lastname": "Dela Cruz",
      "firstname": "Juan",
      "middlename": "Santos",
      "extension": "",
      "gender": "M"
    }
  ]
}
```

### Export Output Columns (Final Attendance Format)

The export (Excel / Google Sheets) uses a standardised attendance format.
Some columns are extracted from PDFs; others are optional defaults the user
can fill in via the UI before exporting.

| Column             | Source           | Required? |
|--------------------|------------------|-----------|
| Full Name          | Concatenated: `Lastname, Firstname Middlename Extension` | Auto |
| Email              | User input (optional, default blank) | Optional |
| Gender             | Extracted from PDF | Auto |
| Beneficiary        | Dropdown: Youth · Educator · Parent | Optional |
| Age Range          | Dropdown: 15-20 · 21-25 · 26-30 · 31-35 · Over 35 | Optional |
| Affiliation Type   | Dropdown: School · Community · Workplace · University | Optional |
| Affiliation Name   | Free text | Optional |

> **Note**: All columns are always present in the output, even when left blank.

---

## File Structure

```
pdf-attendance-extractor/
├── backend/
│   ├── main.py              # FastAPI app entry point, route definitions
│   ├── extractor.py         # PDF parsing logic (pdfplumber)
│   ├── exporter.py          # Excel + Google Sheets export
│   ├── models.py            # Pydantic models for requests/responses
│   └── requirements.txt     # Python dependencies
├── frontend/
│   ├── index.html           # Single-page UI
│   ├── style.css            # Styling
│   └── app.js               # Upload, preview, export logic
├── tests/
│   ├── test_extractor.py    # Unit tests for PDF parsing
│   ├── test_exporter.py     # Unit tests for export logic
│   ├── test_api.py          # Integration tests for API endpoints
│   └── sample_pdfs/         # Test fixture PDFs
├── credentials/             # Google service account JSON (gitignored)
├── SPECS.md                 # This file
├── .gitignore
└── README.md
```

---

## Implementation Phases

### Phase 1: Core PDF Extraction Engine

**Owner**: Dev · **Reviewer**: Lead · **Validator**: QA

| #  | Task                                                                 | Status      |
|----|----------------------------------------------------------------------|-------------|
| 1a | Set up project structure, virtualenv, `requirements.txt`            | Not started |
| 1b | Implement `extractor.py` — open PDF, detect table, extract rows     | Not started |
| 1c | Implement column mapper — match headers by text, extract target cols | Not started |
| 1d | Implement batch processor — iterate files, aggregate results         | Not started |
| 1e | QA: write `test_extractor.py`, run against sample PDFs              | Not started |

### Phase 2: FastAPI Backend

**Owner**: Dev · **Reviewer**: Lead · **Validator**: QA

| #  | Task                                                                 | Status      |
|----|----------------------------------------------------------------------|-------------|
| 2a | Implement `models.py` — Pydantic schemas for student, upload, etc.  | Not started |
| 2b | Implement `POST /api/upload` — multi-file upload, temp storage      | Not started |
| 2c | Implement `POST /api/extract` — run parser, return JSON preview     | Not started |
| 2d | Implement `POST /api/export/excel` — generate `.xlsx`, return file  | Not started |
| 2e | Implement `POST /api/export/gsheet` — push to Google Sheets         | Not started |
| 2f | Error handling — malformed PDFs, missing columns, empty tables      | Not started |
| 2g | QA: write `test_api.py`, integration tests for all endpoints        | Not started |

### Phase 3: Frontend UI

**Owner**: Dev · **Reviewer**: Lead · **Validator**: QA

| #  | Task                                                                 | Status      |
|----|----------------------------------------------------------------------|-------------|
| 3a | Build `index.html` — drag-and-drop upload zone, layout              | Not started |
| 3b | Build `app.js` — upload handler, call `/api/extract`, render table  | Not started |
| 3c | Add Excel download button — calls `/api/export/excel`               | Not started |
| 3d | Add Google Sheets button — calls `/api/export/gsheet`               | Not started |
| 3e | Progress/status indicators — file count, errors per file            | Not started |
| 3f | QA: manual UI testing across browsers, edge case validation         | Not started |

### Phase 4: Polish & Config

**Owner**: Dev · **Reviewer**: Lead · **Validator**: QA

| #  | Task                                                                 | Status      |
|----|----------------------------------------------------------------------|-------------|
| 4a | Google Sheets auth setup — service account config + instructions    | Not started |
| 4b | Configurable column mapping (handle varying PDF formats)            | Not started |
| 4c | Duplicate detection — flag/merge duplicate students across PDFs     | Not started |
| 4d | README with setup, usage, and screenshots                           | Not started |
| 4e | `.gitignore` for credentials, temp files, venv                     | Not started |
| 4f | QA: end-to-end regression with batch of real PDFs                  | Not started |

---

## Dependencies

```txt
fastapi>=0.110.0
uvicorn>=0.27.0
pdfplumber>=0.11.0
openpyxl>=3.1.0
gspread>=6.0.0
google-auth>=2.28.0
python-multipart>=0.0.9
pytest>=8.0.0
httpx>=0.27.0
```

---

## Risks & Mitigations

| Risk                                    | Mitigation                                                        |
| --------------------------------------- | ----------------------------------------------------------------- |
| PDF table structure varies between forms | Flexible column-matching by header text, not column index         |
| Scanned/image PDFs (no text layer)       | Detect and warn user; OCR via `pytesseract` as future stretch     |
| Google Sheets API quota limits           | Batch writes in single API call; Excel as primary fallback        |
| Merged cells or multi-line rows in PDF   | `pdfplumber` table settings tuning; fallback to row heuristics    |
| Empty or corrupted PDF files             | Graceful skip with per-file error reporting in UI                 |

---

## Acceptance Criteria

- [ ] User can upload 1–50 PDFs at once via drag-and-drop
- [ ] Extracted data displays in a preview table before export
- [ ] User can download a single `.xlsx` file with all aggregated data
- [ ] User can push aggregated data to a Google Sheet (with auth configured)
- [ ] Malformed or empty PDFs are reported without crashing the batch
- [ ] Column matching works regardless of minor header text variations
- [ ] Source filename is tracked per row in the output
