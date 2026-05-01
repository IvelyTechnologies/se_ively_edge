# mediamtx writer

import json
import os
import re
import shlex
import subprocess
import urllib.parse
from typing import Optional

SITE_CONFIG_PATH = "/opt/ively/agent/site.json"

# Model substring -> manufacturer key (first match wins; check more specific first)
MODEL_TO_MANUFACTURER = [
    ("hikvision", "hikvision"),
    ("ds-2cd", "hikvision"),
    ("ds-2de", "hikvision"),
    ("ezviz", "ezviz"),
    ("hanwha", "hanwha"),
    ("samsung techwin", "hanwha"),
    ("dahua", "dahua"),
    ("dh-", "dahua"),
    ("cp plus", "cp plus"),
    ("godrej", "godrej"),
    ("prama", "prama"),
    ("tp-link", "tp-link"),
    ("tp link", "tp-link"),
    ("imou", "imou"),
    ("reolink", "reolink"),
    ("axis", "axis"),
    ("bosch", "bosch"),
    ("panasonic", "panasonic"),
    ("sony", "sony"),
    ("samsung", "samsung"),
    ("pelco", "pelco"),
    ("avigilon", "avigilon"),
    ("mobotix", "mobotix"),
    ("zicom", "zicom"),
    ("secureye", "secureye"),
    ("uniview", "uniview"),
    ("tiandy", "tiandy"),
]

# (main_stream_format, sub_stream_format). Use {username}, {password}, {ip}, {channel}, {profile}
RTSP_FORMATS = {
    "hikvision": (
        "rtsp://{username}:{password}@{ip}:554/Streaming/Channels/{channel}01",
        "rtsp://{username}:{password}@{ip}:554/Streaming/Channels/{channel}02",
    ),
    "dahua": (
        "rtsp://{username}:{password}@{ip}:554/cam/realmonitor?channel={channel}&subtype=1",
        "rtsp://{username}:{password}@{ip}:554/cam/realmonitor?channel={channel}&subtype=1",
    ),
    "cp plus": (
        "rtsp://{username}:{password}@{ip}:554/cam/realmonitor?channel={channel}&subtype=1",
        "rtsp://{username}:{password}@{ip}:554/cam/realmonitor?channel={channel}&subtype=1",
    ),
    "godrej": (
        "rtsp://{username}:{password}@{ip}:554/Streaming/Channels/{channel}01",
        "rtsp://{username}:{password}@{ip}:554/Streaming/Channels/{channel}02",
    ),
    "prama": (
        "rtsp://{username}:{password}@{ip}:554/Streaming/Channels/{channel}01",
        "rtsp://{username}:{password}@{ip}:554/Streaming/Channels/{channel}02",
    ),
    "axis": (
        "rtsp://{username}:{password}@{ip}:554/axis-media/media.amp",
        "rtsp://{username}:{password}@{ip}:554/axis-media/media.amp",
    ),
    "bosch": (
        "rtsp://{username}:{password}@{ip}:554/rtsp_tunnel",
        "rtsp://{username}:{password}@{ip}:554/rtsp_tunnel",
    ),
    "hanwha": (
        "rtsp://{username}:{password}@{ip}:554/streaming/channels/{channel}02",
        "rtsp://{username}:{password}@{ip}:554/streaming/channels/{channel}01",
    ),
    "zicom": (
        "rtsp://{username}:{password}@{ip}:554/onvif/profile2",
        "rtsp://{username}:{password}@{ip}:554/onvif/profile1",
    ),
    "tp-link": (
        "rtsp://{username}:{password}@{ip}:554/stream1",
        "rtsp://{username}:{password}@{ip}:554/stream1",
    ),
    "ezviz": (
        "rtsp://{username}:{password}@{ip}:554/live",
        "rtsp://{username}:{password}@{ip}:554/live",
    ),
    "imou": (
        "rtsp://{username}:{password}@{ip}:554/live",
        "rtsp://{username}:{password}@{ip}:554/live",
    ),
    "reolink": (
        "rtsp://{username}:{password}@{ip}:554/h264Preview_01_main",
        "rtsp://{username}:{password}@{ip}:554/h264Preview_02_sub",
    ),
    "panasonic": (
        "rtsp://{username}:{password}@{ip}:554/media/1",
        "rtsp://{username}:{password}@{ip}:554/media/2",
    ),
    "sony": (
        "rtsp://{username}:{password}@{ip}:554/streaming/channels/{channel}01",
        "rtsp://{username}:{password}@{ip}:554/streaming/channels/{channel}02",
    ),
    "samsung": (
        "rtsp://{username}:{password}@{ip}:554/onvif/profile2",
        "rtsp://{username}:{password}@{ip}:554/onvif/profile1",
    ),
    "pelco": (
        "rtsp://{username}:{password}@{ip}:554/Streaming/Channels/{channel}01",
        "rtsp://{username}:{password}@{ip}:554/Streaming/Channels/{channel}02",
    ),
    "avigilon": (
        "rtsp://{username}:{password}@{ip}:554/stream1",
        "rtsp://{username}:{password}@{ip}:554/stream1",
    ),
    "mobotix": (
        "rtsp://{username}:{password}@{ip}:554/full",
        "rtsp://{username}:{password}@{ip}:554/full",
    ),
    "secureye": (
        "rtsp://{username}:{password}@{ip}:554/user={username}_password={password}_channel={channel}_stream=0.sdp",
        "rtsp://{username}:{password}@{ip}:554/user={username}_password={password}_channel={channel}_stream=1.sdp",
    ),
    "uniview": (
        "rtsp://{username}:{password}@{ip}:554/streaming/channels/{channel}01",
        "rtsp://{username}:{password}@{ip}:554/streaming/channels/{channel}02",
    ),
    "tiandy": (
        "rtsp://{username}:{password}@{ip}:554/cam/realmonitor?channel={channel}&subtype=0",
        "rtsp://{username}:{password}@{ip}:554/cam/realmonitor?channel={channel}&subtype=1",
    ),
    "onvif": (
        "rtsp://{username}:{password}@{ip}:554/onvif1",
        "rtsp://{username}:{password}@{ip}:554/onvif1",
    ),
}



MANUFACTURER_OVERRIDE_PATH = "/opt/ively/agent/camera.manufacturer"


def _manufacturer_from_model(model: str) -> str:
    """Match camera model string to manufacturer key."""
    model_lower = (model or "").lower()
    for keyword, manufacturer in MODEL_TO_MANUFACTURER:
        if keyword in model_lower:
            return manufacturer
    return "onvif"


def _path_prefix() -> str:
    """Customer and site from provisioning; sanitized for use in path names (e.g. acme_warehouse_a)."""
    try:
        with open(SITE_CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        customer = (data.get("customer") or "customer").strip()
        site = (data.get("site") or "site").strip()
        # Alphanumeric + underscore only, collapse spaces to single underscore
        raw = f"{customer}_{site}".strip("_")
        sanitized = re.sub(r"[^a-zA-Z0-9_]+", "_", raw).strip("_") or "default"
        return sanitized.lower()
    except Exception:
        return ""


def _load_manufacturer_override(path: str = MANUFACTURER_OVERRIDE_PATH) -> Optional[str]:
    """Read manufacturer override from file (set during provisioning). Returns None if not set or 'auto'."""
    try:
        with open(path, encoding="utf-8") as f:
            value = f.read().strip() or None
            return None if value == "auto" else value
    except Exception:
        return None


def _rtsp_low_url(
    ip: str,
    model: str,
    username: str,
    password: str,
    manufacturer_override: Optional[str] = None,
    channel: str = "1",
) -> str:
    """Return low/sub-stream RTSP URL with credentials embedded."""
    if manufacturer_override and manufacturer_override in RTSP_FORMATS:
        manufacturer = manufacturer_override
    else:
        manufacturer = _manufacturer_from_model(model)
    formats = RTSP_FORMATS.get(manufacturer, RTSP_FORMATS["onvif"])
    _, sub_fmt = formats
    safe_user = urllib.parse.quote(username or "", safe="")
    safe_pass = urllib.parse.quote(password or "", safe="")
    params = {
        "username": safe_user,
        "password": safe_pass,
        "ip": ip,
        "channel": channel,
        "profile": "2",
    }
    try:
        low_url = sub_fmt.format(**params)
    except KeyError:
        low_url = sub_fmt.replace("{username}", safe_user).replace(
            "{password}", safe_pass
        ).replace("{ip}", ip)
    return low_url


def _load_credentials(vault_path: str = "/opt/ively/agent/camera.vault"):
    """Load and decrypt camera credentials from vault. Returns (user, password) or (None, None)."""
    try:
        from agent.security.vault import decrypt
        with open(vault_path, encoding="utf-8") as f:
            vault = json.load(f)
        return (decrypt(vault["user"]), decrypt(vault["password"]))
    except Exception:
        return (None, None)


_NVENC_AVAILABLE: Optional[bool] = None


def _ffmpeg_has_h264_nvenc() -> bool:
    """True if this system's ffmpeg build lists NVIDIA H.264 encoding."""
    global _NVENC_AVAILABLE
    if _NVENC_AVAILABLE is not None:
        return _NVENC_AVAILABLE
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        out = (r.stdout or "") + (r.stderr or "")
        _NVENC_AVAILABLE = "h264_nvenc" in out
    except Exception:
        _NVENC_AVAILABLE = False
    return _NVENC_AVAILABLE


def _use_nvenc_encoder() -> bool:
    """NVENC is opt-in (IVELY_USE_NVENC=1): avoids failures when ffmpeg has nvenc but no GPU."""
    v = (os.environ.get("IVELY_USE_NVENC") or "").strip().lower()
    return v in ("1", "true", "yes") and _ffmpeg_has_h264_nvenc()


def _ffmpeg_transcode_publish_command(rtsp_input_url: str) -> str:
    """
    FFmpeg pulls camera RTSP (H.265/H.264/MJPEG, etc.) and publishes H.264 to this MediaMTX path
    via RTSP (publisher). Output is browser-safe: yuv420p, short GOP, no B-frames (WebRTC/HLS friendly).
    """
    quoted_in = shlex.quote(rtsp_input_url)
    publish_to = "rtsp://127.0.0.1:$RTSP_PORT/$MTX_PATH"

    if _use_nvenc_encoder():
        venc = [
            "-c:v",
            "h264_nvenc",
            "-preset",
            "p4",
            "-profile:v",
            "main",
            "-bf",
            "0",
        ]
    else:
        venc = [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-tune",
            "zerolatency",
            "-profile:v",
            "main",
            "-level",
            "4.1",
            "-bf",
            "0",
        ]

    parts = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-rtsp_transport",
        "tcp",
        "-fflags",
        "nobuffer",
        "-flags",
        "low_delay",
        "-i",
        quoted_in,
        "-map",
        "0:v:0",
        "-an",
        *venc,
        "-g",
        "50",
        "-keyint_min",
        "25",
        "-sc_threshold",
        "0",
        "-pix_fmt",
        "yuv420p",
        "-f",
        "rtsp",
        "-rtsp_transport",
        "tcp",
        publish_to,
    ]
    return " ".join(parts)


def generate(
    cams,
    config_path: str = "/opt/ively/mediamtx/mediamtx.yml",
    username: Optional[str] = None,
    password: Optional[str] = None,
    vault_path: str = "/opt/ively/agent/camera.vault",
    manufacturer_override: Optional[str] = None,
):
    """Generate mediamtx.yml from discovered cameras. Only _low paths are generated."""
    if username is None or password is None:
        username, password = _load_credentials(vault_path)
    if not username:
        username = ""
    if not password:
        password = ""
    if manufacturer_override is None:
        manufacturer_override = _load_manufacturer_override()

    prefix = _path_prefix()
    path_label = f"{prefix}_" if prefix else ""

    cfg = """# --- Protocol Configuration ---
# RTSP server
rtsp: yes
rtspAddress: :8554

# HLS server
hls: yes
hlsAddress: :8888

# WebRTC disabled
webrtc: no

# Camera paths use FFmpeg to publish H.264 (browser-safe for HLS). Source may be H.265/HEVC.

paths:
"""
    camera_index = 1
    for c in cams:
        ip = c["ip"]
        model = c.get("model", "")

        # Support both formats:
        #   - "selected_channels": [1, 2]  (from provision UI / manual override)
        #   - "channels": 4                (from auto-discovery count)
        selected_channels = c.get("selected_channels")
        if selected_channels:
            channel_list = selected_channels
        else:
            channels_count = c.get("channels", 1)
            channel_list = list(range(1, channels_count + 1))

        for ch in channel_list:
            low_url = _rtsp_low_url(
                ip, model, username, password, manufacturer_override, channel=str(ch)
            )
            low_cmd = _ffmpeg_transcode_publish_command(low_url)
            cfg += f"""
  {path_label}cam{camera_index}_low:
    source: publisher
    runOnDemand: {low_cmd}
    runOnDemandRestart: yes
    runOnDemandStartTimeout: 35s
    runOnDemandCloseAfter: 15s
"""
            camera_index += 1
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(cfg)
