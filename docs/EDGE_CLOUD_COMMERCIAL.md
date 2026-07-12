# Edge ↔ Cloud Commercial Integration (Phase 4 / EDGE-02, SEC-03)

**Repo:** `C:\Users\officeadmin\PycharmProjects\se_ively_edge` (sibling to `se_backend`)

This document describes how the **se_ively_edge** agent integrates with **se_backend** for commercial go-live.

Backend spec: `se_backend/documents/EDGE_HEARTBEAT_SPEC.md`

---

## Heartbeat (EDGE-02)

The agent sends WebSocket heartbeats every `IVELY_HEARTBEAT_INTERVAL` seconds (default **60**) to:

```
wss://{CLOUD_URL}/ws/{DEVICE_ID}
```

### Payload (required for camera health alerts)

```json
{
  "type": "heartbeat",
  "version": "1.4.2",
  "vpn_status": "connected",
  "cameras": {
    "streams": [
      {
        "stream_name": "customer_site_cam1_low",
        "status": "ok",
        "fps": 15.2,
        "last_frame_age_sec": 1.1
      }
    ],
    "total": 4,
    "active": 4,
    "healthy": 3
  }
}
```

**Implementation:**

| Component | File |
|-----------|------|
| Payload builder | `agent/heartbeat_streams.py` |
| Worker metrics + `last_frame_age_sec` | `agent/camera/camera_worker.py` |
| WebSocket sender | `agent/ws_client.py` → `build_heartbeat_payload()` |

`stream_name` must match the path segment in the camera `rtsp_url` on the cloud (e.g. `rtsp://10.20.0.5:8554/prefix_cam1_low` → `prefix_cam1_low`).

---

## Provisioning (SEC-03)

When the cloud has `EDGE_PROVISIONING_SECRET` set, export the matching key **before** provisioning:

```bash
export IVELY_EDGE_PROVISION_KEY='same-as-cloud-secret'
```

Used by:

- `installer/provision_device.py` → `POST /register-edge` with header `X-Edge-Provision-Key`
- Provision UI subprocess inherits `os.environ` — set the variable in the shell or systemd unit for `ively-provision`

---

## Environment variables

| Variable | Where | Purpose |
|----------|-------|---------|
| `DEVICE_ID` | `/opt/ively/agent/.env` | Set by register-edge |
| `TOKEN` | `.env` | Device auth token |
| `CLOUD_URL` | `.env` | Host only (no scheme) |
| `IVELY_HEARTBEAT_INTERVAL` | `agent/config.py` | 30–60 recommended |
| `IVELY_EDGE_PROVISION_KEY` | install-time env | register-edge auth |
| `IVELY_HLS_CDN_SECRET` | edge MediaMTX | Signed HLS (see `docs/HLS_MOBILE_PROXY.md`) |

---

## Verification

On the edge device:

```bash
# Local metrics (includes per-stream status)
curl -s http://127.0.0.1:8080/metrics | python3 -m json.tool

# Heartbeat payload (dry run)
cd /opt/ively/edge && python3 -c "
from agent.ws_client import build_heartbeat_payload
import json; print(json.dumps(build_heartbeat_payload(), indent=2))
"
```

On the cloud:

```bash
# Stream health for customer
curl -H "Authorization: Bearer $TOKEN" \
  "$API/api/v1/health/stream-health/1"
```

---

## Tests

```bash
cd /opt/ively/edge
python3 -m pytest tests/test_heartbeat_streams.py -q
```

---

## Related

- `se_backend/scripts/edge_heartbeat_reference.py` — reference payload
- `se_backend/deploy/verify-wireguard.sh` — VPN checks
- `se_backend/documents/PHASE4_IMPLEMENTATION.md` — tracker
