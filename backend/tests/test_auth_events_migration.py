import sqlite3

import pytest

from migrations.add_auth_events import (
    _TABLES,
    _has_exact_unique_index,
    upgrade_database,
)


def _create_legacy_database(path):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE datasets (
            id VARCHAR NOT NULL PRIMARY KEY,
            name VARCHAR,
            status VARCHAR,
            uploaded_at DATETIME
        );
        CREATE TABLE repair_records (
            id VARCHAR NOT NULL PRIMARY KEY,
            dataset_id VARCHAR NOT NULL,
            finding_id VARCHAR,
            operation_type VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            input_file_sha256 VARCHAR NOT NULL,
            affected_rows INTEGER NOT NULL,
            operation_metadata JSON
        );
        """
    )
    connection.execute(
        "INSERT INTO datasets (id, name, status) VALUES (?, ?, ?)",
        ("legacy-dataset", "Legacy", "Analyzed"),
    )
    connection.executemany(
        """
        INSERT INTO repair_records
            (id, dataset_id, operation_type, status, input_file_sha256,
             affected_rows, operation_metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                f"legacy-operation-{index}",
                "legacy-dataset",
                "repair",
                "completed",
                f"{index:064x}",
                index,
                '{"existing":"metadata"}' if index == 0 else None,
            )
            for index in range(14)
        ],
    )
    connection.commit()
    connection.close()


def test_auth_events_migration_preserves_legacy_rows_and_is_idempotent(tmp_path):
    database = tmp_path / "legacy.sqlite"
    _create_legacy_database(database)

    before = sqlite3.connect(database)
    repair_rows_before = before.execute(
        """
        SELECT id, dataset_id, finding_id, operation_type, status,
               input_file_sha256, affected_rows, operation_metadata
        FROM repair_records ORDER BY id
        """
    ).fetchall()
    before.close()

    assert upgrade_database(database) is True
    assert upgrade_database(database) is False

    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {"datasets", "repair_records", "users", "auth_sessions",
            "audit_events", "notifications"} <= tables

    owner_column = {
        row[1]: row
        for row in connection.execute("PRAGMA table_info(datasets)")
    }["owner_user_id"]
    assert owner_column[2].upper() == "VARCHAR"
    assert owner_column[3] == 0  # nullable
    assert owner_column[4] is None  # no default or legacy-owner assignment

    assert connection.execute("SELECT COUNT(*) FROM datasets").fetchone() == (1,)
    assert connection.execute(
        "SELECT id, name, status, owner_user_id FROM datasets"
    ).fetchall() == [("legacy-dataset", "Legacy", "Analyzed", None)]
    assert connection.execute("SELECT COUNT(*) FROM repair_records").fetchone() == (14,)
    assert connection.execute(
        """
        SELECT id, dataset_id, operation_type, status, input_file_sha256,
               affected_rows, operation_metadata
        FROM repair_records ORDER BY id
        """
    ).fetchall()[0] == (
        "legacy-operation-0",
        "legacy-dataset",
        "repair",
        "completed",
        f"{0:064x}",
        0,
        '{"existing":"metadata"}',
    )
    assert connection.execute(
        "SELECT COUNT(*) FROM repair_records WHERE operation_metadata IS NULL"
    ).fetchone() == (13,)
    assert connection.execute(
        """
        SELECT id, dataset_id, finding_id, operation_type, status,
               input_file_sha256, affected_rows, operation_metadata
        FROM repair_records ORDER BY id
        """
    ).fetchall() == repair_rows_before
    connection.close()


def test_auth_events_migration_rejects_missing_database_or_datasets_table(tmp_path):
    missing = tmp_path / "missing.sqlite"
    try:
        upgrade_database(missing)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("migration must not create a missing database")
    assert not missing.exists()

    no_datasets = tmp_path / "without-datasets.sqlite"
    sqlite3.connect(no_datasets).close()
    try:
        upgrade_database(no_datasets)
    except RuntimeError as error:
        assert "datasets" in str(error)
    else:
        raise AssertionError("migration must require the datasets table")


def test_auth_events_migration_completes_a_valid_partial_schema(tmp_path):
    database = tmp_path / "partially-migrated.sqlite"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE datasets (
            id VARCHAR NOT NULL PRIMARY KEY,
            owner_user_id VARCHAR REFERENCES users(id)
        );
        CREATE TABLE users (
            id VARCHAR NOT NULL PRIMARY KEY,
            email VARCHAR NOT NULL UNIQUE,
            display_name VARCHAR NOT NULL,
            password_hash VARCHAR NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    connection.commit()
    connection.close()

    assert upgrade_database(database) is True
    assert upgrade_database(database) is False
    connection = sqlite3.connect(database)
    assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert connection.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='notifications'"
    ).fetchone() == (1,)
    connection.close()


def test_incompatible_existing_schema_fails_without_partial_ddl(tmp_path):
    database = tmp_path / "incompatible.sqlite"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE datasets (id VARCHAR NOT NULL PRIMARY KEY);
        CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT);
        """
    )
    connection.commit()
    tables_before = connection.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    columns_before = connection.execute("PRAGMA table_info(datasets)").fetchall()
    connection.close()

    try:
        upgrade_database(database)
    except RuntimeError as error:
        assert "Incompatible schema" in str(error)
    else:
        raise AssertionError("incompatible existing schema must be rejected")

    connection = sqlite3.connect(database)
    assert connection.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall() == tables_before
    assert connection.execute("PRAGMA table_info(datasets)").fetchall() == columns_before
    assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    connection.close()


@pytest.mark.parametrize(
    ("index_sql", "expected"),
    [
        ("CREATE UNIQUE INDEX idx_exact ON items (deduplication_key)", True),
        (
            "CREATE UNIQUE INDEX idx_partial ON items (deduplication_key) "
            "WHERE deduplication_key IS NOT NULL",
            False,
        ),
        (
            "CREATE UNIQUE INDEX idx_composite "
            "ON items (deduplication_key, event_type)",
            False,
        ),
        ("CREATE INDEX idx_non_unique ON items (deduplication_key)", False),
        ("CREATE UNIQUE INDEX idx_other ON items (event_type)", False),
        (None, False),
    ],
)
def test_deduplication_requires_an_exact_single_column_unique_index(
    tmp_path, index_sql, expected
):
    database = tmp_path / "index-contract.sqlite"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE items (deduplication_key VARCHAR, event_type VARCHAR)"
    )
    if index_sql:
        connection.execute(index_sql)

    assert _has_exact_unique_index(connection, "items", "deduplication_key") is expected
    connection.close()


@pytest.mark.parametrize("table_name", ["audit_events", "notifications"])
def test_composite_deduplication_index_rejects_migration_and_rolls_back(
    tmp_path, table_name
):
    database = tmp_path / f"composite-{table_name}.sqlite"
    connection = sqlite3.connect(database)
    connection.execute(_TABLES["users"])
    connection.execute(
        """
        CREATE TABLE datasets (
            id VARCHAR NOT NULL PRIMARY KEY,
            name VARCHAR
        )
        """
    )
    connection.execute(
        "INSERT INTO datasets (id, name) VALUES ('legacy-dataset', 'Legacy')"
    )
    connection.execute(
        """
        CREATE TABLE repair_records (
            id VARCHAR NOT NULL PRIMARY KEY,
            dataset_id VARCHAR NOT NULL,
            operation_type VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            input_file_sha256 VARCHAR NOT NULL,
            affected_rows INTEGER NOT NULL,
            operation_metadata JSON
        )
        """
    )
    connection.execute(
        """
        INSERT INTO repair_records
            (id, dataset_id, operation_type, status, input_file_sha256,
             affected_rows, operation_metadata)
        VALUES ('legacy-operation', 'legacy-dataset', 'repair', 'completed',
                ?, 2, '{"preserve":true}')
        """,
        ("a" * 64,),
    )

    if table_name == "audit_events":
        connection.execute(
            """
            CREATE TABLE audit_events (
                id VARCHAR NOT NULL PRIMARY KEY,
                user_id VARCHAR NOT NULL REFERENCES users(id),
                dataset_id VARCHAR,
                finding_id VARCHAR,
                operation_id VARCHAR,
                event_type VARCHAR NOT NULL,
                outcome VARCHAR NOT NULL,
                details JSON,
                deduplication_key VARCHAR,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (deduplication_key, event_type)
            )
            """
        )
    else:
        connection.execute(
            """
            CREATE TABLE notifications (
                id VARCHAR NOT NULL PRIMARY KEY,
                user_id VARCHAR NOT NULL REFERENCES users(id),
                event_type VARCHAR NOT NULL,
                title VARCHAR NOT NULL,
                message TEXT NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                read_at DATETIME,
                dataset_id VARCHAR,
                finding_id VARCHAR,
                operation_id VARCHAR,
                deduplication_key VARCHAR,
                UNIQUE (deduplication_key, event_type)
            )
            """
        )
    connection.commit()

    schema_before = connection.execute(
        """
        SELECT type, name, tbl_name, sql FROM sqlite_master
        WHERE type IN ('table', 'index') ORDER BY type, name
        """
    ).fetchall()
    datasets_before = connection.execute(
        "SELECT id, name FROM datasets"
    ).fetchall()
    operations_before = connection.execute(
        "SELECT id, dataset_id, operation_metadata FROM repair_records"
    ).fetchall()
    connection.close()

    with pytest.raises(RuntimeError, match="Missing unique constraints"):
        upgrade_database(database)

    connection = sqlite3.connect(database)
    assert connection.execute(
        """
        SELECT type, name, tbl_name, sql FROM sqlite_master
        WHERE type IN ('table', 'index') ORDER BY type, name
        """
    ).fetchall() == schema_before
    assert connection.execute(
        "SELECT id, name FROM datasets"
    ).fetchall() == datasets_before
    assert connection.execute(
        "SELECT id, dataset_id, operation_metadata FROM repair_records"
    ).fetchall() == operations_before
    assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    connection.close()
