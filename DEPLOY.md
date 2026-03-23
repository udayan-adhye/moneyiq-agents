# MoneyIQ Agent Server - Hetzner Deployment Guide

## Step 1: Create a Hetzner Server

1. Go to https://console.hetzner.cloud
2. Create a new project (e.g., "MoneyIQ")
3. Add a server:
   - Location: Nuremberg or Helsinki (cheapest)
   - Image: Ubuntu 22.04
   - Type: CX22 (2 vCPU, 4GB RAM) - around 4.15 EUR/month
   - SSH key: Add your SSH key (or use password)
4. Note the server IP address

## Step 2: Connect to Your Server

```bash
ssh root@YOUR_SERVER_IP
```

## Step 3: Install Dependencies

Run these commands one by one:

```bash
# Update system
apt update && apt upgrade -y

# Install Python and pip
apt install python3 python3-pip python3-venv git -y

# Create a folder for the app
mkdir -p /opt/moneyiq
cd /opt/moneyiq
```

## Step 4: Upload Your Code

From your local machine (not the server), run:

```bash
scp -r "/path/to/AI OS Money IQ/"* root@YOUR_SERVER_IP:/opt/moneyiq/
```

Or if you use Git:

```bash
# On the server
cd /opt/moneyiq
git clone YOUR_REPO_URL .
```

## Step 5: Set Up Environment

On the server:

```bash
cd /opt/moneyiq

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install packages
pip install -r requirements.txt
```

## Step 6: Set Environment Variables

```bash
nano /opt/moneyiq/.env
```

Add these lines:

```
PORT=5000
CRON_SECRET=your-secret-here-change-this
DASHBOARD_PASSWORD=your-dashboard-password
```

## Step 7: Create a Systemd Service (keeps it running forever)

```bash
nano /etc/systemd/system/moneyiq.service
```

Paste this:

```ini
[Unit]
Description=MoneyIQ Agent Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/moneyiq
EnvironmentFile=/opt/moneyiq/.env
ExecStart=/opt/moneyiq/venv/bin/gunicorn server:app --bind 0.0.0.0:5000 --timeout 300 --workers 2
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then enable and start it:

```bash
systemctl daemon-reload
systemctl enable moneyiq
systemctl start moneyiq
```

Check it's running:

```bash
systemctl status moneyiq
```

## Step 8: Set Up Nginx (so you can use a domain name + HTTPS)

```bash
apt install nginx certbot python3-certbot-nginx -y

nano /etc/nginx/sites-available/moneyiq
```

Paste this (replace YOUR_DOMAIN with your actual domain):

```nginx
server {
    listen 80;
    server_name YOUR_DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300;
    }
}
```

Enable it:

```bash
ln -s /etc/nginx/sites-available/moneyiq /etc/nginx/sites-enabled/
rm /etc/nginx/sites-enabled/default
nginx -t
systemctl restart nginx
```

Add HTTPS (free SSL):

```bash
certbot --nginx -d YOUR_DOMAIN
```

If you don't have a domain, you can skip Nginx and just use http://YOUR_SERVER_IP:5000

## Step 9: Set Up Cron Jobs

```bash
crontab -e
```

Add these lines:

```cron
# Calendly intake - every 15 minutes
*/15 * * * * curl -s "http://localhost:5000/cron/calendly-intake?secret=your-secret-here-change-this" > /dev/null 2>&1

# Daily lead checker - every day at 8 AM IST (2:30 AM UTC)
30 2 * * * curl -s "http://localhost:5000/cron/daily-lead-checker?secret=your-secret-here-change-this" > /dev/null 2>&1

# Weekly call review - every Monday at 9 AM IST (3:30 AM UTC)
30 3 * * 1 curl -s "http://localhost:5000/cron/call-review?secret=your-secret-here-change-this" > /dev/null 2>&1
```

## Step 10: Register Fireflies Webhook

1. Go to Fireflies - Settings - Integrations - Webhooks
2. Add webhook URL: `https://YOUR_DOMAIN/webhook/fireflies`
3. Select event: "Transcription complete"
4. Save

## Done!

Your dashboard is at: https://YOUR_DOMAIN/dashboard

## Useful Commands

```bash
# Check server status
systemctl status moneyiq

# View live logs
journalctl -u moneyiq -f

# Restart after code update
systemctl restart moneyiq

# Manual run (process last 7 days)
curl "http://localhost:5000/run?days=7"
```

## Updating Code

When you make changes:

```bash
# Upload new files
scp -r "/path/to/AI OS Money IQ/"* root@YOUR_SERVER_IP:/opt/moneyiq/

# Restart the server
ssh root@YOUR_SERVER_IP "systemctl restart moneyiq"
```
