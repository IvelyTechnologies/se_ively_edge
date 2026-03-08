# Ively Edge – SmartEye

One-click edge installer for MINI PC devices in the **SmartEye** project. Enables P2P communication between edge devices and the cloud.

---

## Important steps for the edge device

Use this section as the main reference for setting up and operating the edge device.

### 1. Prerequisites

- **OS:** Debian or Ubuntu (Raspberry Pi OS, Armbian, or x86_64).
- **Network:** Edge device and cameras on the **same LAN**; device can reach the cloud (e.g. `cloud.ively.ai` or your cloud IP) for registration.
- **Access:** SSH or console to the device with `sudo`.

### 2. Install on the device (run once)

Run **on the edge device** as root (not from your laptop, not inside a venv):

```bash
cd /path/to/se_ively_edge
sudo bash installer/install-with-venv.sh
```

Or with system Python:

```bash
sudo bash installer/install.sh
```

- Installs: `curl`, `git`, `python3`, `pip`, `ffmpeg`, `jq`, `avahi-daemon`, MediaMTX, Python deps, systemd units.
- Repo is cloned/updated at `/opt/ively/edge`.
- At the end you get a message with the device IP and URLs — note them.

### 3. Provision the device (web UI, run once)

1. On a machine on the **same network**, open a browser:  
   **http://edge.local:2025** or **http://&lt;device-ip&gt;:2025**
2. Fill in:
   - **Cloud URL** — hostname or IP (e.g. `cloud.ively.ai` or `192.168.1.10`)
   - **Customer name**, **Site name**
   - **Camera manufacturer** (or Auto-detect)
   - **Camera username** / **Camera password** (if required by your cameras)
3. Click **Start Setup**.  
   The device registers with the cloud, saves credentials, discovers cameras, and generates the MediaMTX config. The provision service then stops and the agent runs.

### 4. Verify after provisioning

| Action | URL or command |
|--------|-----------------|
| View live streams | **http://&lt;device-ip&gt;:8080/view** (or http://edge.local:8080/view) |
| See provisioned device & camera list | **http://&lt;device-ip&gt;:8080/provisioned** |
| Check services | `sudo systemctl status ively-agent mediamtx` |

Both services should be **active (running)**.

### 5. New camera added later (no full setup again)

You do **not** need to run Provision setup again.

1. Open **http://&lt;device-ip&gt;:8080/provisioned** (or **http://&lt;device-ip&gt;:2025** if the provision UI is running and already provisioned).
2. Click **Rediscover cameras**.  
   Discovery runs in the background and updates the MediaMTX config.
3. Refresh the page to see the new stream paths. Streams appear at **http://&lt;device-ip&gt;:8080/view**.

### 6. Service commands (on the device)

| Purpose | Command |
|---------|--------|
| Restart agent | `sudo systemctl restart ively-agent` |
| Restart MediaMTX | `sudo systemctl restart mediamtx` |
| Start provision UI (e.g. to show table or rediscover) | `sudo systemctl start ively-provision` |
| Stop provision UI (free port 2025) | `sudo systemctl stop ively-provision` |
| Agent logs (live) | `sudo journalctl -u ively-agent -f` |
| Provision UI logs | `sudo journalctl -u ively-provision -n 50 --no-pager` |
| MediaMTX logs | `sudo journalctl -u mediamtx -n 50 --no-pager` |

### 7. Ports and URLs quick reference

| Port | Service | URL |
|------|---------|-----|
| **2025** | Provision UI (setup, table view, rediscover) | http://&lt;device-ip&gt;:2025 |
| **8080** | Agent (stream viewer, provisioned table) | http://&lt;device-ip&gt;:8080 |
| **8080/view** | Stream viewer | http://&lt;device-ip&gt;:8080/view |
| **8080/provisioned** | Provisioned device & cameras table | http://&lt;device-ip&gt;:8080/provisioned |
| **8889** | MediaMTX WebRTC (used by stream viewer) | — |

### 8. If Provision UI (port 2025) does not load

- **Port conflict:** Only one service can use 2025. If the agent is running, stop it first, then start the provision UI:

  ```bash
  sudo systemctl stop ively-agent
  sudo systemctl start ively-provision
  ```

- **Firewall:** Allow ports 2025 and 8080:

  ```bash
  sudo ufw allow 2025/tcp
  sudo ufw allow 8080/tcp
  ```

- **Check service and logs:**

  ```bash
  sudo systemctl status ively-provision
  sudo journalctl -u ively-provision -n 40 --no-pager
  ss -tlnp | grep 2025
  ```

- Use the **device IP** from the install message or `hostname -I` in the browser.

### 9. Update code on the device

If you pull new code (e.g. from GitHub) into the repo on the device:

```bash
cd /opt/ively/edge
sudo git fetch && sudo git reset --hard origin/main
sudo systemctl restart ively-agent
# If using venv and dependencies changed:
# /opt/ively/venv/bin/pip install -r requirements.txt
# sudo systemctl restart ively-agent
```

### 10. Important paths on the device

| Path | Purpose |
|------|---------|
| `/opt/ively/edge` | Repo (agent, provision-ui, installer) |
| `/opt/ively/venv` | Python venv (if using install-with-venv.sh) |
| `/opt/ively/agent` | Provisioned config: `.env`, `site.json`, `camera.vault`, `camera.manufacturer` |
| `/opt/ively/mediamtx` | MediaMTX binary and `mediamtx.yml` |
| `/opt/ively/.provisioned` | Marker file: device has been provisioned |
| `/recordings` | Recordings directory (if used) |

---

## Features (overview)

- **One-click installer** – Deploy the full edge stack from a single script
- **Web provisioning UI** – Browser-based setup (port 2025)
- **Device registration** – Registers with the cloud and receives a device ID
- **ONVIF auto discovery** – Scans the LAN for IP cameras
- **MediaMTX** – RTSP → WebRTC; config generated from discovered cameras
- **Provisioned device table** – View Device ID, Customer, Site, cameras (port 8080/provisioned or 2025 when already provisioned)
- **Rediscover cameras** – Add new cameras without running full setup again
- **systemd services** – `ively-agent`, `mediamtx`, `ively-provision`
- **Self-healing** – Watchdog restarts services, re-discovers cameras, recovers from internet loss
- **OTA updates** – From the cloud; see [docs/OTA_CLOUD.md](docs/OTA_CLOUD.md)

## Architecture

```
installer/          # install.sh, install-with-venv.sh, base_install.sh, provision_device.py
provision-ui/       # FastAPI app (port 2025): setup form, provisioned table, rediscover
agent/              # Edge agent (health server on port 8080, WebSocket, discovery, watchdog)
services/           # systemd: ively-agent.service, mediamtx.service, ively-provision.service
```

## After installation

- **Runtime** — Agent and MediaMTX run as systemd services; the agent keeps a WebSocket connection to the cloud.
- **OTA** — From the cloud dashboard, send an update command; edge backs up, pulls, installs, and rolls back on failure. See [docs/OTA_CLOUD.md](docs/OTA_CLOUD.md).
- **Cloud / AI** — Use the **`_low`** stream path and HLS URL for inference. See [docs/STREAM_URLS_CLOUD.md](docs/STREAM_URLS_CLOUD.md).

## License

See repository license file.
