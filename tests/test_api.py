"""
QA Agent — Integration tests for the FastAPI API endpoints.

Tests upload, extraction, and export routes using httpx + TestClient.
"""

import io
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from main import app

client = TestClient(app)


# ═══════════════════════════════════════════════════════════════════
# Helper — create a minimal fake PDF in-memory
# ═══════════════════════════════════════════════════════════════════

def make_fake_pdf(filename: str = "test.pdf") -> tuple[str, io.BytesIO, str]:
    """Return a tuple suitable for httpx file upload."""
    buf = io.BytesIO(b"%PDF-1.4 fake content for testing")
    return (filename, buf, "application/pdf")


# ═══════════════════════════════════════════════════════════════════
# POST /api/upload  (upload + extract)
# ═══════════════════════════════════════════════════════════════════


class TestUploadEndpoint:
    def test_no_files_returns_400(self):
        res = client.post("/api/upload")
        assert res.status_code == 422  # FastAPI validation error (no files)

    def test_non_pdf_files_rejected(self):
        files = [("files", ("test.txt", io.BytesIO(b"hello"), "text/plain"))]
        res = client.post("/api/upload", files=files)
        assert res.status_code == 400
        assert "no valid pdf" in res.json()["detail"].lower()

    @patch("main.extract_batch")
    def test_successful_upload_and_extract(self, mock_extract):
        """Upload a fake PDF and verify extraction response shape."""
        from extractor import ExtractionResult, StudentRecord

        mock_extract.return_value = [
            ExtractionResult(
                source_file="test.pdf",
                students=[
                    StudentRecord(lastname="Cruz", firstname="Ana", gender="F"),
                ],
            )
        ]

        files = [("files", make_fake_pdf("test.pdf"))]
        res = client.post("/api/upload", files=files)

        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["total_students"] == 1
        assert len(body["data"]) == 1
        assert body["data"][0]["students"][0]["lastname"] == "Cruz"

    @patch("main.extract_batch")
    def test_multiple_files(self, mock_extract):
        from extractor import ExtractionResult, StudentRecord

        mock_extract.return_value = [
            ExtractionResult(
                source_file="file1.pdf",
                students=[StudentRecord(lastname="A", firstname="B", gender="M")],
            ),
            ExtractionResult(
                source_file="file2.pdf",
                students=[StudentRecord(lastname="C", firstname="D", gender="F")],
            ),
        ]

        files = [
            ("files", make_fake_pdf("file1.pdf")),
            ("files", make_fake_pdf("file2.pdf")),
        ]
        res = client.post("/api/upload", files=files)

        assert res.status_code == 200
        body = res.json()
        assert body["total_students"] == 2
        assert len(body["data"]) == 2


# ═══════════════════════════════════════════════════════════════════
# POST /api/export/excel
# ═══════════════════════════════════════════════════════════════════


class TestExcelExportEndpoint:
    def test_empty_data_returns_400(self):
        res = client.post("/api/export/excel", json={"data": []})
        assert res.status_code == 400

    def test_successful_excel_export(self):
        payload = {
            "data": [
                {
                    "source_file": "test.pdf",
                    "students": [
                        {
                            "lastname": "Dela Cruz",
                            "firstname": "Juan",
                            "middlename": "Santos",
                            "extension": "",
                            "gender": "M",
                        }
                    ],
                    "errors": [],
                }
            ],
            "beneficiary": "Youth",
            "age_range": "15-20",
            "affiliation_type": "University",
            "affiliation_name": "UB",
        }
        res = client.post("/api/export/excel", json=payload)

        assert res.status_code == 200
        assert "spreadsheetml" in res.headers["content-type"]
        assert "attachment" in res.headers["content-disposition"]
        assert len(res.content) > 0


# ═══════════════════════════════════════════════════════════════════
# POST /api/export/gsheet
# ═══════════════════════════════════════════════════════════════════


class TestGsheetExportEndpoint:
    def test_empty_data_returns_400(self):
        res = client.post(
            "/api/export/gsheet",
            json={"data": [], "spreadsheet_name": "Test", "worksheet_name": "Sheet1"},
        )
        assert res.status_code == 400

    @patch("main.export_to_google_sheet")
    def test_missing_credentials_returns_404(self, mock_export):
        mock_export.side_effect = FileNotFoundError("credentials not found")

        payload = {
            "data": [
                {
                    "source_file": "test.pdf",
                    "students": [
                        {"lastname": "X", "firstname": "Y", "middlename": "", "extension": "", "gender": "M"}
                    ],
                    "errors": [],
                }
            ],
            "spreadsheet_name": "Test",
            "worksheet_name": "Sheet1",
        }
        res = client.post("/api/export/gsheet", json=payload)
        assert res.status_code == 404

    @patch("main.export_to_google_sheet")
    def test_successful_gsheet_export(self, mock_export):
        mock_export.return_value = "https://docs.google.com/spreadsheets/d/test123"

        payload = {
            "data": [
                {
                    "source_file": "test.pdf",
                    "students": [
                        {"lastname": "X", "firstname": "Y", "middlename": "", "extension": "", "gender": "M"}
                    ],
                    "errors": [],
                }
            ],
            "spreadsheet_name": "Test Export",
            "worksheet_name": "Data",
        }
        res = client.post("/api/export/gsheet", json=payload)

        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert "test123" in body["message"]
