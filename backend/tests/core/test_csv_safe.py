import csv
from io import StringIO

from app.core.csv_safe import stream_csv_rows


def test_stream_csv_rows_serializes_generator_one_row_at_a_time() -> None:
    consumed: list[str] = []

    def rows():
        consumed.append("first")
        yield ["=SUM(A1)", "value,with,commas"]
        consumed.append("second")
        yield ["line\nbreak", 42]

    stream = stream_csv_rows(header=["name", "value"], rows=rows())

    assert next(stream) == "name,value\r\n"
    assert consumed == []
    assert next(stream) == "'=SUM(A1),\"value,with,commas\"\r\n"
    assert consumed == ["first"]

    remaining = "".join(stream)
    assert consumed == ["first", "second"]
    assert list(csv.reader(StringIO(remaining))) == [["line\nbreak", "42"]]
