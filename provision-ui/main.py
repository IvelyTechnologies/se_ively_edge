from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

app = FastAPI()

EDGE_DIR = Path("/opt/ively/edge")
if str(EDGE_DIR) not in sys.path:
    sys.path.insert(0, str(EDGE_DIR))

import agent.camera.onvif_scan as onvif_scan

AGENT_DIR = Path("/opt/ively/agent")
PROVISIONED_MARKER = Path("/opt/ively/.provisioned")
MEDIAMTX_CONFIG = Path("/opt/ively/mediamtx/mediamtx.yml")

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
    info = {"device_id": "—", "cloud_url": "—", "customer": "—", "site": "—", "cameras": []}
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
    except Exception:
        pass
    if MEDIAMTX_CONFIG.exists():
        try:
            text = MEDIAMTX_CONFIG.read_text(encoding="utf-8")
            info["cameras"] = re.findall(r"^\s+([a-zA-Z0-9_]+):\s*$", text, re.MULTILINE)
        except Exception:
            pass
    return info


def _provisioned_table_html(info: dict) -> str:
    """Provisioned device table view (dark theme) with Rediscover button."""
    camera_rows = "".join(f"<tr><td>{p}</td></tr>" for p in info["cameras"])
    if not camera_rows:
        camera_rows = "<tr><td>No cameras in config yet. Run Rediscover to scan.</td></tr>"
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
          <tr><th>Customer</th><td>{info['customer']}</td></tr>
          <tr><th>Site</th><td>{info['site']}</td></tr>
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
      <form method="post" action="/setup">
        <div class="field">
          <label for="cloud_url">Cloud URL</label>
          <!-- Accept hostname or IP; no URL format validation -->
          <input id="cloud_url" name="cloud_url" type="text" placeholder="cloud.ively.ai or IP" value="cloud.ively.ai" required autocomplete="off">
        </div>
        <div class="field">
          <label for="ndvr_ip">NDVR / Camera IP <span class="optional">(optional for full sweep)</span></label>
          <input id="ndvr_ip" name="ndvr_ip" type="text" placeholder="e.g. 192.168.0.104">
        </div>
        <div class="field">
          <label for="customer">Customer name</label>
          <input id="customer" name="customer" type="text" placeholder="e.g. Acme Corp" required>
        </div>
        <div class="field">
          <label for="customer_id">Customer ID <span class="optional">(optional)</span></label>
          <input id="customer_id" name="customer_id" type="number" placeholder="e.g. 123">
        </div>
        <div class="field">
          <label for="site">Site name</label>
          <input id="site" name="site" type="text" placeholder="e.g. Warehouse A" required>
        </div>
        <div class="field">
          <label for="site_id">Site ID <span class="optional">(optional)</span></label>
          <input id="site_id" name="site_id" type="number" placeholder="e.g. 456">
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
        checkboxes = "<p style='color: #fca5a5;'>No ONVIF streams discovered. Hit back, clear the NDVR IP field for a full network sweep, or check your credentials.</p>"
        
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
        <h2>Detected Cameras</h2>
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
              {checkboxes}
            </div>
            
            <button type="submit" class="btn" {'disabled' if not cams else ''}>Confirm & Provision Device</button>
        </form>
    </div>
  </main>
</body>
</html>
"""


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

from fastapi import Request
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
    
    selected_cams = form.getlist("selected_cams")
    
    try:
        cams = json.loads(cams_json_str)
        final_cams = []
        for c in cams:
            ip = c["ip"]
            selected_chs = []
            for sel in selected_cams:
                parts = sel.split(":")
                if len(parts) == 2 and parts[0] == ip:
                    selected_chs.append(int(parts[1]))
            if selected_chs:
                c["selected_channels"] = selected_chs
                final_cams.append(c)
                
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




