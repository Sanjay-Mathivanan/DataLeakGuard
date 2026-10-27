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

## Add authentication, ownership, audit events, and notifications

`add_auth_events.py` is a separate, forward-only SQLite migration for the
authentication and persistent activity workstream. It creates:

- `users` with a unique email, display name, password hash, and timestamps;
- `auth_sessions` with hashed opaque session/CSRF tokens, expiry, and revocation;
- `audit_events` and `notifications`, both user-scoped and optionally linked to
  dataset, finding, or operation IDs; and
- a nullable `datasets.owner_user_id` foreign key and index.

It does not assign owners to existing datasets or rewrite existing records.
Unowned legacy datasets are intended to remain inaccessible to authenticated
users until a separately reviewed ownership decision is made. It does not
alter `repair_records` or `operation_metadata`.

The migration validates expected column types, nullability, primary keys,
foreign-key targets, defaults, unique constraints, and named index definitions
before commit. A mismatch raises an error and rolls back DDL from that
invocation. A correctly migrated schema is idempotent; compatible partial
schemas are completed, while incompatible definitions are rejected. It refuses
to create a missing database or run if the foundational `datasets` table is
absent. Test it only against a disposable SQLite database first:

```powershell
python -m migrations.add_auth_events --database .\disposable-auth-events.sqlite
```

The command above is an example only; do not point it at the configured
database until a separate backup, migration review, and explicit approval.
The project has no automatic migration runner, so application startup does not
apply this migration.

## Authentication endpoint safeguards

Login and registration use the `limits` library with moving windows (defaults:
`5/minute` per request client address for login and `3/hour` for registration).
Limits expire naturally; there is no permanent account lockout.
`AUTH_RATE_LIMIT_STORAGE_URI` defaults to `memory://` for local development.
Multi-worker or multi-instance deployments must configure a shared backend
supported by the installed `limits` storage provider, or enforce equivalent
limits at a trusted ingress. The repository does not declare a shared-storage
provider or its client dependency. Install and pin a compatible provider, then
use its documented URI format with the actual endpoint supplied through
managed deployment configuration; do not copy a sample endpoint from project
documentation.
Forwarded client-IP headers are not trusted by application code; configure
Uvicorn to consume them only from explicitly trusted proxy addresses.

Authentication requests require an `Origin` or `Referer` whose origin is in
`BACKEND_CORS_ORIGINS`. In production, configure exact HTTPS origins and set
`AUTH_COOKIE_SECURE=True`, particularly when TLS terminates at a reverse
proxy. Direct HTTPS requests also set Secure cookies. Configure the proxy to
overwrite forwarded headers, restrict backend network access, and use only
trusted proxy addresses for forwarded client information. SQLite foreign-key
enforcement is enabled on application-created SQLite connections.
