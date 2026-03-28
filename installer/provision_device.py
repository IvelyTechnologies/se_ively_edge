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

resp = requests.post(
    f"http://{cloud_host}:2018/register-edge",
    json=register_payload,
    timeout=30,
).json()

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

site_config = {"customer": customer_name, "site": site_name}
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
# 5. Discover cameras
# ---------------------------------------------------------------------------
print("Discovering cameras...")
subprocess.run(
    ["python3", "-m", "agent.camera.discover"],
    cwd="/opt/ively/edge",
    check=False,
)

# ---------------------------------------------------------------------------
# 6. Enable and start services
# ---------------------------------------------------------------------------
subprocess.run(["systemctl", "enable", "mediamtx"])
subprocess.run(["systemctl", "enable", "ively-agent"])
subprocess.run(["systemctl", "restart", "mediamtx"])
subprocess.run(["systemctl", "restart", "ively-agent"])

with open("/opt/ively/.provisioned", "w") as _:
    pass

subprocess.run(["systemctl", "disable", "ively-provision"])

print("Provision Complete")
