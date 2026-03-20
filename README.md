# KAS DDNS Updater

Dynamic DNS Updater for ALL-INKL.COM (KAS API). Updates A-Records automatically when your public IP changes — ideal for DSL connections with dynamic IPs.

## Features

- Automatic public IP detection (multiple fallback services)
- KAS SOAP API with SHA1 authentication
- Updates only when IP actually changed
- KAS flood protection compliance (3s delay between API calls)
- Docker-ready for Portainer deployment
- Configurable update interval

## Quick Start

### 1. Clone & Configure

```bash
git clone https://github.com/DEIN-USERNAME/kas-ddns-updater.git
cd kas-ddns-updater
cp .env.example .env
# Edit .env with your KAS credentials
```

### 2. Deploy with Docker Compose / Portainer

```bash
docker compose up -d
```

Or in **Portainer**: Add a new Stack, paste the `docker-compose.yml` content, and add your environment variables.

### 3. Check Logs

```bash
docker logs -f kas-ddns-updater
```

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `KAS_LOGIN` | Yes | - | KAS Login (z.B. `w0123456`) |
| `KAS_PASSWORD` | Yes | - | KAS Passwort |
| `KAS_DOMAINS` | Yes | - | Komma-getrennte Domains (z.B. `example.com,sub.example.com`) |
| `KAS_RECORD_NAMES` | No | *(alle)* | Nur bestimmte Record-Namen updaten |
| `UPDATE_INTERVAL` | No | `300` | Intervall in Sekunden |
| `LOG_LEVEL` | No | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

## How it works

1. Gets your current public IP via multiple services (ipify, ifconfig.me, etc.)
2. Authenticates with the KAS API (SHA1)
3. Fetches DNS records for your configured zones
4. Compares A-record IPs with current IP
5. Updates only changed records
6. Waits for the configured interval, then repeats

## KAS Credentials

Your KAS login and password can be found in the [ALL-INKL KAS panel](https://kas.all-inkl.com/). The login is your KAS username (e.g., `w0123456`), and the password is your KAS password (not your customer password).

## Portainer Deployment

1. Go to **Stacks** > **Add Stack**
2. Name: `kas-ddns-updater`
3. Build method: **Repository** (point to your GitHub repo) or **Web editor** (paste docker-compose.yml)
4. Add environment variables under **Environment variables**
5. Click **Deploy the stack**
