password for 

i what was

or the erp_ai_user for postgresql d f

# ERP AI Deployment Guide

This project is a FastAPI app that serves:

- API endpoints from `main.py`
- The dashboard frontend from `static/`
- A local SQLite database by default: `erp_ai_memory.db`
- Or PostgreSQL in production via `DATABASE_URL`

The clean production shape is:

- `uvicorn` running on `127.0.0.1:8001`
- `nginx` reverse proxy on ports `80` and `443`
- `systemd` managing the FastAPI process

## 1. Copy the project to the server

Example path:

```bash
/var/www/erp_ai
```

## 2. Install system packages

Ubuntu/Debian example:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx postgresql postgresql-contrib
```

## 3. Create the Python environment

```bash
cd /var/www/erp_ai
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 4. Create the production `.env`

Start from `env.tmpl` and create `.env`:

```env
AI_PROVIDER=openai
AI_MODEL=gpt-4o
OPENAI_API_KEY=your_openai_key

ERP_URL=https://your-erp-domain.com
ERP_API_KEY=your_erp_api_key
ERP_API_SECRET=your_erp_api_secret

ENVIRONMENT=production

MOTHERBRAIN_URL=https://your-motherbrain-endpoint/api/motherbrain/ingest
MOTHERBRAIN_API_KEY=your_motherbrain_api_key

# Recommended for production
# DATABASE_URL=postgresql+psycopg://erp_ai_user:strong_password@127.0.0.1:5432/erp_ai
```

Notes:

- `ENVIRONMENT=production` hides SQL output in the UI.
- If you keep SQLite, make sure the service user can write to the project directory.
- For higher reliability, PostgreSQL is better than SQLite on a busy multi-user server.

## 5. PostgreSQL setup and SQLite data migration

If you already have records in `erp_ai_memory.db`, do not delete it. Import that file into PostgreSQL first, then switch the app over.

Create the PostgreSQL database and user:

```bash
sudo -u postgres psql
```

Inside `psql`:

```sql
CREATE DATABASE erp_ai;
CREATE USER erp_ai_user WITH ENCRYPTED PASSWORD 'strong_password_here';
GRANT ALL PRIVILEGES ON DATABASE erp_ai TO erp_ai_user;
\q
```

Grant schema permissions:

```bash
sudo -u postgres psql -d erp_ai -c "GRANT ALL ON SCHEMA public TO erp_ai_user;"
sudo -u postgres psql -d erp_ai -c "ALTER SCHEMA public OWNER TO erp_ai_user;"
```

Back up the old SQLite file before you touch anything:

```bash
cd /var/www/erp_ai
cp erp_ai_memory.db erp_ai_memory.db.backup-$(date +%Y%m%d-%H%M%S)
```

Install Python dependencies, including the PostgreSQL driver:

```bash
cd /var/www/erp_ai
source .venv/bin/activate
pip install -r requirements.txt
```

Run the one-time import from SQLite into PostgreSQL:

```bash
cd /var/www/erp_ai
source .venv/bin/activate
python scripts/migrate_sqlite_to_postgres.py \
  --sqlite-path /var/www/erp_ai/erp_ai_memory.db \
  --postgres-url postgresql+psycopg://erp_ai_user:strong_password_here@127.0.0.1:5432/erp_ai
```

The migration script:

- Creates the PostgreSQL tables if they do not exist
- Copies existing rows from SQLite into PostgreSQL
- Preserves existing primary key IDs
- Resets PostgreSQL sequences so future inserts continue correctly
- Stops if the PostgreSQL target tables already contain data

Verify the copied data:

```bash
sudo -u postgres psql -d erp_ai
```

Then run a few checks:

```sql
SELECT COUNT(*) FROM conversations;
SELECT COUNT(*) FROM conversation_messages;
SELECT COUNT(*) FROM saved_reports;
SELECT COUNT(*) FROM client_configs;
\q
```

After the counts look correct, update `.env`:

```env
DATABASE_URL=postgresql+psycopg://erp_ai_user:strong_password_here@127.0.0.1:5432/erp_ai
```

Restart the app:

```bash
sudo systemctl restart erp-ai
sudo systemctl status erp-ai
```

Keep the original SQLite file for rollback until you have verified the app in production.

## 6. Test the app manually

```bash
cd /var/www/erp_ai
source .venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8001
```

Then open:

- `http://server-ip/` after nginx is configured
- Direct app test: `http://127.0.0.1:8001/`
- Health check: `http://127.0.0.1:8001/health`

The root path now redirects to `/static/login.html`.

## 7. Create the systemd service

Copy `deploy/erp-ai.service` to:

```bash
/etc/systemd/system/erp-ai.service
```

Then run:

```bash
sudo systemctl daemon-reload
sudo systemctl enable erp-ai
sudo systemctl start erp-ai
sudo systemctl status erp-ai
```

Logs:

```bash
sudo journalctl -u erp-ai -f
```

## 8. Configure nginx

Copy `deploy/nginx-erp-ai.conf` to:

```bash
/etc/nginx/sites-available/erp-ai
```

Enable it:

```bash
sudo ln -s /etc/nginx/sites-available/erp-ai /etc/nginx/sites-enabled/erp-ai
sudo nginx -t
sudo systemctl reload nginx
```

## 9. Add SSL

If your domain already points to the server:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com -d www.your-domain.com
```

## 10. Useful update flow

```bash
cd /var/www/erp_ai
git pull
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart erp-ai
```

## 11. Common issues

- `502 Bad Gateway`: `uvicorn` is not running or nginx points to the wrong port.
- `Permission denied` on SQLite: fix ownership on the app directory and DB file.
- `psycopg` import error: re-run `pip install -r requirements.txt` inside the app virtualenv.
- PostgreSQL auth failure: verify `DATABASE_URL`, username, password, and host.
- Migration script aborts because target tables are not empty: create a fresh PostgreSQL database and run the import again.
- Blank dashboard: check browser dev tools and nginx logs.
- ERP requests failing: verify `ERP_URL`, `ERP_API_KEY`, and `ERP_API_SECRET`.
- AI requests failing: verify `OPENAI_API_KEY` and outbound internet access from the server.
