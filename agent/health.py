# health server + stream viewer (for P2P verification after install)

import re
import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()

# MediaMTX WebRTC/HTTP port (from mediamtx.yml webrtcAddress :8889; HTTP often same or 8888)
MEDIAMTX_PORT = 8889


def _stream_paths():
    """Read path names from mediamtx.yml so we can list them on the view page."""
    path = Path("/opt/ively/mediamtx/mediamtx.yml")
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
        return re.findall(r"^\s+([a-zA-Z0-9_]+):\s*$", text, re.MULTILINE)
    except Exception:
        return []


@app.get("/")
def root():
    """Redirect to stream viewer so http://edge.local:8080 shows streams after install."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/view", status_code=302)


@app.get("/health")
def health():
    """Liveness/readiness for load balancers and watchdog."""
    return {"status": "ok"}


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
  <p>Use these links to verify camera feeds after installation. Streams are served by MediaMTX (WebRTC).</p>
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
