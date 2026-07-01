"""Neutralize CSV/spreadsheet formula injection in exported cells.

A value beginning with one of these characters is interpreted as a formula by
Excel/LibreOffice/Sheets, so a string that reaches a CSV from request-derived data
could execute when an admin opens the export. Prefixing with a single quote forces
the cell to be treated as text.
"""

import csv
from collections.abc import Iterable, Iterator
from io import StringIO
from typing import Any

CSV_EXPORT_MAX_ROWS = 10_000
_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def sanitize_csv_cell(value: Any) -> Any:
    if isinstance(value, str) and value and value[0] in _FORMULA_TRIGGERS:
        return "'" + value
    return value


def stream_csv_rows(
    *,
    header: Iterable[object],
    rows: Iterable[Iterable[object]],
) -> Iterator[str]:
    yield _serialize_csv_row(header)
    for row in rows:
        yield _serialize_csv_row(sanitize_csv_cell(cell) for cell in row)


def _serialize_csv_row(row: Iterable[object]) -> str:
    output = StringIO()
    csv.writer(output).writerow(row)
    return output.getvalue()
