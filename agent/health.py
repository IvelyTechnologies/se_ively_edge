# health server + stream viewer + remote diagnostics (for P2P verification after install)

import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, RedirectResponse

app = FastAPI()

# Remote diagnostics (imported from commands module)
try:
    from agent.commands import run_diagnostics, DIAGNOSTIC_COMMANDS
    HAS_DIAGNOSTICS = True
except ImportError:
    HAS_DIAGNOSTICS = False
    DIAGNOSTIC_COMMANDS = {}

# Protocol ports (match mediamtx_writer.py config)
RTSP_PORT = 8554
HLS_PORT = 8888

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
        # Filter out YAML section headers / config keys that aren't actual streams
        _NON_STREAM = {"paths", "rtsp", "hls", "webrtc", "api", "record", "metrics"}
        return [
            p for p in re.findall(r"^\s+([a-zA-Z0-9_]+):\s*$", text, re.MULTILINE)
            if p.lower() not in _NON_STREAM
        ]
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


def _styles() -> str:
    """Dark-theme CSS shared across all pages."""
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
      --warning: #fbbf24;
      --danger: #f87171;
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
      padding: 1.5rem;
      line-height: 1.5;
    }
    .container {
      max-width: 960px;
      margin: 0 auto;
    }
    .nav {
      display: flex;
      gap: 1rem;
      align-items: center;
      margin-bottom: 1.5rem;
      padding-bottom: 1rem;
      border-bottom: 1px solid var(--border);
    }
    .nav a {
      color: var(--accent);
      text-decoration: none;
      font-weight: 500;
      padding: 0.25rem 0.5rem;
      border-radius: 6px;
      transition: background 0.2s;
    }
    .nav a:hover { background: rgba(56,189,248,0.1); }
    .nav a.active {
      background: rgba(56,189,248,0.15);
      color: var(--accent-hover);
    }
    .logo { font-size: 1.125rem; font-weight: 700; color: var(--text); margin-right: auto; }
    .card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 1.5rem;
      box-shadow: var(--shadow);
      margin-bottom: 1.25rem;
    }
    .card h2 {
      font-size: 0.8125rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--text-muted);
      margin-bottom: 1rem;
    }
    table { width: 100%; border-collapse: collapse; }
    th, td { border: 1px solid var(--border); padding: 0.5rem 0.75rem; text-align: left; }
    th { color: var(--text-muted); font-weight: 600; background: rgba(0,0,0,0.15); }
    .btn {
      display: inline-block;
      padding: 0.625rem 1.25rem;
      font-family: inherit;
      font-size: 0.875rem;
      font-weight: 600;
      color: var(--bg);
      background: var(--accent);
      border: none;
      border-radius: 8px;
      cursor: pointer;
      transition: background 0.2s, transform 0.05s;
      text-decoration: none;
    }
    .btn:hover { background: var(--accent-hover); }
    .btn:active { transform: scale(0.98); }
    .btn-sm { padding: 0.375rem 0.75rem; font-size: 0.8125rem; }
    .badge {
      display: inline-block;
      padding: 0.125rem 0.5rem;
      border-radius: 9999px;
      font-size: 0.75rem;
      font-weight: 600;
    }
    .badge-green { background: rgba(52,211,153,0.2); color: var(--success); }
    .badge-red   { background: rgba(248,113,113,0.2); color: var(--danger); }
    .tip { color: var(--text-muted); font-size: 0.875rem; margin-top: 1rem; }

    /* Stream viewer */
    .stream-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
      gap: 1rem;
    }
    .stream-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      overflow: hidden;
      transition: border-color 0.2s;
    }
    .stream-card:hover { border-color: var(--accent); }
    .stream-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0.75rem 1rem;
      background: rgba(0,0,0,0.15);
      border-bottom: 1px solid var(--border);
    }
    .stream-name { font-weight: 600; font-size: 0.9375rem; }
    .stream-body { padding: 0.75rem 1rem; }
    .stream-video {
      width: 100%;
      aspect-ratio: 16/9;
      background: #000;
      border-radius: 8px;
      margin-bottom: 0.75rem;
    }
    .url-row {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      margin-bottom: 0.5rem;
      font-size: 0.8125rem;
    }
    .url-label {
      flex-shrink: 0;
      font-weight: 700;
      padding: 0.125rem 0.375rem;
      border-radius: 4px;
      font-size: 0.6875rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .url-label-hls  { background: rgba(56,189,248,0.2); color: var(--accent); }
    .url-label-rtsp { background: rgba(251,191,36,0.2); color: var(--warning); }
    .url-value {
      flex: 1;
      font-family: 'Cascadia Code', 'Fira Code', monospace;
      color: var(--text-muted);
      font-size: 0.75rem;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .copy-btn {
      flex-shrink: 0;
      background: transparent;
      border: 1px solid var(--border);
      color: var(--text-muted);
      border-radius: 4px;
      padding: 0.125rem 0.375rem;
      cursor: pointer;
      font-size: 0.75rem;
      transition: all 0.2s;
    }
    .copy-btn:hover { border-color: var(--accent); color: var(--accent); }
    .copy-btn.copied { border-color: var(--success); color: var(--success); }

    /* Protocol tab buttons */
    .proto-tabs {
      display: flex;
      gap: 0.5rem;
      margin-bottom: 0.75rem;
    }
    .proto-tab {
      padding: 0.25rem 0.75rem;
      font-size: 0.8125rem;
      font-weight: 600;
      border: 1px solid var(--border);
      border-radius: 6px;
      cursor: pointer;
      background: transparent;
      color: var(--text-muted);
      transition: all 0.2s;
    }
    .proto-tab:hover { border-color: var(--accent); color: var(--accent); }
    .proto-tab.active { background: rgba(56,189,248,0.15); border-color: var(--accent); color: var(--accent); }

    /* IP selector */
    .ip-selector {
      display: flex;
      align-items: center;
      gap: 0.75rem;
      padding: 0.75rem 1rem;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      margin-bottom: 1.25rem;
    }
    .ip-selector label { font-size: 0.875rem; font-weight: 600; white-space: nowrap; }
    .ip-selector select {
      flex: 1;
      padding: 0.5rem 0.75rem;
      font-family: inherit;
      font-size: 0.875rem;
      color: var(--text);
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 6px;
      cursor: pointer;
    }
    .ip-selector select:focus { outline: none; border-color: var(--accent); }
    """


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
  <style>{_styles()}</style>
</head>
<body>
  <div class="container">
    <div class="nav">
      <span class="logo">Ively SmartEye™</span>
      <a href="/view">Streams</a>
      <a href="/provisioned" class="active">Device</a>
      <a href="/diagnostics/ui">Diagnostics</a>
    </div>

    <div class="card">
      <h2>Device Info</h2>
      <table>
        <tr><th>Device ID</th><td>{info['device_id']}</td></tr>
        <tr><th>Cloud URL</th><td>{info['cloud_url']}</td></tr>
        <tr><th>Customer</th><td>{info['customer']}</td></tr>
        <tr><th>Site</th><td>{info['site']}</td></tr>{vpn_row}
      </table>
    </div>

    <div class="card">
      <h2>Cameras (MediaMTX Config)</h2>
      <table>
        <thead><tr><th>Stream path</th></tr></thead>
        <tbody>{camera_rows}</tbody>
      </table>
      <form method="post" action="/rediscover" style="margin-top: 1rem;">
        <button type="submit" class="btn">Rediscover cameras</button>
      </form>
      <p class="tip">Added a new camera? Click <strong>Rediscover cameras</strong> to scan the network again.</p>
    </div>
  </div>
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
    Stream viewer: HLS playback in-browser + RTSP URLs for each camera.
    Supports LAN IP and WireGuard VPN IP switching.
    """
    paths = _stream_paths()
    if not paths:
        paths = ["cam1_hd", "cam1_low"]

    # Get VPN IP if available
    vpn_ip = None
    vpn = _vpn_status_dict()
    if vpn and vpn.get("interface_up") and vpn.get("vpn_ip"):
        vpn_ip = vpn["vpn_ip"]

    vpn_ip_json = json.dumps(vpn_ip)
    paths_json = json.dumps(paths)

    return f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Ively Edge – Stream Viewer</title>
  <style>{_styles()}</style>
  <script src="https://cdn.jsdelivr.net/npm/hls.js@1"></script>
</head>
<body>
  <div class="container">
    <div class="nav">
      <span class="logo">Ively SmartEye™</span>
      <a href="/view" class="active">Streams</a>
      <a href="/provisioned">Device</a>
      <a href="/diagnostics/ui">Diagnostics</a>
    </div>

    <!-- IP / Host selector -->
    <div class="ip-selector">
      <label for="host-select">Access via:</label>
      <select id="host-select">
        <option value="__browser__" selected>Current (Browser Host)</option>
      </select>
      <span class="badge badge-green" id="vpn-badge" style="display: none;">VPN</span>
    </div>

    <!-- Stream grid -->
    <div class="stream-grid" id="stream-grid"></div>

    <p class="tip" style="margin-top: 1.5rem;">
      <strong>HLS</strong> plays directly in the browser. <strong>RTSP</strong> URLs can be opened in VLC or any RTSP player.
      Switch the access host above to use VPN IP for remote playback.
    </p>
  </div>

  <script>
  (function() {{
    const RTSP_PORT = {RTSP_PORT};
    const HLS_PORT  = {HLS_PORT};
    const PATHS     = {paths_json};
    const VPN_IP    = {vpn_ip_json};

    const hostSelect = document.getElementById('host-select');
    const vpnBadge   = document.getElementById('vpn-badge');
    const grid       = document.getElementById('stream-grid');

    // Populate host options
    const browserHost = window.location.hostname;
    hostSelect.querySelector('option[value="__browser__"]').textContent =
      'LAN (' + browserHost + ')';

    if (VPN_IP) {{
      const opt = document.createElement('option');
      opt.value = VPN_IP;
      opt.textContent = 'VPN (' + VPN_IP + ')';
      hostSelect.appendChild(opt);
      vpnBadge.style.display = 'inline-block';
    }}

    function getHost() {{
      const v = hostSelect.value;
      return v === '__browser__' ? browserHost : v;
    }}

    function hlsUrl(host, path) {{
      return 'http://' + host + ':' + HLS_PORT + '/' + path + '/index.m3u8';
    }}
    function rtspUrl(host, path) {{
      return 'rtsp://' + host + ':' + RTSP_PORT + '/' + path;
    }}

    function copyToClipboard(text, btn) {{
      navigator.clipboard.writeText(text).then(function() {{
        btn.classList.add('copied');
        btn.textContent = '✓';
        setTimeout(function() {{ btn.classList.remove('copied'); btn.textContent = 'Copy'; }}, 1500);
      }});
    }}

    function buildCards() {{
      const host = getHost();
      grid.innerHTML = '';

      PATHS.forEach(function(path) {{
        const card = document.createElement('div');
        card.className = 'stream-card';

        const hls  = hlsUrl(host, path);
        const rtsp = rtspUrl(host, path);
        const videoId = 'video-' + path.replace(/[^a-zA-Z0-9]/g, '_');

        card.innerHTML = `
          <div class="stream-header">
            <span class="stream-name">${{path}}</span>
            <div class="proto-tabs">
              <button class="proto-tab active" data-proto="hls" data-path="${{path}}">HLS</button>
              <button class="proto-tab" data-proto="rtsp" data-path="${{path}}">RTSP</button>
            </div>
          </div>
          <div class="stream-body">
            <div class="player-area" id="player-${{path}}">
              <video id="${{videoId}}" class="stream-video" controls autoplay muted playsinline></video>
            </div>
            <div class="url-row">
              <span class="url-label url-label-hls">HLS</span>
              <span class="url-value" title="${{hls}}">${{hls}}</span>
              <button class="copy-btn" onclick="copyUrl(this, '${{hls}}')">Copy</button>
            </div>
            <div class="url-row">
              <span class="url-label url-label-rtsp">RTSP</span>
              <span class="url-value" title="${{rtsp}}">${{rtsp}}</span>
              <button class="copy-btn" onclick="copyUrl(this, '${{rtsp}}')">Copy</button>
            </div>
          </div>
        `;

        grid.appendChild(card);

        // Attach HLS player
        const videoEl = document.getElementById(videoId);
        attachHls(videoEl, hls);

        // Proto tab switching
        card.querySelectorAll('.proto-tab').forEach(function(tab) {{
          tab.addEventListener('click', function() {{
            card.querySelectorAll('.proto-tab').forEach(t => t.classList.remove('active'));
            this.classList.add('active');

            const proto = this.getAttribute('data-proto');
            const playerArea = card.querySelector('.player-area');

            if (proto === 'hls') {{
              playerArea.innerHTML = `<video id="${{videoId}}" class="stream-video" controls autoplay muted playsinline></video>`;
              const newVideo = document.getElementById(videoId);
              attachHls(newVideo, hlsUrl(getHost(), path));
            }} else {{
              const r = rtspUrl(getHost(), path);
              playerArea.innerHTML = `
                <div class="stream-video" style="display: flex; flex-direction: column; align-items: center; justify-content: center; color: var(--text-muted); gap: 0.75rem;">
                  <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M15.91 11.672a.375.375 0 010 .656l-5.603 3.113a.375.375 0 01-.557-.328V8.887c0-.286.307-.466.557-.327l5.603 3.112z"/><path d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                  <span style="font-size: 0.875rem; font-weight: 600;">RTSP Stream</span>
                  <code style="font-size: 0.75rem; color: var(--accent); word-break: break-all; text-align: center; padding: 0 1rem;">${{r}}</code>
                  <span style="font-size: 0.75rem;">Open this URL in VLC or any RTSP-compatible player</span>
                </div>
              `;
            }}
          }});
        }});
      }});
    }}

    function attachHls(videoEl, url) {{
      if (!videoEl) return;
      if (Hls.isSupported()) {{
        const hls = new Hls({{ enableWorker: true, lowLatencyMode: true }});
        hls.loadSource(url);
        hls.attachMedia(videoEl);
        hls.on(Hls.Events.ERROR, function(event, data) {{
          if (data.fatal) {{
            videoEl.poster = '';
            videoEl.parentElement.innerHTML = `
              <div class="stream-video" style="display: flex; align-items: center; justify-content: center; color: var(--danger); font-size: 0.875rem;">
                Stream unavailable — waiting for camera feed
              </div>
            `;
          }}
        }});
      }} else if (videoEl.canPlayType('application/vnd.apple.mpegurl')) {{
        // Native HLS (Safari)
        videoEl.src = url;
      }}
    }}

    // Expose copy helper globally (used in onclick)
    window.copyUrl = function(btn, url) {{ copyToClipboard(url, btn); }};

    // Rebuild cards when host changes
    hostSelect.addEventListener('change', buildCards);

    // Initial build
    buildCards();
  }})();
  </script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Remote Diagnostics — JSON API + Web UI
# ---------------------------------------------------------------------------

@app.get("/diagnostics")
def diagnostics_api(
    commands: Optional[str] = Query(None, description="Comma-separated command names, or 'all'"),
    timeout: int = Query(15, ge=1, le=60),
):
    """
    JSON API for remote diagnostics. Called by server over VPN or WebSocket.

    Examples:
      GET /diagnostics                           → default MediaMTX debug bundle
      GET /diagnostics?commands=mediamtx_logs,disk_usage
      GET /diagnostics?commands=all              → run all available commands
    """
    if not HAS_DIAGNOSTICS:
        return {"success": False, "message": "Diagnostics module not available"}

    cmd_list = None
    if commands:
        if commands.strip().lower() == "all":
            cmd_list = sorted(DIAGNOSTIC_COMMANDS.keys())
        else:
            cmd_list = [c.strip() for c in commands.split(",") if c.strip()]

    return run_diagnostics(commands=cmd_list, timeout=timeout)


@app.get("/diagnostics/ui", response_class=HTMLResponse)
def diagnostics_ui():
    """Interactive diagnostics dashboard — run debug commands from the browser."""
    cmd_names = sorted(DIAGNOSTIC_COMMANDS.keys()) if HAS_DIAGNOSTICS else []
    cmd_names_json = json.dumps(cmd_names)

    return f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Ively Edge – Diagnostics</title>
  <style>{_styles()}
    .diag-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
      gap: 0.5rem;
      margin-bottom: 1.25rem;
    }}
    .diag-chip {{
      display: flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.5rem 0.75rem;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      cursor: pointer;
      font-size: 0.8125rem;
      font-weight: 500;
      color: var(--text-muted);
      transition: all 0.2s;
      user-select: none;
    }}
    .diag-chip:hover {{ border-color: var(--accent); color: var(--text); }}
    .diag-chip.selected {{
      background: rgba(56,189,248,0.15);
      border-color: var(--accent);
      color: var(--accent);
    }}
    .diag-chip input {{ display: none; }}
    .diag-chip .check {{
      width: 16px; height: 16px;
      border: 2px solid var(--border);
      border-radius: 4px;
      display: flex; align-items: center; justify-content: center;
      flex-shrink: 0;
      transition: all 0.2s;
    }}
    .diag-chip.selected .check {{
      background: var(--accent);
      border-color: var(--accent);
    }}
    .diag-chip.selected .check::after {{
      content: '✓';
      color: var(--bg);
      font-size: 0.625rem;
      font-weight: 700;
    }}
    .action-bar {{
      display: flex;
      gap: 0.75rem;
      margin-bottom: 1.5rem;
      flex-wrap: wrap;
    }}
    .result-block {{
      margin-bottom: 1rem;
    }}
    .result-header {{
      display: flex;
      align-items: center;
      gap: 0.75rem;
      margin-bottom: 0.5rem;
    }}
    .result-header h3 {{
      font-size: 0.875rem;
      font-weight: 700;
      margin: 0;
    }}
    .result-status {{
      font-size: 0.6875rem;
      padding: 0.125rem 0.5rem;
      border-radius: 4px;
      font-weight: 600;
    }}
    .result-status.ok {{ background: rgba(52,211,153,0.2); color: var(--success); }}
    .result-status.fail {{ background: rgba(248,113,113,0.2); color: var(--danger); }}
    .result-status.err {{ background: rgba(251,191,36,0.2); color: var(--warning); }}
    pre.output {{
      background: #0b1120;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 1rem;
      font-size: 0.75rem;
      line-height: 1.6;
      color: #e2e8f0;
      overflow-x: auto;
      white-space: pre-wrap;
      word-break: break-word;
      max-height: 300px;
      overflow-y: auto;
    }}
    .spinner {{
      display: inline-block;
      width: 18px; height: 18px;
      border: 2px solid var(--border);
      border-top-color: var(--accent);
      border-radius: 50%;
      animation: spin 0.7s linear infinite;
    }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
    #results-area {{ min-height: 100px; }}
    .empty-state {{
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 200px;
      color: var(--text-muted);
      font-size: 0.875rem;
      border: 2px dashed var(--border);
      border-radius: var(--radius);
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="nav">
      <span class="logo">Ively SmartEye™</span>
      <a href="/view">Streams</a>
      <a href="/provisioned">Device</a>
      <a href="/diagnostics/ui" class="active">Diagnostics</a>
    </div>

    <div class="card">
      <h2>Remote Diagnostics Console</h2>
      <p style="color: var(--text-muted); font-size: 0.875rem; margin-bottom: 1rem;">
        Select diagnostic commands to execute on this edge device. Results are displayed in real-time.
      </p>

      <div class="diag-grid" id="cmd-grid"></div>

      <div class="action-bar">
        <button class="btn" id="btn-run" onclick="runSelected()">▶ Run Selected</button>
        <button class="btn" style="background: var(--success);" onclick="runAll()">⚡ Run All</button>
        <button class="btn btn-sm" style="background: transparent; border: 1px solid var(--border); color: var(--text-muted);" onclick="selectDefault()">MediaMTX Bundle</button>
        <button class="btn btn-sm" style="background: transparent; border: 1px solid var(--border); color: var(--text-muted);" onclick="clearAll()">Clear Selection</button>
      </div>
    </div>

    <div id="results-area">
      <div class="empty-state">Select commands above and click <strong>&nbsp;▶ Run Selected&nbsp;</strong> to begin</div>
    </div>
  </div>

  <script>
  (function() {{
    const COMMANDS = {cmd_names_json};
    const DEFAULT_BUNDLE = ['mediamtx_config', 'mediamtx_logs', 'mediamtx_ports', 'mediamtx_paths'];
    const grid = document.getElementById('cmd-grid');
    const results = document.getElementById('results-area');

    // Build chips
    COMMANDS.forEach(function(name) {{
      const chip = document.createElement('label');
      chip.className = 'diag-chip';
      chip.innerHTML = '<span class="check"></span><span>' + name.replace(/_/g, ' ') + '</span>';
      chip.dataset.cmd = name;
      chip.addEventListener('click', function() {{
        this.classList.toggle('selected');
      }});
      grid.appendChild(chip);
    }});

    function getSelected() {{
      return Array.from(grid.querySelectorAll('.diag-chip.selected')).map(c => c.dataset.cmd);
    }}

    window.selectDefault = function() {{
      grid.querySelectorAll('.diag-chip').forEach(c => {{
        c.classList.toggle('selected', DEFAULT_BUNDLE.includes(c.dataset.cmd));
      }});
    }};

    window.clearAll = function() {{
      grid.querySelectorAll('.diag-chip').forEach(c => c.classList.remove('selected'));
    }};

    window.runAll = function() {{
      grid.querySelectorAll('.diag-chip').forEach(c => c.classList.add('selected'));
      runSelected();
    }};

    window.runSelected = function() {{
      const cmds = getSelected();
      if (cmds.length === 0) {{
        results.innerHTML = '<div class="empty-state" style="border-color: var(--warning);">⚠ No commands selected</div>';
        return;
      }}

      results.innerHTML = '<div class="card" style="display: flex; align-items: center; gap: 0.75rem;"><div class="spinner"></div><span>Running ' + cmds.length + ' diagnostic command(s)…</span></div>';

      fetch('/diagnostics?commands=' + cmds.join(','))
        .then(r => r.json())
        .then(function(data) {{
          if (!data.success) {{
            results.innerHTML = '<div class="card" style="border-color: var(--danger);"><h2>Error</h2><pre class="output">' + (data.message || 'Unknown error') + '</pre></div>';
            return;
          }}
          let html = '';
          const diag = data.diagnostics || {{}};
          for (const [name, info] of Object.entries(diag)) {{
            const hasError = !!info.error;
            const rc = info.returncode;
            let statusClass = 'ok';
            let statusText = 'exit ' + rc;
            if (hasError) {{
              statusClass = 'err';
              statusText = 'error';
            }} else if (rc !== 0) {{
              statusClass = 'fail';
            }}

            let outputText = '';
            if (hasError) {{
              outputText = info.error;
            }} else {{
              outputText = info.stdout || '';
              if (info.stderr) outputText += '\n--- stderr ---\n' + info.stderr;
              if (!outputText.trim()) outputText = '(no output)';
            }}

            html += '<div class="result-block"><div class="result-header">';
            html += '<h3>' + name.replace(/_/g, ' ') + '</h3>';
            html += '<span class="result-status ' + statusClass + '">' + statusText + '</span>';
            html += '</div>';
            html += '<pre class="output">' + escapeHtml(outputText) + '</pre></div>';
          }}
          results.innerHTML = '<div class="card">' + html + '</div>';
        }})
        .catch(function(err) {{
          results.innerHTML = '<div class="card" style="border-color: var(--danger);"><h2>Request Failed</h2><pre class="output">' + err + '</pre></div>';
        }});
    }};

    function escapeHtml(text) {{
      const el = document.createElement('span');
      el.textContent = text;
      return el.innerHTML;
    }}

    // Auto-select default bundle on load
    selectDefault();
  }})();
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
