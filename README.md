# KAS DDNS Updater

Dynamic DNS Updater for [ALL-INKL.COM](https://all-inkl.com/) (KAS API). Updates A-Records automatically when your public IP changes — ideal for DSL connections with dynamic IPs.

![Dashboard](https://img.shields.io/badge/Web_UI-Dashboard-blue?style=flat-square)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white)
![License](https://img.shields.io/github/license/iljabecker/KAS-DDNS-Updater?style=flat-square)

## Features

- **Web Dashboard** with real-time status, live logs, and manual controls
- **Automatic IP detection** with multiple fallback services
- **KAS SOAP API** with plain-text authentication
- **Smart updates** — only when IP actually changed
- **Multi-domain support** — monitor multiple zones at once
- **KAS flood protection** compliance (3s delay between API calls)
- **Docker-ready** for Portainer deployment
- **Configurable update interval** via Web UI

## Web Interface

The updater comes with a built-in web interface featuring three tabs:

| Tab | Description |
|-----|-------------|
| **Dashboard** | Live status overview — current IP, monitored records, update countdown, manual check & update buttons |
| **DNS Records** | Add/remove domains, test KAS connection, select which A-Records to monitor |
| **Logs** | Color-coded live log viewer with filters (All, Errors, Updates) |

## Quick Start

### Deploy with Portainer

1. Go to **Stacks** → **Add Stack**
2. Name: `kas-ddns-updater`
3. Paste this into the **Web Editor**:

```yaml
services:
  kas-ddns-updater:
    image: ghcr.io/iljabecker/kas-ddns-updater:latest
    container_name: kas-ddns-updater
    ports:
      - "8001:8000"
    restart: unless-stopped
    environment:
      - KAS_LOGIN=${KAS_LOGIN}
      - KAS_PASSWORD=${KAS_PASSWORD}
      - TZ=Europe/Berlin
    volumes:
      - kas-ddns-data:/data

volumes:
  kas-ddns-data:
```

4. Add **Environment Variables** below the editor:
   - `KAS_LOGIN` = your KAS username (e.g. `w0123456`)
   - `KAS_PASSWORD` = your KAS password
5. Click **Deploy the stack**
6. Open `http://<your-server-ip>:8001`

### Deploy with Docker Compose

```bash
git clone https://github.com/iljabecker/KAS-DDNS-Updater.git
cd KAS-DDNS-Updater
cp .env.example .env
# Edit .env with your KAS credentials
docker compose up -d
```

## Setup

1. Open the Web UI at `http://<your-server-ip>:8001`
2. Go to the **DNS Records** tab
3. Add your domain(s) (e.g. `example.de`, `subdomain.example.de`)
4. Click **"Verbindung testen & A-Records laden"**
5. Select the A-Records you want to keep updated
6. Click **"Auswahl speichern & DDNS aktivieren"**
7. Switch to the **Dashboard** tab to monitor

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `KAS_LOGIN` | Yes | — | KAS username (e.g. `w0123456`) |
| `KAS_PASSWORD` | Yes | — | KAS password |
| `TZ` | No | `UTC` | Timezone (e.g. `Europe/Berlin`) |
| `LOG_LEVEL` | No | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `CONFIG_PATH` | No | `/data/config.json` | Path to config file |

> **Note:** Domains and record selection are configured via the Web UI — no environment variables needed for that.

## How It Works

1. Detects your current public IP via multiple services (ipify, ifconfig.me, icanhazip, AWS)
2. Authenticates with the KAS SOAP API (plain-text auth)
3. Fetches DNS records for your configured zones
4. Compares A-Record IPs with your current public IP
5. Updates only records that have changed
6. Waits for the configured interval, then repeats
7. All activity is visible in the Dashboard and Logs

## KAS Credentials

Your KAS login and password can be found in the [ALL-INKL KAS Panel](https://kas.all-inkl.com/).

- **Login:** Your KAS username (e.g. `w0123456`)
- **Password:** Your KAS password (not the customer/billing password)

## Tech Stack

- **Python 3.12** with Flask
- **Docker** (multi-arch: amd64/arm64)
- **KAS SOAP API** (raw XML, no external SOAP library)
- **Vanilla JS** frontend (no framework dependencies)

## License

[MIT](LICENSE)
