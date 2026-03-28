# health server + stream viewer (for P2P verification after install)

import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse

app = FastAPI()

# MediaMTX WebRTC/HTTP port (from mediamtx.yml webrtcAddress :8889; HTTP often same or 8888)
MEDIAMTX_PORT = 8889
EDGE_DIR = Path("/opt/ively/edge")
AGENT_DIR = Path("/opt/ively/agent")
PROVISIONED_MARKER = Path("/opt/ively/.provisioned")
MEDIAMTX_CONFIG = Path("/opt/ively/mediamtx/mediamtx.yml")

# WireGuard status (optional)
try:
    from agent.wireguard.client import get_status as wg_get_status, load_state as wg_load_state
    HAS_WIREGUARD = True
except ImportError:
    HAS_WIREGUARD = False


def _stream_paths():
    """Read path names from mediamtx.yml so we can list them on the view page."""
    if not MEDIAMTX_CONFIG.exists():
        return []
    try:
        text = MEDIAMTX_CONFIG.read_text(encoding="utf-8")
        return re.findall(r"^\s+([a-zA-Z0-9_]+):\s*$", text, re.MULTILINE)
    except Exception:
        return []


def _vpn_status_dict() -> dict | None:
    """Return VPN status dict or None if WireGuard not available."""
    if not HAS_WIREGUARD:
        return None
    state = wg_load_state()
    if state is None:
        return None
    try:
        return wg_get_status()
    except Exception:
        return {"interface_up": False, "vpn_ip": state.get("vpn_ip")}


def _provisioned_info():
    """
    Read provisioned device info from disk. Returns dict with device_id, cloud_url, customer, site, cameras (list of path names), or None if not provisioned.
    """
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
    info["cameras"] = _stream_paths()
    return info


@app.get("/")
def root():
    """Redirect to stream viewer so http://edge.local:8080 shows streams after install."""
    return RedirectResponse(url="/view", status_code=302)


@app.get("/health")
def health():
    """Liveness/readiness for load balancers and watchdog."""
    result = {"status": "ok"}
    vpn = _vpn_status_dict()
    if vpn is not None:
        result["vpn"] = "connected" if vpn.get("interface_up") else "disconnected"
        result["vpn_ip"] = vpn.get("vpn_ip")
    return result


def _provisioned_page_html(info: dict) -> str:
    """Render provisioned device table and camera list with Rediscover button and VPN status."""
    camera_rows = "".join(
        f"<tr><td>{p}</td></tr>" for p in info["cameras"]
    ) or "<tr><td>No cameras in config yet. Run Rediscover to scan.</td></tr>"

    # VPN status row
    vpn_row = ""
    vpn = _vpn_status_dict()
    if vpn is not None:
        vpn_status = "🟢 Connected" if vpn.get("interface_up") else "🔴 Disconnected"
        vpn_ip = vpn.get("vpn_ip") or "—"
        vpn_row = f"""
    <tr><th>VPN Status</th><td>{vpn_status}</td></tr>
    <tr><th>VPN IP</th><td>{vpn_ip}</td></tr>"""

    return f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Ively Edge – Provisioned device</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; max-width: 800px; }}
    h2 {{ color: #1e293b; margin-top: 1.5rem; }}
    h2:first-child {{ margin-top: 0; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #cbd5e1; padding: 0.5rem 0.75rem; text-align: left; }}
    th {{ background: #f1f5f9; font-weight: 600; }}
    .btn {{ display: inline-block; margin-top: 1rem; padding: 0.5rem 1rem; background: #0ea5e9; color: #fff; text-decoration: none; border-radius: 6px; border: none; font-size: 1rem; cursor: pointer; }}
    .btn:hover {{ background: #0284c7; }}
    .nav {{ margin-bottom: 1.5rem; }}
    .nav a {{ color: #0ea5e9; margin-right: 1rem; }}
    .tip {{ color: #64748b; font-size: 0.9rem; margin-top: 1rem; }}
  </style>
</head>
<body>
  <div class="nav"><a href="/view">Streams</a> | <strong>Provisioned device</strong></div>
  <h2>Provisioned device</h2>
  <table>
    <tr><th>Device ID</th><td>{info['device_id']}</td></tr>
    <tr><th>Cloud URL</th><td>{info['cloud_url']}</td></tr>
    <tr><th>Customer</th><td>{info['customer']}</td></tr>
    <tr><th>Site</th><td>{info['site']}</td></tr>{vpn_row}
  </table>
  <h2>Cameras (from MediaMTX config)</h2>
  <table>
    <thead><tr><th>Stream path</th></tr></thead>
    <tbody>{camera_rows}</tbody>
  </table>
  <form method="post" action="/rediscover" style="margin-top: 1rem;">
    <button type="submit" class="btn">Rediscover cameras</button>
  </form>
  <p class="tip">Added a new camera? Click <strong>Rediscover cameras</strong> to scan the network again and update the list. You do not need to run Provision setup again.</p>
</body>
</html>
"""


@app.get("/provisioned", response_class=HTMLResponse)
def provisioned():
    """Table view of provisioned device info and camera list; supports Rediscover."""
    info = _provisioned_info()
    if info is None:
        return HTMLResponse(
            content="<html><body><p>Device not provisioned yet. Run setup at port 2025.</p><a href='/view'>Streams</a></body></html>",
            status_code=200,
        )
    return _provisioned_page_html(info)


@app.get("/vpn-status")
def vpn_status():
    """JSON endpoint for WireGuard tunnel status."""
    vpn = _vpn_status_dict()
    if vpn is None:
        return {"vpn": "not_available"}
    return vpn


@app.post("/rediscover", response_class=HTMLResponse)
def rediscover():
    """Run camera discovery and regenerate mediamtx config; redirect to /provisioned."""
    env = {**os.environ, "PYTHONPATH": str(EDGE_DIR)}
    subprocess.Popen(
        [sys.executable, "-m", "agent.camera.discover"],
        cwd=str(EDGE_DIR),
        env=env,
    )
    return RedirectResponse(url="/provisioned", status_code=303)


@app.get("/view", response_class=HTMLResponse)
def view():
    """
    Stream viewer: after installation, open this page to verify P2P video.
    Links to MediaMTX player for each camera stream (cam1_hd, cam1_low, etc.).
    """
    paths = _stream_paths()
    if not paths:
        paths = ["cam1_hd", "cam1_low"]

    # Use same host as request so it works via edge.local or IP
    base = "http://localhost"
    # When accessed as http://edge.local:8080/view, we want links to edge.local:8889
    # So we use a small JS that replaces host with current window.location.hostname
    rows = "".join(
        f"""
        <tr>
          <td>{name}</td>
          <td><a href="#" class="stream-link" data-path="{name}">Open stream</a></td>
        </tr>"""
        for name in paths
    )

    return f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Ively Edge – Streams</title>
  <style>
    body {{ font-family: sans-serif; margin: 2rem; }}
    h2 {{ color: #333; }}
    table {{ border-collapse: collapse; }}
    th, td {{ border: 1px solid #ccc; padding: 0.5rem 1rem; text-align: left; }}
    th {{ background: #eee; }}
    .stream-link {{ color: #06c; }}
    iframe {{ width: 100%; height: 480px; border: 1px solid #ccc; margin-top: 1rem; }}
    .player {{ margin-top: 1rem; }}
  </style>
</head>
<body>
  <h2>Ively SmartEye™ – Live streams (P2P)</h2>
  <p>Use these links to verify camera feeds after installation. Streams are served by MediaMTX (WebRTC). <a href="/provisioned">Provisioned device &amp; cameras</a></p>
  <table>
    <thead><tr><th>Stream</th><th>Action</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <div class="player" id="player"></div>
  <script>
    document.querySelectorAll('.stream-link').forEach(function(a) {{
      a.onclick = function(e) {{
        e.preventDefault();
        var path = this.getAttribute('data-path');
        var host = window.location.hostname;
        var url = 'http://' + host + ':{MEDIAMTX_PORT}/' + path + '/';
        document.getElementById('player').innerHTML =
          '<p>Playing: ' + path + ' – <a href="' + url + '" target="_blank">Open in new tab</a></p>' +
          '<iframe src="' + url + '" title="' + path + '"></iframe>';
      }};
    }});
  </script>
</body>
</html>
"""


def start_health(host: str = "0.0.0.0", port: int = 8080):
    """Run the health + view server in a daemon thread (so main thread can run WebSocket)."""
    import uvicorn

    def run():
        uvicorn.run(app, host=host, port=port, log_level="warning")

    t = threading.Thread(target=run, daemon=True)
    t.start()
