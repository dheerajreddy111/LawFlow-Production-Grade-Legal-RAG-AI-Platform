# LawFlow operations

Day-2 reference: migrations, bootstrap admin, required production
environment. Paths are relative to the repo root unless noted.

## Database migrations

LawFlow uses **Alembic** for schema management. The runtime startup
runs `alembic upgrade head` automatically via the FastAPI lifespan
(see `backend/app/db/migrations.py`); the table-of-tables
(`alembic_version`) keeps it idempotent across restarts.

### Layout

```
backend/
  alembic.ini                 Alembic configuration (read by both CLI + runtime)
  migrations/
    env.py                    Configures the async engine + target_metadata
    script.py.mako            Template for newly generated migrations
    versions/                 One file per migration, ordered by filename timestamp
  app/db/
    migrations.py             Programmatic runner (used by startup + tests)
    session.py                Async engine; `create_all` retained for tests only
```

### Day-to-day commands

All Alembic commands run from `backend/` with the project venv
activated. `DATABASE_URL` is read from the environment if set;
otherwise it falls back to `app.config.settings.database_url`.

```bash
# Apply every pending migration up to the latest revision
alembic upgrade head

# Roll back the most recent migration
alembic downgrade -1

# Roll back to an empty schema (testing only — wipes all app tables)
alembic downgrade base

# Inspect the current revision
alembic current

# Show migration history
alembic history --verbose
```

### Generating a new migration

After changing an SQLAlchemy model, autogenerate a migration:

```bash
alembic revision --autogenerate -m "short imperative description"
```

Then **always inspect the generated file** in
`migrations/versions/<timestamp>_<short_rev>_<slug>.py`. Autogenerate
does not know about:

- Server-side defaults on existing rows during column adds
- Data migrations
- Index renames (it sees a drop + create)

For a column added with `NOT NULL`, fill in a backfill in the
`upgrade()` body before the `add_column` enforces the constraint, or
add the column nullable, backfill, then `alter_column` to NOT NULL in
a follow-up migration.

### Production rollout

1. Take a logical backup of the live DB (`pg_dump` or `sqlite3 .dump`
   depending on dialect).
2. Run `alembic upgrade head` either out-of-band or by deploying the
   new image (the FastAPI lifespan applies migrations on startup).
3. Smoke-test by hitting `/health` and one admin endpoint.

If a deploy fails after the migration applied but before the new
code stabilises, `alembic downgrade -1` reverts the schema. Pair the
downgrade with a code rollback to the previous image.

### Migration safety

- **Idempotent**: `alembic upgrade head` is safe to run on an
  already-migrated DB — it consults `alembic_version` and exits.
- **Deterministic**: revisions are linked by `down_revision`, not by
  filename order. Renaming files won't change ordering.
- **SQLite compatible**: `env.py` enables `render_as_batch=True` so
  generated migrations use SQLite-friendly batch-ALTER blocks.
- **Tested**: `backend/tests/test_migrations.py` exercises upgrade
  head, idempotency, downgrade base, and env-URL override on every
  CI run.

## Bootstrapping a fresh deployment

Set both env vars before first start:

```
BOOTSTRAP_ADMIN_EMAIL=ops@example.com
BOOTSTRAP_ADMIN_PASSWORD=<generated-strong-password>
```

On startup `backend/app/auth/bootstrap.py::ensure_bootstrap_admin`
runs and:

- **creates** an admin for that email if one does not yet exist,
- **does nothing** if an admin with that email is already present
  (idempotent — leaving the env vars set across restarts is safe),
- **refuses to mutate** if the email is held by a non-admin user
  (logs a warning; resolve manually with a different email or by
  promoting the existing user via a one-off DB session),
- **skips entirely** when either env var is absent.

The password is **only read at creation time**. Rotating it via the
env var has no effect on the live row — the admin must change their
password through the normal login + (future) reset flow, or an
operator must update the `password_hash` column directly.

### Operational rules

- **Generate the password out-of-band** (e.g.
  `python -c "import secrets; print(secrets.token_urlsafe(24))"`)
  and inject via your secret store. Never commit it to the repo.
- **Never use a default or placeholder password in production.**
  The `.env.example` placeholders exist for local dev only and
  must be replaced before any deployment.
- **Rotate immediately** if a bootstrap password ever leaks. Treat
  it the same as any production credential.
- The bootstrap email is logged at INFO so operators can confirm
  which account was provisioned. The plaintext password is never
  logged and never appears in any API response.

## Required production env

| Variable                | Required           | Notes                                          |
|-------------------------|--------------------|------------------------------------------------|
| `DATABASE_URL`          | yes                | SQLAlchemy URL, e.g. `sqlite+aiosqlite:///./lawflow.db` |
| `JWT_SECRET_KEY`        | yes (prod)         | 48+ chars; absence raises in production env   |
| `ENVIRONMENT`           | yes                | `production` activates strict checks           |
| `COOKIE_SECURE`         | yes (behind HTTPS) | `true` to flag the refresh cookie Secure       |
| `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` | first deploy | See bootstrap section above                       |
| `GROQ_API_KEY` / `ANTHROPIC_API_KEY` | optional | Required for the RAG path; deterministic still works without |
| `LANGCHAIN_TRACING_V2` + `LANGCHAIN_API_KEY` | optional | Enables LangSmith tracing |
