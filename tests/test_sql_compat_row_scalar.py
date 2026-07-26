"""Helpers for MySQL DictCursor vs sqlite3.Row access."""

from app.storage.sql_compat import row_scalar


def test_row_scalar_dict_count() -> None:
    assert row_scalar({"COUNT(*)": 4}) == 4
    assert row_scalar({"c": 7}, key="c") == 7


def test_row_scalar_sequence() -> None:
    assert row_scalar((9,)) == 9
