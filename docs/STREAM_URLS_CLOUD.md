# Stream URLs for Cloud / AI

How the cloud (or an AI pipeline) should form and use edge stream URLs.

---

## 1. Stream path format (per device)

After provisioning, each edge has a **customer** and **site**; paths in MediaMTX are:

| Path pattern | Description |
|--------------|-------------|
| `{customer}_{site}_cam{i}_low` | Substream (lower resolution, lower bandwidth) |
| `{customer}_{site}_cam{i}_hd`  | Main stream (HD) |

- `{customer}_{site}` is derived from the install form and sanitized (e.g. `Acme Corp` + `Warehouse A` → `acme_corp_warehouse_a`).
- `{i}` is the camera index: `1`, `2`, …

**Examples:**

- `acme_corp_warehouse_a_cam1_low`, `acme_corp_warehouse_a_cam1_hd`
- `acme_corp_warehouse_a_cam2_low`, `acme_corp_warehouse_a_cam2_hd`

---

## 2. Full URL the cloud should use

MediaMTX on the edge serves **WebRTC** (port 8889) and **HLS** on the same port. The cloud needs the **edge’s reachable base URL** (public IP, tunnel URL, or relay).

**Base:** `{BASE}` = e.g. `http://edge-public-ip:8889` or `https://tunnel.example.com`  
**Path:** one of the path names above (e.g. `acme_corp_warehouse_a_cam1_low`).

---

## 3. HLS URL for AI (recommended in the cloud)

**Yes — use the HLS URL for AI in the cloud.** HLS is HTTP-based, easy to consume from servers (ffmpeg, OpenCV, GStreamer, or any HLS client), and avoids WebRTC signaling.

**HLS URL format:**

```
{BASE}/{path}/
```

or the explicit playlist URL:

```
{BASE}/{path}/index.m3u8
```

**Examples (AI pipeline input):**

| Stream        | HLS URL (use this in cloud AI) |
|---------------|----------------------------------|
| Cam 1, low    | `http://203.0.113.10:8889/acme_corp_warehouse_a_cam1_low/` or `.../acme_corp_warehouse_a_cam1_low/index.m3u8` |
| Cam 1, HD     | `http://203.0.113.10:8889/acme_corp_warehouse_a_cam1_hd/` or `.../acme_corp_warehouse_a_cam1_hd/index.m3u8` |

**Typical use in code:**

- **ffmpeg:** `ffmpeg -i "http://edge:8889/acme_warehouse_a_cam1_low/index.m3u8" -frames:v 1 out.jpg`
- **OpenCV:** `cv2.VideoCapture("http://edge:8889/acme_warehouse_a_cam1_low/index.m3u8")`
- **Python (e.g. streamlink, ffmpeg-python):** open the HLS URL and read frames for inference.

The cloud stores **device_id → base URL** (and path list if needed); then it builds the HLS URL as `{base}/{path}/` or `{base}/{path}/index.m3u8`.

---

## 4. Which stream to use for AI

| Use case | Prefer | Reason |
|----------|--------|--------|
| **AI inference (detection, analytics)** | **`_low`** | Lower bandwidth and CPU; resolution is usually enough for person/vehicle detection. |
| **High‑detail analysis (e.g. face, plates)** | **`_hd`** | Higher resolution when the model or use case needs it. |
| **Recording / archive** | **`_hd`** | Better quality for playback. |

**Recommendation for AI in the cloud:** use the **`_low`** path by default (e.g. `{customer}_{site}_cam1_low`) to reduce cost and latency; switch to **`_hd`** only when the pipeline or model requires it.

---

## 5. Getting paths and base URL on the cloud

- **Base URL:**  
  - Set at provisioning or device registration (e.g. tunnel URL or public IP + port 8889).  
  - Optionally: edge sends it in the first message or heartbeat (e.g. `stream_base: "http://..."`) so the cloud can store it per `device_id`.

- **Path list:**  
  - Either fixed by convention: `{customer}_{site}_cam1_low`, `{customer}_{site}_cam1_hd`, … up to max cameras.  
  - Or: edge includes in heartbeat a list like `stream_paths: ["acme_corp_warehouse_a_cam1_low", "acme_corp_warehouse_a_cam1_hd", ...]` (you’d add this to the agent if you want).

- **Customer/site:**  
  - Stored in `/opt/ively/agent/site.json` on the edge; if the cloud needs it for display or routing, the edge can send `customer` and `site` in the heartbeat so the cloud can rebuild path names.

---

## 6. Example: HLS URL for AI pipeline

For device `device_abc123`, customer/site `acme_warehouse_a`, camera index `1`, using substream for AI:

- **Path:** `acme_warehouse_a_cam1_low`
- **Edge base:** `http://203.0.113.10:8889`
- **HLS URL for AI:** `http://203.0.113.10:8889/acme_warehouse_a_cam1_low/index.m3u8`

Use this HLS URL as the input to your cloud AI service (ffmpeg, OpenCV, or any HLS client).
