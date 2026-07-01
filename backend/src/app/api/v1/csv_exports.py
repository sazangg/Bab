from collections.abc import Sequence

from fastapi import HTTPException, status

from app.core.csv_safe import CSV_EXPORT_MAX_ROWS


def require_export_within_limit(rows: Sequence[object]) -> None:
    if len(rows) > CSV_EXPORT_MAX_ROWS:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="export exceeds 10000 rows; narrow the filters",
        )
