import sqlite3

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import RepairRecord
from migrations.add_operation_metadata import upgrade_database


LEGACY_REPAIR_RECORDS = """
CREATE TABLE repair_records (
    id VARCHAR NOT NULL PRIMARY KEY,
    dataset_id VARCHAR NOT NULL,
    finding_id VARCHAR,
    operation_type VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    input_file_sha256 VARCHAR NOT NULL,
    output_file_sha256 VARCHAR,
    output_filename VARCHAR,
    affected_rows INTEGER NOT NULL,
    affected_columns JSON,
    quarantine_info JSON,
    created_at DATETIME,
    completed_at DATETIME,
    error_info JSON
)
"""


def test_forward_migration_preserves_existing_records_and_json_round_trips(tmp_path):
    database = tmp_path / "legacy.sqlite"
    connection = sqlite3.connect(database)
    connection.execute(LEGACY_REPAIR_RECORDS)
    connection.execute(
        """
        INSERT INTO repair_records (
            id, dataset_id, finding_id, operation_type, status,
            input_file_sha256, output_file_sha256, output_filename,
            affected_rows
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "existing-operation",
            "existing-dataset",
            "existing-finding",
            "repair",
            "completed",
            "a" * 64,
            "b" * 64,
            "existing.csv",
            2,
        ),
    )
    connection.commit()
    connection.close()

    assert upgrade_database(database) is True
    assert upgrade_database(database) is False

    connection = sqlite3.connect(database)
    columns = {
        row[1]: row[2]
        for row in connection.execute("PRAGMA table_info(repair_records)")
    }
    original = connection.execute(
        """
        SELECT id, dataset_id, finding_id, operation_type, status,
               input_file_sha256, output_file_sha256, output_filename, affected_rows
        FROM repair_records WHERE id = ?
        """,
        ("existing-operation",),
    ).fetchone()
    assert columns["operation_metadata"].upper() == "JSON"
    assert original == (
        "existing-operation",
        "existing-dataset",
        "existing-finding",
        "repair",
        "completed",
        "a" * 64,
        "b" * 64,
        "existing.csv",
        2,
    )
    assert connection.execute(
        "SELECT operation_metadata FROM repair_records WHERE id = ?",
        ("existing-operation",),
    ).fetchone()[0] is None
    connection.close()

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with Session(engine) as session:
        record = session.query(RepairRecord).filter_by(id="existing-operation").one()
        assert record.operation_metadata is None
        record.operation_metadata = {
            "selected_finding_ids": ["finding-a", "finding-b"],
            "original_row_count": 5,
            "final_row_count": 3,
            "duplicate_rows_removed": 2,
            "skipped_findings": [],
        }
        session.commit()

    with Session(engine) as session:
        stored = session.query(RepairRecord).filter_by(id="existing-operation").one()
        assert stored.operation_metadata == {
            "selected_finding_ids": ["finding-a", "finding-b"],
            "original_row_count": 5,
            "final_row_count": 3,
            "duplicate_rows_removed": 2,
            "skipped_findings": [],
        }
    engine.dispose()


def test_migration_refuses_missing_database_or_missing_table(tmp_path):
    missing = tmp_path / "does-not-exist.sqlite"
    try:
        upgrade_database(missing)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("migration must not create a missing database")
    assert not missing.exists()

    database = tmp_path / "no-repair-records.sqlite"
    sqlite3.connect(database).close()
    try:
        upgrade_database(database)
    except RuntimeError as error:
        assert "repair_records" in str(error)
    else:
        raise AssertionError("migration must reject a database without repair_records")
