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
provision-ui/       # FastAPI app for web provisioning (port 8080)
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

## Quick start

1. **Install (on the MINI PC)**

   ```bash
   bash installer/install.sh
   ```

2. **Provision** – Open `http://<device-ip>:8080` (or `http://edge.local`), enter camera credentials, and complete device registration.

3. **Runtime** – The agent and MediaMTX run as systemd services; the agent keeps a WebSocket connection to the cloud for P2P communication.

4. **Verify streams (P2P video view)** – After installation, open **http://edge.local:8080** (or `http://<device-ip>:8080`). You get the **stream viewer**: click a stream (e.g. `cam1_hd`) to play the live camera feed from MediaMTX (WebRTC). This confirms P2P pipelines are working without using the cloud.

5. **OTA** – From the cloud dashboard, send an update command; edge backs up, pulls, installs, and rolls back automatically if health check fails. See [docs/OTA_CLOUD.md](docs/OTA_CLOUD.md) for cloud integration.

**Cloud / AI:** For AI inference, use the **`_low`** stream path (e.g. `{customer}_{site}_cam1_low`) to reduce bandwidth. Full URL format: [docs/STREAM_URLS_CLOUD.md](docs/STREAM_URLS_CLOUD.md).

## License

See repository license file.
