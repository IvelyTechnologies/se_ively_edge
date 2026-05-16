# agent config — centralized edge agent configuration
# All paths, thresholds, and tuning knobs in a single place.

import os
from pathlib import Path

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

# ---------------------------------------------------------------------------
# Protocol ports (match MediaMTX config)
# ---------------------------------------------------------------------------
RTSP_PORT = 8554
HLS_PORT = 8888
WEBRTC_PORT = 8889
AGENT_HTTP_PORT = 8080

# ---------------------------------------------------------------------------
# Camera worker settings
# ---------------------------------------------------------------------------
WORKER_MAX_RESTARTS = int(os.environ.get("IVELY_WORKER_MAX_RESTARTS", "3"))
WORKER_COOLDOWN_SEC = int(os.environ.get("IVELY_WORKER_COOLDOWN_SEC", "300"))
WORKER_HEALTH_CHECK_SEC = 15  # how often workers check their FFmpeg process

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
# WebRTC (Google STUN)
# ---------------------------------------------------------------------------
WEBRTC_ICE_SERVERS = os.environ.get(
    "IVELY_WEBRTC_ICE_SERVERS",
    "stun:stun.l.google.com:19302",
)

# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------
HEARTBEAT_INTERVAL_SEC = int(os.environ.get("IVELY_HEARTBEAT_INTERVAL", "60"))
