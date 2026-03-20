"""KAS DDNS Updater - Updates ALL-INKL DNS A-Records with current public IP."""

import hashlib
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from xml.etree import ElementTree

import requests
from flask import Flask, jsonify, request as flask_request

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("kas-ddns")

KAS_AUTH_URL = "https://kasapi.kasserver.com/soap/KasAuth.php"
KAS_API_URL = "https://kasapi.kasserver.com/soap/KasApi.php"

IP_SERVICES = [
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://icanhazip.com",
    "https://checkip.amazonaws.com",
]

CONFIG_PATH = Path(os.getenv("CONFIG_PATH", "/data/config.json"))

app = Flask(__name__)


# ── Config Persistence ───────────────────────────────────────────────────────

def load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {"domains": [], "record_ids": [], "update_interval": 300}


def save_config(cfg: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


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
         padding: 2rem; }
  .container { max-width: 760px; margin: 0 auto; }
  h1 { font-size: 1.5rem; margin-bottom: 0.25rem; }
  .subtitle { color: #94a3b8; margin-bottom: 1.5rem; font-size: 0.9rem; }
  .card { background: #1e293b; border-radius: 12px; padding: 1.5rem;
          border: 1px solid #334155; margin-bottom: 1rem; }
  .card h2 { font-size: 1.1rem; margin-bottom: 1rem; }
  .btn { background: #3b82f6; color: #fff; border: none; padding: 0.6rem 1.2rem;
         border-radius: 8px; font-size: 0.9rem; cursor: pointer;
         transition: background 0.2s; }
  .btn:hover { background: #2563eb; }
  .btn:disabled { background: #475569; cursor: not-allowed; }
  .btn-sm { padding: 0.4rem 0.8rem; font-size: 0.8rem; }
  .btn-red { background: #dc2626; }
  .btn-red:hover { background: #b91c1c; }
  .btn-green { background: #16a34a; }
  .btn-green:hover { background: #15803d; }
  .btn-full { width: 100%; }
  .spinner { display: inline-block; width: 16px; height: 16px;
             border: 2px solid #fff; border-top-color: transparent;
             border-radius: 50%; animation: spin 0.8s linear infinite;
             vertical-align: middle; margin-right: 6px; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .input-row { display: flex; gap: 0.5rem; margin-bottom: 0.75rem; }
  input[type="text"], input[type="number"] {
    background: #0f172a; border: 1px solid #334155; color: #e2e8f0;
    padding: 0.6rem 0.75rem; border-radius: 8px; font-size: 0.9rem;
    flex: 1; outline: none; }
  input:focus { border-color: #3b82f6; }
  .domain-list { list-style: none; }
  .domain-list li { display: flex; align-items: center; justify-content: space-between;
                     padding: 0.5rem 0.75rem; background: #0f172a; border-radius: 8px;
                     margin-bottom: 0.5rem; font-family: monospace; font-size: 0.9rem; }
  .ip-box { background: #0f172a; border-radius: 8px; padding: 1rem;
            margin-bottom: 1rem; display: flex; justify-content: space-between;
            align-items: center; }
  .ip-label { color: #94a3b8; font-size: 0.85rem; }
  .ip-value { font-family: monospace; font-size: 1.1rem; color: #22c55e; }
  table { width: 100%; border-collapse: collapse; margin-top: 0.5rem; }
  th { text-align: left; padding: 0.5rem 0.6rem; color: #94a3b8;
       font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em;
       border-bottom: 1px solid #334155; }
  td { padding: 0.5rem 0.6rem; border-bottom: 1px solid #1e293b; font-size: 0.85rem; }
  tr:hover td { background: #1e293b; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px;
           font-size: 0.75rem; font-weight: 600; }
  .badge-ok { background: #14532d; color: #4ade80; }
  .badge-update { background: #7c2d12; color: #fb923c; }
  .badge-active { background: #1e3a5f; color: #60a5fa; }
  .error { background: #7f1d1d; border: 1px solid #991b1b; border-radius: 8px;
           padding: 1rem; color: #fca5a5; margin-bottom: 1rem; display: none; }
  .error.show { display: block; }
  .success { background: #14532d; border: 1px solid #166534; border-radius: 8px;
             padding: 1rem; color: #4ade80; margin-bottom: 1rem; display: none; }
  .success.show { display: block; }
  .hidden { display: none; }
  .section-label { color: #94a3b8; font-size: 0.8rem; margin-bottom: 0.5rem; }
  .interval-row { display: flex; align-items: center; gap: 0.5rem; margin-top: 0.75rem; }
  .interval-row label { color: #94a3b8; font-size: 0.85rem; white-space: nowrap; }
  .interval-row input { width: 100px; }
  .check-col { width: 40px; text-align: center; }
  input[type="checkbox"] { width: 18px; height: 18px; accent-color: #3b82f6; cursor: pointer; }
</style>
</head>
<body>
<div class="container">
  <h1>KAS DDNS Updater</h1>
  <p class="subtitle">DNS A-Records automatisch aktualisieren</p>

  <div class="error" id="error"></div>
  <div class="success" id="success"></div>

  <!-- Step 1: Domain Management -->
  <div class="card">
    <h2>1. Domains verwalten</h2>
    <div class="input-row">
      <input type="text" id="domainInput" placeholder="z.B. example.de" onkeydown="if(event.key==='Enter')addDomain()">
      <button class="btn btn-sm" onclick="addDomain()">Hinzufuegen</button>
    </div>
    <ul class="domain-list" id="domainList"></ul>
    <div class="interval-row">
      <label>Update-Intervall:</label>
      <input type="number" id="intervalInput" min="60" step="60" value="300">
      <label>Sekunden</label>
    </div>
  </div>

  <!-- Step 2: Test Connection -->
  <div class="card">
    <h2>2. Verbindung testen</h2>
    <button class="btn btn-full" id="testBtn" onclick="testConnection()">
      Verbindung testen &amp; A-Records laden
    </button>
  </div>

  <!-- Step 3: Select Records -->
  <div class="card hidden" id="recordsCard">
    <h2>3. A-Records auswaehlen</h2>
    <div class="ip-box">
      <div>
        <div class="ip-label">Deine aktuelle oeffentliche IP</div>
        <div class="ip-value" id="currentIp">-</div>
      </div>
    </div>
    <p class="section-label">Waehle die Records, die automatisch aktualisiert werden sollen:</p>
    <table>
      <thead>
        <tr>
          <th class="check-col"></th>
          <th>Record</th>
          <th>Zone</th>
          <th>Aktuelle IP</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody id="recordsBody"></tbody>
    </table>
    <div style="margin-top:1rem;">
      <button class="btn btn-green btn-full" onclick="saveSelection()">
        Auswahl speichern &amp; DDNS aktivieren
      </button>
    </div>
  </div>

  <!-- Status -->
  <div class="card hidden" id="statusCard">
    <h2>Status</h2>
    <div id="activeRecords"></div>
  </div>

  <!-- Debug -->
  <div class="card">
    <div style="display:flex; justify-content:space-between; align-items:center; cursor:pointer"
         onclick="document.getElementById('debugContent').classList.toggle('hidden'); this.querySelector('span').textContent = document.getElementById('debugContent').classList.contains('hidden') ? '&#9654;' : '&#9660;'">
      <h2 style="margin:0">Debug</h2>
      <span style="color:#94a3b8">&#9654;</span>
    </div>
    <div id="debugContent" class="hidden" style="margin-top:1rem">
      <button class="btn btn-full" id="debugBtn" onclick="runDebug()" style="background:#6366f1">
        KAS API Raw Response laden
      </button>
      <pre id="debugOutput" style="margin-top:1rem; background:#0f172a; border-radius:8px;
           padding:1rem; font-size:0.75rem; overflow-x:auto; max-height:500px;
           overflow-y:auto; white-space:pre-wrap; word-break:break-all; display:none"></pre>
    </div>
  </div>
</div>

<script>
let domains = [];
let interval = 300;
let records = [];
let savedRecordIds = [];

async function loadConfig() {
  try {
    const resp = await fetch('/api/config');
    const cfg = await resp.json();
    domains = cfg.domains || [];
    savedRecordIds = cfg.record_ids || [];
    interval = cfg.update_interval || 300;
    document.getElementById('intervalInput').value = interval;
    renderDomains();
    if (savedRecordIds.length > 0) {
      showStatus();
    }
  } catch(e) {}
}

function renderDomains() {
  const ul = document.getElementById('domainList');
  ul.innerHTML = '';
  domains.forEach((d, i) => {
    ul.innerHTML += '<li>' + esc(d)
      + ' <button class="btn btn-sm btn-red" onclick="removeDomain('+i+')">Entfernen</button></li>';
  });
}

function addDomain() {
  const inp = document.getElementById('domainInput');
  const val = inp.value.trim().toLowerCase();
  if (!val || domains.includes(val)) return;
  domains.push(val);
  inp.value = '';
  renderDomains();
}

function removeDomain(i) {
  domains.splice(i, 1);
  renderDomains();
}

async function testConnection() {
  if (domains.length === 0) {
    showError('Bitte mindestens eine Domain hinzufuegen.');
    return;
  }
  const btn = document.getElementById('testBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Verbinde mit KAS API...';
  hideMessages();
  document.getElementById('recordsCard').classList.add('hidden');

  try {
    const resp = await fetch('/api/test', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ domains: domains })
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || 'Unbekannter Fehler');

    document.getElementById('currentIp').textContent = data.current_ip;
    records = data.records;
    const tbody = document.getElementById('recordsBody');
    tbody.innerHTML = '';
    records.forEach(r => {
      const match = r.current_ip === data.current_ip;
      const badge = match
        ? '<span class="badge badge-ok">Aktuell</span>'
        : '<span class="badge badge-update">Update noetig</span>';
      const checked = savedRecordIds.includes(r.record_id) ? 'checked' : '';
      tbody.innerHTML += '<tr>'
        + '<td class="check-col"><input type="checkbox" value="'+esc(r.record_id)+'" '+checked+'></td>'
        + '<td>' + esc(r.name || '@') + '</td>'
        + '<td>' + esc(r.zone) + '</td>'
        + '<td style="font-family:monospace">' + esc(r.current_ip) + '</td>'
        + '<td>' + badge + '</td></tr>';
    });
    document.getElementById('recordsCard').classList.remove('hidden');
  } catch(e) {
    showError(e.message);
  }
  btn.disabled = false;
  btn.innerHTML = 'Verbindung testen &amp; A-Records laden';
}

async function saveSelection() {
  const checks = document.querySelectorAll('#recordsBody input[type=checkbox]:checked');
  const ids = Array.from(checks).map(c => c.value);
  interval = parseInt(document.getElementById('intervalInput').value) || 300;

  try {
    const resp = await fetch('/api/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        domains: domains,
        record_ids: ids,
        update_interval: interval
      })
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || 'Fehler beim Speichern');
    savedRecordIds = ids;
    showSuccess('Konfiguration gespeichert! DDNS Updater ist aktiv.');
    showStatus();
  } catch(e) {
    showError(e.message);
  }
}

function showStatus() {
  const card = document.getElementById('statusCard');
  const div = document.getElementById('activeRecords');
  if (savedRecordIds.length === 0) {
    card.classList.add('hidden');
    return;
  }
  card.classList.remove('hidden');
  let html = '<p class="section-label">Aktive Records (Update alle ' + interval + 's):</p>';
  savedRecordIds.forEach(id => {
    const r = records.find(x => x.record_id === id);
    const label = r ? (r.name || '@') + '.' + r.zone : 'Record #' + id;
    html += '<span class="badge badge-active" style="margin:2px">' + esc(label) + '</span> ';
  });
  div.innerHTML = html;
}

function showError(msg) {
  const el = document.getElementById('error');
  el.textContent = 'Fehler: ' + msg;
  el.classList.add('show');
}
function showSuccess(msg) {
  const el = document.getElementById('success');
  el.textContent = msg;
  el.classList.add('show');
}
function hideMessages() {
  document.getElementById('error').classList.remove('show');
  document.getElementById('success').classList.remove('show');
}

async function runDebug() {
  if (domains.length === 0) { showError('Bitte mindestens eine Domain hinzufuegen.'); return; }
  const btn = document.getElementById('debugBtn');
  const out = document.getElementById('debugOutput');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Lade Raw Response...';
  out.style.display = 'none';
  try {
    const resp = await fetch('/api/debug', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ domain: domains[0] })
    });
    const data = await resp.json();
    out.textContent = JSON.stringify(data, null, 2);
    out.style.display = 'block';
  } catch(e) {
    out.textContent = 'Error: ' + e.message;
    out.style.display = 'block';
  }
  btn.disabled = false;
  btn.innerHTML = 'KAS API Raw Response laden';
}
function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

loadConfig();
</script>
</body>
</html>"""

# ── KAS API Functions ────────────────────────────────────────────────────────


def get_public_ip() -> str:
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
    # Try sha1 first, fall back to plain if disabled
    for auth_type, auth_val in [
        ("sha1", hashlib.sha1(password.encode()).hexdigest()),
        ("plain", password),
    ]:
        token = _try_auth(login, auth_type, auth_val)
        if token:
            return token
    raise RuntimeError("KAS authentication failed with both sha1 and plain")


def _try_auth(login: str, auth_type: str, auth_data: str) -> str | None:
    params_json = json.dumps({
        "KasUser": login,
        "KasAuthType": auth_type,
        "KasAuthData": auth_data,
    })

    soap_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"
  xmlns:ns1="urn:xmethodsKasApi"
  xmlns:xsd="http://www.w3.org/2001/XMLSchema"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xmlns:SOAP-ENC="http://schemas.xmlsoap.org/soap/encoding/"
  SOAP-ENV:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <SOAP-ENV:Body>
    <ns1:KasAuth>
      <Params xsi:type="xsd:string">{params_json}</Params>
    </ns1:KasAuth>
  </SOAP-ENV:Body>
</SOAP-ENV:Envelope>"""

    resp = requests.post(
        KAS_AUTH_URL,
        data=soap_body.encode("utf-8"),
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "urn:xmethodsKasApi#KasAuth",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        log.warning("Auth with %s failed: HTTP %d", auth_type, resp.status_code)
        return None
    if "Fault" in resp.text:
        log.warning("Auth with %s failed: %s", auth_type, resp.text[:200])
        return None
    try:
        return _parse_auth_token(resp.text)
    except RuntimeError:
        log.warning("Auth with %s: could not parse token", auth_type)
        return None


def _parse_auth_token(xml_text: str) -> str:
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
    params_json = json.dumps({
        "KasUser": login,
        "KasAuthType": "session",
        "KasAuthData": token,
        "KasRequestType": action,
        "KasRequestParams": params or {},
    })

    soap_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"
  xmlns:ns1="urn:xmethodsKasApi"
  xmlns:xsd="http://www.w3.org/2001/XMLSchema"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xmlns:SOAP-ENC="http://schemas.xmlsoap.org/soap/encoding/"
  SOAP-ENV:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <SOAP-ENV:Body>
    <ns1:KasApi>
      <Params xsi:type="xsd:string">{params_json}</Params>
    </ns1:KasApi>
  </SOAP-ENV:Body>
</SOAP-ENV:Envelope>"""

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
    records = []
    root = ElementTree.fromstring(xml_text)

    current_record = {}
    key = None
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

        if tag == "key" and elem.text:
            key = elem.text.strip()
        elif tag == "value" and elem.text:
            value = elem.text.strip()
            if key:
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
    xml = kas_api_call(token, login, "get_dns_settings", {"zone_host": zone})
    log.info("Raw KAS DNS response (first 2000 chars): %s", xml[:2000])
    records = parse_dns_records(xml)
    log.info("Parsed %d records: %s", len(records), records)
    return records


def update_dns_record(token: str, login: str, record_id: str, new_ip: str) -> bool:
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


@app.route("/api/debug", methods=["POST"])
def api_debug():
    """Return raw KAS API response for debugging."""
    login = os.environ.get("KAS_LOGIN")
    password = os.environ.get("KAS_PASSWORD")
    data = flask_request.get_json() or {}
    domain = data.get("domain", "")

    if not login or not password or not domain:
        return jsonify({"error": "Missing login, password or domain"}), 400

    try:
        token = kas_auth(login, password)
        parts = domain.split(".")
        zone = ".".join(parts[-2:]) + "." if len(parts) >= 2 else domain + "."
        time.sleep(3)
        xml = kas_api_call(token, login, "get_dns_settings", {"zone_host": zone})
        return jsonify({
            "zone": zone,
            "auth": "ok",
            "token_preview": token[:10] + "...",
            "raw_xml": xml[:5000],
            "parsed": parse_dns_records(xml),
        })
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


@app.route("/api/config", methods=["GET"])
def get_config():
    return jsonify(load_config())


@app.route("/api/config", methods=["POST"])
def set_config():
    data = flask_request.get_json()
    if not data:
        return jsonify({"error": "Keine Daten empfangen"}), 400

    cfg = load_config()
    if "domains" in data:
        cfg["domains"] = [d.strip().lower() for d in data["domains"] if d.strip()]
    if "record_ids" in data:
        cfg["record_ids"] = data["record_ids"]
    if "update_interval" in data:
        cfg["update_interval"] = max(60, int(data["update_interval"]))

    save_config(cfg)
    log.info("Config saved: %s", cfg)
    return jsonify({"ok": True})


@app.route("/api/test", methods=["POST"])
def api_test():
    login = os.environ.get("KAS_LOGIN")
    password = os.environ.get("KAS_PASSWORD")

    if not login or not password:
        return jsonify({"error": "KAS_LOGIN oder KAS_PASSWORD nicht konfiguriert"}), 500

    data = flask_request.get_json() or {}
    domain_list = data.get("domains", [])

    if not domain_list:
        return jsonify({"error": "Keine Domains angegeben"}), 400

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
    login = os.environ.get("KAS_LOGIN")
    password = os.environ.get("KAS_PASSWORD")

    if not login or not password:
        log.error("Missing required env vars: KAS_LOGIN, KAS_PASSWORD")
        return

    cfg = load_config()
    domain_list = cfg.get("domains", [])
    record_ids = set(cfg.get("record_ids", []))

    if not domain_list or not record_ids:
        log.info("No domains or records configured yet - skipping update")
        return

    current_ip = get_public_ip()
    log.info("Current public IP: %s", current_ip)

    log.info("Authenticating with KAS API as %s...", login)
    token = kas_auth(login, password)
    log.info("Authentication successful")

    seen_zones = set()
    for domain in domain_list:
        parts = domain.split(".")
        zone = ".".join(parts[-2:]) + "." if len(parts) >= 2 else domain + "."

        if zone in seen_zones:
            continue
        seen_zones.add(zone)

        log.info("Processing zone: %s", zone)
        time.sleep(3)

        records = get_dns_records(token, login, zone)

        for record in records:
            record_id = record.get("record_id", "")
            record_name = record.get("record_name", "")
            record_data = record.get("record_data", "")

            if record.get("record_type") != "A" or record_id not in record_ids:
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
            else:
                log.error("  Failed to update record %s", record_name or "@")

    log.info("DDNS update cycle complete")


def update_loop():
    while True:
        cfg = load_config()
        interval = cfg.get("update_interval", 300)

        try:
            run_update()
        except Exception:
            log.exception("Error during update cycle")

        log.info("Next update in %d seconds...", interval)
        time.sleep(interval)


def main():
    log.info("KAS DDNS Updater starting")

    t = threading.Thread(target=update_loop, daemon=True)
    t.start()

    app.run(host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
