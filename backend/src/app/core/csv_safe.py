"""Neutralize CSV/spreadsheet formula injection in exported cells.

A value beginning with one of these characters is interpreted as a formula by
Excel/LibreOffice/Sheets, so a string that reaches a CSV from request-derived data
could execute when an admin opens the export. Prefixing with a single quote forces
the cell to be treated as text.
"""

from typing import Any

_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def sanitize_csv_cell(value: Any) -> Any:
    if isinstance(value, str) and value and value[0] in _FORMULA_TRIGGERS:
        return "'" + value
    return value
