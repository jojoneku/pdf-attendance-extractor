"""
Pydantic models for the PDF Attendance Extractor API.

Defines request/response schemas for upload, extraction, and export endpoints.
"""

from pydantic import BaseModel


class StudentRecord(BaseModel):
    """A single student record extracted from a PDF attendance form."""

    lastname: str
    firstname: str
    middlename: str = ""
    extension: str = ""
    gender: str = ""


class FileExtractionResult(BaseModel):
    """Extraction result for a single PDF file."""

    source_file: str
    students: list[StudentRecord]
    errors: list[str] = []


class ExtractionResponse(BaseModel):
    """Response from the /api/extract endpoint."""

    success: bool
    data: list[FileExtractionResult] = []
    total_students: int = 0
    error: str | None = None


class ExportRequest(BaseModel):
    """Request body for export endpoints."""

    data: list[FileExtractionResult]
    # Optional default values applied to every row in the export
    email: str = ""
    beneficiary: str = ""         # Youth | Educator | Parent
    age_range: str = ""           # 15-20 | 21-25 | 26-30 | 31-35 | Over 35
    affiliation_type: str = ""    # School | Community | Workplace | University
    affiliation_name: str = ""


class GoogleSheetExportRequest(BaseModel):
    """Request body for the Google Sheets export endpoint."""

    data: list[FileExtractionResult]
    spreadsheet_name: str = "Attendance Export"
    worksheet_name: str = "Sheet1"
    # Optional default values applied to every row in the export
    email: str = ""
    beneficiary: str = ""
    age_range: str = ""
    affiliation_type: str = ""
    affiliation_name: str = ""


class ExportResponse(BaseModel):
    """Response from export endpoints."""

    success: bool
    message: str = ""
    error: str | None = None
