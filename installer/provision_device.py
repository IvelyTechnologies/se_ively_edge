import json
import os
import subprocess
import sys

import requests

from agent.security.vault import encrypt

user = sys.argv[1]
pwd = sys.argv[2]
manufacturer = sys.argv[3] if len(sys.argv) > 3 else "auto"
customer_name = sys.argv[4] if len(sys.argv) > 4 else "customer"
site_name = sys.argv[5] if len(sys.argv) > 5 else "site"
cloud_url = (sys.argv[6] if len(sys.argv) > 6 else "cloud.ively.ai").strip()
# Strip protocol so we can use https for API and wss for WebSocket
cloud_host = cloud_url.replace("https://", "").replace("http://", "").strip("/")

print("Registering device...")

resp = requests.post(f"http://{cloud_host}:2018/register-edge", timeout=30).json()

device_id = resp["device_id"]
token = resp["token"]

# Save encrypted credentials
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

print("Discovering cameras...")
subprocess.run(
    ["python3", "-m", "agent.camera.discover"],
    cwd="/opt/ively/edge",
    check=False,
)

subprocess.run(["systemctl", "enable", "mediamtx"])
subprocess.run(["systemctl", "enable", "ively-agent"])
subprocess.run(["systemctl", "restart", "mediamtx"])
subprocess.run(["systemctl", "restart", "ively-agent"])

with open("/opt/ively/.provisioned", "w") as _:
    pass

subprocess.run(["systemctl", "disable", "ively-provision"])

print("Provision Complete")
