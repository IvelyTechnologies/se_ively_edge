# Ively Edge – SmartEye

One-click edge installer for MINI PC devices in the **SmartEye** project. Enables P2P communication between edge devices and the cloud.

---

## E2E Ively SmartEye Edge Device Installation

End-to-end flow from preparing the device to a working, provisioned edge with streams and cloud connection.

### Phase 1 — Prepare the device and network

| Step | Action | Notes |
|------|--------|--------|
| 1.1 | **Hardware** | MINI PC or Debian/Ubuntu machine (x86_64 or ARM). Monitor/keyboard or SSH access. |
| 1.2 | **OS** | Install **Debian** or **Ubuntu** (or Raspberry Pi OS / Armbian). Ensure `sudo` works. |
| 1.3 | **Network** | Connect the edge device to the **same LAN** as the IP cameras. Ensure the device can reach the **cloud** (e.g. `cloud.ively.ai` or your cloud server IP) for registration. |
| 1.4 | **Get the code** | Clone the repo onto the device (or copy the repo folder). Example: `git clone https://github.com/IvelyTechnologies/se_ively_edge.git` then `cd se_ively_edge`. |

### Phase 2 — Run the installer (on the device)

| Step | Action | Expected outcome |
|------|--------|------------------|
| 2.1 | **SSH or console** into the edge device. | You have a shell on the device. |
| 2.2 | `cd` into the repo (e.g. `cd ~/se_ively_edge` or `cd /path/to/se_ively_edge`). | Current directory is the repo root. |
| 2.3 | Run **one** of the installers **as root**: | |
| | **Venv (recommended):** `sudo bash installer/install-with-venv.sh` | |
| | **System Python:** `sudo bash installer/install.sh` | |
| 2.4 | Wait for the script to finish. | `apt` packages install; repo is cloned/updated to `/opt/ively/edge`; Python deps install; MediaMTX is downloaded and extracted; systemd units are installed; **ively-provision** is started. |
| 2.5 | Note the **banner** at the end: **Open http://edge.local or http://&lt;device-ip&gt;:2025 to provision.** | Use this IP (or `edge.local`) in the next phase. |

**If the installer fails:**

- **MediaMTX download error:** Ensure the device can reach `api.github.com` and `github.com`. Install `curl` if missing: `sudo apt install -y curl`, then re-run the installer.
- **python-multipart / Form error:** Run `/opt/ively/venv/bin/pip install python-multipart` (venv) or `pip3 install python-multipart` (system), then `sudo systemctl restart ively-provision`.
- **Port 2025 not listening:** See **Section 8** below (port conflict, firewall, logs).

### Phase 3 — Provision the device (web UI)

| Step | Action | Expected outcome |
|------|--------|------------------|
| 3.1 | From a **PC on the same network**, open a browser. | — |
| 3.2 | Go to **http://&lt;device-ip&gt;:2025** (or **http://edge.local:2025**). | Provision UI loads (dark theme, “Ively SmartEye™” and “Provision device” form). |
| 3.3 | Fill the form: | |
| | **Cloud URL** — Your cloud hostname or IP (e.g. `cloud.ively.ai` or `192.168.1.10`). No URL validation; IP is fine. | |
| | **Customer name**, **Site name** — e.g. "Acme Corp", "Warehouse A". | |
| | **Camera manufacturer** — Select or leave "Auto-detect from camera". | |
| | **Camera username / Camera password** — If your cameras need login. | |
| 3.4 | Click **Start setup**. | Response: “Provisioning started” (success page). |
| 3.5 | Backend: device registers with cloud, receives device ID and token; credentials are saved; ONVIF discovery runs; MediaMTX config is generated; **ively-provision** is disabled and **ively-agent** + **mediamtx** are started. | After ~1–2 minutes the device is fully provisioned. |

**If provisioning fails:**

- **Cannot connect to cloud:** Check Cloud URL (hostname or IP), network, and firewall. Ensure the edge device can reach the cloud (e.g. `curl -v https://<cloud-host>`).
- **ModuleNotFoundError: agent:** Ensure the **latest** provision-ui code is on the device (it must run the provision script with `PYTHONPATH` and `cwd`). Update repo and restart: `sudo systemctl restart ively-provision`.

### Phase 4 — Verify (post-provision)

| Step | Action | Expected outcome |
|------|--------|------------------|
| 4.1 | Open **http://&lt;device-ip&gt;:8080/view**. | Stream viewer page; list of stream paths (e.g. `cam1_low`, `cam1_hd`). Click “Open stream” to verify video. |
| 4.2 | Open **http://&lt;device-ip&gt;:8080/provisioned**. | Table: Device ID, Cloud URL, Customer, Site, and list of camera stream paths. |
| 4.3 | On the device run: `sudo systemctl status ively-agent mediamtx`. | Both show **active (running)**. |

**If streams don’t load:**

- Ensure cameras are on the same LAN and ONVIF discovery found them. Use **Rediscover cameras** on the provisioned page if you added cameras later.
- Check MediaMTX: `sudo systemctl status mediamtx` and `sudo journalctl -u mediamtx -n 30 --no-pager`. If you see “Failed to resolve hostname my_camera”, replace `mediamtx.yml` with a minimal config (see README troubleshooting) and restart MediaMTX.

### Phase 5 — Add a camera later (no full setup)

| Step | Action | Expected outcome |
|------|--------|------------------|
| 5.1 | Open **http://&lt;device-ip&gt;:8080/provisioned** (or **http://&lt;device-ip&gt;:2025** if provision UI is running and already provisioned). | Provisioned device table is shown. |
| 5.2 | Click **Rediscover cameras**. | Discovery runs in the background; mediamtx config is updated. |
| 5.3 | Refresh the page. | New stream paths appear in the table. View them at **http://&lt;device-ip&gt;:8080/view**. |

You do **not** need to run Provision setup again; only discovery is re-run.

### E2E summary

```
[Prepare device & network] → [Run installer on device] → [Open :2025 in browser]
       → [Fill form & Start setup] → [Verify :8080/view and :8080/provisioned]
       → [Optional: Rediscover cameras later]
```

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

### 11. E2E troubleshooting quick reference

| Symptom | Likely phase | What to do |
|---------|--------------|------------|
| Install fails: MediaMTX download / 404 / empty | Phase 2 | Device needs internet to `api.github.com` and `github.com`. Install `curl`; re-run installer. |
| Install fails: python-multipart / Form data | Phase 2 | `pip install python-multipart` (venv or system); restart `ively-provision`. |
| :2025 does not load / connection refused | Phase 2 / 3 | Port conflict: `sudo systemctl stop ively-agent` then `sudo systemctl start ively-provision`. Firewall: `sudo ufw allow 2025/tcp 8080/tcp`. Check `journalctl -u ively-provision -n 40`. |
| Provision fails: No module named 'agent' | Phase 3 | Update repo on device; ensure latest `provision-ui/main.py` (uses PYTHONPATH + cwd). Restart `ively-provision`. |
| Provision fails: cannot reach cloud | Phase 3 | Verify Cloud URL (IP or hostname), network from edge to cloud, firewall. |
| Agent crashes: camera.vault not found | Phase 4 | Normal if agent starts before provisioning. After provisioning, vault is created. Restart agent. |
| Logs: Failed to resolve hostname my_camera | Phase 4 | Replace `/opt/ively/mediamtx/mediamtx.yml` with minimal config (no placeholder paths); restart `mediamtx`. |
| No streams / empty list | Phase 4 / 5 | Cameras on same LAN? Run **Rediscover cameras** from :8080/provisioned or :2025. Check camera credentials in provision form. |

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
