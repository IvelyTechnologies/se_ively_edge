import json
import os
import subprocess
import sys

import requests

from agent.security.vault import encrypt
from agent.wireguard.keys import get_or_create_keypair
from agent.wireguard.client import provision_tunnel

user = sys.argv[1]
pwd = sys.argv[2]
manufacturer = sys.argv[3] if len(sys.argv) > 3 else "auto"
customer_name = sys.argv[4] if len(sys.argv) > 4 else "customer"
site_name = sys.argv[5] if len(sys.argv) > 5 else "site"
cloud_url = (sys.argv[6] if len(sys.argv) > 6 else "cloud.ively.ai").strip()
customer_id = sys.argv[7] if len(sys.argv) > 7 else ""
site_id = sys.argv[8] if len(sys.argv) > 8 else ""

# Strip protocol so we can use https for API and wss for WebSocket
cloud_host = cloud_url.replace("https://", "").replace("http://", "").strip("/")

# ---------------------------------------------------------------------------
# 1. Generate WireGuard key pair (before registration so we can send public key)
# ---------------------------------------------------------------------------
print("Generating WireGuard keys...")
try:
    _wg_private, wg_public_key = get_or_create_keypair()
except Exception as e:
    print(f"WARNING: WireGuard key generation failed: {e}")
    wg_public_key = None

# ---------------------------------------------------------------------------
# 2. Register device with cloud (include WG public key for VPN provisioning)
# ---------------------------------------------------------------------------
print("Registering device...")

from typing import Any
register_payload: dict[str, Any] = {}
if wg_public_key:
    register_payload["wg_public_key"] = wg_public_key
if customer_id:
    try:
        register_payload["customer_id"] = int(customer_id)
    except ValueError:
        pass
if site_id:
    try:
        register_payload["site_id"] = int(site_id)
    except ValueError:
        pass

def _register_with_cloud(host: str, payload: dict) -> dict:
    """
    POST to /register-edge. Tries https first, falls back to http.
    On any failure (non-2xx, bad JSON, missing fields) prints exactly what
    the server returned so the operator can diagnose from the provisioning
    UI logs instead of seeing a bare KeyError.
    """
    last_err: str = ""
    for scheme in ("https", "http"):
        url = f"{scheme}://{host}/register-edge"
        try:
            r = requests.post(url, json=payload, timeout=30)
        except requests.RequestException as exc:
            last_err = f"{scheme}: {exc}"
            print(f"  tried {url} -> network error: {exc}")
            continue

        body_preview = (r.text or "")[:1000]
        if r.status_code >= 400:
            last_err = f"{scheme}: HTTP {r.status_code}"
            print(f"  tried {url} -> HTTP {r.status_code}")
            print(f"  response body: {body_preview}")
            # Keep trying the other scheme in case it's a redirect/misconfig
            continue

        try:
            data = r.json()
        except ValueError:
            last_err = f"{scheme}: non-JSON response"
            print(f"  tried {url} -> non-JSON response:")
            print(f"  response body: {body_preview}")
            continue

        missing = [k for k in ("device_id", "token") if k not in data]
        if missing:
            print(f"  tried {url} -> JSON missing required fields: {missing}")
            print(f"  full response: {json.dumps(data)[:1000]}")
            last_err = f"{scheme}: missing fields {missing}"
            continue

        print(f"  registered via {url}")
        return data

    print(f"ERROR: device registration failed on host '{host}'. Last error: {last_err}")
    print("       Check: cloud URL correctness, that /register-edge exists,")
    print("       that customer_id/site_id (if required) are valid, and that")
    print("       the device can reach the cloud (internet + DNS).")
    sys.exit(1)


resp = _register_with_cloud(cloud_host, register_payload)
device_id = resp["device_id"]
token = resp["token"]

# ---------------------------------------------------------------------------
# 3. Save encrypted camera credentials
# ---------------------------------------------------------------------------
vault = {
    "user": encrypt(user),
    "password": encrypt(pwd),
}

os.makedirs("/opt/ively/agent", exist_ok=True)

with open("/opt/ively/agent/camera.vault", "w", encoding="utf-8") as f:
    f.write(json.dumps(vault))

with open("/opt/ively/agent/camera.manufacturer", "w", encoding="utf-8") as f:
    f.write(manufacturer)

site_config: dict[str, Any] = {"customer": customer_name, "site": site_name}
# Also persist IDs when we have them, so the provisioned-info UI can show
# both the name and the ID. Absent fields stay None and the UI hides them.
if customer_id:
    try:
        site_config["customer_id"] = int(customer_id)
    except ValueError:
        site_config["customer_id"] = customer_id
if site_id:
    try:
        site_config["site_id"] = int(site_id)
    except ValueError:
        site_config["site_id"] = site_id
with open("/opt/ively/agent/site.json", "w", encoding="utf-8") as f:
    json.dump(site_config, f, indent=2)

# Save device config (cloud host without protocol for agent to build wss:// and https://)
with open("/opt/ively/agent/.env", "w", encoding="utf-8") as f:
    f.write(f"DEVICE_ID={device_id}\nTOKEN={token}\nCLOUD_URL={cloud_host}\n")

# ---------------------------------------------------------------------------
# 4. Configure and start WireGuard VPN tunnel
# ---------------------------------------------------------------------------
wg_config = resp.get("wireguard")
if wg_config and wg_public_key:
    print("Configuring WireGuard VPN tunnel...")
    vpn_ip = wg_config.get("vpn_ip")
    server_pub = wg_config.get("server_public_key")
    endpoint = wg_config.get("endpoint")
    allowed_ips = wg_config.get("allowed_ips", "10.20.0.0/16")
    keepalive = wg_config.get("keepalive", 25)

    if vpn_ip and server_pub and endpoint:
        ok = provision_tunnel(
            vpn_ip=vpn_ip,
            server_public_key=server_pub,
            endpoint=endpoint,
            allowed_ips=allowed_ips,
            keepalive=keepalive,
        )
        if ok:
            print(f"WireGuard tunnel established — VPN IP: {vpn_ip}")
        else:
            print("WARNING: WireGuard tunnel setup failed (device will use direct connection)")
    else:
        print("WARNING: Incomplete WireGuard config from cloud — skipping VPN setup")
else:
    print("INFO: No WireGuard config from cloud — VPN tunnel not configured")
    print("      (Cloud may not support WireGuard yet, or wg is not installed)")

# ---------------------------------------------------------------------------
# 5. Apply Selected Cameras to MediaMTX (+ worker config via agent on start)
# ---------------------------------------------------------------------------
EDGE_DIR = "/opt/ively/edge"
PY = sys.executable
if os.path.isfile("/opt/ively/venv/bin/python3"):
    PY = "/opt/ively/venv/bin/python3"

from agent.camera.pipeline import apply_camera_config, edge_agent_env, restart_stream_services

cams_file = "/opt/ively/agent/cams.json"
if os.path.exists(cams_file):
    print("Applying selected cameras to MediaMTX...")
    try:
        with open(cams_file, encoding="utf-8") as f:
            cams = json.load(f)
        apply_camera_config(cams)
        print(f"MediaMTX configured for {len(cams)} endpoints.")
    except Exception as e:
        print(f"Error structuring MediaMTX configuration: {e}")
else:
    print("No cams.json found. Running ONVIF discovery...")
    subprocess.run(
        [PY, "-m", "agent.camera.discover"],
        cwd=EDGE_DIR,
        env=edge_agent_env(),
        check=False,
    )

# ---------------------------------------------------------------------------
# 6. Enable boot services and start streaming stack (MediaMTX → agent)
# ---------------------------------------------------------------------------
subprocess.run(["bash", f"{EDGE_DIR}/installer/ensure-services-enabled.sh"], check=False)
restart_stream_services(restart_mediamtx=True, restart_agent=True)

with open("/opt/ively/.provisioned", "w") as _:
    pass

subprocess.run(["systemctl", "disable", "ively-provision"])

print("Provision Complete")
