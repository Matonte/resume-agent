"""DB backend: SQLite (local/tests) or MySQL (RDS via DATABASE_URL).

When ``DATABASE_URL`` / ``MYSQL_HOST`` is set, structured app data uses MySQL.
Uploaded files, Playwright profiles, and DOCX artifacts stay on disk (``OUTPUTS_DIR``).
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator, Optional, Sequence, Union
from urllib.parse import unquote, urlparse

from app.config import settings

Params = Union[Sequence[Any], dict[str, Any], None]


def row_scalar(row: Any, *, key: Optional[str] = None) -> Any:
    """First column of a query row — works for sqlite3.Row and MySQL DictCursor dicts."""
    if row is None:
        return None
    if isinstance(row, dict):
        if key is not None and key in row:
            return row[key]
        # Prefer common aliases before falling back to insertion order.
        for alias in ("c", "count", "COUNT(*)", key):
            if alias and alias in row:
                return row[alias]
        return next(iter(row.values()), None)
    if key is not None and hasattr(row, "keys") and key in row.keys():
        return row[key]
    try:
        return row[0]
    except (KeyError, IndexError, TypeError):
        if hasattr(row, "keys"):
            keys = list(row.keys())
            if keys:
                return row[keys[0]]
        raise


def use_mysql() -> bool:
    url = (settings.database_url or "").strip()
    if url.startswith("mysql"):
        return True
    return bool((settings.mysql_host or "").strip())


def _mysql_connect_kwargs() -> dict[str, Any]:
    url = (settings.database_url or "").strip()
    if url.startswith("mysql"):
        # mysql+pymysql://user:pass@host:3306/db
        parsed = urlparse(url.replace("mysql+pymysql://", "mysql://", 1))
        return {
            "host": parsed.hostname or "127.0.0.1",
            "port": parsed.port or 3306,
            "user": unquote(parsed.username or ""),
            "password": unquote(parsed.password or ""),
            "database": (parsed.path or "/").lstrip("/") or "resume_agent",
            "charset": "utf8mb4",
            "autocommit": False,
        }
    return {
        "host": settings.mysql_host,
        "port": int(settings.mysql_port or 3306),
        "user": settings.mysql_user,
        "password": settings.mysql_password,
        "database": settings.mysql_database or "resume_agent",
        "charset": "utf8mb4",
        "autocommit": False,
    }


def adapt_sql_for_mysql(sql: str) -> str:
    """Best-effort SQLite → MySQL dialect rewrite for this codebase's SQL."""
    s = sql
    s = s.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "INT AUTO_INCREMENT PRIMARY KEY")
    s = s.replace("AUTOINCREMENT", "AUTO_INCREMENT")
    # MySQL cannot index unbounded TEXT as PRIMARY KEY without a prefix length.
    s = re.sub(
        r"\bTEXT\s+PRIMARY\s+KEY\b",
        "VARCHAR(191) PRIMARY KEY",
        s,
        flags=re.IGNORECASE,
    )
    # Timestamp columns before generic TEXT rewrite.
    s = re.sub(
        r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s+TEXT\b([^,)]*?)\s+DEFAULT\s*\(\s*datetime\('now'\)\s*\)",
        r"\1 DATETIME\2 DEFAULT CURRENT_TIMESTAMP",
        s,
        flags=re.IGNORECASE,
    )
    # BLOB/TEXT cannot take literal string DEFAULTs under MySQL strict mode (error 1101).
    s = re.sub(
        r"\b(TEXT|BLOB|MEDIUMTEXT|LONGTEXT)\b([^,)]*?)\s+DEFAULT\s+(?:'[^']*'|\"[^\"]*\")",
        r"\1\2",
        s,
        flags=re.IGNORECASE,
    )
    # MySQL has no CREATE INDEX IF NOT EXISTS (unlike MariaDB); ignore 1061 instead.
    s = re.sub(
        r"CREATE\s+INDEX\s+IF\s+NOT\s+EXISTS\s+",
        "CREATE INDEX ",
        s,
        flags=re.IGNORECASE,
    )
    # Map remaining short TEXT → VARCHAR; keep long content as MEDIUMTEXT.
    _long_text = {
        "jd_full",
        "screening_json",
        "embedding_json",
        "extra_json",
        "text",
        "error",
        "data",
    }

    def _rewrite_text_col(match: re.Match[str]) -> str:
        col = match.group(1)
        rest = match.group(2) or ""
        if col.lower() in _long_text:
            return f"{col} MEDIUMTEXT{rest}"
        return f"{col} VARCHAR(191){rest}"

    s = re.sub(
        r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s+TEXT\b([^,)]*)",
        _rewrite_text_col,
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"DEFAULT\s*\(\s*datetime\('now'\)\s*\)",
        "DEFAULT CURRENT_TIMESTAMP",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"\bdatetime\('now'\)", "UTC_TIMESTAMP()", s, flags=re.IGNORECASE)
    # SQLite UPSERT → MySQL
    if "ON CONFLICT" in s.upper():
        s = re.sub(
            r"ON CONFLICT\s*\(\s*(\w+)\s*\)\s*DO UPDATE SET",
            "AS _excluded ON DUPLICATE KEY UPDATE",
            s,
            flags=re.IGNORECASE,
        )
        s = re.sub(r"\bexcluded\.", "_excluded.", s)
    # Positional placeholders
    s = s.replace("?", "%s")
    # Named :param → %(param)s (avoid matching ::)
    s = re.sub(r"(?<!:):([a-zA-Z_][a-zA-Z0-9_]*)", r"%(\1)s", s)
    return s


class _MysqlCursorProxy:
    def __init__(self, cur: Any) -> None:
        self._cur = cur

    def fetchone(self) -> Any:
        return self._cur.fetchone()

    def fetchall(self) -> Any:
        return self._cur.fetchall()

    @property
    def lastrowid(self) -> Any:
        return self._cur.lastrowid

    @property
    def rowcount(self) -> Any:
        return self._cur.rowcount


class MysqlConnectionProxy:
    """Thin proxy so call sites can keep using sqlite-style ``?`` / ``:name`` SQL."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def execute(self, sql: str, params: Params = None) -> _MysqlCursorProxy:
        adapted = adapt_sql_for_mysql(sql)
        cur = self._conn.cursor()
        if params is None:
            cur.execute(adapted)
        else:
            cur.execute(adapted, params)
        return _MysqlCursorProxy(cur)

    def executescript(self, script: str) -> None:
        # Strip SQLite-only PRAGMA lines; split on semicolons.
        parts = []
        for stmt in script.split(";"):
            chunk = stmt.strip()
            if not chunk or chunk.upper().startswith("PRAGMA"):
                continue
            parts.append(adapt_sql_for_mysql(chunk))
        cur = self._conn.cursor()
        for stmt in parts:
            try:
                cur.execute(stmt)
            except Exception as exc:  # noqa: BLE001
                # 1050 table exists, 1061 duplicate key name, 1060 duplicate column
                code = getattr(exc, "args", [None])[0]
                if code in (1050, 1060, 1061):
                    continue
                raise

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()

    def cursor(self) -> Any:
        return self._conn.cursor()


def mysql_table_columns(conn: MysqlConnectionProxy, table: str) -> set[str]:
    cur = conn.execute(
        """
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
        """,
        (table,),
    )
    rows = cur.fetchall() or []
    out: set[str] = set()
    for r in rows:
        if isinstance(r, dict):
            out.add(str(r.get("COLUMN_NAME") or r.get("column_name") or ""))
        else:
            out.add(str(r[0]))
    return {c for c in out if c}


@contextmanager
def connect_sqlite(path: str) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def connect_mysql() -> Iterator[MysqlConnectionProxy]:
    try:
        import pymysql
        from pymysql.cursors import DictCursor
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "PyMySQL is required for DATABASE_URL/MySQL. pip install PyMySQL"
        ) from exc

    raw = pymysql.connect(cursorclass=DictCursor, **_mysql_connect_kwargs())
    proxy = MysqlConnectionProxy(raw)
    try:
        yield proxy
    finally:
        proxy.close()


__all__ = [
    "use_mysql",
    "adapt_sql_for_mysql",
    "row_scalar",
    "MysqlConnectionProxy",
    "mysql_table_columns",
    "connect_sqlite",
    "connect_mysql",
]
