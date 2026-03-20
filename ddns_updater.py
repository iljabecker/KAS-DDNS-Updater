"""KAS DDNS Updater - Updates ALL-INKL DNS A-Records with current public IP."""

import hashlib
import logging
import os
import sys
import threading
import time
from xml.etree import ElementTree

import requests
from flask import Flask, jsonify

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("kas-ddns")

KAS_AUTH_URL = "https://kasapi.kasserver.com/soap/KasAuth.php"
KAS_API_URL = "https://kasapi.kasserver.com/soap/KasApi.php"

# IP lookup services (fallback chain)
IP_SERVICES = [
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://icanhazip.com",
    "https://checkip.amazonaws.com",
]

app = Flask(__name__)

# ── HTML Web UI ──────────────────────────────────────────────────────────────

HTML_PAGE = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KAS DDNS Updater</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0f172a; color: #e2e8f0; min-height: 100vh;
         display: flex; align-items: center; justify-content: center; }
  .container { max-width: 720px; width: 100%; padding: 2rem; }
  h1 { font-size: 1.5rem; margin-bottom: 0.5rem; }
  .subtitle { color: #94a3b8; margin-bottom: 2rem; font-size: 0.9rem; }
  .card { background: #1e293b; border-radius: 12px; padding: 1.5rem;
          border: 1px solid #334155; margin-bottom: 1rem; }
  .btn { background: #3b82f6; color: #fff; border: none; padding: 0.75rem 1.5rem;
         border-radius: 8px; font-size: 1rem; cursor: pointer; width: 100%;
         transition: background 0.2s; }
  .btn:hover { background: #2563eb; }
  .btn:disabled { background: #475569; cursor: not-allowed; }
  .spinner { display: inline-block; width: 18px; height: 18px;
             border: 2px solid #fff; border-top-color: transparent;
             border-radius: 50%; animation: spin 0.8s linear infinite;
             vertical-align: middle; margin-right: 8px; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .result { margin-top: 1.5rem; display: none; }
  .result.show { display: block; }
  .ip-box { background: #0f172a; border-radius: 8px; padding: 1rem;
            margin-bottom: 1rem; display: flex; justify-content: space-between;
            align-items: center; }
  .ip-label { color: #94a3b8; font-size: 0.85rem; }
  .ip-value { font-family: monospace; font-size: 1.1rem; color: #22c55e; }
  table { width: 100%; border-collapse: collapse; margin-top: 0.5rem; }
  th { text-align: left; padding: 0.6rem 0.75rem; color: #94a3b8;
       font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em;
       border-bottom: 1px solid #334155; }
  td { padding: 0.6rem 0.75rem; border-bottom: 1px solid #1e293b;
       font-size: 0.9rem; }
  tr:hover td { background: #1e293b; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px;
           font-size: 0.75rem; font-weight: 600; }
  .badge-ok { background: #14532d; color: #4ade80; }
  .badge-update { background: #7c2d12; color: #fb923c; }
  .error { background: #7f1d1d; border: 1px solid #991b1b; border-radius: 8px;
           padding: 1rem; color: #fca5a5; margin-top: 1rem; display: none; }
  .error.show { display: block; }
</style>
</head>
<body>
<div class="container">
  <h1>KAS DDNS Updater</h1>
  <p class="subtitle">Verbindung testen und DNS A-Records pruefen</p>
  <div class="card">
    <button class="btn" id="testBtn" onclick="testConnection()">
      Verbindung testen
    </button>
  </div>
  <div class="error" id="error"></div>
  <div class="result" id="result">
    <div class="card">
      <div class="ip-box">
        <div>
          <div class="ip-label">Deine aktuelle oeffentliche IP</div>
          <div class="ip-value" id="currentIp">—</div>
        </div>
      </div>
      <h3 style="margin-bottom:0.5rem; font-size:1rem;">A-Records</h3>
      <table>
        <thead>
          <tr>
            <th>Record</th>
            <th>Zone</th>
            <th>Aktuelle IP</th>
            <th>ID</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody id="recordsBody"></tbody>
      </table>
    </div>
  </div>
</div>
<script>
async function testConnection() {
  const btn = document.getElementById('testBtn');
  const result = document.getElementById('result');
  const error = document.getElementById('error');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Verbinde mit KAS API...';
  result.classList.remove('show');
  error.classList.remove('show');
  try {
    const resp = await fetch('/api/test', { method: 'POST' });
    const data = await resp.json();
    if (!resp.ok) {
      throw new Error(data.error || 'Unbekannter Fehler');
    }
    document.getElementById('currentIp').textContent = data.current_ip;
    const tbody = document.getElementById('recordsBody');
    tbody.innerHTML = '';
    data.records.forEach(r => {
      const match = r.current_ip === data.current_ip;
      const badge = match
        ? '<span class="badge badge-ok">Aktuell</span>'
        : '<span class="badge badge-update">Update noetig</span>';
      tbody.innerHTML += '<tr>'
        + '<td>' + esc(r.name || '@') + '</td>'
        + '<td>' + esc(r.zone) + '</td>'
        + '<td style="font-family:monospace">' + esc(r.current_ip) + '</td>'
        + '<td style="font-family:monospace;color:#94a3b8">' + esc(r.record_id) + '</td>'
        + '<td>' + badge + '</td></tr>';
    });
    result.classList.add('show');
  } catch (e) {
    error.textContent = 'Fehler: ' + e.message;
    error.classList.add('show');
  }
  btn.disabled = false;
  btn.innerHTML = 'Verbindung testen';
}
function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}
</script>
</body>
</html>"""

# ── KAS API Functions ────────────────────────────────────────────────────────


def get_public_ip() -> str:
    """Get current public IPv4 address."""
    for service in IP_SERVICES:
        try:
            resp = requests.get(service, timeout=10)
            resp.raise_for_status()
            ip = resp.text.strip()
            log.debug("Got IP %s from %s", ip, service)
            return ip
        except requests.RequestException as e:
            log.warning("Failed to get IP from %s: %s", service, e)
    raise RuntimeError("Could not determine public IP from any service")


def kas_auth(login: str, password: str) -> str:
    """Authenticate with KAS API and get a session token."""
    auth_data = hashlib.sha1(password.encode()).hexdigest()

    soap_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <KasAuth xmlns="urn:xmethodsKasApi">
      <Params>
        <item>
          <key>kas_login</key>
          <value>{login}</value>
        </item>
        <item>
          <key>kas_auth_type</key>
          <value>sha1</value>
        </item>
        <item>
          <key>kas_auth_data</key>
          <value>{auth_data}</value>
        </item>
      </Params>
    </KasAuth>
  </soap:Body>
</soap:Envelope>"""

    resp = requests.post(
        KAS_AUTH_URL,
        data=soap_body.encode("utf-8"),
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "urn:xmethodsKasApi#KasAuth",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return _parse_auth_token(resp.text)


def _parse_auth_token(xml_text: str) -> str:
    """Extract credential token from KAS auth SOAP response."""
    root = ElementTree.fromstring(xml_text)
    for elem in root.iter():
        if elem.tag and "return" in elem.tag.lower():
            if elem.text and len(elem.text) > 10:
                return elem.text.strip()
        if elem.text and len(elem.text.strip()) > 20 and elem.text.strip().isalnum():
            return elem.text.strip()

    all_text = []
    for elem in root.iter():
        if elem.text and elem.text.strip():
            all_text.append(elem.text.strip())

    candidates = [t for t in all_text if len(t) > 20]
    if candidates:
        return max(candidates, key=len)

    raise RuntimeError(f"Could not parse auth token from response: {xml_text[:500]}")


def kas_api_call(token: str, login: str, action: str, params: dict | None = None) -> str:
    """Make a KAS API SOAP call using session token auth."""
    params_xml = ""
    if params:
        for key, value in params.items():
            params_xml += f"""
          <item>
            <key>{key}</key>
            <value>{value}</value>
          </item>"""

    soap_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <KasApi xmlns="urn:xmethodsKasApi">
      <Params>
        <item>
          <key>kas_login</key>
          <value>{login}</value>
        </item>
        <item>
          <key>kas_auth_type</key>
          <value>session</value>
        </item>
        <item>
          <key>kas_auth_data</key>
          <value>{token}</value>
        </item>
        <item>
          <key>kas_action</key>
          <value>{action}</value>
        </item>
        <item>
          <key>kas_action_params</key>
          <value>{params_xml}
          </value>
        </item>
      </Params>
    </KasApi>
  </soap:Body>
</soap:Envelope>"""

    resp = requests.post(
        KAS_API_URL,
        data=soap_body.encode("utf-8"),
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "urn:xmethodsKasApi#KasApi",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.text


def parse_dns_records(xml_text: str) -> list[dict]:
    """Parse DNS records from KAS API SOAP response."""
    records = []
    root = ElementTree.fromstring(xml_text)

    current_record = {}
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

        if tag == "key" and elem.text:
            key = elem.text.strip()
        elif tag == "value" and elem.text:
            value = elem.text.strip()
            if "key" in dir() and key:
                current_record[key] = value
                if key == "record_aux":
                    records.append(current_record)
                    current_record = {}
                key = None

    if not records:
        log.debug("Primary parsing found no records, trying fallback parser")
        records = _fallback_parse_records(xml_text)

    return records


def _fallback_parse_records(xml_text: str) -> list[dict]:
    """Fallback parser that extracts DNS records from SOAP response."""
    records = []
    root = ElementTree.fromstring(xml_text)

    all_items = []
    for elem in root.iter():
        children = list(elem)
        if len(children) == 2:
            tags = [c.tag.split("}")[-1] if "}" in c.tag else c.tag for c in children]
            if tags == ["key", "value"]:
                k = children[0].text.strip() if children[0].text else ""
                v = children[1].text.strip() if children[1].text else ""
                all_items.append((k, v))

    current = {}
    for k, v in all_items:
        if k == "record_id" and current:
            records.append(current)
            current = {}
        if k.startswith("record_") or k in ("zone_host",):
            current[k] = v
    if current and "record_id" in current:
        records.append(current)

    return records


def get_dns_records(token: str, login: str, zone: str) -> list[dict]:
    """Get all DNS records for a zone."""
    xml = kas_api_call(token, login, "get_dns_settings", {"zone_host": zone})
    return parse_dns_records(xml)


def update_dns_record(token: str, login: str, record_id: str, new_ip: str) -> bool:
    """Update a DNS record's data (IP address)."""
    xml = kas_api_call(
        token, login, "update_dns_settings",
        {"record_id": record_id, "record_data": new_ip},
    )
    log.debug("Update response: %s", xml[:500])
    return "true" in xml.lower() or "fault" not in xml.lower()


# ── Flask Routes ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return HTML_PAGE


@app.route("/api/test", methods=["POST"])
def api_test():
    """Test KAS connection and return DNS A-records."""
    login = os.environ.get("KAS_LOGIN")
    password = os.environ.get("KAS_PASSWORD")
    domains = os.environ.get("KAS_DOMAINS", "")

    if not login or not password:
        return jsonify({"error": "KAS_LOGIN oder KAS_PASSWORD nicht konfiguriert"}), 500
    if not domains:
        return jsonify({"error": "KAS_DOMAINS nicht konfiguriert"}), 500

    domain_list = [d.strip() for d in domains.split(",") if d.strip()]

    try:
        current_ip = get_public_ip()
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    try:
        token = kas_auth(login, password)
    except Exception as e:
        return jsonify({"error": f"KAS Authentifizierung fehlgeschlagen: {e}"}), 401

    a_records = []
    seen_zones = set()

    for domain in domain_list:
        parts = domain.split(".")
        zone = ".".join(parts[-2:]) + "." if len(parts) >= 2 else domain + "."

        if zone in seen_zones:
            continue
        seen_zones.add(zone)

        try:
            time.sleep(3)  # KAS flood protection
            records = get_dns_records(token, login, zone)
        except Exception as e:
            return jsonify({"error": f"DNS-Records fuer {zone} konnten nicht geladen werden: {e}"}), 500

        for record in records:
            if record.get("record_type") == "A":
                a_records.append({
                    "name": record.get("record_name", ""),
                    "zone": zone.rstrip("."),
                    "current_ip": record.get("record_data", ""),
                    "record_id": record.get("record_id", ""),
                })

    return jsonify({"current_ip": current_ip, "records": a_records})


# ── DDNS Background Update Loop ─────────────────────────────────────────────

def run_update():
    """Main update logic."""
    login = os.environ.get("KAS_LOGIN")
    password = os.environ.get("KAS_PASSWORD")
    domains = os.environ.get("KAS_DOMAINS", "")
    record_names = os.environ.get("KAS_RECORD_NAMES", "")

    if not login or not password or not domains:
        log.error("Missing required env vars: KAS_LOGIN, KAS_PASSWORD, KAS_DOMAINS")
        return

    domain_list = [d.strip() for d in domains.split(",") if d.strip()]
    record_name_list = [r.strip() for r in record_names.split(",") if r.strip()] if record_names else []

    current_ip = get_public_ip()
    log.info("Current public IP: %s", current_ip)

    log.info("Authenticating with KAS API as %s...", login)
    token = kas_auth(login, password)
    log.info("Authentication successful")

    for domain in domain_list:
        parts = domain.split(".")
        zone = ".".join(parts[-2:]) + "." if len(parts) >= 2 else domain + "."

        log.info("Processing domain: %s (zone: %s)", domain, zone)
        time.sleep(3)

        records = get_dns_records(token, login, zone)
        log.info("Found %d DNS records for zone %s", len(records), zone)

        updated = 0
        for record in records:
            record_type = record.get("record_type", "")
            record_name = record.get("record_name", "")
            record_data = record.get("record_data", "")
            record_id = record.get("record_id", "")

            if record_type != "A":
                continue

            should_update = False
            if record_name_list:
                if record_name in record_name_list:
                    should_update = True
            else:
                full_name = record_name + zone if record_name else zone.rstrip(".")
                for d in domain_list:
                    if d.rstrip(".") in full_name or record_name == "" or record_name == domain.split(".")[0]:
                        should_update = True
                        break

            if not should_update:
                continue

            if record_data == current_ip:
                log.info("  Record %s (ID: %s) already points to %s - skipping",
                         record_name or "@", record_id, current_ip)
                continue

            log.info("  Updating record %s (ID: %s): %s -> %s",
                     record_name or "@", record_id, record_data, current_ip)

            time.sleep(3)
            success = update_dns_record(token, login, record_id, current_ip)
            if success:
                log.info("  Successfully updated record %s", record_name or "@")
                updated += 1
            else:
                log.error("  Failed to update record %s", record_name or "@")

        if updated == 0:
            log.info("No records needed updating for %s", domain)
        else:
            log.info("Updated %d record(s) for %s", updated, domain)

    log.info("DDNS update cycle complete")


def update_loop():
    """Background thread: periodically runs DDNS updates."""
    interval = int(os.environ.get("UPDATE_INTERVAL", "300"))
    log.info("DDNS update loop started (interval: %ds)", interval)

    while True:
        try:
            run_update()
        except Exception:
            log.exception("Error during update cycle")
        log.info("Next update in %d seconds...", interval)
        time.sleep(interval)


def main():
    log.info("KAS DDNS Updater starting")

    # Start DDNS update loop in background thread
    t = threading.Thread(target=update_loop, daemon=True)
    t.start()

    # Start Flask web server
    app.run(host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
