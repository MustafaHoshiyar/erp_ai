# PostgreSQL Migration Guide

This guide moves the app's internal database from SQLite to PostgreSQL without losing the existing records stored in `erp_ai_memory.db`.

## What changes in this app

The PostgreSQL migration affects the app-owned tables only:

- `global_queries`
- `saved_reports`
- `conversations`
- `conversation_messages`
- `client_context_overrides`
- `client_configs`

The generated ERP reporting SQL is still executed against ERPNext via the API layer in `erp_client.py`.

## Recommended cutover sequence

1. Back up the existing SQLite database file on the server.
2. Install PostgreSQL and create an empty target database.
3. Install updated Python requirements.
4. Run `scripts/migrate_sqlite_to_postgres.py` to copy the existing data.
5. Verify row counts in PostgreSQL.
6. Change `DATABASE_URL` in the app `.env`.
7. Restart the FastAPI service.
8. Smoke-test the app.
9. Keep the SQLite backup file until you are confident in the cutover.

## Example migration command

```bash
python scripts/migrate_sqlite_to_postgres.py \
  --sqlite-path /var/www/erp_ai/erp_ai_memory.db \
  --postgres-url postgresql+psycopg://erp_ai_user:strong_password_here@127.0.0.1:5432/erp_ai
```

## What the migration script does

- Creates the current app tables in PostgreSQL
- Reads rows from the SQLite file
- Inserts those rows into PostgreSQL in dependency-safe order
- Preserves numeric primary key IDs
- Resets PostgreSQL sequences after the copy
- Fails fast if the target PostgreSQL tables already contain data

## Rollback

If anything looks wrong after cutover:

1. Point `DATABASE_URL` back to SQLite or remove it to fall back to `sqlite:///./erp_ai_memory.db`.
2. Restart the app service.
3. Review logs and row counts before trying the import again.
