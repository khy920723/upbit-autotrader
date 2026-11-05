"""SQLite 초기화.

데이터 모델(docs/04-data/data-model.md 3·6장, D-041 대기)을 따른다: 적용한 마이그레이션은
`schema_migrations` 표와 `PRAGMA user_version`에 함께 기록하고, 테이블은 STRICT로 만든다.
마이그레이션 파일(`storage/migrations/0001_initial.sql` 등)과 적용 절차는 이후 단계에서 더한다.
지금은 기록용 표만 만들고 최신 번호는 0이다.
"""

import sqlite3
from contextlib import closing
from pathlib import Path

SCHEMA_VERSION = 0
"""앱이 아는 최신 마이그레이션 번호. 마이그레이션이 없으면 0."""

MIN_SQLITE_VERSION = (3, 37, 0)
"""STRICT 테이블을 쓰려면 SQLite 3.37.0 이상이 필요하다."""

_CREATE_SCHEMA_MIGRATIONS = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    applied_at  TEXT    NOT NULL,
    app_version TEXT    NOT NULL
) STRICT
"""


class SchemaVersionError(RuntimeError):
    """DB 스키마 기록이 이 앱과 맞지 않는다(새 버전 앱이 만든 DB, 또는 기록이 서로 다름)."""


class SQLiteVersionError(RuntimeError):
    """SQLite가 STRICT 테이블을 지원하지 않는다."""


def check_sqlite_version(version: str = sqlite3.sqlite_version) -> None:
    """SQLite 라이브러리 버전이 MIN_SQLITE_VERSION 이상인지 확인한다."""
    parts = tuple(int(part) for part in version.split(".")[:3])
    if parts < MIN_SQLITE_VERSION:
        minimum = ".".join(map(str, MIN_SQLITE_VERSION))
        raise SQLiteVersionError(
            f"SQLite {version}은 STRICT 테이블을 지원하지 않습니다({minimum} 이상 필요)."
        )


def initialize_database(path: Path) -> int:
    """DB 파일을 열어(없으면 만들어) WAL 모드와 schema_migrations 표를 준비한다.

    돌려주는 값은 스키마 번호(user_version)다.
    """
    check_sqlite_version()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn:
        current = _user_version(conn)
        if current > SCHEMA_VERSION:
            raise SchemaVersionError(
                f"DB 스키마 번호 {current}은 이 앱이 아는 번호({SCHEMA_VERSION})보다 높습니다. "
                "새 버전 앱이 만든 DB이므로 건드리지 않습니다."
            )
        recorded = _latest_recorded(conn)
        if recorded is not None and recorded != current:
            raise SchemaVersionError(
                f"schema_migrations의 최신 번호({recorded})와 user_version({current})이 다릅니다."
            )
        conn.execute("PRAGMA journal_mode = WAL")
        with conn:
            conn.execute(_CREATE_SCHEMA_MIGRATIONS)
        return current


def read_schema_version(path: Path) -> int | None:
    """스키마 번호(user_version). 파일이나 schema_migrations 표가 없으면 None.

    파일을 만들거나 바꾸지 않는다.
    """
    if not path.is_file():
        return None
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as conn:
        if not _has_migrations_table(conn):
            return None
        return _user_version(conn)


def _user_version(conn: sqlite3.Connection) -> int:
    (version,) = conn.execute("PRAGMA user_version").fetchone()
    return version


def _has_migrations_table(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    return row is not None


def _latest_recorded(conn: sqlite3.Connection) -> int | None:
    """schema_migrations의 최신 번호. 표가 없으면 None, 비어 있으면 0."""
    if not _has_migrations_table(conn):
        return None
    (version,) = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
    return version
