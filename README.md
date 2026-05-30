# Ively Edge – SmartEye

One-click edge installer for MINI PC devices in the **SmartEye** project. Enables secure cloud connectivity via **WireGuard VPN tunnel** for AI processing, and **P2P WebRTC** for live dashboard viewing.

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
| 2.4 | Wait for the script to finish. | `apt` packages install (including **WireGuard**); repo is cloned/updated to `/opt/ively/edge`; Python deps install; MediaMTX is downloaded and extracted; systemd units are installed; **ively-provision** is started. |
| 2.5 | Note the **banner** at the end: **Open http://edge.local or http://&lt;device-ip&gt;:2025 to provision.** | Use this IP (or `edge.local`) in the next phase. |

**If the installer fails:**

- **MediaMTX download error:** Ensure the device can reach `api.github.com` and `github.com`. Install `curl` if missing: `sudo apt install -y curl`, then re-run the installer.
- **WireGuard install fails:** `sudo apt install -y wireguard wireguard-tools`. The agent still works without VPN (direct WebSocket to cloud), but VPN is recommended for production.
- **python-multipart / Form error:** Run `/opt/ively/venv/bin/pip install python-multipart` (venv) or `pip3 install python-multipart` (system), then `sudo systemctl restart ively-provision`.
- **Port 2025 not listening:** See **Section 8** below (port conflict, firewall, logs).

### Phase 3 — Provision the device (web UI)

| Step | Action | Expected outcome |
|------|--------|------------------|
| 3.1 | From a **PC on the same network**, open a browser. | — |
| 3.2 | Go to **http://&lt;device-ip&gt;:2025** (or **http://edge.local:2025**). | Provision UI loads (dark theme, "Ively SmartEye™" and "Provision device" form). |
| 3.3 | Fill the form: | |
| | **Cloud URL** — Your cloud hostname or IP (e.g. `cloud.ively.ai` or `192.168.1.10`). No URL validation; IP is fine. | |
| | **Customer name**, **Site name** — e.g. "Acme Corp", "Warehouse A". | |
| | **Customer ID**, **Site ID** — Optional numeric IDs to associate with cloud database. | |
| | **Camera manufacturer** — Select or leave "Auto-detect from camera". | |
| | **Camera username / Camera password** — If your cameras need login. | |
| 3.4 | Click **Start setup**. | Response: "Provisioning started" (success page). |
| 3.5 | Backend: registers with cloud (VPN + credentials); writes **cams.json**; generates **mediamtx.yml** (`source: publisher` paths); starts **mediamtx** then **ively-agent** (FFmpeg workers publish H.264 to each path). | After ~1–2 minutes: VPN up, workers running, streams available. |

**If provisioning fails:**

- **Cannot connect to cloud:** Check Cloud URL (hostname or IP), network, and firewall. Ensure the edge device can reach the cloud (e.g. `curl -v https://<cloud-host>`).
- **WireGuard tunnel not established:** Check `sudo wg show` and `sudo journalctl -u wg-quick@wg0`. The device still works via direct WebSocket connection, but VPN is recommended.
- **ModuleNotFoundError: agent:** Ensure the **latest** provision-ui code is on the device (it must run the provision script with `PYTHONPATH` and `cwd`). Update repo and restart: `sudo systemctl restart ively-provision`.

### Phase 4 — Verify (post-provision)

| Step | Action | Expected outcome |
|------|--------|------------------|
| 4.1 | Open **http://&lt;device-ip&gt;:8080/view**. | Stream viewer page; list of stream paths (e.g. `cam1_low`). Click "Open stream" to verify video. |
| 4.2 | Open **http://&lt;device-ip&gt;:8080/provisioned**. | Table: Device ID, Cloud URL, Customer, Site, **VPN Status**, **VPN IP**, and list of camera stream paths. |
| 4.3 | On the device run: `sudo systemctl status mediamtx ively-agent`. | Both **active (running)** (agent starts after MediaMTX). |
| 4.3b | After **reboot**, same check without manual start. | Services auto-start if enabled: `systemctl is-enabled mediamtx ively-agent` → **enabled**. |
| 4.4 | `curl -s http://localhost:9997/v3/paths/list \| jq` | Each path shows **`"ready": true`** (FFmpeg publisher connected). |
| 4.5 | `curl -s http://127.0.0.1:8080/metrics \| jq '.summary, .live_workers'` | Workers **ok**, FPS &gt; 0. |
| 4.6 | Check VPN: `sudo wg show` and `curl http://localhost:8080/vpn-status`. | Tunnel connected. |

**If streams don't load:**

- **`ready: false`** on paths/list → workers not publishing: `curl -s -X POST http://127.0.0.1:8080/workers/reload` then recheck paths/list.
- Ensure cameras on same LAN; credentials in provision form match NVR.
- `sudo journalctl -u ively-agent -f` — look for `[worker:..._low] Started` and RTSP errors.
- Use **Rediscover cameras** on :8080/provisioned (regenerates config + reloads workers).

### Phase 5 — Add a camera later (no full setup)

| Step | Action | Expected outcome |
|------|--------|------------------|
| 5.1 | Open **http://&lt;device-ip&gt;:8080/provisioned** (or **http://&lt;device-ip&gt;:2025** if provision UI is running and already provisioned). | Provisioned device table is shown. |
| 5.2 | Click **Rediscover cameras**. | Updates mediamtx.yml and reloads FFmpeg workers (no full re-provision). |
| 5.3 | Wait ~30s, then `curl -s http://localhost:9997/v3/paths/list \| jq` | Paths **`ready: true`**. View at **http://&lt;device-ip&gt;:8080/view**. |

You do **not** need to run Provision setup again; only discovery is re-run.

### E2E summary

```
[Install] → [:2025 provision] → [cams.json + mediamtx.yml]
       → [mediamtx start] → [ively-agent starts FFmpeg workers per camera]
       → [paths/list ready:true] → [:8080/view + VPN/cloud]
       → [Optional: Rediscover → worker reload]
```

### Streaming architecture (enterprise)

Every camera gets **one published path** (e.g. `customer_site_cam1_low`). The pipeline is:

```
Camera/NVR (any codec: H.265, H.264, MJPEG, …)
        │
        ▼  FFmpeg worker (persistent, per camera)
   Transcode → H.264 (yuv420p, main profile, no B-frames)
        │
        ▼  RTSP publish → MediaMTX path (source: publisher)
        │
        ├── RTSP  :8554/{path}           ← AI / OpenCV / ffprobe (recommended)
        ├── HLS   :8888/{path}/index.m3u8 ← browsers, players
        └── WebRTC :8889/{path}           ← low-latency dashboard
```

**Guarantees:**

| Layer | Behavior |
|-------|----------|
| **Input** | Any RTSP codec from camera/NVR; no NVR menu changes required |
| **Transcode** | Always **H.264** at configured profile (default 640×360 @ 10fps) |
| **Output** | Same H.264 stream on **all three** protocols — MediaMTX remuxes only, no second encode |
| **Readiness** | Path `"ready": true` on `:9997/v3/paths/list` means FFmpeg is publishing |

**Backend integration:** `GET /metrics` includes `stream_endpoints` with `rtsp`, `hls`, and `webrtc` URLs (host = VPN IP when tunnel is up). Prefer **RTSP** for cloud AI ingestion over VPN.

**Encoder profile** (override via `IVELY_STREAM_PROFILES_JSON`):

```json
{"low": {"width": "640", "height": "360", "fps": "10", "bitrate": "512k"}}
```

Optional: `IVELY_USE_NVENC=1` for GPU encode; `IVELY_STREAM_ULTRA_LOW=1` for weak links.

**WebRTC ICE (edge)** — VPN direct + Google STUN; TURN optional when coturn is deployed:

| Role | Setting | Example |
|------|---------|---------|
| Cloud API (REST/WebSocket) | `CLOUD_URL` in `.env` | `api.ivelytech.com` |
| Edge stream (VPN) | `webrtcIPsFromInterfacesList: [wg0]` | `10.20.0.3:8889` / `:8189` |
| STUN (edge default) | `webrtcICEServers2` | `stun:stun.l.google.com:19302` |
| TURN (optional) | `IVELY_TURN_*` in `.env` when coturn runs | `turn.ivelytech.com` |
| **Do not use** | ~~`webrtcAdditionalHosts: api.ivelytech.com`~~ | cloud API ≠ edge WebRTC |

TURN is **disabled by default** on the edge (Google STUN only). When you deploy coturn, add to `/opt/ively/agent/.env`:

```bash
IVELY_TURN_HOST=turn.ivelytech.com
IVELY_TURN_USERNAME=ivelyturn
IVELY_TURN_PASSWORD=your_secret
```

Then `sudo systemctl restart ively-agent mediamtx` and verify:

```bash
grep -A20 webrtcICEServers2 /opt/ively/mediamtx/mediamtx.yml
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

- Installs: `curl`, `git`, `python3`, `pip`, `ffmpeg`, `jq`, `avahi-daemon`, **WireGuard**, MediaMTX, Python deps, systemd units.
- Repo is cloned/updated at `/opt/ively/edge`.
- At the end you get a message with the device IP and URLs — note them.

### 3. Provision the device (web UI, run once)

1. On a machine on the **same network**, open a browser:  
   **http://edge.local:2025** or **http://&lt;device-ip&gt;:2025**
2. Fill in:
   - **Cloud URL** — hostname or IP (e.g. `cloud.ively.ai` or `192.168.1.10`)
   - **Customer name**, **Site name**
   - **Customer ID**, **Site ID** (optional)
   - **Camera manufacturer** (or Auto-detect)
   - **Camera username** / **Camera password** (if required by your cameras)
3. Click **Start Setup**.  
   The device registers with the cloud, **establishes a WireGuard VPN tunnel**, saves credentials, discovers cameras, and generates the MediaMTX config. The provision service then stops and the agent runs.

### 4. Verify after provisioning

| Action | URL or command |
|--------|-----------------|
| View live streams | **http://&lt;device-ip&gt;:8080/view** (or http://edge.local:8080/view) |
| See provisioned device & camera list | **http://&lt;device-ip&gt;:8080/provisioned** |
| Check services | `sudo systemctl status ively-agent mediamtx` |
| Check VPN tunnel | `sudo wg show` |
| VPN status API | `curl http://localhost:8080/vpn-status` |

Both services should be **active (running)** and VPN should show a recent handshake.

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
| Restart agent | `sudo systemctl restart ively-agent` |
| Fix boot autostart (one-time) | `sudo bash /opt/ively/edge/installer/ensure-services-enabled.sh` |
| Check enabled on boot | `systemctl is-enabled mediamtx ively-agent` |
| Restart WireGuard | `sudo wg-quick down wg0 && sudo wg-quick up wg0` |
| Start provision UI (e.g. to show table or rediscover) | `sudo systemctl start ively-provision` |
| Stop provision UI (free port 2025) | `sudo systemctl stop ively-provision` |
| Agent logs (live) | `sudo journalctl -u ively-agent -f` |
| Provision UI logs | `sudo journalctl -u ively-provision -n 50 --no-pager` |
| MediaMTX logs | `sudo journalctl -u mediamtx -n 50 --no-pager` |
| WireGuard status | `sudo wg show` |

### 7. Ports and URLs quick reference

| Port | Service | URL |
|------|---------|-----|
| **2025** | Provision UI (setup, table view, rediscover) | http://&lt;device-ip&gt;:2025 |
| **8080** | Agent (stream viewer, provisioned table, VPN status) | http://&lt;device-ip&gt;:8080 |
| **8080/view** | Stream viewer | http://&lt;device-ip&gt;:8080/view |
| **8080/provisioned** | Provisioned device & cameras table | http://&lt;device-ip&gt;:8080/provisioned |
| **8080/vpn-status** | WireGuard VPN status (JSON) | http://&lt;device-ip&gt;:8080/vpn-status |
| **8554** | MediaMTX RTSP | `rtsp://&lt;device-ip&gt;:8554/&lt;path&gt;` |
| **8888** | MediaMTX HLS | `http://&lt;device-ip&gt;:8888/&lt;path&gt;/index.m3u8` |
| **8889** | MediaMTX WebRTC | `http://&lt;device-ip&gt;:8889/&lt;path&gt;` |
| **9997** | MediaMTX API (paths/list) | `http://127.0.0.1:9997/v3/paths/list` |
| **8189** | WebRTC internal UDP/TCP routing ports | — |
| **51820/udp** | WireGuard VPN tunnel | — |

### 8. If Provision UI (port 2025) does not load

- **Port conflict:** Only one service can use 2025. If the agent is running, stop it first, then start the provision UI:

  ```bash
  sudo systemctl stop ively-agent
  sudo systemctl start ively-provision
  ```

- **Firewall:** Allow ports 2025, 8080, and 51820:

  ```bash
  sudo ufw allow 2025/tcp
  sudo ufw allow 8080/tcp
  sudo ufw allow 51820/udp
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
| `/opt/ively/agent/wg_keys` | WireGuard key pair (privatekey, publickey) |
| `/opt/ively/agent/wg_state.json` | WireGuard VPN state (vpn_ip, server_public_key, endpoint) |
| `/opt/ively/mediamtx` | MediaMTX binary and `mediamtx.yml` |
| `/opt/ively/.provisioned` | Marker file: device has been provisioned |
| `/etc/wireguard/wg0.conf` | WireGuard VPN config (auto-generated during provisioning) |
| `/recordings` | Recordings directory (if used) |

### 11. WireGuard VPN Architecture

The edge device uses WireGuard to create a secure encrypted tunnel to the Ively cloud:

```
Customer Site                              Ively Cloud
─────────────                              ───────────
Camera                                     WireGuard Server (10.20.0.1)
   │                                              │
   ▼                                              │
Edge Device                                       │
 ├ MediaMTX (RTSP/WebRTC)                         │
 ├ WireGuard Client (10.20.0.x) ◄─── VPN ───►    │
 └ Device Agent                                   │
                                                  │
                                            ├ AI Workers
                                            ├ FastAPI Backend
                                            └ Dashboard
```

**How it works:**

1. During provisioning, the edge device generates a WireGuard key pair
2. The public key is sent to the cloud during registration
3. The cloud assigns a VPN IP and returns the server config
4. The edge device configures WireGuard and establishes the tunnel
5. WireGuard auto-starts on boot (`wg-quick@wg0`)

**Cloud access to streams via VPN:**

```
rtsp://10.20.0.x:8554/customer_site_cam1_low
```

**Benefits:**
- ✅ No port forwarding required at customer site
- ✅ Encrypted tunnel (ChaCha20)
- ✅ Works behind NAT and firewalls
- ✅ Plug-and-play installation
- ✅ Self-healing (watchdog monitors tunnel health)

**Remote VPN management (via WebSocket commands):**

| Command | Action |
|---------|--------|
| `{"action": "wg_status"}` | Get VPN tunnel status |
| `{"action": "wg_restart"}` | Restart VPN tunnel |
| `{"action": "wg_pubkey"}` | Get device public key |
| `{"action": "wg_provision", ...}` | Push new VPN config |

### 12. E2E troubleshooting quick reference

| Symptom | Likely phase | What to do |
|---------|--------------|------------|
| Install fails: MediaMTX download / 404 / empty | Phase 2 | Device needs internet to `api.github.com` and `github.com`. Install `curl`; re-run installer. |
| Install fails: WireGuard not available | Phase 2 | `sudo apt install -y wireguard wireguard-tools`. Agent works without VPN but it's recommended. |
| Install fails: python-multipart / Form data | Phase 2 | `pip install python-multipart` (venv or system); restart `ively-provision`. |
| :2025 does not load / connection refused | Phase 2 / 3 | Port conflict: `sudo systemctl stop ively-agent` then `sudo systemctl start ively-provision`. Firewall: `sudo ufw allow 2025/tcp 8080/tcp`. Check `journalctl -u ively-provision -n 40`. |
| Provision fails: No module named 'agent' | Phase 3 | Update repo on device; ensure latest `provision-ui/main.py` (uses PYTHONPATH + cwd). Restart `ively-provision`. |
| Provision fails: cannot reach cloud | Phase 3 | Verify Cloud URL (IP or hostname), network from edge to cloud, firewall. |
| VPN not connected / no handshake | Phase 3 / 4 | `sudo wg show`, `sudo wg-quick down wg0 && sudo wg-quick up wg0`. Check cloud WG server is running. |
| Agent crashes: `No module named 'psutil'` | Phase 4 | Use venv: `sudo /opt/ively/venv/bin/pip install -r /opt/ively/edge/requirements.txt` then deploy `run-ively-agent.sh` service and `sudo systemctl daemon-reload && sudo systemctl restart ively-agent`. Or: `sudo pip3 install psutil`. |
| Agent crashes: camera.vault not found | Phase 4 | Normal if agent starts before provisioning. After provisioning, vault is created. Restart agent. |
| MediaMTX crashes without workers | Phase 4 | MediaMTX config may contain bad paths; check `/opt/ively/mediamtx/mediamtx.yml` (all sources should be `publisher`). |
| No streams / empty list | Phase 4 / 5 | Cameras on same LAN? Run **Rediscover cameras** from :8080/provisioned or :2025. Check camera credentials in provision form. |
| RTSP works but HLS/WebRTC 404 | Phase 4 | On edge: `sudo ss -tlnp \| grep -E '8554\|8888\|8889\|9997'`. Config must have `hls: yes`, `webrtc: yes`, `api: yes` in `/opt/ively/mediamtx/mediamtx.yml` (not `/etc/mediamtx/`). Regenerate: rediscover cameras or restart agent after code update; `sudo systemctl restart mediamtx`. List paths: `curl -s http://127.0.0.1:9997/v3/paths/list \| jq` — use exact path names in URLs. |
| WebRTC `deadline exceeded while waiting connection` | Phase 4 | HTTP signaling OK but ICE failed. RTSP from cloud (`10.20.0.1`) working means VPN TCP is fine — WebRTC media uses **UDP/TCP :8189**. On edge: `webrtcIPsFromInterfacesList: [wg0]`. Allow VPN → edge: `sudo ufw allow from 10.20.0.0/16 to any port 8189`. TURN is optional — only set `IVELY_TURN_*` when coturn is actually running. **Cloud AI should use RTSP :8554**. |
| WebRTC “no stream” from cloud browser | Phase 4 | Path must show `"ready": true`. `webrtcAdditionalHosts` = hostnames of the **edge** WebRTC server (not TURN). Only add `api.ivelytech.com` if browsers open WebRTC at that hostname and DNS routes to the edge. For VPN cloud→edge use `wg0` ICE list. TURN goes in `IVELY_TURN_URL`, not additionalHosts. |

### 13. Enterprise Edge Architecture (Observability & Self-Healing)

The edge system now natively runs an **Enterprise Worker Architecture** prioritizing extreme stream stability and low latency. It abandons `runOnDemand` pulling and replaces it with persistent per-camera processes.

**Key Operations Mechanisms:**

- **Persistent Processes**: The `ively-agent` (`CameraWorkerManager`) runs a persistent `ffmpeg` process per camera. These push to MediaMTX. No more reconnect storms due to MediaMTX tearing down idle listeners.
- **Deep Freeze Detection**: The local watchdog scans local streaming pipes for locked bitrates, delayed/stalled frame decoding, and low FPS counts. If a stream freezes, the agent restarts *only* the single broken worker, leaving all other 99 cameras online.
- **SQLite Database Metrics**: CPU, memory, Disk percentage, WireGuard Tunnel heartbeats, individual stream FPS, reconnects, and bitrates are synced every 30 seconds to `/opt/ively/agent/metrics.db` (retention: 7 days).
- **WebRTC Enabled by Default**: MediaMTX is bound out-of-the-box with Google's STUN for millisecond latency on the `http://<device-ip>:8080/view` dashboard.

**How to observe the health API (JSON):**

```bash
# General real-time stream status and diagnostics
curl -s http://localhost:8080/metrics | jq .
```

**Troubleshooting New Edge Workers:**

| Symptom | Cause & Action |
|---------|----------------|
| `curl` metrics shows camera status `frozen` or `stalled` | The stream is broken at the source or the camera crashed. The `watchdog` will auto-restart the individual worker. If it hits max restarts (default: 3), it enters a cooldown. Check the camera physical network connection. |
| Camera stuck in `cooldown` | Worker crashed >3 times within 5 minutes. The system is protecting CPU from spin loops. It will automatically try again after the cooldown window expires. |
| MediaMTX logs show no activity | This is normal! Subprocesses handle fetching. To view actual camera stream health logs, check the agent trace: `sudo journalctl -u ively-agent -f`. Look for lines tagged `[worker:cam1_low]`. |
| Want to manually clear a cooldown? | Rather than restarting MediaMTX (which drops all feeds), restart the agent which flushes the manager's restart tracker: `sudo systemctl restart ively-agent`. |
| `metrics.db` size growing too large? | The agent auto-prunes records older than 7 days per loop. No manual cleanup is required. |

### 14. CP Plus / Dahua camera behind NVR (important)

When the camera is added **on the NVR** (e.g. camera IP `192.168.0.2`, NVR web UI at `192.168.0.195`, **channel 4**):

| Field | Use |
|-------|-----|
| RTSP host | **NVR IP** (`192.168.0.195`) — not the camera IP |
| Channel | **NVR channel** (`4` in your screenshot) — not always `1` |
| Credentials | **NVR login** (`admin` + NVR password) — from provision form / vault |
| Stream | `subtype=1` (substream) — edge default |

Example `cams.json`:

```json
[
  {
    "ip": "192.168.0.2",
    "rtsp_host": "192.168.0.195",
    "model": "cp plus",
    "selected_channels": [4]
  }
]
```

Test from edge PC:

```bash
ffprobe -rtsp_transport tcp "rtsp://admin:YOUR_NVR_PASSWORD@192.168.0.195:554/cam/realmonitor?channel=4&subtype=1"
```

### 15. H.265 / Dahua NVR — no menu changes required

The edge **accepts H.265 (HEVC) or H.264** from the NVR over RTSP and **always publishes H.264** to MediaMTX (default: 640×360, 10 fps, 512 kbps). You do **not** need to switch the NVR to H.264.

**Defaults (no env vars):**

- Dahua / CP Plus: use **substream only** (`subtype=1`) — avoids broken main streams.
- **ffprobe** each RTSP URL before starting workers; only working URLs are used.
- FFmpeg input: corrupt-packet discard, HEVC error concealment, tolerant timestamps (Smart H.265+).

**Optional overrides:**

| Variable | Default | Purpose |
|----------|---------|---------|
| `IVELY_SUBSTREAM_ONLY` | `1` | `0` = also try main stream |
| `IVELY_RTSP_PROBE_URLS` | `1` | `0` = skip ffprobe URL filter |
| Per camera in `cams.json` | — | `"rtsp_url": "rtsp://..."` if you know the exact working URL |

After deploy: `sudo systemctl restart ively-agent` then `curl -s -X POST http://127.0.0.1:8080/workers/reload`.

---

## Features (overview)

- **One-click installer** – Deploy the full edge stack from a single script
- **WireGuard VPN tunnel** – Secure encrypted connection to cloud (auto-configured during provisioning)
- **Web provisioning UI** – Browser-based setup (port 2025)
- **Device registration** – Registers with the cloud and receives a device ID + VPN config
- **ONVIF auto discovery** – Scans the LAN for IP cameras
- **MediaMTX & Persistent Workers** – RTSP → HLS/WebRTC pipeline using robust, self-healing workers
- **Provisioned device table** – View Device ID, Customer, Site, VPN status, cameras (port 8080/provisioned or 2025 when already provisioned)
- **Rediscover cameras** – Add new cameras without running full setup again
- **systemd services** – `ively-agent`, `mediamtx`, `ively-provision`, `wg-quick@wg0`
- **Self-healing Enterprise Watchdog** – Restarts isolated camera workers instantly upon frozen packets without disrupting the global multi-tenant site cluster.
- **OTA updates** – From the cloud; see [docs/OTA_CLOUD.md](docs/OTA_CLOUD.md)
- **Remote VPN management** – Cloud can query status, restart tunnel, push new config via WebSocket

## Architecture

```
installer/          # install.sh, install-with-venv.sh, base_install.sh, provision_device.py
provision-ui/       # FastAPI app (port 2025): setup form, provisioned table, rediscover
agent/              # Edge agent (health server on port 8080, WebSocket, discovery, watchdog)
agent/wireguard/    # WireGuard VPN client: key management, tunnel lifecycle, health monitoring
services/           # systemd: ively-agent.service, mediamtx.service, ively-provision.service
```

## After installation

- **Runtime** — Agent and MediaMTX run as systemd services; the agent keeps a WebSocket connection to the cloud. WireGuard VPN runs as `wg-quick@wg0` for secure tunnel connectivity.
- **VPN** — Cloud AI workers access camera streams via WireGuard VPN: `rtsp://10.20.0.x:8554/cam_path`. No port forwarding needed.
- **OTA** — From the cloud dashboard, send an update command; edge backs up, pulls, installs, and rolls back on failure. See [docs/OTA_CLOUD.md](docs/OTA_CLOUD.md).
- **Cloud / AI** — Use the **`_low`** stream path and HLS URL for inference. See [docs/STREAM_URLS_CLOUD.md](docs/STREAM_URLS_CLOUD.md).

## License

See repository license file.
