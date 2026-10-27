import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

import app.db.session  # Registers the SQLite Engine connect hook.


def test_application_sqlite_connection_hook_enforces_foreign_keys(tmp_path):
    database = tmp_path / "foreign-keys.sqlite"
    engine = create_engine(
        f"sqlite:///{database.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    try:
        with engine.begin() as connection:
            assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
            connection.execute(text("CREATE TABLE parent (id INTEGER PRIMARY KEY)"))
            connection.execute(
                text("CREATE TABLE child (parent_id INTEGER REFERENCES parent(id))")
            )
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text("INSERT INTO child (parent_id) VALUES (999)")
                )
    finally:
        engine.dispose()
