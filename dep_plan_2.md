To deploy your FastAPI project (`erp_ai`) to a production server (like an Ubuntu Linux server), you'll need to set up a robust environment using **Gunicorn/Uvicorn** to run the app, **Systemd** to keep it running in the background, and **Nginx** as a reverse proxy to handle incoming web traffic. 

Here is the step-by-step guide from scratch:

### Prerequisites
1.  **A remote server** (e.g., Ubuntu 22.04 or 24.04 on AWS, DigitalOcean, Linode).
2.  **A Domain Name** (optional but recommended, to point to your server's IP).
3.  Your code pushed to a Git repository (like GitHub/GitLab).

---

### Step 1: Prepare and Connect to the Server

Connect to your server via SSH. Replace `your_server_ip` with your actual server IP.
```bash
ssh username@your_server_ip
```

Once logged in, update the package list and install the necessary system packages:
```bash
sudo apt update
sudo apt upgrade -y
sudo apt install python3-pip python3-venv python3-dev nginx git -y
```

---

### Step 2: Clone Your Project to the Server

Navigate to the `/var/www` directory and clone your project (or copy it over via SFTP/SCP).
```bash
cd /var/www
sudo git clone https://github.com/your-username/erp_ai.git
```

Change the ownership of the project folder to your current user so you can modify files:
```bash
sudo chown -R $USER:$USER /var/www/erp_ai
cd /var/www/erp_ai
```

---

### Step 3: Set Up the Python Virtual Environment

Create a virtual environment, activate it, and install your project dependencies.
```bash
# Create a virtual environment named 'venv'
python3 -m venv venv

# Activate the virtual environment
source venv/bin/activate

# Install the required packages
pip install -r requirements.txt

# Also install Gunicorn (the production process manager)
pip install gunicorn uvicorn
```

Create your `.env` file for your production environment:
```bash
nano .env
```
*(Paste your production environment variables here, save with `Ctrl + O`, `Enter`, and exit with `Ctrl + X`)*.

---

### Step 4: Create a Systemd Service

You need the app to run in the background and start automatically if the server reboots. We will create a `systemd` service file for it.

Open a new service file:
```bash
sudo nano /etc/systemd/system/erp_ai.service
```

Add the following configuration (replace `your_username` with your actual Ubuntu username, e.g., `ubuntu` or `root`):
```ini
[Unit]
Description=Gunicorn instance to serve erp_ai
After=network.target

[Service]
User=your_username
Group=www-data
WorkingDirectory=/var/www/erp_ai
Environment="PATH=/var/www/erp_ai/venv/bin"
# Run Gunicorn using Uvicorn workers on port 9000
ExecStart=/var/www/erp_ai/venv/bin/gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 127.0.0.1:9000

[Install]
WantedBy=multi-user.target
```
*(Note: `-w 4` means 4 worker processes. A general rule is `(2 x num_cores) + 1`)*.

Save (`Ctrl + O`, `Enter`) and close the file (`Ctrl + X`).

Now, start and enable the service:
```bash
# Reload systemd to read the new service file
sudo systemctl daemon-reload

# Start the service
sudo systemctl start erp_ai

# Enable the service to start on boot
sudo systemctl enable erp_ai
```

Check the status to make sure it's running without errors:
```bash
sudo systemctl status erp_ai
```

---

### Step 5: Configure Nginx as a Reverse Proxy

Nginx will face the internet on port 80 (HTTP) and route traffic to your FastAPI app running internally on port 9000.

Create a new Nginx server block configuration file:
```bash
sudo nano /etc/nginx/sites-available/erp_ai
```

Add the following configuration (replace `your_domain_or_IP` with your domain name or just your server's public IP address):
```nginx
server {
    listen 80;
    server_name your_domain_or_IP;

    location / {
        proxy_pass http://127.0.0.1:9000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable the Nginx configuration by creating a symbolic link to the `sites-enabled` directory:
```bash
sudo ln -s /etc/nginx/sites-available/erp_ai /etc/nginx/sites-enabled/
```

Test your Nginx configuration for syntax errors:
```bash
sudo nginx -t
```
If it says `syntax is ok` and `test is successful`, restart Nginx:
```bash
sudo systemctl restart nginx
```

---

### Step 6: Configure the Firewall (UFW)

Ensure your firewall is configured to allow Nginx traffic and SSH:
```bash
sudo ufw allow 'Nginx Full'
sudo ufw allow OpenSSH
sudo ufw enable
```

---

### Step 7: (Optional but highly recommended) Set up SSL with Certbot

If you are using a domain name, you should secure your site with HTTPS.

```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d your_domain.com
```

### Done! 🎉
Your application should now be live! You can visit your server's IP address or domain name in your browser to see your FastAPI application running in production.

**How to update your app in the future:**
Whenever you push new code to your repository, log into your server and run:
```bash
cd /var/www/erp_ai
git pull origin main
sudo systemctl restart erp_ai
```
