"""Forward-only SQLite migration adding RepairRecord operation metadata.

Run explicitly from the backend directory after making a verified database
backup:

    python -m migrations.add_operation_metadata --database ./test.db

The migration refuses to create a missing database file. It is safe to rerun.
"""

import argparse
import sqlite3
from pathlib import Path


def upgrade_database(database_path: str | Path) -> bool:
    """Add the nullable JSON column, returning whether a change was made."""
    path = Path(database_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Database file does not exist: {path}")

    # mode=rw ensures sqlite cannot silently create a new database here.
    connection = sqlite3.connect(f"{path.as_uri()}?mode=rw", uri=True, timeout=30)
    try:
        connection.execute("BEGIN IMMEDIATE")
        table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("repair_records",),
        ).fetchone()
        if table_exists is None:
            raise RuntimeError("Database does not contain the repair_records table")

        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(repair_records)")
        }
        if "operation_metadata" in columns:
            connection.commit()
            return False

        connection.execute(
            "ALTER TABLE repair_records ADD COLUMN operation_metadata JSON"
        )
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        required=True,
        help="Existing SQLite database file to migrate; no default database is selected.",
    )
    args = parser.parse_args()
    changed = upgrade_database(args.database)
    print(
        "Added repair_records.operation_metadata."
        if changed
        else "repair_records.operation_metadata already exists; no changes made."
    )


if __name__ == "__main__":
    main()
