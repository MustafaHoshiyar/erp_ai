# ERP AI Deployment Guide

This project is a FastAPI app that serves:

- API endpoints from `main.py`
- The dashboard frontend from `static/`
- A local SQLite database by default: `erp_ai_memory.db`

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
sudo apt install -y python3 python3-venv python3-pip nginx
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

# Optional: move off SQLite for production if needed
# DATABASE_URL=postgresql://user:password@127.0.0.1:5432/erp_ai
```

Notes:

- `ENVIRONMENT=production` hides SQL output in the UI.
- If you keep SQLite, make sure the service user can write to the project directory.
- For higher reliability, PostgreSQL is better than SQLite on a busy multi-user server.

## 5. Test the app manually

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

## 6. Create the systemd service

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

## 7. Configure nginx

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

## 8. Add SSL

If your domain already points to the server:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com -d www.your-domain.com
```

## 9. Useful update flow

```bash
cd /var/www/erp_ai
git pull
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart erp-ai
```

## 10. Common issues

- `502 Bad Gateway`: `uvicorn` is not running or nginx points to the wrong port.
- `Permission denied` on SQLite: fix ownership on the app directory and DB file.
- Blank dashboard: check browser dev tools and nginx logs.
- ERP requests failing: verify `ERP_URL`, `ERP_API_KEY`, and `ERP_API_SECRET`.
- AI requests failing: verify `OPENAI_API_KEY` and outbound internet access from the server.
