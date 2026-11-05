"""SQLite 초기화. 지금은 스키마 버전 표만 만든다.

DB 접근 방식(직접 SQL 또는 경량 ORM)과 마이그레이션 방법은 1단계 설계에서 정한다.
그때 SCHEMA_VERSION을 올리고 버전별 마이그레이션을 여기에 더한다.
"""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 1

_CREATE_SCHEMA_VERSION = """
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT    NOT NULL
)
"""


class SchemaVersionError(RuntimeError):
    """DB가 이 앱이 아는 것보다 새 스키마다(새 버전 앱이 만든 DB)."""


def initialize_database(path: Path) -> int:
    """DB 파일을 열어(없으면 만들어) WAL 모드와 스키마 버전 표를 준비하고 현재 버전을 돌려준다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn:
        current = _current_version(conn)
        if current is not None and current > SCHEMA_VERSION:
            raise SchemaVersionError(
                f"DB 스키마 버전 {current}은 이 앱이 아는 버전({SCHEMA_VERSION})보다 높습니다. "
                "새 버전 앱이 만든 DB이므로 건드리지 않습니다."
            )
        conn.execute("PRAGMA journal_mode = WAL")
        if current is None:
            with conn:
                conn.execute(_CREATE_SCHEMA_VERSION)
                conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, datetime.now(UTC).isoformat(timespec="seconds")),
                )
            current = SCHEMA_VERSION
        return current


def read_schema_version(path: Path) -> int | None:
    """기록된 스키마 버전. 파일이나 표가 없으면 None. 파일을 만들거나 바꾸지 않는다."""
    if not path.is_file():
        return None
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as conn:
        return _current_version(conn)


def _current_version(conn: sqlite3.Connection) -> int | None:
    has_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'"
    ).fetchone()
    if not has_table:
        return None
    (version,) = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return version
