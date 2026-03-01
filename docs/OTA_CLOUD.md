# OTA (Over-The-Air) Updates — Cloud Integration

Edge devices receive update commands over the existing WebSocket connection. The cloud dashboard triggers OTA by sending a JSON command; the edge responds with success or failure and can send heartbeats with the current version.

---

## 1. WebSocket connection

- **Endpoint (edge → cloud):** `wss://cloud.ively.ai/ws/{DEVICE_ID}`
- **Device ID:** From provisioning; stored in `/opt/ively/agent/.env` as `DEVICE_ID`.
- **Connection:** Long-lived; edge reconnects with backoff (e.g. 5s) on disconnect.

---

## 2. Heartbeat (edge → cloud)

The edge sends a heartbeat message about every **60 seconds** so the cloud can show device status and **current firmware version**:

```json
{
  "type": "heartbeat",
  "version": "1.0.0"
}
```

**Cloud use:**

- Display “Edge version” in the dashboard.
- Decide if a device needs an update (e.g. `version < "1.1.0"`).
- Use “last heartbeat” as online/offline indicator.

---

## 3. OTA command (cloud → edge)

To trigger an update, the cloud sends a JSON message on the device’s WebSocket:

```json
{
  "action": "ota_update",
  "version": "1.1.0",
  "repo": "https://github.com/ivelyai/ively-edge.git"
}
```

| Field     | Required | Description                                                                 |
|----------|----------|-----------------------------------------------------------------------------|
| `action` | Yes      | Must be `"ota_update"`.                                                     |
| `version`| No       | Display/logging (e.g. "1.1.0"). Edge does not enforce it; used for rollout. |
| `repo`   | Yes      | HTTPS Git repo URL. Edge only allows `https://` URLs.                      |

**Security (edge enforces):**

- Only **HTTPS** `repo` URLs are accepted.
- Safe-update checks run before applying (CPU, disk, service health); see Edge logic below.

---

## 4. OTA response (edge → cloud)

After handling `ota_update`, the edge sends one JSON response:

**Success:**

```json
{
  "success": true,
  "message": "Updated to 1.1.0"
}
```

**Failure (no rollback):**

```json
{
  "success": false,
  "message": "Safe-update check failed: CPU usage too high"
}
```

**Failure (rollback performed):**

```json
{
  "success": false,
  "message": "Health check failed after update",
  "rollback_performed": true
}
```

**Cloud use:**

- Show “Update succeeded” or “Update failed: {message}” in the UI.
- If `rollback_performed: true`, show “Update failed and device was rolled back.”

---

## 5. Edge OTA flow (for reference)

1. **Download:** Backup `/opt/ively/edge` → `/opt/ively/edge_backup`, then `git fetch` + `git reset --hard origin/main` + `git pull`.
2. **Verify:** Only HTTPS repo; safe-update checks (CPU, disk, service).
3. **Switch:** `pip3 install -r requirements.txt`, then `systemctl restart ively-agent`.
4. **Health check:** After 10s, check `systemctl is-active ively-agent`.
5. **Commit or rollback:** If healthy, remove backup; otherwise restore backup and restart agent.

**Safe-update checks (no update if):**

- CPU > 80%
- Disk free < 2 GB
- Agent service not active

---

## 6. Example cloud flow (pseudo-code)

```javascript
// 1) List devices and versions from last heartbeat
const devices = await getDevices();
devices.forEach(d => {
  console.log(d.id, d.lastHeartbeat?.version); // e.g. "1.0.0"
});

// 2) User clicks "Update Edge" for device DEVICE_ID
const ws = getDeviceWebSocket(DEVICE_ID); // existing connection
ws.send(JSON.stringify({
  action: "ota_update",
  version: "1.1.0",
  repo: "https://github.com/ivelyai/ively-edge.git"
}));

// 3) Handle response
ws.on("message", (data) => {
  const msg = JSON.parse(data);
  if (msg.type === "heartbeat") {
    updateDeviceVersion(deviceId, msg.version);
  } else if (msg.success !== undefined) {
    if (msg.success) showToast("Update succeeded");
    else showToast("Update failed: " + msg.message);
  }
});
```

---

## 7. Checklist for cloud

- [ ] WebSocket server at `wss://cloud.ively.ai/ws/{DEVICE_ID}` (or your domain).
- [ ] Store `DEVICE_ID` (and optional token) per device after provisioning.
- [ ] Parse incoming messages: `type === "heartbeat"` → store `version` and last-seen time.
- [ ] “Update Edge” sends `{ action: "ota_update", version: "x.y.z", repo: "https://..." }`.
- [ ] Show OTA response (success / failure / rollback) in the dashboard.
- [ ] Use heartbeat + version to show “Current version” and “Update available” when appropriate.
