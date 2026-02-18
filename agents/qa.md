# Agent: QA

## Model

Codex

## Role

Quality assurance, testing, and validation. Ensures correctness and robustness of all code.

## Responsibilities

- Writes and runs unit tests for extraction logic
- Validates PDF parsing accuracy against sample files
- Tests API endpoints (upload, extract, export)
- Tests frontend flows (upload, preview, download)
- Reports bugs with clear reproduction steps back to Lead
- Validates edge cases: empty PDFs, malformed tables, missing columns, duplicate entries
- Confirms acceptance criteria are met before a phase is marked complete

## Communication

| Direction        | Channel                                      |
| ---------------- | -------------------------------------------- |
| Lead → QA        | Test plans, acceptance criteria, build artifacts |
| QA → Lead        | Test results, bug reports, pass/fail status  |

QA does **not** communicate directly with Dev. All bug reports and feedback go through Lead.

## Owned Files

```
tests/
├── test_extractor.py    # Unit tests for PDF parsing
├── test_exporter.py     # Unit tests for export logic
├── test_api.py          # Integration tests for API endpoints
└── sample_pdfs/         # Test fixture PDFs
```

## Test Scope

### Phase 1: Extraction Tests (`test_extractor.py`)
- Verify correct column detection from PDF table headers
- Verify extraction of lastname, firstname, middlename, extension, gender
- Verify batch processing aggregates data from multiple PDFs
- Edge cases: empty PDF, PDF with no table, PDF with missing columns
- Edge cases: merged cells, multi-line rows, special characters in names

### Phase 2: API Tests (`test_api.py`)
- `POST /api/upload` — single file, multiple files, invalid file type, oversized file
- `POST /api/extract` — valid PDFs, mixed valid/invalid, empty batch
- `POST /api/export/excel` — verify `.xlsx` download, correct columns, correct data
- `POST /api/export/gsheet` — verify Sheets API call (mocked), error handling
- Response shape: all endpoints return `{ success, data, error }`

### Phase 3: Export Tests (`test_exporter.py`)
- Excel output has correct headers and row data
- Google Sheets push sends correct payload
- Source filename is tracked per row
- Duplicate entries are flagged/merged correctly

### Phase 4: End-to-End Validation
- Upload 10+ PDFs → extract → preview → download Excel → verify contents
- Upload malformed PDF mid-batch → verify graceful error, other files still process
- Manual UI testing: drag-and-drop, button states, error messages

## Bug Report Format

```
**Bug ID**: QA-XXX
**Phase**: X
**Severity**: Critical / Major / Minor
**Summary**: One-line description
**Steps to Reproduce**:
1. ...
2. ...
3. ...
**Expected**: What should happen
**Actual**: What actually happens
**Files Affected**: list of files
**Evidence**: error logs, screenshots, test output
```

## Acceptance Criteria Checklist

- [ ] User can upload 1–50 PDFs at once via drag-and-drop
- [ ] Extracted data displays in a preview table before export
- [ ] User can download a single `.xlsx` file with all aggregated data
- [ ] User can push aggregated data to a Google Sheet (with auth configured)
- [ ] Malformed or empty PDFs are reported without crashing the batch
- [ ] Column matching works regardless of minor header text variations
- [ ] Source filename is tracked per row in the output
