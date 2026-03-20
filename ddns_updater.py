"""KAS DDNS Updater v2.0 - Updates ALL-INKL DNS A-Records with current public IP."""

import json
import logging
import os
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
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

IP_SERVICES = [
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://icanhazip.com",
    "https://checkip.amazonaws.com",
]

VERSION = "2.0.0"

CONFIG_PATH = Path(os.getenv("CONFIG_PATH", "/data/config.json"))

app = Flask(__name__)

# ── State & Log Buffer ──────────────────────────────────────────────────────

app_state = {
    "last_check": None,
    "next_check": None,
    "last_update": None,
    "current_ip": None,
    "records_status": {},
    "update_count": 0,
    "error_count": 0,
    "running": False,
}
state_lock = threading.Lock()

log_buffer = deque(maxlen=200)
log_lock = threading.Lock()


def add_log(level: str, message: str):
    """Add a log entry to the in-memory buffer and also print it."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "message": message,
    }
    with log_lock:
        log_buffer.append(entry)
    # Also log to stdout
    getattr(log, level if level != "success" else "info")(message)


# ── Config Persistence ───────────────────────────────────────────────────────

def load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {"domains": [], "record_ids": [], "record_labels": {}, "update_interval": 300}


def save_config(cfg: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


# ── HTML Web UI ──────────────────────────────────────────────────────────────

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KAS DDNS Updater</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0f172a; color: #e2e8f0; min-height: 100vh; }
  .container { max-width: 900px; margin: 0 auto; padding: 1.5rem; }

  /* Header */
  .header { display: flex; justify-content: space-between; align-items: baseline;
            margin-bottom: 0.25rem; }
  h1 { font-size: 1.5rem; }
  .version { color: #475569; font-size: 0.75rem; font-family: monospace; }
  .subtitle { color: #94a3b8; margin-bottom: 1rem; font-size: 0.9rem; }

  /* Tabs */
  .tabs { display: flex; gap: 0; border-bottom: 2px solid #1e293b; margin-bottom: 1.5rem; }
  .tab { padding: 0.75rem 1.5rem; cursor: pointer; color: #94a3b8; font-size: 0.9rem;
         font-weight: 500; border-bottom: 2px solid transparent; margin-bottom: -2px;
         transition: all 0.2s; user-select: none; }
  .tab:hover { color: #e2e8f0; }
  .tab.active { color: #3b82f6; border-bottom-color: #3b82f6; }
  .tab-content { display: none; }
  .tab-content.active { display: block; }

  /* Cards */
  .card { background: #1e293b; border-radius: 12px; padding: 1.5rem;
          border: 1px solid #334155; margin-bottom: 1rem; }
  .card h2 { font-size: 1.1rem; margin-bottom: 1rem; }
  .card h3 { font-size: 0.95rem; margin-bottom: 0.75rem; color: #cbd5e1; }

  /* Stat Cards Grid */
  .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                gap: 0.75rem; margin-bottom: 1rem; }
  .stat-card { background: #0f172a; border-radius: 10px; padding: 1rem;
               border: 1px solid #334155; }
  .stat-label { color: #94a3b8; font-size: 0.75rem; text-transform: uppercase;
                letter-spacing: 0.05em; margin-bottom: 0.25rem; }
  .stat-value { font-size: 1.25rem; font-weight: 600; font-family: monospace; }
  .stat-value.ip { color: #22c55e; }
  .stat-value.count { color: #3b82f6; }
  .stat-value.ok { color: #4ade80; }
  .stat-value.warn { color: #fb923c; }
  .stat-value.error { color: #f87171; }
  .stat-sub { color: #64748b; font-size: 0.75rem; margin-top: 0.25rem; }

  /* Buttons */
  .btn { background: #3b82f6; color: #fff; border: none; padding: 0.6rem 1.2rem;
         border-radius: 8px; font-size: 0.9rem; cursor: pointer;
         transition: background 0.2s; display: inline-flex; align-items: center; gap: 0.5rem; }
  .btn:hover { background: #2563eb; }
  .btn:disabled { background: #475569; cursor: not-allowed; }
  .btn-sm { padding: 0.4rem 0.8rem; font-size: 0.8rem; }
  .btn-red { background: #dc2626; }
  .btn-red:hover { background: #b91c1c; }
  .btn-green { background: #16a34a; }
  .btn-green:hover { background: #15803d; }
  .btn-orange { background: #ea580c; }
  .btn-orange:hover { background: #c2410c; }
  .btn-full { width: 100%; justify-content: center; }
  .btn-group { display: flex; gap: 0.5rem; margin-bottom: 1rem; flex-wrap: wrap; }

  /* Spinner */
  .spinner { display: inline-block; width: 16px; height: 16px;
             border: 2px solid #fff; border-top-color: transparent;
             border-radius: 50%; animation: spin 0.8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* Inputs */
  .input-row { display: flex; gap: 0.5rem; margin-bottom: 0.75rem; }
  input[type="text"], input[type="number"] {
    background: #0f172a; border: 1px solid #334155; color: #e2e8f0;
    padding: 0.6rem 0.75rem; border-radius: 8px; font-size: 0.9rem;
    flex: 1; outline: none; }
  input:focus { border-color: #3b82f6; }

  /* Domain list */
  .domain-list { list-style: none; }
  .domain-list li { display: flex; align-items: center; justify-content: space-between;
                    padding: 0.5rem 0.75rem; background: #0f172a; border-radius: 8px;
                    margin-bottom: 0.5rem; font-family: monospace; font-size: 0.9rem; }

  /* Interval row */
  .interval-row { display: flex; align-items: center; gap: 0.5rem; margin-top: 0.75rem; }
  .interval-row label { color: #94a3b8; font-size: 0.85rem; white-space: nowrap; }
  .interval-row input { width: 100px; }

  /* Table */
  table { width: 100%; border-collapse: collapse; margin-top: 0.5rem; }
  th { text-align: left; padding: 0.5rem 0.6rem; color: #94a3b8;
       font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em;
       border-bottom: 1px solid #334155; }
  td { padding: 0.5rem 0.6rem; border-bottom: 1px solid #1e293b; font-size: 0.85rem; }
  tr:hover td { background: rgba(59,130,246,0.05); }
  .check-col { width: 40px; text-align: center; }
  input[type="checkbox"] { width: 18px; height: 18px; accent-color: #3b82f6; cursor: pointer; }

  /* Badges */
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px;
           font-size: 0.75rem; font-weight: 600; }
  .badge-ok { background: #14532d; color: #4ade80; }
  .badge-update { background: #7c2d12; color: #fb923c; }
  .badge-error { background: #7f1d1d; color: #fca5a5; }
  .badge-active { background: #1e3a5f; color: #60a5fa; }
  .badge-pending { background: #3b3b0f; color: #fde047; }

  /* Messages */
  .msg { border-radius: 8px; padding: 1rem; margin-bottom: 1rem; display: none; }
  .msg.show { display: block; }
  .msg-error { background: #7f1d1d; border: 1px solid #991b1b; color: #fca5a5; }
  .msg-success { background: #14532d; border: 1px solid #166534; color: #4ade80; }

  /* Log viewer */
  .log-container { background: #0f172a; border-radius: 8px; border: 1px solid #334155;
                   height: 500px; overflow-y: auto; padding: 0.75rem; font-family: 'Cascadia Code',
                   'Fira Code', 'JetBrains Mono', monospace; font-size: 0.8rem; line-height: 1.6; }
  .log-entry { padding: 2px 0; border-bottom: 1px solid #1e293b; }
  .log-time { color: #64748b; margin-right: 0.5rem; }
  .log-level { display: inline-block; width: 60px; font-weight: 600; text-transform: uppercase; }
  .log-level.info { color: #60a5fa; }
  .log-level.success { color: #4ade80; }
  .log-level.warning { color: #fbbf24; }
  .log-level.error { color: #f87171; }
  .log-msg { color: #cbd5e1; }

  .section-label { color: #94a3b8; font-size: 0.8rem; margin-bottom: 0.5rem; }
  .hidden { display: none; }

  /* Pulse animation for active indicator */
  .pulse { display: inline-block; width: 8px; height: 8px; background: #4ade80;
           border-radius: 50%; margin-right: 0.5rem; animation: pulse 2s ease-in-out infinite; }
  .pulse.inactive { background: #64748b; animation: none; }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }

  /* No-data placeholder */
  .empty-state { text-align: center; padding: 3rem 1rem; color: #64748b; }
  .empty-state p { margin-top: 0.5rem; font-size: 0.9rem; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>KAS DDNS Updater</h1>
    <span class="version">{{VERSION}}</span>
  </div>
  <p class="subtitle">DNS A-Records automatisch aktualisieren</p>

  <div class="msg msg-error" id="globalError"></div>
  <div class="msg msg-success" id="globalSuccess"></div>

  <!-- Tab Navigation -->
  <div class="tabs">
    <div class="tab active" data-tab="dashboard" onclick="switchTab('dashboard')">Dashboard</div>
    <div class="tab" data-tab="records" onclick="switchTab('records')">DNS Records</div>
    <div class="tab" data-tab="logs" onclick="switchTab('logs')">Logs</div>
  </div>

  <!-- ═══ TAB: Dashboard ═══ -->
  <div class="tab-content active" id="tab-dashboard">
    <div id="dashboardEmpty" class="card">
      <div class="empty-state">
        <p style="font-size:2rem">&#9881;</p>
        <p><strong>Noch keine Records konfiguriert</strong></p>
        <p>Wechsle zum Tab "DNS Records", um Domains und A-Records hinzuzufuegen.</p>
      </div>
    </div>

    <div id="dashboardContent" class="hidden">
      <!-- Stats -->
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">Oeffentliche IP</div>
          <div class="stat-value ip" id="dashIp">-</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Ueberwachte Records</div>
          <div class="stat-value count" id="dashTotal">0</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Aktuell</div>
          <div class="stat-value ok" id="dashOk">0</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Update noetig</div>
          <div class="stat-value warn" id="dashOutdated">0</div>
        </div>
      </div>

      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">Letzter Check</div>
          <div class="stat-value" id="dashLastCheck" style="font-size:0.95rem;color:#cbd5e1">-</div>
          <div class="stat-sub" id="dashLastCheckRel"></div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Naechster Check</div>
          <div class="stat-value" id="dashNextCheck" style="font-size:0.95rem;color:#cbd5e1">-</div>
          <div class="stat-sub" id="dashCountdown"></div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Updates gesamt</div>
          <div class="stat-value count" id="dashUpdates">0</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Fehler</div>
          <div class="stat-value error" id="dashErrors">0</div>
        </div>
      </div>

      <!-- Actions -->
      <div class="btn-group">
        <button class="btn" id="checkBtn" onclick="manualCheck()">
          &#128269; Jetzt pruefen
        </button>
        <button class="btn btn-orange" id="updateBtn" onclick="manualUpdate()">
          &#9889; Jetzt aktualisieren
        </button>
      </div>

      <!-- Records Table -->
      <div class="card">
        <h2><span class="pulse" id="dashPulse"></span>Ueberwachte A-Records</h2>
        <table>
          <thead>
            <tr>
              <th>Record</th>
              <th>Zone</th>
              <th>DNS IP</th>
              <th>Soll IP</th>
              <th>Status</th>
              <th>Letztes Update</th>
            </tr>
          </thead>
          <tbody id="dashRecordsBody"></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- ═══ TAB: DNS Records ═══ -->
  <div class="tab-content" id="tab-records">
    <div class="card">
      <h2>Domains verwalten</h2>
      <div class="input-row">
        <input type="text" id="domainInput" placeholder="z.B. example.de"
               onkeydown="if(event.key==='Enter')addDomain()">
        <button class="btn btn-sm" onclick="addDomain()">Hinzufuegen</button>
      </div>
      <ul class="domain-list" id="domainList"></ul>
      <div class="interval-row">
        <label>Update-Intervall:</label>
        <input type="number" id="intervalInput" min="60" step="60" value="300">
        <label>Sekunden</label>
      </div>
    </div>

    <div class="card">
      <h2>Verbindung testen</h2>
      <button class="btn btn-full" id="testBtn" onclick="testConnection()">
        Verbindung testen &amp; A-Records laden
      </button>
    </div>

    <div class="card hidden" id="recordsCard">
      <h2>A-Records auswaehlen</h2>
      <div style="background:#0f172a;border-radius:8px;padding:1rem;margin-bottom:1rem;
                  display:flex;justify-content:space-between;align-items:center">
        <div>
          <div class="stat-label">Deine aktuelle oeffentliche IP</div>
          <div style="font-family:monospace;font-size:1.1rem;color:#22c55e" id="currentIp">-</div>
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
      <div style="margin-top:1rem">
        <button class="btn btn-green btn-full" onclick="saveSelection()">
          Auswahl speichern &amp; DDNS aktivieren
        </button>
      </div>
    </div>
  </div>

  <!-- ═══ TAB: Logs ═══ -->
  <div class="tab-content" id="tab-logs">
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">
        <h2 style="margin:0">Live Logs</h2>
        <div class="btn-group" style="margin:0">
          <button class="btn btn-sm log-filter active" data-filter="all" onclick="setLogFilter('all')">Alle</button>
          <button class="btn btn-sm log-filter" data-filter="error" onclick="setLogFilter('error')" style="background:#7f1d1d">Fehler</button>
          <button class="btn btn-sm log-filter" data-filter="success" onclick="setLogFilter('success')" style="background:#14532d">Updates</button>
        </div>
      </div>
      <div class="log-container" id="logContainer"></div>
    </div>
  </div>
</div>

<script>
// ── State ──
let domains = [];
let interval = 300;
let records = [];
let savedRecordIds = [];
let savedRecordLabels = {};
let currentLogFilter = 'all';
let statusInterval = null;
let logInterval = null;
let lastLogCount = 0;
let nextCheckTime = null;

// ── Tab Navigation ──
function switchTab(tab) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelector('[data-tab="'+tab+'"]').classList.add('active');
  document.getElementById('tab-'+tab).classList.add('active');
  window.location.hash = tab;

  if (tab === 'dashboard') refreshStatus();
  if (tab === 'logs') refreshLogs();
}

// ── Init ──
async function init() {
  await loadConfig();
  await refreshStatus();

  // Auto-refresh
  statusInterval = setInterval(refreshStatus, 10000);
  logInterval = setInterval(() => {
    if (document.querySelector('[data-tab="logs"]').classList.contains('active')) {
      refreshLogs();
    }
  }, 5000);

  // Countdown ticker
  setInterval(updateCountdown, 1000);

  // Hash navigation
  const hash = window.location.hash.replace('#','');
  if (['dashboard','records','logs'].includes(hash)) switchTab(hash);
}

// ── Config ──
async function loadConfig() {
  try {
    const resp = await fetch('/api/config');
    const cfg = await resp.json();
    domains = cfg.domains || [];
    savedRecordIds = cfg.record_ids || [];
    savedRecordLabels = cfg.record_labels || {};
    interval = cfg.update_interval || 300;
    document.getElementById('intervalInput').value = interval;
    renderDomains();
  } catch(e) {}
}

// ── Dashboard ──
async function refreshStatus() {
  try {
    const resp = await fetch('/api/status');
    const s = await resp.json();

    const hasRecords = Object.keys(s.records_status).length > 0;
    document.getElementById('dashboardEmpty').classList.toggle('hidden', hasRecords);
    document.getElementById('dashboardContent').classList.toggle('hidden', !hasRecords);

    if (!hasRecords) return;

    document.getElementById('dashIp').textContent = s.current_ip || '-';

    const recs = Object.values(s.records_status);
    const total = recs.length;
    const ok = recs.filter(r => r.status === 'ok').length;
    const outdated = recs.filter(r => r.status === 'outdated').length;

    document.getElementById('dashTotal').textContent = total;
    document.getElementById('dashOk').textContent = ok;
    document.getElementById('dashOutdated').textContent = outdated;
    document.getElementById('dashUpdates').textContent = s.update_count;
    document.getElementById('dashErrors').textContent = s.error_count;

    // Pulse indicator
    document.getElementById('dashPulse').classList.toggle('inactive', !s.running);

    // Timestamps
    if (s.last_check) {
      const d = new Date(s.last_check);
      document.getElementById('dashLastCheck').textContent = d.toLocaleTimeString('de-DE');
      document.getElementById('dashLastCheckRel').textContent = timeAgo(d);
    }
    if (s.next_check) {
      nextCheckTime = new Date(s.next_check);
      document.getElementById('dashNextCheck').textContent = nextCheckTime.toLocaleTimeString('de-DE');
      updateCountdown();
    }

    // Records table
    const tbody = document.getElementById('dashRecordsBody');
    tbody.innerHTML = '';
    for (const [id, r] of Object.entries(s.records_status)) {
      let badge = '';
      if (r.status === 'ok') badge = '<span class="badge badge-ok">Aktuell</span>';
      else if (r.status === 'outdated') badge = '<span class="badge badge-update">Update noetig</span>';
      else if (r.status === 'error') badge = '<span class="badge badge-error">Fehler</span>';
      else badge = '<span class="badge badge-pending">Warte...</span>';

      const lastUp = r.last_updated ? new Date(r.last_updated).toLocaleString('de-DE') : '-';

      tbody.innerHTML += '<tr>'
        + '<td>' + esc(r.name || '@') + '</td>'
        + '<td>' + esc(r.zone || '') + '</td>'
        + '<td style="font-family:monospace">' + esc(r.dns_ip || '-') + '</td>'
        + '<td style="font-family:monospace">' + esc(s.current_ip || '-') + '</td>'
        + '<td>' + badge + '</td>'
        + '<td style="font-size:0.8rem;color:#94a3b8">' + lastUp + '</td>'
        + '</tr>';
    }
  } catch(e) { console.error('Status refresh failed:', e); }
}

function updateCountdown() {
  if (!nextCheckTime) return;
  const diff = Math.max(0, Math.floor((nextCheckTime - new Date()) / 1000));
  const m = Math.floor(diff / 60);
  const s = diff % 60;
  document.getElementById('dashCountdown').textContent =
    diff > 0 ? 'in ' + m + ':' + String(s).padStart(2,'0') : 'jetzt...';
}

function timeAgo(date) {
  const s = Math.floor((new Date() - date) / 1000);
  if (s < 60) return 'vor ' + s + 's';
  if (s < 3600) return 'vor ' + Math.floor(s/60) + ' Min';
  if (s < 86400) return 'vor ' + Math.floor(s/3600) + ' Std';
  return 'vor ' + Math.floor(s/86400) + ' Tagen';
}

async function manualCheck() {
  const btn = document.getElementById('checkBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Pruefe...';
  try {
    const resp = await fetch('/api/check', {method:'POST'});
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error);
    showSuccess('Check abgeschlossen: ' + data.message);
    await refreshStatus();
  } catch(e) { showError(e.message); }
  btn.disabled = false;
  btn.innerHTML = '&#128269; Jetzt pruefen';
}

async function manualUpdate() {
  const btn = document.getElementById('updateBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Aktualisiere...';
  try {
    const resp = await fetch('/api/update', {method:'POST'});
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error);
    showSuccess('Update abgeschlossen: ' + data.message);
    await refreshStatus();
  } catch(e) { showError(e.message); }
  btn.disabled = false;
  btn.innerHTML = '&#9889; Jetzt aktualisieren';
}

// ── DNS Records Tab ──
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
  if (domains.length === 0) { showError('Bitte mindestens eine Domain hinzufuegen.'); return; }
  const btn = document.getElementById('testBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Verbinde mit KAS API...';
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
  } catch(e) { showError(e.message); }
  btn.disabled = false;
  btn.innerHTML = 'Verbindung testen &amp; A-Records laden';
}

async function saveSelection() {
  const checks = document.querySelectorAll('#recordsBody input[type=checkbox]:checked');
  const ids = Array.from(checks).map(c => c.value);
  interval = parseInt(document.getElementById('intervalInput').value) || 300;

  const labels = {};
  ids.forEach(id => {
    const r = records.find(x => x.record_id === id);
    if (r) labels[id] = (r.name || '@') + '.' + r.zone;
  });

  try {
    const resp = await fetch('/api/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ domains, record_ids: ids, record_labels: labels, update_interval: interval })
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || 'Fehler beim Speichern');
    savedRecordIds = ids;
    savedRecordLabels = labels;
    showSuccess('Konfiguration gespeichert! DDNS Updater ist aktiv.');
    // Switch to dashboard after saving
    setTimeout(() => switchTab('dashboard'), 1500);
  } catch(e) { showError(e.message); }
}

// ── Logs Tab ──
async function refreshLogs() {
  try {
    const resp = await fetch('/api/logs?filter=' + currentLogFilter);
    const data = await resp.json();
    const container = document.getElementById('logContainer');
    const wasScrolledToBottom = container.scrollTop + container.clientHeight >= container.scrollHeight - 50;

    container.innerHTML = '';
    data.logs.forEach(entry => {
      const div = document.createElement('div');
      div.className = 'log-entry';
      const ts = new Date(entry.timestamp).toLocaleString('de-DE');
      div.innerHTML = '<span class="log-time">' + ts + '</span>'
        + '<span class="log-level ' + entry.level + '">' + entry.level + '</span> '
        + '<span class="log-msg">' + esc(entry.message) + '</span>';
      container.appendChild(div);
    });

    if (wasScrolledToBottom || lastLogCount !== data.logs.length) {
      container.scrollTop = container.scrollHeight;
    }
    lastLogCount = data.logs.length;
  } catch(e) { console.error('Log refresh failed:', e); }
}

function setLogFilter(f) {
  currentLogFilter = f;
  document.querySelectorAll('.log-filter').forEach(b => {
    b.classList.toggle('active', b.dataset.filter === f);
    if (b.dataset.filter === f) b.style.opacity = '1';
    else b.style.opacity = '0.5';
  });
  refreshLogs();
}

// ── Helpers ──
function showError(msg) {
  const el = document.getElementById('globalError');
  el.textContent = 'Fehler: ' + msg;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 8000);
}
function showSuccess(msg) {
  const el = document.getElementById('globalSuccess');
  el.textContent = msg;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 5000);
}
function hideMessages() {
  document.getElementById('globalError').classList.remove('show');
  document.getElementById('globalSuccess').classList.remove('show');
}

function esc(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

init();
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


KAS_API_URL = "https://kasapi.kasserver.com/soap/KasApi.php"


def kas_api_call(login: str, password: str, action: str, params: dict | None = None) -> str:
    """Make a KAS API call with direct plain auth (no separate auth step)."""
    params_json = json.dumps({
        "kas_login": login,
        "kas_auth_type": "plain",
        "kas_auth_data": password,
        "kas_action": action,
        "KasRequestParams": params or {},
    })

    soap_body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"'
        ' xmlns:ns1="urn:xmethodsKasApi"'
        ' xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
        ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
        ' xmlns:SOAP-ENC="http://schemas.xmlsoap.org/soap/encoding/"'
        ' SOAP-ENV:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        '<SOAP-ENV:Body>'
        '<ns1:KasApi>'
        '<Params xsi:type="xsd:string">' + _xml_escape(params_json) + '</Params>'
        '</ns1:KasApi>'
        '</SOAP-ENV:Body>'
        '</SOAP-ENV:Envelope>'
    )

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


def _xml_escape(s: str) -> str:
    """Escape a string for safe embedding in XML."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def parse_dns_records(xml_text: str) -> list[dict]:
    """Parse DNS records from KAS SOAP response XML."""
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
        if k == "record_zone" and current and "record_id" in current:
            records.append(current)
            current = {}
        if k.startswith("record_"):
            current[k] = v
    if current and "record_id" in current:
        records.append(current)

    return records


def get_dns_records(login: str, password: str, zone: str) -> list[dict]:
    xml = kas_api_call(login, password, "get_dns_settings", {"zone_host": zone})
    records = parse_dns_records(xml)
    return records


def update_dns_record(login: str, password: str, record_id: str, new_ip: str) -> bool:
    try:
        xml = kas_api_call(
            login, password, "update_dns_settings",
            {"record_id": record_id, "record_data": new_ip},
        )
        return "Fault" not in xml
    except Exception as e:
        log.error("Update failed: %s", e)
        return False


def get_zone_for_domain(domain: str) -> str:
    """Extract zone from domain (e.g., 'sub.example.de' -> 'example.de.')."""
    parts = domain.split(".")
    return ".".join(parts[-2:]) + "." if len(parts) >= 2 else domain + "."


# ── Flask Routes ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return HTML_PAGE.replace("{{VERSION}}", f"v{VERSION}")


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
    if "record_labels" in data:
        cfg["record_labels"] = data["record_labels"]
    if "update_interval" in data:
        cfg["update_interval"] = max(60, int(data["update_interval"]))

    save_config(cfg)
    add_log("success", f"Konfiguration gespeichert: {len(cfg.get('record_ids', []))} Records aktiv")
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

    a_records = []
    seen_zones = set()

    for domain in domain_list:
        zone = get_zone_for_domain(domain)
        if zone in seen_zones:
            continue
        seen_zones.add(zone)

        try:
            time.sleep(3)
            records = get_dns_records(login, password, zone)
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

    add_log("info", f"Verbindungstest: {len(a_records)} A-Records gefunden")
    return jsonify({"current_ip": current_ip, "records": a_records})


@app.route("/api/status", methods=["GET"])
def api_status():
    """Return current dashboard state."""
    with state_lock:
        return jsonify({**app_state})


@app.route("/api/check", methods=["POST"])
def api_check():
    """Manual check - refresh record status without updating."""
    login = os.environ.get("KAS_LOGIN")
    password = os.environ.get("KAS_PASSWORD")

    if not login or not password:
        return jsonify({"error": "KAS Credentials fehlen"}), 500

    cfg = load_config()
    record_ids = set(cfg.get("record_ids", []))
    record_labels = cfg.get("record_labels", {})

    if not record_ids:
        return jsonify({"error": "Keine Records konfiguriert"}), 400

    try:
        current_ip = get_public_ip()
        _refresh_records_status(login, password, cfg, current_ip)
        add_log("info", f"Manueller Check: IP ist {current_ip}")

        with state_lock:
            recs = app_state["records_status"]
            ok = sum(1 for r in recs.values() if r["status"] == "ok")
            outdated = sum(1 for r in recs.values() if r["status"] == "outdated")

        return jsonify({"message": f"{ok} aktuell, {outdated} veraltet"})
    except Exception as e:
        add_log("error", f"Check fehlgeschlagen: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/update", methods=["POST"])
def api_update():
    """Manual update - update all outdated records now."""
    login = os.environ.get("KAS_LOGIN")
    password = os.environ.get("KAS_PASSWORD")

    if not login or not password:
        return jsonify({"error": "KAS Credentials fehlen"}), 500

    cfg = load_config()
    record_ids = set(cfg.get("record_ids", []))

    if not record_ids:
        return jsonify({"error": "Keine Records konfiguriert"}), 400

    try:
        current_ip = get_public_ip()
        updated, errors = _do_update(login, password, cfg, current_ip)
        return jsonify({"message": f"{updated} aktualisiert, {errors} Fehler"})
    except Exception as e:
        add_log("error", f"Manuelles Update fehlgeschlagen: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/logs", methods=["GET"])
def api_logs():
    """Return log entries from buffer."""
    filter_level = flask_request.args.get("filter", "all")
    with log_lock:
        entries = list(log_buffer)

    if filter_level == "error":
        entries = [e for e in entries if e["level"] in ("error", "warning")]
    elif filter_level == "success":
        entries = [e for e in entries if e["level"] == "success"]

    return jsonify({"logs": entries})


# ── Core Update Logic ────────────────────────────────────────────────────────

def _refresh_records_status(login: str, password: str, cfg: dict, current_ip: str):
    """Fetch current DNS state and update app_state."""
    record_ids = set(cfg.get("record_ids", []))
    record_labels = cfg.get("record_labels", {})
    domain_list = cfg.get("domains", [])
    now = datetime.now(timezone.utc).isoformat()

    new_status = {}
    seen_zones = set()

    for domain in domain_list:
        zone = get_zone_for_domain(domain)
        if zone in seen_zones:
            continue
        seen_zones.add(zone)

        try:
            time.sleep(3)
            records = get_dns_records(login, password, zone)
        except Exception as e:
            add_log("error", f"Fehler beim Laden von {zone}: {e}")
            # Mark all records of this zone as error
            for rid in record_ids:
                label = record_labels.get(rid, "")
                if label.endswith(zone.rstrip(".")):
                    new_status[rid] = {
                        "name": label.split(".")[0] if "." in label else "@",
                        "zone": zone.rstrip("."),
                        "dns_ip": "?",
                        "status": "error",
                        "last_updated": None,
                    }
            continue

        for record in records:
            rid = record.get("record_id", "")
            if rid not in record_ids or record.get("record_type") != "A":
                continue

            dns_ip = record.get("record_data", "")
            name = record.get("record_name", "") or "@"

            # Preserve last_updated from previous state
            prev = app_state.get("records_status", {}).get(rid, {})
            last_updated = prev.get("last_updated")

            new_status[rid] = {
                "name": name,
                "zone": zone.rstrip("."),
                "dns_ip": dns_ip,
                "status": "ok" if dns_ip == current_ip else "outdated",
                "last_updated": last_updated,
            }

    with state_lock:
        app_state["current_ip"] = current_ip
        app_state["records_status"] = new_status
        app_state["last_check"] = now


def _do_update(login: str, password: str, cfg: dict, current_ip: str) -> tuple[int, int]:
    """Update all outdated records. Returns (updated_count, error_count)."""
    record_ids = set(cfg.get("record_ids", []))
    record_labels = cfg.get("record_labels", {})

    # First refresh status
    _refresh_records_status(login, password, cfg, current_ip)

    updated = 0
    errors = 0
    now = datetime.now(timezone.utc).isoformat()

    with state_lock:
        outdated = {rid: info for rid, info in app_state["records_status"].items()
                    if info["status"] == "outdated"}

    for rid, info in outdated.items():
        label = f"{info['name']}.{info['zone']}"
        add_log("info", f"Aktualisiere {label}: {info['dns_ip']} -> {current_ip}")
        time.sleep(3)

        success = update_dns_record(login, password, rid, current_ip)
        if success:
            updated += 1
            add_log("success", f"{label} erfolgreich aktualisiert auf {current_ip}")
            with state_lock:
                if rid in app_state["records_status"]:
                    app_state["records_status"][rid]["dns_ip"] = current_ip
                    app_state["records_status"][rid]["status"] = "ok"
                    app_state["records_status"][rid]["last_updated"] = now
                app_state["update_count"] += 1
                app_state["last_update"] = now
        else:
            errors += 1
            add_log("error", f"Fehler beim Aktualisieren von {label}")
            with state_lock:
                if rid in app_state["records_status"]:
                    app_state["records_status"][rid]["status"] = "error"
                app_state["error_count"] += 1

    return updated, errors


# ── DDNS Background Update Loop ─────────────────────────────────────────────

def run_update():
    login = os.environ.get("KAS_LOGIN")
    password = os.environ.get("KAS_PASSWORD")

    if not login or not password:
        add_log("error", "KAS_LOGIN oder KAS_PASSWORD fehlt")
        return

    cfg = load_config()
    record_ids = set(cfg.get("record_ids", []))

    if not cfg.get("domains") or not record_ids:
        add_log("info", "Noch keine Domains/Records konfiguriert - ueberspringe")
        return

    try:
        with state_lock:
            app_state["running"] = True

        current_ip = get_public_ip()
        add_log("info", f"Aktuelle oeffentliche IP: {current_ip}")

        updated, errors = _do_update(login, password, cfg, current_ip)

        if updated > 0:
            add_log("success", f"Update-Zyklus abgeschlossen: {updated} aktualisiert, {errors} Fehler")
        else:
            add_log("info", "Alle Records sind aktuell")

    except Exception as e:
        add_log("error", f"Fehler im Update-Zyklus: {e}")
        with state_lock:
            app_state["error_count"] += 1
    finally:
        with state_lock:
            app_state["running"] = False


def update_loop():
    # Initial delay to let Flask start
    time.sleep(5)
    add_log("info", "DDNS Background-Updater gestartet")

    while True:
        cfg = load_config()
        interval = cfg.get("update_interval", 300)

        now = datetime.now(timezone.utc)
        with state_lock:
            app_state["next_check"] = (
                datetime.fromtimestamp(now.timestamp() + interval, tz=timezone.utc).isoformat()
            )

        try:
            run_update()
        except Exception:
            log.exception("Error during update cycle")

        cfg = load_config()
        interval = cfg.get("update_interval", 300)
        add_log("info", f"Naechster Check in {interval} Sekunden")

        with state_lock:
            app_state["next_check"] = (
                datetime.fromtimestamp(
                    datetime.now(timezone.utc).timestamp() + interval, tz=timezone.utc
                ).isoformat()
            )

        time.sleep(interval)


def main():
    add_log("info", f"KAS DDNS Updater v{VERSION} gestartet")

    t = threading.Thread(target=update_loop, daemon=True)
    t.start()

    app.run(host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
