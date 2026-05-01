from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, List, Union

import requests

app = FastAPI()

EDGE_DIR = Path("/opt/ively/edge")
if str(EDGE_DIR) not in sys.path:
    sys.path.insert(0, str(EDGE_DIR))

import agent.camera.onvif_scan as onvif_scan

AGENT_DIR = Path("/opt/ively/agent")
PROVISIONED_MARKER = Path("/opt/ively/.provisioned")
MEDIAMTX_CONFIG = Path("/opt/ively/mediamtx/mediamtx.yml")

# Cloud REST API (customer / site lists for provisioning UI). Override base if needed.
IVELY_API_BASE = (os.environ.get("IVELY_API_BASE") or "https://api.ivelytech.com").rstrip("/")
CUSTOMER_USERS_LIMIT = int(os.environ.get("IVELY_CUSTOMER_USERS_LIMIT", "500"))
IVELY_API_TIMEOUT = float(os.environ.get("IVELY_API_TIMEOUT", "15"))


def _ively_api_headers() -> dict:
    h = {"accept": "application/json"}
    token = (os.environ.get("IVELY_API_TOKEN") or os.environ.get("IVELY_CLOUD_API_KEY") or "").strip()
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _get_json(url: str) -> Any:
    r = requests.get(url, headers=_ively_api_headers(), timeout=IVELY_API_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _get_json_or_empty_on_404(url: str) -> Any:
    r = requests.get(url, headers=_ively_api_headers(), timeout=IVELY_API_TIMEOUT)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    return r.json()


_CUSTOMER_NAME_KEYS = (
    "customer_name",
    "company_name",
    "org_name",
    "organization_name",
    "organisation_name",
    "display_name",
    "full_name",
    "name",
)


def _extract_customer_name(row: dict) -> str:
    """
    Pull a human-readable customer name out of a getCustomerUsers row, trying
    a variety of common field shapes so we don't fall back to "Customer <id>"
    just because the cloud API uses a slightly different key.
    """
    for k in _CUSTOMER_NAME_KEYS:
        v = row.get(k)
        if v:
            s = str(v).strip()
            if s:
                return s

    # Nested: {"customer": {"name": "..."}}
    cust = row.get("customer")
    if isinstance(cust, dict):
        for k in _CUSTOMER_NAME_KEYS:
            v = cust.get(k)
            if v:
                s = str(v).strip()
                if s:
                    return s

    # Fallback: first_name + last_name (the per-user row identity)
    fn = str(row.get("first_name") or "").strip()
    ln = str(row.get("last_name") or "").strip()
    combo = (fn + " " + ln).strip()
    return combo


def _dedupe_customers(rows: List[dict]) -> List[dict]:
    """Build unique customers from getCustomerUsers rows (same customer_id may repeat per user)."""
    by_id: dict = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        cid = row.get("customer_id")
        if cid is None:
            continue
        name = _extract_customer_name(row)
        if cid not in by_id:
            by_id[cid] = {"customer_id": cid, "name": name or f"Customer {cid}"}
        elif name and (
            by_id[cid]["name"].startswith("Customer ")
            or not (by_id[cid]["name"] or "").strip()
        ):
            by_id[cid]["name"] = name
    return sorted(by_id.values(), key=lambda x: int(x["customer_id"]))


def _normalize_sites_payload(data: Union[dict, list, None]) -> List[dict]:
    if data is None:
        return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        if "sites" in data and isinstance(data["sites"], list):
            return [x for x in data["sites"] if isinstance(x, dict)]
        if "data" in data and isinstance(data["data"], list):
            return [x for x in data["data"] if isinstance(x, dict)]
        return [data]
    return []


MANUFACTURERS = [
    ("auto", "Auto-detect from camera"),
    ("hikvision", "Hikvision"),
    ("dahua", "Dahua"),
    ("cp plus", "CP Plus"),
    ("godrej", "Godrej"),
    ("prama", "Prama"),
    ("axis", "Axis"),
    ("bosch", "Bosch"),
    ("hanwha", "Hanwha (Samsung Techwin)"),
    ("zicom", "Zicom"),
    ("tp-link", "TP-Link"),
    ("ezviz", "Ezviz"),
    ("imou", "Imou"),
    ("reolink", "Reolink"),
    ("panasonic", "Panasonic"),
    ("sony", "Sony"),
    ("samsung", "Samsung"),
    ("pelco", "Pelco"),
    ("avigilon", "Avigilon"),
    ("mobotix", "Mobotix"),
    ("secureye", "Secureye"),
    ("uniview", "Uniview"),
    ("tiandy", "Tiandy"),
    ("onvif", "ONVIF (generic)"),
]


def _styles() -> str:
    return """
    :root {
      --bg: #0f172a;
      --surface: #1e293b;
      --border: #334155;
      --text: #f1f5f9;
      --text-muted: #94a3b8;
      --accent: #38bdf8;
      --accent-hover: #7dd3fc;
      --success: #34d399;
      --radius: 12px;
      --shadow: 0 25px 50px -12px rgba(0,0,0,0.4);
      --font: 'Segoe UI', system-ui, -apple-system, sans-serif;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: var(--font);
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 1.5rem;
      line-height: 1.5;
    }
    .page {
      width: 100%;
      max-width: 420px;
    }
    .logo {
      text-align: center;
      margin-bottom: 1.75rem;
    }
    .logo h1 {
      font-size: clamp(1.25rem, 4vw, 3.5rem);
      font-weight: 700;
      letter-spacing: -0.02em;
      color: var(--text);
    }
    .logo p {
      font-size: 0.875rem;
      color: var(--text-muted);
      margin-top: 0.25rem;
    }
    .card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 1.75rem;
      box-shadow: var(--shadow);
    }
    .card h2 {
      font-size: 0.8125rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--text-muted);
      margin-bottom: 1.25rem;
    }
    .field {
      margin-bottom: 1.25rem;
    }
    .field:last-of-type { margin-bottom: 0; }
    .field label {
      display: block;
      font-size: 0.875rem;
      font-weight: 500;
      color: var(--text);
      margin-bottom: 0.375rem;
    }
    .field label .optional { font-weight: 400; color: var(--text-muted); }
    .field input,
    .field select {
      width: 100%;
      padding: 0.75rem 1rem;
      font-family: inherit;
      font-size: 1rem;
      color: var(--text);
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      transition: border-color 0.2s, box-shadow 0.2s;
    }
    .field input::placeholder { color: var(--text-muted); opacity: 0.8; }
    .field input:focus,
    .field select:focus {
      outline: none;
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.2);
    }
    .field select {
      cursor: pointer;
      appearance: none;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' fill='%2394a3b8' viewBox='0 0 16 16'%3E%3Cpath d='M8 11L3 6h10l-5 5z'/%3E%3C/svg%3E");
      background-repeat: no-repeat;
      background-position: right 1rem center;
      padding-right: 2.5rem;
    }
    .btn {
      width: 100%;
      margin-top: 1.5rem;
      padding: 0.875rem 1.25rem;
      font-family: inherit;
      font-size: 1rem;
      font-weight: 600;
      color: var(--bg);
      background: var(--accent);
      border: none;
      border-radius: 8px;
      cursor: pointer;
      transition: background 0.2s, transform 0.05s;
    }
    .btn:hover { background: var(--accent-hover); }
    .btn:active { transform: scale(0.99); }
    .btn:focus {
      outline: none;
      box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.35);
    }
    .footer {
      text-align: center;
      margin-top: 1.5rem;
      font-size: 0.8125rem;
      color: var(--text-muted);
    }
    .field-hint {
      font-size: 0.8125rem;
      color: var(--text-muted);
      margin-top: 0.35rem;
    }
    .field-hint.error { color: #fca5a5; }
    .link-toggle {
      background: none;
      border: none;
      color: var(--accent);
      cursor: pointer;
      font-size: 0.8125rem;
      text-decoration: underline;
      padding: 0;
      margin-top: 0.5rem;
    }
    /* Success page */
    .success-card {
      text-align: center;
      padding: 2rem 1.75rem;
    }
    .success-icon {
      width: 56px;
      height: 56px;
      margin: 0 auto 1.25rem;
      background: rgba(52, 211, 153, 0.15);
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 1.75rem;
    }
    .success-card h2 { text-transform: none; font-size: 1.125rem; color: var(--text); margin-bottom: 0.5rem; }
    .success-card p { color: var(--text-muted); font-size: 0.9375rem; }
    .table-wrap { overflow-x: auto; margin-top: 0.5rem; }
    .table-wrap table { width: 100%; border-collapse: collapse; }
    .table-wrap th, .table-wrap td { border: 1px solid var(--border); padding: 0.5rem 0.75rem; text-align: left; }
    .table-wrap th { color: var(--text-muted); font-weight: 600; }
    .table-wrap tr:not(:first-child) th { width: 40%; }
    """


def _provisioned_info():
    """Return dict with device_id, cloud_url, customer, site, cameras; or None if not provisioned."""
    if not PROVISIONED_MARKER.exists() and not (AGENT_DIR / ".env").exists():
        return None
    info: dict = {
        "device_id": "—",
        "cloud_url": "—",
        "customer": "—",
        "customer_id": None,
        "site": "—",
        "site_id": None,
        "cameras": [],
    }
    try:
        env_path = AGENT_DIR / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").strip().splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip()
                    if k == "DEVICE_ID":
                        info["device_id"] = v
                    elif k == "CLOUD_URL":
                        info["cloud_url"] = v
    except Exception:
        pass
    try:
        site_path = AGENT_DIR / "site.json"
        if site_path.exists():
            data = json.loads(site_path.read_text(encoding="utf-8"))
            info["customer"] = data.get("customer") or "—"
            info["site"] = data.get("site") or "—"
            # Optional ID fields — only present on deployments provisioned
            # after we started persisting them; old site.json files are fine.
            if data.get("customer_id") not in (None, ""):
                info["customer_id"] = data.get("customer_id")
            if data.get("site_id") not in (None, ""):
                info["site_id"] = data.get("site_id")
    except Exception:
        pass
    if MEDIAMTX_CONFIG.exists():
        try:
            text = MEDIAMTX_CONFIG.read_text(encoding="utf-8")
            _NON_STREAM = {"paths", "rtsp", "hls", "webrtc", "api", "record", "metrics"}
            info["cameras"] = [
                p for p in re.findall(r"^\s+([a-zA-Z0-9_]+):\s*$", text, re.MULTILINE)
                if p.lower() not in _NON_STREAM
            ]
        except Exception:
            pass
    return info


def _provisioned_table_html(info: dict) -> str:
    """Provisioned device table view (dark theme) with Rediscover button."""
    camera_rows = "".join(f"<tr><td>{p}</td></tr>" for p in info["cameras"])
    if not camera_rows:
        camera_rows = "<tr><td>No cameras in config yet. Run Rediscover to scan.</td></tr>"

    # Show "Name (ID: 123)" when an ID was persisted; otherwise just the name.
    customer_cell = info["customer"]
    if info.get("customer_id") not in (None, ""):
        customer_cell = f"{info['customer']} <span style='color:var(--text-muted)'>(ID: {info['customer_id']})</span>"
    site_cell = info["site"]
    if info.get("site_id") not in (None, ""):
        site_cell = f"{info['site']} <span style='color:var(--text-muted)'>(ID: {info['site_id']})</span>"

    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Ively SmartEye — Provisioned device</title>
  <style>{_styles()}</style>
</head>
<body>
  <main class="page" style="max-width: 520px;">
    <div class="logo">
      <h1>Ively SmartEye™</h1>
      <p>Provisioned device</p>
    </div>
    <div class="card">
      <h2>Device</h2>
      <div class="table-wrap">
        <table>
          <tr><th>Device ID</th><td>{info['device_id']}</td></tr>
          <tr><th>Cloud URL</th><td>{info['cloud_url']}</td></tr>
          <tr><th>Customer</th><td>{customer_cell}</td></tr>
          <tr><th>Site</th><td>{site_cell}</td></tr>
        </table>
      </div>
    </div>
    <div class="card" style="margin-top: 1rem;">
      <h2>Cameras (MediaMTX)</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Stream path</th></tr></thead>
          <tbody>{camera_rows}</tbody>
        </table>
      </div>
      <form method="post" action="/rediscover" style="margin-top: 1rem;">
        <button type="submit" class="btn" style="margin-top: 0;">Rediscover cameras</button>
      </form>
      <form method="post" action="/reset" style="margin-top: 0.75rem;" onsubmit="return confirm('This will securely wipe all device configurations, camera targets, and credentials, requiring a completely fresh setup. Continue?');">
        <button type="submit" class="btn" style="background: transparent; border: 1px solid #7f1d1d; margin-top: 0; color: #fca5a5;">Wipe && Re-setup</button>
      </form>
      <p class="footer" style="margin-top: 1rem;">Added a new camera? Click <strong>Rediscover cameras</strong>. To fully wipe the device, click <strong>Wipe && Re-setup</strong>. Streams: port <strong>8080</strong>, path <strong>/view</strong>.</p>
    </div>
  </main>
</body>
</html>
"""


def _setup_form_html() -> str:
    options = "".join(
        f'<option value="{v}">{label}</option>' for v, label in MANUFACTURERS
    )
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Ively SmartEye — Setup</title>
  <style>{_styles()}</style>
</head>
<body>
  <main class="page">
    <div class="logo">
      <h1>Ively SmartEye™</h1>
      <p>Edge device setup</p>
    </div>
    <div class="card">
      <h2>Provision & Discover</h2>
      <form id="setup_form" method="post" action="/setup">
        <input type="hidden" name="customer" id="f_customer" value="">
        <input type="hidden" name="customer_id" id="f_customer_id" value="">
        <input type="hidden" name="site" id="f_site" value="">
        <input type="hidden" name="site_id" id="f_site_id" value="">
        <div class="field">
          <label for="cloud_url">Cloud URL</label>
          <input id="cloud_url" name="cloud_url" type="text" placeholder="https://api.ivelytech.com or IP" value="209.74.93.16" required autocomplete="off">
        </div>
        <div class="field">
          <label for="ndvr_ip">NDVR / Camera IP <span class="optional">(optional for full sweep)</span></label>
          <input id="ndvr_ip" name="ndvr_ip" type="text" placeholder="e.g. 192.168.0.104">
        </div>
        <div id="cs_api_mode">
          <div class="field">
            <label for="customer_select">Customer</label>
            <select id="customer_select" aria-describedby="customer_site_err">
              <option value="">Loading customers…</option>
            </select>
            <p id="customer_site_err" class="field-hint error" style="display:none;"></p>
          </div>
          <div class="field">
            <label for="site_select">Site</label>
            <select id="site_select" disabled>
              <option value="">Select customer first</option>
            </select>
            <p class="field-hint">Lists load from the cloud API (via this device).</p>
          </div>
          <button type="button" class="link-toggle" id="btn_manual_cs">Enter customer / site manually instead</button>
        </div>
        <div id="cs_manual_mode" style="display:none;">
          <div class="field">
            <label for="customer_manual">Customer name</label>
            <input id="customer_manual" type="text" placeholder="e.g. Acme Corp" autocomplete="organization">
          </div>
          <div class="field">
            <label for="customer_id_manual">Customer ID <span class="optional">(optional)</span></label>
            <input id="customer_id_manual" type="number" placeholder="e.g. 10000000001" inputmode="numeric">
          </div>
          <div class="field">
            <label for="site_manual">Site name</label>
            <input id="site_manual" type="text" placeholder="e.g. Warehouse A" autocomplete="off">
          </div>
          <div class="field">
            <label for="site_id_manual">Site ID <span class="optional">(optional)</span></label>
            <input id="site_id_manual" type="number" placeholder="e.g. 10000000002" inputmode="numeric">
          </div>
          <button type="button" class="link-toggle" id="btn_api_cs">Use customer &amp; site lists from API</button>
        </div>
        <div class="field">
          <label for="manufacturer">Camera manufacturer</label>
          <select id="manufacturer" name="manufacturer">{options}</select>
        </div>
        <div class="field">
          <label for="user">NDVR username <span class="optional">(optional)</span></label>
          <input id="user" name="user" type="text" placeholder="Admin or device user">
        </div>
        <div class="field">
          <label for="pwd">NDVR password <span class="optional">(optional)</span></label>
          <input id="pwd" name="pwd" type="password" placeholder="••••••••">
        </div>
        <button type="submit" class="btn">Discover Cameras</button>
      </form>
    </div>
    <p class="footer">Next, you'll select which cameras to process for AI.</p>
  </main>
  <script>
(function() {{
  const form = document.getElementById('setup_form');
  const custSel = document.getElementById('customer_select');
  const siteSel = document.getElementById('site_select');
  const apiMode = document.getElementById('cs_api_mode');
  const manualMode = document.getElementById('cs_manual_mode');
  const errEl = document.getElementById('customer_site_err');
  const fCust = document.getElementById('f_customer');
  const fCustId = document.getElementById('f_customer_id');
  const fSite = document.getElementById('f_site');
  const fSiteId = document.getElementById('f_site_id');
  const mCust = document.getElementById('customer_manual');
  const mCustId = document.getElementById('customer_id_manual');
  const mSite = document.getElementById('site_manual');
  const mSiteId = document.getElementById('site_id_manual');

  function setErr(msg) {{
    if (!errEl) return;
    errEl.textContent = msg || '';
    errEl.style.display = msg ? 'block' : 'none';
  }}

  function syncFromApi() {{
    const co = custSel.options[custSel.selectedIndex];
    fCustId.value = custSel.value || '';
    // Prefer clean name stored on data-name; fall back to label (which may include "(ID: ...)").
    fCust.value = (co && custSel.value)
      ? ((co.dataset && co.dataset.name) ? co.dataset.name : co.textContent.trim())
      : '';
    const so = siteSel.options[siteSel.selectedIndex];
    fSiteId.value = siteSel.value || '';
    fSite.value = (so && siteSel.value)
      ? ((so.dataset && so.dataset.name) ? so.dataset.name : so.textContent.trim())
      : '';
  }}

  function syncFromManual() {{
    fCust.value = (mCust.value || '').trim();
    fCustId.value = (mCustId.value || '').trim();
    fSite.value = (mSite.value || '').trim();
    fSiteId.value = (mSiteId.value || '').trim();
  }}

  async function loadCustomers() {{
    custSel.innerHTML = '<option value="">Loading…</option>';
    custSel.disabled = true;
    try {{
      const r = await fetch('/api/provision/customers');
      const body = await r.json().catch(function() {{ return {{}}; }});
      if (!r.ok) throw new Error(body.detail || r.statusText || 'Request failed');
      const list = body.customers || [];
      custSel.innerHTML = '<option value="">Select customer…</option>';
      list.forEach(function(c) {{
        const o = document.createElement('option');
        o.value = String(c.customer_id);
        const cleanName = c.name || ('Customer ' + c.customer_id);
        // Keep the pure name for the hidden form field (preserves site.json shape),
        // but show "Name (ID: 123)" in the dropdown so both are visible to the operator.
        o.dataset.name = cleanName;
        o.textContent = c.name
          ? (cleanName + '  (ID: ' + c.customer_id + ')')
          : cleanName;
        custSel.appendChild(o);
      }});
      custSel.disabled = false;
      setErr('');
      siteSel.innerHTML = '<option value="">Select customer first</option>';
      siteSel.disabled = true;
    }} catch (e) {{
      custSel.innerHTML = '<option value="">Could not load</option>';
      custSel.disabled = true;
      setErr((e && e.message) ? e.message : 'Could not load customers.');
    }}
  }}

  async function loadSites(customerId) {{
    if (!customerId) {{
      siteSel.innerHTML = '<option value="">Select customer first</option>';
      siteSel.disabled = true;
      syncFromApi();
      return;
    }}
    siteSel.innerHTML = '<option value="">Loading sites…</option>';
    siteSel.disabled = true;
    try {{
      const r = await fetch('/api/provision/customers/' + encodeURIComponent(customerId) + '/sites');
      const body = await r.json().catch(function() {{ return {{}}; }});
      if (!r.ok) throw new Error(body.detail || r.statusText || 'Request failed');
      const list = body.sites || [];
      siteSel.innerHTML = '<option value="">Select site…</option>';
      list.forEach(function(s) {{
        const o = document.createElement('option');
        o.value = String(s.site_id);
        const cleanName = s.name || ('Site ' + s.site_id);
        o.dataset.name = cleanName;
        o.textContent = s.name
          ? (cleanName + '  (ID: ' + s.site_id + ')')
          : cleanName;
        siteSel.appendChild(o);
      }});
      siteSel.disabled = list.length === 0;
      if (list.length === 0) {{
        siteSel.innerHTML = '<option value="">No sites for this customer</option>';
      }}
    }} catch (e) {{
      siteSel.innerHTML = '<option value="">Failed to load sites</option>';
      siteSel.disabled = true;
    }}
    syncFromApi();
  }}

  custSel.addEventListener('change', function() {{
    syncFromApi();
    loadSites(custSel.value);
  }});
  siteSel.addEventListener('change', syncFromApi);

  [mCust, mCustId, mSite, mSiteId].forEach(function(el) {{
    el.addEventListener('input', syncFromManual);
  }});

  document.getElementById('btn_manual_cs').addEventListener('click', function() {{
    apiMode.style.display = 'none';
    manualMode.style.display = 'block';
    syncFromManual();
  }});
  document.getElementById('btn_api_cs').addEventListener('click', function() {{
    manualMode.style.display = 'none';
    apiMode.style.display = 'block';
    syncFromApi();
  }});

  form.addEventListener('submit', function(e) {{
    if (manualMode.style.display !== 'none') {{
      syncFromManual();
      if (!(fCust.value || '').trim() || !(fSite.value || '').trim()) {{
        e.preventDefault();
        alert('Please enter customer name and site name.');
        return;
      }}
    }} else {{
      syncFromApi();
      if (!custSel.value || !siteSel.value) {{
        e.preventDefault();
        alert('Please select a customer and a site.');
        return;
      }}
    }}
  }});

  loadCustomers();
}})();
  </script>
</body>
</html>
"""


def _success_html() -> str:
    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Setup started — Ively SmartEye</title>
  <style>""" + _styles() + """</style>
</head>
<body>
  <main class="page">
    <div class="logo">
      <h1>Ively SmartEye™</h1>
      <p>Edge device setup</p>
    </div>
    <div class="card success-card">
      <div class="success-icon" aria-hidden="true">✓</div>
      <h2>Provisioning started</h2>
      <p>This device is registering and discovering cameras. Check the stream viewer in a minute.</p>
    </div>
    <p class="footer">Stream viewer: same address, path <strong>/view</strong> (after agent is running)</p>
  </main>
</body>
</html>
"""


def _camera_selection_html(cams, user, pwd, manufacturer, customer, site, cloud_url, customer_id, site_id) -> str:
    cams_json = json.dumps(cams).replace('"', '&quot;')
    checkboxes = ""
    for c in cams:
        ip = c["ip"]
        channels_count = c.get("channels", 1)
        for ch in range(1, channels_count + 1):
            cam_val = f"{ip}:{ch}"
            checkboxes += f"""
            <label style="display: block; margin-bottom: 0.5rem; background: var(--bg); padding: 0.5rem; border-radius: 6px; border: 1px solid var(--border);">
                <input type="checkbox" name="selected_cams" value="{cam_val}" checked style="width: auto; margin-right: 0.5rem; display: inline-block; cursor: pointer;">
                {ip} — Channel {ch}
            </label>
            """
            
    if not checkboxes:
        checkboxes = "<p style='color: #fca5a5;'>No ONVIF streams discovered automatically. Use the manual override below.</p>"
        
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Ively SmartEye — Camera Selection</title>
  <style>{_styles()}</style>
</head>
<body>
  <main class="page">
    <div class="logo">
      <h1>Ively SmartEye™</h1>
      <p>Select AI Targets</p>
    </div>
    <div class="card">
        <h2>Cameras & Streams</h2>
        <form method="post" action="/finalize_setup">
            <input type="hidden" name="user" value="{user}">
            <input type="hidden" name="pwd" value="{pwd}">
            <input type="hidden" name="manufacturer" value="{manufacturer}">
            <input type="hidden" name="customer" value="{customer}">
            <input type="hidden" name="site" value="{site}">
            <input type="hidden" name="cloud_url" value="{cloud_url}">
            <input type="hidden" name="customer_id" value="{customer_id}">
            <input type="hidden" name="site_id" value="{site_id}">
            <input type="hidden" name="cams_json" value="{cams_json}">
            
            <div class="field">
              <label>Auto-Discovered</label>
              {checkboxes}
            </div>
            
            <div class="field" style="margin-top: 1.5rem; padding-top: 1.5rem; border-top: 1px dotted var(--border);">
              <label for="manual_cams">Manual Override <span class="optional">(One per line)</span></label>
              <textarea id="manual_cams" name="manual_cams" rows="3" placeholder="IP Address or IP:Channel&#10;e.g., 192.168.0.195:1&#10;e.g., 192.168.0.195:2" style="width: 100%; padding: 0.75rem; background: var(--bg); color: var(--text); border: 1px solid var(--border); border-radius: 8px; font-family: monospace;"></textarea>
            </div>
            
            <button type="submit" class="btn">Confirm & Provision Device</button>
        </form>
    </div>
  </main>
</body>
</html>
"""


@app.get("/api/provision/customers")
def api_provision_customers():
    """Proxy: unique customers from cloud getCustomerUsers (deduped by customer_id)."""
    try:
        url = (
            f"{IVELY_API_BASE}/api/v1/customer_users/getCustomerUsers"
            f"?skip=0&limit={CUSTOMER_USERS_LIMIT}"
        )
        data = _get_json(url)
        if not isinstance(data, list):
            raise ValueError("customer_users response is not a JSON array")
        customers = _dedupe_customers(data)
        return JSONResponse({"customers": customers})
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=str(e) or "upstream request failed")
    except (ValueError, TypeError, KeyError) as e:
        raise HTTPException(status_code=502, detail=str(e))


_SITE_ID_KEYS = ("id", "site_id", "siteId")
_SITE_NAME_KEYS = ("name", "site_name", "display_name", "title", "label")


def _extract_site_id(row: dict):
    for k in _SITE_ID_KEYS:
        v = row.get(k)
        if v is not None:
            return v
    site = row.get("site")
    if isinstance(site, dict):
        for k in _SITE_ID_KEYS:
            v = site.get(k)
            if v is not None:
                return v
    return None


def _extract_site_name(row: dict) -> str:
    for k in _SITE_NAME_KEYS:
        v = row.get(k)
        if v:
            s = str(v).strip()
            if s:
                return s
    site = row.get("site")
    if isinstance(site, dict):
        for k in _SITE_NAME_KEYS:
            v = site.get(k)
            if v:
                s = str(v).strip()
                if s:
                    return s
    return ""


@app.get("/api/provision/customers/{customer_id}/sites")
def api_provision_customer_sites(customer_id: int):
    """Proxy: sites for a customer from getCustomerSites/{customer_id}."""
    try:
        url = f"{IVELY_API_BASE}/api/v1/customer_sites/getSitesByCustomerId/{customer_id}"
        data = _get_json_or_empty_on_404(url)
        raw = _normalize_sites_payload(data)
        sites = []
        for s in raw:
            sid = _extract_site_id(s)
            if sid is None:
                continue
            nm = _extract_site_name(s) or f"Site {sid}"
            sites.append({"site_id": sid, "name": nm})
        sites.sort(key=lambda x: int(x["site_id"]))
        return JSONResponse({"sites": sites})
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=str(e) or "upstream request failed")


@app.get("/", response_class=HTMLResponse)
def page():
    info = _provisioned_info()
    if info is not None:
        return _provisioned_table_html(info)
    return _setup_form_html()


@app.get("/setup", response_class=HTMLResponse)
def show_setup():
    """Unconditionally show the setup form for re-setup."""
    return _setup_form_html()


@app.post("/setup", response_class=HTMLResponse)
def setup_step1_discover(
    ndvr_ip: str = Form(""),
    user: str = Form(""),
    pwd: str = Form(""),
    manufacturer: str = Form("auto"),
    customer: str = Form(""),
    site: str = Form(""),
    cloud_url: str = Form("cloud.ively.ai"),
    customer_id: str = Form(""),
    site_id: str = Form(""),
):
    # Run the fast parallel discovery
    cams = onvif_scan.scan(target_ip=ndvr_ip.strip() or None, user=user.strip(), passwd=pwd.strip())
    
    return _camera_selection_html(
        cams, user, pwd, manufacturer, customer, site, cloud_url, customer_id, site_id
    )

@app.post("/finalize_setup", response_class=HTMLResponse)
async def finalize_setup(request: Request):
    form = await request.form()
    
    user = form.get("user", "")
    pwd = form.get("pwd", "")
    manufacturer = form.get("manufacturer", "auto")
    customer = form.get("customer", "")
    site = form.get("site", "")
    cloud_url = form.get("cloud_url", "cloud.ively.ai")
    customer_id = form.get("customer_id", "")
    site_id = form.get("site_id", "")
    cams_json_str = form.get("cams_json", "[]")
    manual_cams_raw = form.get("manual_cams", "")
    
    selected_cams = form.getlist("selected_cams")
    
    try:
        # 1. Parse Auto-Discovered Cameras
        cams = json.loads(cams_json_str)
        final_cams_dict = {}
        for c in cams:
            ip = c["ip"]
            selected_chs = []
            for sel in selected_cams:
                parts = sel.split(":")
                if len(parts) == 2 and parts[0] == ip:
                    selected_chs.append(int(parts[1]))
            if selected_chs:
                c["selected_channels"] = sorted(list(set(selected_chs)))
                final_cams_dict[ip] = c
                
        # 2. Parse Manual Overrides
        for line in manual_cams_raw.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(":")
            ip = parts[0].strip()
            ch = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
            
            if ip not in final_cams_dict:
                final_cams_dict[ip] = {"ip": ip, "model": "manual", "selected_channels": []}
            
            if ch not in final_cams_dict[ip]["selected_channels"]:
                final_cams_dict[ip]["selected_channels"].append(ch)
                final_cams_dict[ip]["selected_channels"].sort()
                
        final_cams = list(final_cams_dict.values())
                
        os.makedirs(str(AGENT_DIR), exist_ok=True)
        with open(AGENT_DIR / "cams.json", "w", encoding="utf-8") as f:
            json.dump(final_cams, f)
    except Exception as e:
        print(f"Error parsing channels: {e}")

    edge_dir = "/opt/ively/edge"
    env = {**os.environ, "PYTHONPATH": edge_dir}
    subprocess.Popen(
        [
            sys.executable,
            os.path.join(edge_dir, "installer", "provision_device.py"),
            user,
            pwd,
            manufacturer,
            customer.strip() or "customer",
            site.strip() or "site",
            cloud_url.strip() or "cloud.ively.ai",
            customer_id.strip(),
            site_id.strip(),
        ],
        cwd=edge_dir,
        env=env,
    )
    return _success_html()


@app.post("/rediscover", response_class=HTMLResponse)
def rediscover():
    """Run camera discovery and regenerate mediamtx config; redirect to /."""
    edge_dir = "/opt/ively/edge"
    env = {**os.environ, "PYTHONPATH": edge_dir}
    subprocess.Popen(
        [sys.executable, "-m", "agent.camera.discover"],
        cwd=edge_dir,
        env=env,
    )
    return RedirectResponse(url="/", status_code=303)


@app.post("/reset", response_class=HTMLResponse)
def reset_device():
    """Fully wipe the edge device configuration files and restart states."""
    # Stop background tasks to release any active file locks
    subprocess.run(["systemctl", "stop", "ively-agent"], check=False)
    subprocess.run(["systemctl", "stop", "mediamtx"], check=False)

    wipe_targets = [
        PROVISIONED_MARKER,
        AGENT_DIR / ".env",
        AGENT_DIR / "site.json",
        AGENT_DIR / "camera.vault",
        AGENT_DIR / "camera.manufacturer",
        MEDIAMTX_CONFIG  # Critical: Deleting this clears "old" camera discoveries
    ]

    for p in wipe_targets:
        try:
            if p.exists():
                p.unlink()
        except Exception as e:
            print(f"Cleanup error for {p}: {e}")

    # Optionally re-enable provision GUI as active
    subprocess.run(["systemctl", "enable", "ively-provision"], check=False)

    resp = RedirectResponse(url="/", status_code=303)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp




