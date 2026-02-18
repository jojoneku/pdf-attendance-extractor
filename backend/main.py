"""
FastAPI application for the PDF Attendance Extractor.

Provides endpoints for uploading PDFs, extracting attendance data,
and exporting to Excel or Google Sheets.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile

# ── Logging setup ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("attendance-extractor")
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from extractor import ExtractionResult as ExtractorResult
from extractor import aggregate_students, extract_batch
from exporter import _build_full_name, export_to_excel, export_to_google_sheet
from models import (
    ExportRequest,
    ExportResponse,
    ExtractionResponse,
    FileExtractionResult,
    GoogleSheetExportRequest,
    StudentRecord,
)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = FastAPI(
    title="PDF Attendance Extractor",
    description="Upload attendance PDFs, extract student data, export to Excel or Google Sheets.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend static files
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

# Temporary upload directory — use system temp to avoid triggering --reload watcher
UPLOAD_DIR = Path(tempfile.gettempdir()) / "pdf_attendance_uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# Google credentials path (configurable via env var)
GOOGLE_CREDENTIALS_PATH = Path(
    os.environ.get("GOOGLE_CREDENTIALS_PATH", str(Path(__file__).resolve().parent.parent / "credentials" / "service_account.json"))
)

log.info("=" * 60)
log.info("PDF Attendance Extractor starting up")
log.info(f"Frontend dir : {FRONTEND_DIR} (exists={FRONTEND_DIR.exists()})")
log.info(f"Upload dir   : {UPLOAD_DIR}")
log.info(f"GSheet creds : {GOOGLE_CREDENTIALS_PATH} (exists={GOOGLE_CREDENTIALS_PATH.exists()})")
log.info("=" * 60)


# ---------------------------------------------------------------------------
# Helper: convert extractor dataclass → Pydantic model
# ---------------------------------------------------------------------------

def _to_response_model(result: ExtractorResult) -> FileExtractionResult:
    """Convert the extractor's dataclass result to Pydantic model."""
    return FileExtractionResult(
        source_file=result.source_file,
        students=[
            StudentRecord(
                lastname=s.lastname,
                firstname=s.firstname,
                middlename=s.middlename,
                extension=s.extension,
                gender=s.gender,
            )
            for s in result.students
        ],
        errors=result.errors,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    """Redirect to the frontend UI."""
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.post("/api/upload", response_model=ExtractionResponse)
async def upload_and_extract(files: list[UploadFile] = File(...)):
    """
    Upload one or more PDF files, extract attendance data, and return a preview.

    Combines upload + extraction into a single step for convenience.
    """
    log.info(f"[UPLOAD] Received {len(files)} file(s)")

    if not files:
        log.warning("[UPLOAD] No files provided")
        raise HTTPException(status_code=400, detail="No files provided.")

    # Save uploaded files to temp dir
    session_id = str(uuid.uuid4())
    session_dir = UPLOAD_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    log.debug(f"[UPLOAD] Session dir: {session_dir}")

    saved_paths: list[Path] = []
    for f in files:
        log.debug(f"[UPLOAD] Processing file: {f.filename} (content_type={f.content_type})")
        if not f.filename or not f.filename.lower().endswith(".pdf"):
            log.warning(f"[UPLOAD] Skipping non-PDF: {f.filename}")
            continue
        dest = session_dir / f.filename
        with open(dest, "wb") as out:
            content = await f.read()
            out.write(content)
        log.info(f"[UPLOAD] Saved: {f.filename} ({len(content)} bytes)")
        saved_paths.append(dest)

    if not saved_paths:
        log.warning("[UPLOAD] No valid PDF files after filtering")
        shutil.rmtree(session_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="No valid PDF files found in upload.")

    # Extract
    log.info(f"[EXTRACT] Starting extraction on {len(saved_paths)} PDF(s)...")
    results = extract_batch(saved_paths)
    response_data = [_to_response_model(r) for r in results]
    total = sum(len(r.students) for r in response_data)

    for r in results:
        log.info(f"[EXTRACT] {r.source_file}: {len(r.students)} students, {len(r.errors)} errors")
        for err in r.errors:
            log.warning(f"[EXTRACT]   ⚠ {err}")

    log.info(f"[EXTRACT] Total: {total} student records from {len(results)} file(s)")

    # Clean up temp files
    shutil.rmtree(session_dir, ignore_errors=True)

    return ExtractionResponse(success=True, data=response_data, total_students=total)


@app.post("/api/export/excel")
async def export_excel(request: ExportRequest):
    """
    Generate an Excel file from the provided extraction data.

    Returns the .xlsx file as a downloadable stream.
    """
    log.info("[EXCEL] Export requested")

    all_records: list[dict] = []
    for file_result in request.data:
        for student in file_result.students:
            raw = {
                "lastname": student.lastname,
                "firstname": student.firstname,
                "middlename": student.middlename,
                "extension": student.extension,
            }
            all_records.append({
                "full_name": _build_full_name(raw),
                "email": request.email,
                "gender": student.gender,
                "beneficiary": request.beneficiary,
                "age_range": request.age_range,
                "affiliation_type": request.affiliation_type,
                "affiliation_name": request.affiliation_name,
            })

    log.info(f"[EXCEL] {len(all_records)} records to export")

    if not all_records:
        log.warning("[EXCEL] No records — returning 400")
        raise HTTPException(status_code=400, detail="No student records to export.")

    stream = export_to_excel(all_records)
    log.info("[EXCEL] ✓ File generated, sending download")

    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=attendance_export.xlsx"},
    )


@app.post("/api/export/gsheet", response_model=ExportResponse)
async def export_google_sheet(request: GoogleSheetExportRequest):
    """
    Push extraction data to a Google Sheet.

    Requires a service account credentials JSON in the credentials/ directory.
    """
    log.info(f"[GSHEET] Export requested → sheet='{request.spreadsheet_name}', tab='{request.worksheet_name}'")

    all_records: list[dict] = []
    for file_result in request.data:
        for student in file_result.students:
            raw = {
                "lastname": student.lastname,
                "firstname": student.firstname,
                "middlename": student.middlename,
                "extension": student.extension,
            }
            all_records.append({
                "full_name": _build_full_name(raw),
                "email": request.email,
                "gender": student.gender,
                "beneficiary": request.beneficiary,
                "age_range": request.age_range,
                "affiliation_type": request.affiliation_type,
                "affiliation_name": request.affiliation_name,
            })

    log.info(f"[GSHEET] {len(all_records)} records to export")

    if not all_records:
        log.warning("[GSHEET] No records — returning 400")
        raise HTTPException(status_code=400, detail="No student records to export.")

    log.info(f"[GSHEET] Using credentials: {GOOGLE_CREDENTIALS_PATH}")

    try:
        url = export_to_google_sheet(
            records=all_records,
            credentials_path=GOOGLE_CREDENTIALS_PATH,
            spreadsheet_name=request.spreadsheet_name,
            worksheet_name=request.worksheet_name,
        )
        log.info(f"[GSHEET] ✓ Exported successfully → {url}")
        return ExportResponse(success=True, message=f"Exported to Google Sheets: {url}")
    except FileNotFoundError as e:
        log.error(f"[GSHEET] ✗ Credentials not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.error(f"[GSHEET] ✗ Export failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Google Sheets export failed: {str(e)}")
