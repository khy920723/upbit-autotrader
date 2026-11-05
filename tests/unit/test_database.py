"""SQLite 초기화. 데이터 모델(docs/04-data/data-model.md 3·6장)의 schema_migrations와
PRAGMA user_version 규칙을 따른다. 마이그레이션 파일은 아직 없다(최신 번호 0)."""

import sqlite3
from contextlib import closing

import pytest

from autotrader.core import errors
from autotrader.storage.database import (
    MIN_SQLITE_VERSION,
    SCHEMA_VERSION,
    SchemaVersionError,
    SQLiteVersionError,
    check_sqlite_version,
    initialize_database,
    read_schema_version,
)


def table_names(db_path):
    with closing(sqlite3.connect(db_path)) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {name for (name,) in rows}


def pragma(db_path, name):
    with closing(sqlite3.connect(db_path)) as conn:
        (value,) = conn.execute(f"PRAGMA {name}").fetchone()
    return value


def make_db(db_path, *, user_version, rows=(), journal="delete"):
    """앱이 아닌 다른 버전이 만든 DB를 흉내 낸다."""
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(f"PRAGMA journal_mode = {journal}")
        with conn:
            conn.execute(
                "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL,"
                " applied_at TEXT NOT NULL, app_version TEXT NOT NULL) STRICT"
            )
            conn.executemany("INSERT INTO schema_migrations VALUES (?, ?, ?, ?)", rows)
        conn.execute(f"PRAGMA user_version = {user_version}")


def test_no_migrations_exist_yet():
    assert SCHEMA_VERSION == 0


def test_minimum_sqlite_version_is_for_strict_tables():
    assert MIN_SQLITE_VERSION == (3, 37, 0)


def test_initialize_creates_parent_folder_and_only_the_migrations_table(tmp_path):
    db_path = tmp_path / "data" / "autotrader.db"

    version = initialize_database(db_path)

    assert version == SCHEMA_VERSION
    assert db_path.is_file()
    assert table_names(db_path) == {"schema_migrations"}
    assert pragma(db_path, "user_version") == SCHEMA_VERSION


def test_migrations_table_is_strict_with_the_documented_columns(tmp_path):
    db_path = tmp_path / "autotrader.db"

    initialize_database(db_path)

    with closing(sqlite3.connect(db_path)) as conn:
        (sql,) = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'schema_migrations'"
        ).fetchone()
        columns = [row[1] for row in conn.execute("PRAGMA table_info(schema_migrations)")]
        with pytest.raises(sqlite3.Error):  # STRICT: 정수 열에 문자열을 넣을 수 없다
            conn.execute("INSERT INTO schema_migrations VALUES ('x', 'n', 't', 'v')")
    assert sql.rstrip().endswith("STRICT")
    assert columns == ["version", "name", "applied_at", "app_version"]


def test_initialize_twice_is_harmless(tmp_path):
    db_path = tmp_path / "autotrader.db"

    assert initialize_database(db_path) == initialize_database(db_path) == SCHEMA_VERSION
    assert table_names(db_path) == {"schema_migrations"}


def test_initialize_turns_on_wal_mode(tmp_path):
    db_path = tmp_path / "autotrader.db"

    initialize_database(db_path)

    assert pragma(db_path, "journal_mode") == "wal"


def test_database_from_a_newer_app_is_rejected_and_left_untouched(tmp_path):
    db_path = tmp_path / "autotrader.db"
    newer = SCHEMA_VERSION + 1
    rows = [(newer, f"{newer:04d}_future", "2030-01-01T00:00:00.000Z", "9.9.9")]
    make_db(db_path, user_version=newer, rows=rows)

    with pytest.raises(SchemaVersionError, match=str(newer)):
        initialize_database(db_path)

    assert pragma(db_path, "user_version") == newer
    assert pragma(db_path, "journal_mode") == "delete"
    assert table_names(db_path) == {"schema_migrations"}


def test_user_version_that_disagrees_with_the_migrations_table_is_rejected(tmp_path):
    db_path = tmp_path / "autotrader.db"
    make_db(
        db_path, user_version=0, rows=[(1, "0001_initial", "2030-01-01T00:00:00.000Z", "0.1.0")]
    )

    with pytest.raises(SchemaVersionError, match="user_version"):
        initialize_database(db_path)


def test_read_schema_version_of_an_initialized_database(tmp_path):
    db_path = tmp_path / "autotrader.db"
    initialize_database(db_path)

    assert read_schema_version(db_path) == SCHEMA_VERSION


def test_read_schema_version_of_an_empty_database_is_none(tmp_path):
    db_path = tmp_path / "empty.db"
    sqlite3.connect(db_path).close()

    assert read_schema_version(db_path) is None


def test_read_schema_version_does_not_create_a_missing_file(tmp_path):
    db_path = tmp_path / "missing.db"

    assert read_schema_version(db_path) is None
    assert not db_path.exists()


@pytest.mark.parametrize("version", ["3.37.0", "3.50.4", "3.100.1"])
def test_supported_sqlite_versions(version):
    check_sqlite_version(version)


@pytest.mark.parametrize("version", ["3.36.9", "3.8.11", "2.99.0"])
def test_sqlite_without_strict_tables_is_rejected(version):
    with pytest.raises(SQLiteVersionError, match=r"3\.37\.0"):
        check_sqlite_version(version)


@pytest.mark.parametrize("cls", [SchemaVersionError, SQLiteVersionError], ids=lambda c: c.__name__)
def test_database_errors_are_storage_errors(cls):
    # 시스템 구성도 7장: StorageError(SQLite 오류) > SchemaVersionError.
    assert issubclass(cls, errors.StorageError)
    assert issubclass(cls, errors.AutotraderError)
    assert not issubclass(cls, errors.ExternalError)
