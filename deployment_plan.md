# ERP AI - Deployment Plan

## 1. Where to Host the Database (`erp_ai_memory.db`)

Since this FastAPI application uses a local SQLite database (`erp_ai_memory.db`) for saved reports and memory tracking, **it is highly recommended to deploy to a Virtual Machine (VPS)** rather than a "Serverless" platform (like Heroku or Vercel).

*   **Virtual Machines (VPS) like EC2, DigitalOcean, Linode, or Hetzner:** 
    *   **Recommended.** The `.db` file simply sits on the server's hard drive right next to your code. It requires zero setup and works exactly like it does on your local machine.
*   **Serverless/Ephemeral Platforms:** 
    *   **Not Recommended.** Every time your app restarts or deploys, the server is wiped clean and replaced with a fresh copy of your code. Your SQLite `.db` file gets deleted, and you lose all your saved data. If you must use these platforms, you would need to attach a persistent "Volume" or migrate from SQLite to PostgreSQL/MySQL.

---

## 2. Server Specifications

Because the heavy lifting (AI processing) is handled remotely by OpenAI/Groq, and the database processing is handled remotely by your ERPNext server, this Python application is very lightweight. It merely acts as a "middleman".

### Minimum / Entry-Level
*Good for up to 10-20 concurrent users.*
*   **CPU:** 1 vCPU
*   **RAM:** 1 GB (FastAPI and Uvicorn have a very low memory footprint)
*   **Storage:** 10 GB to 20 GB SSD
*   **Expected Cost:** ~$4 to $6 per month (e.g., DigitalOcean Basic Droplet, Linode Nanode, AWS Lightsail, Hetzner CX11)

### Recommended / Production
*Good for 50+ concurrent users, providing breathing room if multiple users hit the "Generate Report" button at the exact same time.*
*   **CPU:** 2 vCPU
*   **RAM:** 2 GB
*   **Storage:** 20 GB to 40 GB SSD
*   **Expected Cost:** ~$10 to $12 per month

---

## 3. Deployment Setup Checklist

When deploying to your Linux VM, follow these standard practices for a production FastAPI app:

1. **Environment Setup:** 
   * Install Python 3.9+ and create a virtual environment (`venv`).
   * Clone your Git repository to the server.
   * Run `pip install -r requirements.txt`.
2. **Process Manager:** 
   * Never run your app directly with `uvicorn main:app` in the background for production. 
   * Use **Gunicorn** or **Supervisor** (or a Systemd service) to manage the process. This ensures your app automatically restarts if it crashes or if the server reboots.
3. **Reverse Proxy:** 
   * Use **Nginx** in front of your FastAPI app. Nginx will handle SSL/HTTPS certificates (via Let's Encrypt / Certbot) and route port 80/443 traffic to your internal FastAPI app (which runs on port 8000 by default).
4. **Network Access / Whitelisting:** 
   * Ensure your new server's IP address is whitelisted on your ERPNext server so that `erp_client.py` can successfully make API requests to it securely.
5. **Environment Variables:**
   * Create your `.env` file on the server with production API keys for OpenAI/Groq and ERPNext.

---

## 4. Requirements and Setup

Here are the step-by-step commands you should run on your Linux server to get the application running with SQLite.

### Step 4.1: Install System Dependencies
Update the server's package list and install Python 3 (most Linux distributions come with Python, but these commands ensure you have the virtual environment tools):
```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip git -y
```

### Step 4.2: Clone the Repository
Get your code onto the server:
```bash
git clone https://YOUR_GIT_URL/erp_ai.git
cd erp_ai
```

### Step 4.3: Set up the Virtual Environment & Install Libraries
Create the virtual environment, activate it, and install the required packages:
```bash
# Create the virtual environment
python3 -m venv venv

# Activate it (you must do this every time you work on the app)
source venv/Scripts/Activate.ps1

# Install the necessary libraries directly
pip install fastapi uvicorn pydantic python-dotenv openai groq sqlalchemy httpx
```

*Note: Since you are using standard SQLite, SQLAlchemy handles it natively on Linux without needing any extra database drivers like `psycopg2` or `pymysql`.*

### Step 4.4: Setup your Environment Variables
Create the `.env` file on your server (do not commit your API keys to Git!).
```bash
nano .env
```
Paste your production values inside and save the file:
```env
AI_PROVIDER=openai
AI_MODEL=gpt-4o
OPENAI_API_KEY=your_openai_key
GROQ_API_KEY=your_groq_key
ERP_URL=https://your-erpnext-domain.com
ERP_API_KEY=your_api_key
ERP_API_SECRET=your_api_secret
```

### Step 4.5: Run the Server
To test that it works, you can start Uvicorn manually:
```bash
uvicorn main:app --reload --port 9000
```
*(Press `Ctrl+C` to stop).*

**For Production:** You should run it in the background using a tool like Supervisor, or use a command like this with `nohup`:
```bash
nohup uvicorn main:app --host 0.0.0.0 --port 9000 &
``` 
*The SQLite database (`erp_ai_memory.db`) will be created automatically in the same folder the first time the app attempts to save a report.*
