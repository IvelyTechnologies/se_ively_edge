# Ively Edge – SmartEye

One-click edge installer for MINI PC devices in the **SmartEye** project. Enables P2P communication between edge devices and the cloud.

## Features

- **One-click installer** – Deploy the full edge stack from a single script
- **Web provisioning UI** – Browser-based setup (camera credentials, device registration)
- **Device registration** – Registers the device with the cloud and receives a device ID
- **ONVIF auto discovery** – Scans the local network for IP cameras
- **MediaMTX auto config** – Generates `mediamtx.yml` from discovered cameras (RTSP → WebRTC)
- **Persistent agent** – Long-running process that stays connected to the cloud
- **Encrypted camera credentials** – Device-bound vault for camera user/password
- **systemd services** – `ively-agent`, `mediamtx`, `ively-provision` for reliable process management
- **Self-healing** – Watchdog restarts services, checks streams and disk, re-discovers cameras, recovers from internet loss
- **OTA updates** – Safe over-the-air updates from the cloud (backup → update → health check → rollback on failure)

## Architecture

```
installer/          # One-click install (install.sh, base_install.sh, provision_device.py)
provision-ui/       # FastAPI app for web provisioning (port 2025)
agent/              # Edge agent
  ├── main.py       # Entry: starts health + WebSocket client
  ├── discover.py   # Runs ONVIF scan + writes mediamtx config
  ├── onvif_scan.py # ONVIF camera discovery
  ├── mediamtx_writer.py
  ├── ws_client.py  # WebSocket client to cloud
  ├── health.py     # Health check server
  ├── watchdog.py   # Self-healing (services, stream, disk, re-discovery)
  ├── commands.py   # WebSocket command handler (OTA, etc.)
  ├── ota/          # OTA updater + version
  └── security/     # Device key + vault (encrypted credentials)
services/           # systemd unit files
  ├── ively-agent.service
  ├── mediamtx.service
  └── ively-provision.service
```

## Installation (industry-standard one-click)

Install on the **edge device** (e.g. MINI PC, Raspberry Pi, or any Debian/Ubuntu machine). **Do not** run the installer inside a Python venv or from your laptop — run it **as root on the device** where the agent will run.

### Prerequisites

- **OS:** Debian or Ubuntu (Raspberry Pi OS, Armbian, or x86_64).
- **Network:** Device and cameras on same LAN; device can reach the cloud (e.g. `cloud.ively.ai`) for registration.
- **Access:** SSH or console to the device, with `sudo`.

### Step 1 — Run the installer (recommended: system Python)

Clone or copy this repo onto the device, then run the installer **once** as root:

```bash
cd /path/to/se_ively_edge
sudo bash installer/install.sh
```

- The script installs system packages (`python3`, `pip`, `ffmpeg`, `git`, etc.), clones the repo to `/opt/ively/edge` if needed, installs Python dependencies **system-wide**, installs MediaMTX and systemd units, and starts the **provisioning UI**.
- **Do not** activate a venv before running `install.sh`; the script is intended to run with the system Python.

### Step 2 — Optional: install using a virtualenv

If you prefer dependency isolation (e.g. avoid conflicting with other Python apps on the same machine), use the venv installer:

```bash
sudo bash installer/install-with-venv.sh
```

- Creates `/opt/ively/venv` and installs dependencies there.
- systemd services are configured to use `/opt/ively/venv/bin/python3`.

### Step 3 — Provision the device (web UI)

1. On the same network as the device, open a browser: **http://edge.local** or **http://&lt;device-ip&gt;:2025**.
2. Fill in **Cloud URL** (e.g. `cloud.ively.ai`), **Customer name**, **Site name**, camera manufacturer, and camera username/password.
3. Click **Start Setup**. The device registers with the cloud, saves credentials, discovers cameras, and generates the MediaMTX config. The provisioning service then stops and the agent starts.

### Step 4 — Verify

- **Stream viewer:** Open **http://edge.local:2025** (or **http://&lt;device-ip&gt;:2025**). You should see the stream list; click a stream to confirm live video (P2P via MediaMTX).
- **Services:** `systemctl status ively-agent mediamtx` — both should be `active (running)`.

### Quick reference

| What              | Command / URL |
|-------------------|----------------|
| Install (system)  | `sudo bash installer/install.sh` |
| Install (venv)    | `sudo bash installer/install-with-venv.sh` |
| Provision UI      | http://edge.local:2025 or http://&lt;device-ip&gt;:2025 |
| Stream viewer     | http://edge.local:2025/view (after provisioning) |
| Agent logs        | `journalctl -u ively-agent -f` |

### If http://&lt;device-ip&gt;:2025 does not load ("unable to connect")

On the **device** (SSH or console), run:

```bash
# 1) Check the provision service is running
sudo systemctl status ively-provision

# 2) If it's failed or inactive, view recent logs
sudo journalctl -u ively-provision -n 30 --no-pager

# 3) Open port 2025 in the firewall (Ubuntu/Debian)
sudo ufw allow 2025/tcp
# If ufw is active you may need: sudo ufw reload

# 4) Confirm something is listening on 2025
ss -tlnp | grep 2025
```

Then try **http://&lt;device-ip&gt;:2025** again from your browser (use the device’s actual IP from the install message or `hostname -I`).

---

## After installation

- **Runtime** — The agent and MediaMTX run as systemd services; the agent keeps a WebSocket connection to the cloud for P2P communication.
- **OTA** — From the cloud dashboard, send an update command; edge backs up, pulls, installs, and rolls back automatically if health check fails. See [docs/OTA_CLOUD.md](docs/OTA_CLOUD.md) for cloud integration.
- **Cloud / AI** — For AI inference, use the **`_low`** stream path (e.g. `{customer}_{site}_cam1_low`) and HLS URL. See [docs/STREAM_URLS_CLOUD.md](docs/STREAM_URLS_CLOUD.md).

## License

See repository license file.
