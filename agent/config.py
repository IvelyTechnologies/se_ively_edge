# agent config — centralized edge agent configuration
# All paths, thresholds, and tuning knobs in a single place.

import json
import os
import re
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
EDGE_DIR = Path("/opt/ively/edge")
AGENT_DIR = Path("/opt/ively/agent")
MEDIAMTX_DIR = Path("/opt/ively/mediamtx")
MEDIAMTX_CONFIG = MEDIAMTX_DIR / "mediamtx.yml"
PROVISIONED_MARKER = Path("/opt/ively/.provisioned")
RECORDINGS_DIR = Path("/recordings")
LOCAL_BUFFER_DIR = RECORDINGS_DIR / "buffer"
METRICS_DB_PATH = AGENT_DIR / "metrics.db"
SITE_CONFIG_PATH = AGENT_DIR / "site.json"
VAULT_PATH = AGENT_DIR / "camera.vault"
MANUFACTURER_OVERRIDE_PATH = AGENT_DIR / "camera.manufacturer"
CAMS_JSON_PATH = AGENT_DIR / "cams.json"


def compute_path_prefix(customer: str, site: str) -> str:
    """
    Build stream path prefix from customer + site (e.g. sivakumar_main_office).
    Used in mediamtx paths: {prefix}_cam1_low
    """
    customer = (customer or "").strip()
    site = (site or "").strip()
    if not customer or not site:
        return ""
    raw = f"{customer}_{site}".strip("_")
    sanitized = re.sub(r"[^a-zA-Z0-9_]+", "_", raw).strip("_")
    return sanitized.lower() if sanitized else ""


def load_path_prefix() -> str:
    """
    Load path prefix from site.json.
    Prefers stored path_prefix (set at provision); else derives from customer+site.
    """
    try:
        with open(SITE_CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return ""
        stored = (data.get("path_prefix") or "").strip().lower()
        if stored:
            return stored
        return compute_path_prefix(
            str(data.get("customer") or ""),
            str(data.get("site") or ""),
        )
    except Exception:
        return ""


def ensure_site_path_prefix(prefix: str) -> None:
    """Persist path_prefix into site.json so rediscover/reload cannot drift to cam1_low."""
    if not prefix:
        return
    try:
        path = SITE_CONFIG_PATH
        if not path.exists():
            return
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return
        if (data.get("path_prefix") or "").strip().lower() == prefix:
            return
        data["path_prefix"] = prefix
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(path)
    except Exception:
        pass


def stream_path_name(camera_index: int, prefix: Optional[str] = None) -> str:
    """Canonical MediaMTX path for camera N (e.g. sivakumar_main_office_cam1_low)."""
    if prefix is None:
        prefix = load_path_prefix()
    if prefix:
        return f"{prefix}_cam{camera_index}_low"
    return f"cam{camera_index}_low"


# ---------------------------------------------------------------------------
# Protocol ports (match MediaMTX config)
# ---------------------------------------------------------------------------
RTSP_PORT = 8554
HLS_PORT = 8888
WEBRTC_PORT = 8889
MEDIAMTX_API_PORT = 9997
AGENT_HTTP_PORT = 8080

# ---------------------------------------------------------------------------
# Camera worker settings
# ---------------------------------------------------------------------------
WORKER_MAX_RESTARTS = int(os.environ.get("IVELY_WORKER_MAX_RESTARTS", "3"))
WORKER_COOLDOWN_SEC = int(os.environ.get("IVELY_WORKER_COOLDOWN_SEC", "300"))
WORKER_HEALTH_CHECK_SEC = 15  # how often workers check their FFmpeg process
STREAM_RECOVERY_INTERVAL_SEC = int(os.environ.get("IVELY_STREAM_RECOVERY_INTERVAL", "20"))
STREAM_NOT_READY_ESCALATE_SEC = int(os.environ.get("IVELY_STREAM_NOT_READY_ESCALATE", "90"))

# Substream-only RTSP (no main-stream fallback). Default IVELY_SUBSTREAM_ONLY=1.
# Set IVELY_SUBSTREAM_ONLY=0 to also try main stream (e.g. subtype=0 on Dahua).
# Probe RTSP URLs with ffprobe before starting workers; keep URLs that decode. Default on.
# Set IVELY_RTSP_PROBE_URLS=0 to skip probing.

# Defaults applied to agent subprocesses (discover, provision) and systemd template.
IVELY_SUBSTREAM_ONLY_DEFAULT = os.environ.get("IVELY_SUBSTREAM_ONLY", "1")
IVELY_RTSP_PROBE_URLS_DEFAULT = os.environ.get("IVELY_RTSP_PROBE_URLS", "1")

# ---------------------------------------------------------------------------
# Freeze detection
# ---------------------------------------------------------------------------
FREEZE_TIMEOUT_SEC = int(os.environ.get("IVELY_FREEZE_TIMEOUT_SEC", "20"))
MIN_FPS_RATIO = float(os.environ.get("IVELY_MIN_FPS_RATIO", "0.3"))
ZERO_BITRATE_GRACE_SEC = 30  # ignore zero-bitrate during startup

# ---------------------------------------------------------------------------
# Watchdog
# ---------------------------------------------------------------------------
WATCHDOG_INTERVAL_SEC = int(os.environ.get("IVELY_WATCHDOG_INTERVAL", "30"))
DISCOVERY_INTERVAL_SEC = int(os.environ.get("IVELY_DISCOVERY_INTERVAL", "600"))
CPU_THRESHOLD = float(os.environ.get("IVELY_CPU_THRESHOLD", "90.0"))
DISK_THRESHOLD = float(os.environ.get("IVELY_DISK_THRESHOLD", "85.0"))

# ---------------------------------------------------------------------------
# Metrics / health database
# ---------------------------------------------------------------------------
METRICS_RETENTION_DAYS = int(os.environ.get("IVELY_METRICS_RETENTION_DAYS", "7"))
METRICS_INTERVAL_SEC = int(os.environ.get("IVELY_METRICS_INTERVAL", "30"))

# ---------------------------------------------------------------------------
# Local circular buffer
# ---------------------------------------------------------------------------
LOCAL_BUFFER_HOURS = int(os.environ.get("IVELY_BUFFER_HOURS", "24"))
LOCAL_BUFFER_SEGMENT_SEC = 60  # each segment is 60 seconds
LOCAL_BUFFER_MAX_DISK_PERCENT = float(os.environ.get("IVELY_BUFFER_MAX_DISK", "80.0"))

# ---------------------------------------------------------------------------
# HLS (MediaMTX + browser player) — smooth live with ~3–5s end-user latency
# Override: IVELY_HLS_SEGMENT_DURATION=1s, IVELY_HLS_SEGMENT_COUNT=10
# Keep mpegts (stable); fMP4/lowLatency caused MOOV errors on some clients.
#
# Mobile HLS via api.ivelytech.com /edge-stream/ requires hlsCDNSecret on the
# edge matching nginx Authorization: Bearer on the API server (se_backend doc 7.3.2).
# Set IVELY_HLS_CDN_SECRET or /opt/ively/agent/hls_cdn_secret, then regenerate
# mediamtx.yml (rediscover cameras or restart agent pipeline).
# ---------------------------------------------------------------------------
HLS_SEGMENT_DURATION = os.environ.get("IVELY_HLS_SEGMENT_DURATION", "1s")
HLS_SEGMENT_COUNT = int(os.environ.get("IVELY_HLS_SEGMENT_COUNT", "10"))
HLS_VARIANT = os.environ.get("IVELY_HLS_VARIANT", "mpegts")
HLS_MUXER_CLOSE_AFTER = os.environ.get("IVELY_HLS_MUXER_CLOSE_AFTER", "300s")

_HLS_CDN_SECRET_PATH = AGENT_DIR / "hls_cdn_secret"

# Fleet default — must match api.ivelytech.com nginx Authorization Bearer (se_backend §7.3.2).
# Override per device: IVELY_HLS_CDN_SECRET env or /opt/ively/agent/hls_cdn_secret
HLS_CDN_SECRET_DEFAULT = (
    "7848c36cef9136c35d5b8dfcd6eb0dd9282b0dc541530044fd59654ae13a273c"
)


def load_hls_cdn_secret() -> str:
    """Shared secret for MediaMTX hlsCDNSecret (must match API nginx Bearer token)."""
    env = (os.environ.get("IVELY_HLS_CDN_SECRET") or "").strip()
    if env:
        return env
    try:
        if _HLS_CDN_SECRET_PATH.is_file():
            return _HLS_CDN_SECRET_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return HLS_CDN_SECRET_DEFAULT


HLS_CDN_SECRET = load_hls_cdn_secret()

# hls.js tuning for live MPEG-TS (passed to /view player)
HLS_JS_PLAYER_CONFIG = {
    "enableWorker": True,
    "liveSyncDurationCount": 2,
    "liveMaxLatencyDurationCount": 5,
    "maxBufferLength": 8,
    "maxMaxBufferLength": 12,
    "backBufferLength": 0,
    "stretchShortVideoTrack": True,
    "maxLiveSyncPlaybackRate": 1.5,
}

# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------
HEARTBEAT_INTERVAL_SEC = int(os.environ.get("IVELY_HEARTBEAT_INTERVAL", "60"))


def build_published_stream_urls(host: str, path: str) -> dict:
    """
    Canonical consumer URLs for one published path.

    FFmpeg publishes H.264 to MediaMTX once; the same path is served as RTSP,
    HLS, and WebRTC without re-encoding.
    """
    h = (host or "127.0.0.1").strip()
    if h.startswith("https://"):
        h = h[8:]
    elif h.startswith("http://"):
        h = h[7:]
    h = h.rstrip("/")
    return {
        "path": path,
        "output_codec": "h264",
        "rtsp": f"rtsp://{h}:{RTSP_PORT}/{path}",
        "hls": f"http://{h}:{HLS_PORT}/{path}/index.m3u8",
        "webrtc": f"http://{h}:{WEBRTC_PORT}/{path}",
    }
