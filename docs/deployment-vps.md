# VPS Deployment Guide

This guide deploys the Instagram automation product on an Ubuntu VPS with Docker Compose, Nginx, HTTPS, Postgres, Redis, Celery workers, and the dashboard.

Replace `automation.yourdomain.com` everywhere with your real hostname.

## 1. Prepare Ubuntu

Create a non-root deploy user:

```bash
adduser deploy
usermod -aG sudo deploy
```

Copy your SSH key:

```bash
mkdir -p /home/deploy/.ssh
nano /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys
```

Disable password login:

```bash
sudo nano /etc/ssh/sshd_config
```

Set:

```text
PasswordAuthentication no
PermitRootLogin no
```

Restart SSH:

```bash
sudo systemctl restart ssh
```

Configure UFW:

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

## 2. Install Docker

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker deploy
```

Log out and back in so group membership applies.

## 3. DNS

Create an A record:

```text
automation.yourdomain.com -> <your VPS public IP>
```

Wait for DNS propagation before issuing certificates.

## 4. Clone And Configure

```bash
git clone <your-repo-url> ManyOsirisChat
cd ManyOsirisChat
cp .env.production.example .env.production
```

Edit `.env.production`:

```bash
nano .env.production
```

Generate a Fernet token key:

```bash
python3 - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
```

Set strong values for:

```text
POSTGRES_PASSWORD
JWT_SECRET
APP_SECRET_KEY
TOKEN_ENCRYPTION_KEY
META_APP_SECRET
META_WEBHOOK_VERIFY_TOKEN
```

Set:

```text
APP_BASE_URL=https://automation.yourdomain.com
ALLOWED_ORIGINS=https://automation.yourdomain.com
NEXT_PUBLIC_API_URL=https://automation.yourdomain.com
APP_ENV=production
DISABLE_DOCS=true
```

Update `nginx/default.conf` and replace `automation.yourdomain.com` with your domain.

## 5. SSL With Certbot

Install Certbot on the host:

```bash
sudo apt-get install -y certbot
```

Temporarily stop any service using ports 80/443, then issue a certificate:

```bash
sudo certbot certonly --standalone -d automation.yourdomain.com
```

Copy certificates into the Docker named volume:

```bash
docker volume create manyosirischat_letsencrypt
docker run --rm \
  -v manyosirischat_letsencrypt:/etc/letsencrypt \
  -v /etc/letsencrypt:/host-letsencrypt:ro \
  alpine sh -c "cp -a /host-letsencrypt/* /etc/letsencrypt/"
```

Renew on the host:

```bash
sudo certbot renew
```

After renewal, copy certificates into the volume again and reload Nginx:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml restart nginx
```

An alternative is to terminate TLS at a managed reverse proxy or load balancer and forward HTTP to this Nginx service on a private network.

## 6. Start Services

Build and start production services:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

Run migrations:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec backend alembic upgrade head
```

Create an admin user:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec backend \
  python -m app.scripts.create_admin --email admin@yourdomain.com --password '<strong-password>' --name 'Admin'
```

Check services:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml ps
curl -I https://automation.yourdomain.com/health
```

Open:

```text
https://automation.yourdomain.com/login
```

## 7. Meta Webhook Setup

In Meta Developer Console:

1. Set callback URL to `https://automation.yourdomain.com/webhooks/meta`.
2. Set verify token to `META_WEBHOOK_VERIFY_TOKEN`.
3. Subscribe the required Instagram webhook fields.
4. Keep Meta permissions minimal for the current automation scope.

Test webhook challenge:

```bash
curl "https://automation.yourdomain.com/webhooks/meta?hub.mode=subscribe&hub.verify_token=<token>&hub.challenge=test123"
```

Expected response:

```text
test123
```

## 8. Test A Live Campaign

1. Log into the dashboard.
2. Connect or mock-connect an account in a safe staging environment.
3. Create a draft campaign.
4. Run `Test Message` from the campaign form.
5. Activate the campaign.
6. Send a test Instagram comment that matches a keyword.
7. Check `Logs`, `Leads`, `Messages`, and `/webhooks/health`.

## 9. Backups

Create a backup:

```bash
scripts/backup_postgres.sh
```

Restore a backup:

```bash
scripts/restore_postgres.sh backups/postgres_instagram_automation_YYYYMMDDTHHMMSSZ.sql.gz
```

For production, copy backups off-server to S3, Backblaze B2, rsync storage, or another managed backup target. Test restore procedures before you need them.
