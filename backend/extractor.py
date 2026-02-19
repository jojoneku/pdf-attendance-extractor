"""
PDF Attendance Table Extractor.

Uses pdfplumber to extract student attendance data from PDF files
containing structured tables. Supports flexible column matching
by header text (case-insensitive, partial match).
"""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

# ---------------------------------------------------------------------------
# Target columns we want to extract (lowercase normalised forms)
# ---------------------------------------------------------------------------
DEFAULT_COLUMNS: dict[str, list[str]] = {
    "lastname": ["lastname", "last name", "last_name", "surname"],
    "firstname": ["firstname", "first name", "first_name", "given name"],
    "middlename": ["middlename", "middle name", "middle_name", "mi", "m.i."],
    "extension": ["extension", "ext", "ext.", "name extension", "suffix"],
    "gender": ["gender", "sex"],
}

# Module-level alias kept so existing tests referencing TARGET_COLUMNS still work
TARGET_COLUMNS = DEFAULT_COLUMNS


@dataclass
class StudentRecord:
    """A single extracted student row."""

    lastname: str = ""
    firstname: str = ""
    middlename: str = ""
    extension: str = ""
    gender: str = ""

    def is_empty(self) -> bool:
        """Return True if all fields are blank."""
        return not any([self.lastname, self.firstname, self.middlename, self.extension, self.gender])


@dataclass
class ExtractionResult:
    """Result of extracting one PDF file."""

    source_file: str
    students: list[StudentRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalise(text: str | None) -> str:
    """Lowercase, strip whitespace, collapse inner spaces."""
    if text is None:
        return ""
    return " ".join(str(text).lower().split())


def _match_column(header: str, columns: dict[str, list[str]] | None = None) -> str | None:
    """
    Try to match a table header cell to one of our target columns.

    Returns the canonical column name (e.g. "lastname") or None.
    """
    h = _normalise(header)
    if not h:
        return None
    target = columns or DEFAULT_COLUMNS
    for canonical, variants in target.items():
        for v in variants:
            if v in h or h in v:
                return canonical
    return None


def _build_column_map(headers: list[str | None], columns: dict[str, list[str]] | None = None) -> dict[int, str]:
    """
    Given a list of raw header strings from a PDF table row,
    return a mapping of column-index → canonical field name.
    """
    col_map: dict[int, str] = {}
    for idx, raw in enumerate(headers):
        match = _match_column(raw if raw else "", columns)
        if match and match not in col_map.values():
            col_map[idx] = match
    return col_map


def _row_to_student(row: list[str | None], col_map: dict[int, str]) -> StudentRecord:
    """Convert a table data row to a StudentRecord using the column map."""
    fields: dict[str, str] = {}
    for idx, canonical in col_map.items():
        val = row[idx] if idx < len(row) else None
        fields[canonical] = str(val).strip() if val else ""
    return StudentRecord(**fields)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_from_pdf(
    file_path: str | Path,
    columns: dict[str, list[str]] | None = None,
) -> ExtractionResult:
    """
    Extract student attendance records from a single PDF file.

    Args:
        file_path: Path to the PDF file.
        columns: Optional custom column mapping overriding DEFAULT_COLUMNS.
                 Keys are canonical names (lastname, firstname, …), values
                 are lists of header text variants to match against.

    Returns:
        ExtractionResult containing extracted students and any errors.
    """
    file_path = Path(file_path)
    result = ExtractionResult(source_file=file_path.name)

    if not file_path.exists():
        result.errors.append(f"File not found: {file_path}")
        return result

    if not file_path.suffix.lower() == ".pdf":
        result.errors.append(f"Not a PDF file: {file_path.name}")
        return result

    try:
        with pdfplumber.open(file_path) as pdf:
            if not pdf.pages:
                result.errors.append(f"PDF has no pages: {file_path.name}")
                return result

            col_map: dict[int, str] | None = None

            for page in pdf.pages:
                tables = page.extract_tables()
                if not tables:
                    continue

                for table in tables:
                    if not table or len(table) < 2:
                        continue

                    # First row of the table is treated as headers
                    if col_map is None:
                        col_map = _build_column_map(table[0], columns)
                        if not col_map:
                            # Try second row in case first row is a title
                            if len(table) > 2:
                                col_map = _build_column_map(table[1], columns)
                                if col_map:
                                    # Data starts from row index 2
                                    data_rows = table[2:]
                                else:
                                    continue
                            else:
                                continue
                        else:
                            data_rows = table[1:]
                    else:
                        # Subsequent tables on other pages — skip header row
                        # Check if first row looks like headers again
                        test_map = _build_column_map(table[0], columns)
                        if test_map and len(test_map) >= 2:
                            data_rows = table[1:]
                        else:
                            data_rows = table

                    for row in data_rows:
                        if not row or all(cell is None or str(cell).strip() == "" for cell in row):
                            continue
                        student = _row_to_student(row, col_map)
                        if not student.is_empty():
                            result.students.append(student)

            if col_map is None:
                result.errors.append(f"No recognisable attendance table found in: {file_path.name}")

    except Exception as e:
        result.errors.append(f"Error processing {file_path.name}: {str(e)}")

    return result


def extract_batch(
    file_paths: list[str | Path],
    columns: dict[str, list[str]] | None = None,
) -> list[ExtractionResult]:
    """
    Extract student records from multiple PDF files in parallel.

    Uses a process pool to parse PDFs concurrently, which is significantly
    faster for large batches since pdfplumber is CPU-bound.

    Args:
        file_paths: List of paths to PDF files.
        columns: Optional custom column mapping (forwarded to extract_from_pdf).

    Returns:
        List of ExtractionResult, one per file (order preserved).
    """
    if len(file_paths) <= 1:
        return [extract_from_pdf(fp, columns) for fp in file_paths]

    # Cap workers to file count or CPU count (whichever is smaller)
    max_workers = min(len(file_paths), os.cpu_count() or 4)
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        # functools.partial would work, but a simple wrapper is clearer
        import functools
        _extract = functools.partial(extract_from_pdf, columns=columns)
        results = list(executor.map(_extract, file_paths))
    return results


def aggregate_students(results: list[ExtractionResult]) -> list[dict]:
    """
    Flatten all extraction results into a single list of dicts,
    including the source filename for each record.

    Args:
        results: List of ExtractionResult from batch extraction.

    Returns:
        List of dicts with keys: lastname, firstname, middlename,
        extension, gender, source_file.
    """
    aggregated: list[dict] = []
    for result in results:
        for student in result.students:
            aggregated.append({
                "lastname": student.lastname,
                "firstname": student.firstname,
                "middlename": student.middlename,
                "extension": student.extension,
                "gender": student.gender,
                "source_file": result.source_file,
            })
    return aggregated
