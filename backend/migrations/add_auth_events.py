"""Forward-only SQLite migration for users, sessions, events, notifications.

Run explicitly after backup verification:

    python -m migrations.add_auth_events --database .\\test.db

This script never creates a missing database and does not assign legacy
datasets to users. It is safe to rerun when its schema is already present.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


_TABLES = {
    "users": """
        CREATE TABLE users (
            id VARCHAR NOT NULL PRIMARY KEY,
            email VARCHAR NOT NULL UNIQUE,
            display_name VARCHAR NOT NULL,
            password_hash VARCHAR NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """,
    "auth_sessions": """
        CREATE TABLE auth_sessions (
            id VARCHAR NOT NULL PRIMARY KEY,
            user_id VARCHAR NOT NULL REFERENCES users(id),
            token_hash VARCHAR NOT NULL UNIQUE,
            csrf_token_hash VARCHAR NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at DATETIME NOT NULL,
            revoked_at DATETIME
        )
    """,
    "audit_events": """
        CREATE TABLE audit_events (
            id VARCHAR NOT NULL PRIMARY KEY,
            user_id VARCHAR NOT NULL REFERENCES users(id),
            dataset_id VARCHAR,
            finding_id VARCHAR,
            operation_id VARCHAR,
            event_type VARCHAR NOT NULL,
            outcome VARCHAR NOT NULL,
            details JSON,
            deduplication_key VARCHAR UNIQUE,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """,
    "notifications": """
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
            deduplication_key VARCHAR UNIQUE
        )
    """,
}

_INDEXES = {
    "ix_users_email": "CREATE UNIQUE INDEX ix_users_email ON users (email)",
    "ix_auth_sessions_user_id": "CREATE INDEX ix_auth_sessions_user_id ON auth_sessions (user_id)",
    "ix_auth_sessions_token_hash": "CREATE UNIQUE INDEX ix_auth_sessions_token_hash ON auth_sessions (token_hash)",
    "ix_auth_sessions_expires_at": "CREATE INDEX ix_auth_sessions_expires_at ON auth_sessions (expires_at)",
    "ix_audit_events_user_id": "CREATE INDEX ix_audit_events_user_id ON audit_events (user_id)",
    "ix_audit_events_dataset_id": "CREATE INDEX ix_audit_events_dataset_id ON audit_events (dataset_id)",
    "ix_audit_events_finding_id": "CREATE INDEX ix_audit_events_finding_id ON audit_events (finding_id)",
    "ix_audit_events_operation_id": "CREATE INDEX ix_audit_events_operation_id ON audit_events (operation_id)",
    "ix_audit_events_event_type": "CREATE INDEX ix_audit_events_event_type ON audit_events (event_type)",
    "ix_audit_events_created_at": "CREATE INDEX ix_audit_events_created_at ON audit_events (created_at)",
    "ix_notifications_user_id": "CREATE INDEX ix_notifications_user_id ON notifications (user_id)",
    "ix_notifications_event_type": "CREATE INDEX ix_notifications_event_type ON notifications (event_type)",
    "ix_notifications_created_at": "CREATE INDEX ix_notifications_created_at ON notifications (created_at)",
    "ix_notifications_dataset_id": "CREATE INDEX ix_notifications_dataset_id ON notifications (dataset_id)",
    "ix_notifications_finding_id": "CREATE INDEX ix_notifications_finding_id ON notifications (finding_id)",
    "ix_notifications_operation_id": "CREATE INDEX ix_notifications_operation_id ON notifications (operation_id)",
}

_COLUMN_CONTRACTS = {
    "users": {
        "id": ("VARCHAR", True, True),
        "email": ("VARCHAR", True, False),
        "display_name": ("VARCHAR", True, False),
        "password_hash": ("VARCHAR", True, False),
        "created_at": ("DATETIME", True, False),
        "updated_at": ("DATETIME", True, False),
    },
    "auth_sessions": {
        "id": ("VARCHAR", True, True),
        "user_id": ("VARCHAR", True, False),
        "token_hash": ("VARCHAR", True, False),
        "csrf_token_hash": ("VARCHAR", True, False),
        "created_at": ("DATETIME", True, False),
        "expires_at": ("DATETIME", True, False),
        "revoked_at": ("DATETIME", False, False),
    },
    "audit_events": {
        "id": ("VARCHAR", True, True),
        "user_id": ("VARCHAR", True, False),
        "dataset_id": ("VARCHAR", False, False),
        "finding_id": ("VARCHAR", False, False),
        "operation_id": ("VARCHAR", False, False),
        "event_type": ("VARCHAR", True, False),
        "outcome": ("VARCHAR", True, False),
        "details": ("JSON", False, False),
        "deduplication_key": ("VARCHAR", False, False),
        "created_at": ("DATETIME", True, False),
    },
    "notifications": {
        "id": ("VARCHAR", True, True),
        "user_id": ("VARCHAR", True, False),
        "event_type": ("VARCHAR", True, False),
        "title": ("VARCHAR", True, False),
        "message": ("TEXT", True, False),
        "created_at": ("DATETIME", True, False),
        "read_at": ("DATETIME", False, False),
        "dataset_id": ("VARCHAR", False, False),
        "finding_id": ("VARCHAR", False, False),
        "operation_id": ("VARCHAR", False, False),
        "deduplication_key": ("VARCHAR", False, False),
    },
    "datasets": {
        "id": ("VARCHAR", True, True),
        "owner_user_id": ("VARCHAR", False, False),
    },
}

_EXPECTED_FOREIGN_KEYS = {
    "auth_sessions": {("user_id", "users", "id")},
    "audit_events": {("user_id", "users", "id")},
    "notifications": {("user_id", "users", "id")},
    "datasets": {("owner_user_id", "users", "id")},
}

_EXPECTED_DEFAULTS = {
    ("users", "created_at"): "CURRENT_TIMESTAMP",
    ("users", "updated_at"): "CURRENT_TIMESTAMP",
    ("auth_sessions", "created_at"): "CURRENT_TIMESTAMP",
    ("audit_events", "created_at"): "CURRENT_TIMESTAMP",
    ("notifications", "created_at"): "CURRENT_TIMESTAMP",
}

_UNIQUE_COLUMN_CONTRACTS = {
    "audit_events": {"deduplication_key"},
    "notifications": {"deduplication_key"},
}

_INDEX_CONTRACTS = {
    "ix_users_email": ("users", ("email",), True),
    "ix_auth_sessions_user_id": ("auth_sessions", ("user_id",), False),
    "ix_auth_sessions_token_hash": ("auth_sessions", ("token_hash",), True),
    "ix_auth_sessions_expires_at": ("auth_sessions", ("expires_at",), False),
    "ix_audit_events_user_id": ("audit_events", ("user_id",), False),
    "ix_audit_events_dataset_id": ("audit_events", ("dataset_id",), False),
    "ix_audit_events_finding_id": ("audit_events", ("finding_id",), False),
    "ix_audit_events_operation_id": ("audit_events", ("operation_id",), False),
    "ix_audit_events_event_type": ("audit_events", ("event_type",), False),
    "ix_audit_events_created_at": ("audit_events", ("created_at",), False),
    "ix_notifications_user_id": ("notifications", ("user_id",), False),
    "ix_notifications_event_type": ("notifications", ("event_type",), False),
    "ix_notifications_created_at": ("notifications", ("created_at",), False),
    "ix_notifications_dataset_id": ("notifications", ("dataset_id",), False),
    "ix_notifications_finding_id": ("notifications", ("finding_id",), False),
    "ix_notifications_operation_id": ("notifications", ("operation_id",), False),
    "ix_datasets_owner_user_id": ("datasets", ("owner_user_id",), False),
}


def _validate_column_contracts(connection: sqlite3.Connection) -> None:
    for table_name, expected_columns in _COLUMN_CONTRACTS.items():
        actual = {
            row[1]: row
            for row in connection.execute(f'PRAGMA table_info("{table_name}")')
        }
        for column_name, (expected_type, expected_not_null, expected_pk) in expected_columns.items():
            row = actual.get(column_name)
            if row is None:
                raise RuntimeError(
                    f"Incompatible schema: {table_name}.{column_name} is missing"
                )
            actual_type = (row[2] or "").upper()
            if (
                actual_type != expected_type
                or bool(row[3]) != expected_not_null
                or bool(row[5]) != expected_pk
            ):
                raise RuntimeError(
                    f"Incompatible schema definition for {table_name}.{column_name}"
                )
            expected_default = _EXPECTED_DEFAULTS.get((table_name, column_name))
            actual_default = (row[4] or "").strip(" ()'\"").upper()
            if expected_default and actual_default != expected_default:
                raise RuntimeError(
                    f"Incompatible default for {table_name}.{column_name}"
                )

    for table_name, expected in _EXPECTED_FOREIGN_KEYS.items():
        actual = {
            (row[3], row[2], row[4])
            for row in connection.execute(f'PRAGMA foreign_key_list("{table_name}")')
        }
        if not expected.issubset(actual):
            raise RuntimeError(f"Incompatible foreign keys in {table_name}")

    for table_name, columns in _UNIQUE_COLUMN_CONTRACTS.items():
        if not any(
            _has_exact_unique_index(connection, table_name, column_name)
            for column_name in columns
        ):
            raise RuntimeError(f"Missing unique constraints in {table_name}")


def _has_exact_unique_index(
    connection: sqlite3.Connection, table_name: str, column_name: str
) -> bool:
    for index in connection.execute(f'PRAGMA index_list("{table_name}")'):
        if not index[2] or (len(index) > 4 and index[4]):
            continue
        indexed_columns = tuple(
            row[2]
            for row in connection.execute(
                f'PRAGMA index_info("{index[1]}")'
            )
        )
        # A composite UNIQUE index only guarantees uniqueness of the tuple,
        # not of each member column independently.
        if indexed_columns == (column_name,):
            return True
    return False


def _validate_index_contracts(connection: sqlite3.Connection) -> None:
    for index_name, (expected_table, expected_columns, expected_unique) in _INDEX_CONTRACTS.items():
        row = connection.execute(
            "SELECT tbl_name FROM sqlite_master WHERE type = 'index' AND name = ?",
            (index_name,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"Required index {index_name} is missing")
        index_info = connection.execute(
            f'PRAGMA index_list("{expected_table}")'
        ).fetchall()
        details = next((item for item in index_info if item[1] == index_name), None)
        columns = tuple(
            item[2]
            for item in connection.execute(f'PRAGMA index_info("{index_name}")')
        )
        if (
            row[0] != expected_table
            or details is None
            or bool(details[2]) != expected_unique
            or columns != expected_columns
        ):
            raise RuntimeError(f"Incompatible definition for index {index_name}")


def _validate_auth_schema(connection: sqlite3.Connection) -> None:
    _validate_column_contracts(connection)
    _validate_index_contracts(connection)


def upgrade_database(database_path: str | Path) -> bool:
    """Create missing identity/event schema and nullable dataset ownership.

    Returns True if any schema change occurred. Existing data is not updated
    or removed. The migration assumes the foundational ``datasets`` table
    exists and refuses to run otherwise.
    """
    path = Path(database_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Database file does not exist: {path}")

    connection = sqlite3.connect(f"{path.as_uri()}?mode=rw", uri=True, timeout=30)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        existing_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if "datasets" not in existing_tables:
            raise RuntimeError("Database does not contain the datasets table")

        changed = False
        for table_name, create_sql in _TABLES.items():
            if table_name not in existing_tables:
                connection.execute(create_sql)
                changed = True

        dataset_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(datasets)")
        }
        if "owner_user_id" not in dataset_columns:
            connection.execute(
                "ALTER TABLE datasets ADD COLUMN owner_user_id "
                "VARCHAR REFERENCES users(id)"
            )
            changed = True

        existing_indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
        for index_name, create_sql in _INDEXES.items():
            if index_name not in existing_indexes:
                connection.execute(create_sql)
                changed = True
        if "ix_datasets_owner_user_id" not in existing_indexes:
            connection.execute(
                "CREATE INDEX ix_datasets_owner_user_id ON datasets (owner_user_id)"
            )
            changed = True

        # Validate the final schema before commit. Any mismatch raises inside
        # the transaction, rolling back all DDL performed by this invocation.
        _validate_auth_schema(connection)
        connection.commit()
        return changed
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, help="Existing SQLite database file")
    args = parser.parse_args()
    changed = upgrade_database(args.database)
    print("Identity/event schema added." if changed else "Identity/event schema already exists; no changes made.")


if __name__ == "__main__":
    main()
