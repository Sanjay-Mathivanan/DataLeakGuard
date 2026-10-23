# SQLite migrations

The application currently defaults to SQLite (`sqlite:///./test.db`). When
the backend is started from `backend/`, that resolves to `backend/test.db`.
There is no Alembic or application-startup migration runner in this project.
Migrations are explicit and must not run automatically at import or startup.

## Add repair operation metadata

`add_operation_metadata.py` is a forward-only migration. It adds the nullable
`operation_metadata JSON` column to `repair_records` and leaves all existing
columns and rows intact. It refuses to create a missing database and is
idempotent if the column already exists.

Before applying it to a configured database:

1. Stop the backend so no application writes race the migration.
2. Create a separate, verified SQLite backup using SQLite's backup API (this
   works with SQLite journal/WAL state; do not copy only the main file while
   the database is active). From `backend/`, this creates a new uniquely named
   backup under the user's profile without overwriting an earlier backup
   (choose a protected location with sufficient space):

   ```powershell
   $backupPath = Join-Path $env:USERPROFILE ("dataleakguard-testdb-" + [guid]::NewGuid().ToString("N") + ".sqlite")
   python -c "import sqlite3,sys; source=sqlite3.connect('file:test.db?mode=ro',uri=True); backup=sqlite3.connect(sys.argv[1]); source.backup(backup); backup.close(); source.close()" $backupPath
   ```

3. Record the backup's location and verify it opens and contains the expected
   table/row counts.
4. Run the migration with an explicit `--database` path. The migration does
   not select a database from settings:

   ```powershell
   python -m migrations.add_operation_metadata --database .\test.db
   ```

5. Verify the new column and that existing operation rows are still readable.

Rollback is restore-from-backup, not a destructive down migration: stop the
backend, preserve the migrated database as a separate recovery copy, and point
the pre-migration application at the verified pre-migration backup (for
example, by setting its `DATABASE_URL` to a SQLite URL for that backup).
Keeping both files separate avoids overwriting either copy. Do not delete
either database copy as part of rollback.

The migration has been designed to be tested on a disposable database copy
first. Do not apply it to a user's database until that test and the backup
verification are complete.
