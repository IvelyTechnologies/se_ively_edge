# HLS mobile playback via api.ivelytech.com

Mobile apps and browsers cannot reach edge VPN IPs (`10.20.0.x`) directly. HLS is published on the edge at `:8888` and proxied on the API server at:

```text
https://api.ivelytech.com/edge-stream/{vpn_ip}/{stream_path}/index.m3u8
```

MediaMTX v1.18+ requires a valid HLS **session** for `.ts` segment requests. Through nginx, playlists often load but **segments return 401/404** unless the edge and API server share an **`hlsCDNSecret`**.

Full deployment guide (API nginx): **se_backend** → `documents/UBUNTU_2404_DEPLOYMENT_GUIDE.md` section **7.3.2**.

---

## Step 1 — Edge device (this repo)

Generated config path: `/opt/ively/mediamtx/mediamtx.yml` (from `agent/camera/mediamtx_writer.py`).

### Set the secret (choose one)

**Option A — environment variable** (used when regenerating config):

```bash
# Fleet secret (must match api.ivelytech.com nginx Bearer — see se_backend documents/deploy/nginx-edge-stream-hls-auth.snippet)
# Override: export IVELY_HLS_CDN_SECRET=... or /opt/ively/agent/hls_cdn_secret
export IVELY_HLS_CDN_SECRET="${IVELY_HLS_CDN_SECRET:-7848c36cef9136c35d5b8dfcd6eb0dd9282b0dc541530044fd59654ae13a273c}"
```

**Option B — secret file** (recommended on provisioned devices):

```bash
sudo mkdir -p /opt/ively/agent
echo -n "YOUR_LONG_RANDOM_SECRET" | sudo tee /opt/ively/agent/hls_cdn_secret
sudo chmod 600 /opt/ively/agent/hls_cdn_secret
```

Use the **same string** on every edge and on the API nginx (Step 2). Do not commit real secrets to git.

### Regenerate MediaMTX config and restart

```bash
cd /opt/ively/edge
sudo PYTHONPATH=/opt/ively/edge /opt/ively/venv/bin/python3 -c \
  "from agent.camera.mediamtx_writer import generate; from agent.config import CAMS_JSON_PATH; import json; cams=json.load(open(CAMS_JSON_PATH)) if CAMS_JSON_PATH.exists() else []; generate(cams)"
sudo systemctl restart mediamtx
```

Or use **Rediscover cameras** from the provision UI (`:8080/provisioned`).

### Verify on edge

```bash
grep hlsCDNSecret /opt/ively/mediamtx/mediamtx.yml
# must show hlsCDNSecret: "YOUR_LONG_RANDOM_SECRET"
```

Defaults (override via env): `IVELY_HLS_SEGMENT_COUNT=10`, `IVELY_HLS_MUXER_CLOSE_AFTER=300s`.

---

## Step 2 — API server (se_backend / nginx)

On `api.ivelytech.com`, inside nginx `location ^~ /edge-stream/`:

```nginx
proxy_set_header Authorization "Bearer YOUR_LONG_RANDOM_SECRET";
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## Step 3 — Verify segments (from API server)

Playlists alone are not enough — test a **segment** with **GET**:

```bash
BASE="https://api.ivelytech.com/edge-stream/10.20.0.3/STREAM_PATH"
SECRET="YOUR_LONG_RANDOM_SECRET"

MASTER=$(curl -sL "$BASE/index.m3u8")
echo "$MASTER" | grep -q '^#EXTM3U' || { echo "Stream down"; exit 1; }

V=$(echo "$MASTER" | awk '!/^#/ && NF {print; exit}')
S=$(curl -sL "$BASE/$V" | awk '!/^#/ && NF && /\.(ts|m4s)/ {print; exit}')
echo "Segment=$S"

curl -s -o /dev/null -w "Direct+Bearer: %{http_code}\n" \
  -H "Authorization: Bearer $SECRET" \
  "http://10.20.0.3:8888/STREAM_PATH/$S"

curl -s -o /dev/null -w "Proxy GET:     %{http_code}\n" "$BASE/$S"
```

Both must print **200**. Then retry mobile HLS (`hls_url` from cloud API `playback-urls`).

---

## Troubleshooting

| Symptom | Check |
|---------|--------|
| Master `#EXTM3U` OK, mobile ExoPlayer 404 on segment | Missing or mismatched `hlsCDNSecret` / nginx Bearer |
| `grep hlsCDNSecret` empty on edge | Set secret + regenerate `mediamtx.yml` |
| Direct segment 401 without Bearer | Expected until `hlsCDNSecret` is set |
| `curl -sI` segment 404 but GET 200 | Use GET for tests; HEAD often fails on MediaMTX |

Direct edge HLS (VPN / LAN only): `http://10.20.0.x:8888/{path}/index.m3u8`  
Public mobile HLS: always use `https://api.ivelytech.com/edge-stream/...`
