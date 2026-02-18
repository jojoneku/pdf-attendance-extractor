"""
QA Agent — Unit tests for the PDF extractor module.

Tests column matching, row extraction, batch processing, and edge cases.
Generates in-memory test PDFs using pdfplumber-compatible structures.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# We need to be able to import from backend/
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from extractor import (
    ExtractionResult,
    StudentRecord,
    _build_column_map,
    _match_column,
    _normalise,
    _row_to_student,
    aggregate_students,
    extract_batch,
    extract_from_pdf,
)


# ═══════════════════════════════════════════════════════════════════
# Unit tests — internal helpers
# ═══════════════════════════════════════════════════════════════════


class TestNormalise:
    def test_basic(self):
        assert _normalise("  Last Name  ") == "last name"

    def test_none(self):
        assert _normalise(None) == ""

    def test_multiple_spaces(self):
        assert _normalise("first   name") == "first name"


class TestMatchColumn:
    def test_exact_match(self):
        assert _match_column("lastname") == "lastname"
        assert _match_column("Gender") == "gender"

    def test_partial_match(self):
        assert _match_column("Last Name") == "lastname"
        assert _match_column("FIRST NAME") == "firstname"
        assert _match_column("Middle Name") == "middlename"

    def test_variant_match(self):
        assert _match_column("Ext.") == "extension"
        assert _match_column("Sex") == "gender"
        assert _match_column("M.I.") == "middlename"
        assert _match_column("Surname") == "lastname"

    def test_no_match(self):
        assert _match_column("StudentID") is None
        assert _match_column("Course") is None
        assert _match_column("TimeIn") is None
        assert _match_column("No") is None
        assert _match_column("") is None


class TestBuildColumnMap:
    def test_full_header_row(self):
        headers = ["No", "StudentID", "Lastname", "Firstname", "Middlename",
                    "Extension", "Dept.", "Course", "Gender", "TimeIn"]
        col_map = _build_column_map(headers)
        assert col_map[2] == "lastname"
        assert col_map[3] == "firstname"
        assert col_map[4] == "middlename"
        assert col_map[5] == "extension"
        assert col_map[8] == "gender"
        # Non-target columns should NOT be in the map
        assert 0 not in col_map  # No
        assert 1 not in col_map  # StudentID
        assert 6 not in col_map  # Dept
        assert 7 not in col_map  # Course
        assert 9 not in col_map  # TimeIn

    def test_partial_headers(self):
        headers = ["Lastname", "Gender"]
        col_map = _build_column_map(headers)
        assert col_map[0] == "lastname"
        assert col_map[1] == "gender"

    def test_empty_headers(self):
        col_map = _build_column_map([None, "", None])
        assert col_map == {}


class TestRowToStudent:
    def test_basic_row(self):
        col_map = {2: "lastname", 3: "firstname", 4: "middlename", 5: "extension", 8: "gender"}
        row = ["1", "2021-001", "Dela Cruz", "Juan", "Santos", "", "CCS", "BSIT", "M", "08:00"]
        student = _row_to_student(row, col_map)
        assert student.lastname == "Dela Cruz"
        assert student.firstname == "Juan"
        assert student.middlename == "Santos"
        assert student.extension == ""
        assert student.gender == "M"

    def test_none_values(self):
        col_map = {0: "lastname", 1: "firstname"}
        row = [None, "Ana"]
        student = _row_to_student(row, col_map)
        assert student.lastname == ""
        assert student.firstname == "Ana"

    def test_short_row(self):
        col_map = {0: "lastname", 5: "gender"}
        row = ["Smith"]
        student = _row_to_student(row, col_map)
        assert student.lastname == "Smith"
        assert student.gender == ""


class TestStudentRecord:
    def test_is_empty(self):
        assert StudentRecord().is_empty() is True
        assert StudentRecord(lastname="X").is_empty() is False


# ═══════════════════════════════════════════════════════════════════
# Unit tests — extract_from_pdf (mocked pdfplumber)
# ═══════════════════════════════════════════════════════════════════


class TestExtractFromPdf:
    def test_file_not_found(self):
        result = extract_from_pdf("/nonexistent/file.pdf")
        assert len(result.errors) == 1
        assert "not found" in result.errors[0].lower()

    def test_non_pdf_file(self, tmp_path):
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("hello")
        result = extract_from_pdf(txt_file)
        assert len(result.errors) == 1
        assert "not a pdf" in result.errors[0].lower()

    @patch("extractor.pdfplumber")
    def test_successful_extraction(self, mock_plumber, tmp_path):
        """Simulate a PDF with one table containing student data."""
        # Create a dummy PDF file (just needs to exist)
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 dummy")

        # Mock the pdfplumber chain
        mock_table = [
            ["No", "StudentID", "Lastname", "Firstname", "Middlename", "Extension", "Dept", "Course", "Gender", "TimeIn"],
            ["1", "2021-001", "Dela Cruz", "Juan", "Santos", "", "CCS", "BSIT", "M", "08:00"],
            ["2", "2021-002", "Reyes", "Maria", "Lopez", "Jr.", "CCS", "BSCS", "F", "08:05"],
        ]

        mock_page = MagicMock()
        mock_page.extract_tables.return_value = [mock_table]

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_plumber.open.return_value = mock_pdf

        result = extract_from_pdf(pdf_file)

        assert result.source_file == "test.pdf"
        assert len(result.students) == 2
        assert result.students[0].lastname == "Dela Cruz"
        assert result.students[0].firstname == "Juan"
        assert result.students[0].gender == "M"
        assert result.students[1].lastname == "Reyes"
        assert result.students[1].extension == "Jr."
        assert result.students[1].gender == "F"
        assert len(result.errors) == 0

    @patch("extractor.pdfplumber")
    def test_no_tables_found(self, mock_plumber, tmp_path):
        pdf_file = tmp_path / "empty.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 dummy")

        mock_page = MagicMock()
        mock_page.extract_tables.return_value = []

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_plumber.open.return_value = mock_pdf

        result = extract_from_pdf(pdf_file)
        assert len(result.students) == 0
        assert any("no recognisable" in e.lower() for e in result.errors)

    @patch("extractor.pdfplumber")
    def test_skips_empty_rows(self, mock_plumber, tmp_path):
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 dummy")

        mock_table = [
            ["No", "StudentID", "Lastname", "Firstname", "Middlename", "Extension", "Dept", "Course", "Gender", "TimeIn"],
            ["1", "2021-001", "Cruz", "Ana", "", "", "CCS", "BSIT", "F", "08:00"],
            [None, None, None, None, None, None, None, None, None, None],  # empty row
            ["", "", "", "", "", "", "", "", "", ""],  # blank row
        ]

        mock_page = MagicMock()
        mock_page.extract_tables.return_value = [mock_table]
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_plumber.open.return_value = mock_pdf

        result = extract_from_pdf(pdf_file)
        assert len(result.students) == 1
        assert result.students[0].lastname == "Cruz"


# ═══════════════════════════════════════════════════════════════════
# Unit tests — batch & aggregation
# ═══════════════════════════════════════════════════════════════════


class TestBatchAndAggregate:
    def test_aggregate_students(self):
        results = [
            ExtractionResult(
                source_file="file1.pdf",
                students=[StudentRecord(lastname="A", firstname="B", gender="M")],
            ),
            ExtractionResult(
                source_file="file2.pdf",
                students=[
                    StudentRecord(lastname="C", firstname="D", gender="F"),
                    StudentRecord(lastname="E", firstname="F", gender="M"),
                ],
            ),
        ]
        aggregated = aggregate_students(results)
        assert len(aggregated) == 3
        assert aggregated[0]["source_file"] == "file1.pdf"
        assert aggregated[1]["lastname"] == "C"
        assert aggregated[2]["source_file"] == "file2.pdf"

    def test_aggregate_empty(self):
        assert aggregate_students([]) == []
