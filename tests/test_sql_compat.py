"""SQL dialect adapters for MySQL."""

from app.storage.sql_compat import adapt_sql_for_mysql


def test_adapt_upsert_and_placeholders() -> None:
    sql = """
        INSERT INTO jobs (id, title) VALUES (:id, :title)
        ON CONFLICT(id) DO UPDATE SET
            title = excluded.title,
            status = CASE WHEN jobs.status IN ('approved') THEN jobs.status ELSE excluded.status END
    """
    out = adapt_sql_for_mysql(sql)
    assert "ON DUPLICATE KEY UPDATE" in out
    assert "_excluded.title" in out
    assert "%(id)s" in out
    assert "?" not in out


def test_adapt_autoincrement_and_now() -> None:
    sql = "CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    out = adapt_sql_for_mysql(sql)
    assert "AUTO_INCREMENT" in out
    assert "UTC_TIMESTAMP()" in out
    assert "datetime('now')" not in out
