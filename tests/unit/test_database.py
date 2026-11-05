import sqlite3
from contextlib import closing
from datetime import datetime, timedelta

import pytest

from autotrader.storage.database import (
    SCHEMA_VERSION,
    SchemaVersionError,
    initialize_database,
    read_schema_version,
)


def table_names(db_path):
    with closing(sqlite3.connect(db_path)) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {name for (name,) in rows}


def schema_rows(db_path):
    with closing(sqlite3.connect(db_path)) as conn:
        return conn.execute("SELECT version, applied_at FROM schema_version").fetchall()


def test_first_schema_version_is_one():
    assert SCHEMA_VERSION == 1


def test_initialize_creates_parent_folder_and_only_the_schema_version_table(tmp_path):
    db_path = tmp_path / "data" / "autotrader.db"

    version = initialize_database(db_path)

    assert version == SCHEMA_VERSION
    assert db_path.is_file()
    assert table_names(db_path) == {"schema_version"}


def test_initialize_records_version_with_utc_iso8601_time(tmp_path):
    db_path = tmp_path / "autotrader.db"

    initialize_database(db_path)

    [(version, applied_at)] = schema_rows(db_path)
    assert version == SCHEMA_VERSION
    assert datetime.fromisoformat(applied_at).utcoffset() == timedelta(0)


def test_initialize_twice_keeps_a_single_row(tmp_path):
    db_path = tmp_path / "autotrader.db"

    initialize_database(db_path)
    initialize_database(db_path)

    assert len(schema_rows(db_path)) == 1


def test_initialize_turns_on_wal_mode(tmp_path):
    db_path = tmp_path / "autotrader.db"

    initialize_database(db_path)

    with closing(sqlite3.connect(db_path)) as conn:
        (mode,) = conn.execute("PRAGMA journal_mode").fetchone()
    assert mode == "wal"


def test_database_from_a_newer_app_is_rejected_and_left_untouched(tmp_path):
    db_path = tmp_path / "autotrader.db"
    newer = (SCHEMA_VERSION + 1, "2030-01-01T00:00:00+00:00")
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (?, ?)", newer)

    with pytest.raises(SchemaVersionError, match=str(SCHEMA_VERSION + 1)):
        initialize_database(db_path)

    assert schema_rows(db_path) == [newer]
    with closing(sqlite3.connect(db_path)) as conn:
        (mode,) = conn.execute("PRAGMA journal_mode").fetchone()
    assert mode == "delete"


def test_read_schema_version_of_an_empty_database_is_none(tmp_path):
    db_path = tmp_path / "empty.db"
    sqlite3.connect(db_path).close()

    assert read_schema_version(db_path) is None


def test_read_schema_version_does_not_create_a_missing_file(tmp_path):
    db_path = tmp_path / "missing.db"

    assert read_schema_version(db_path) is None
    assert not db_path.exists()
