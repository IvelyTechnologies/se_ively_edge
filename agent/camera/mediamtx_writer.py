# mediamtx writer

import json
import os
import re
import urllib.parse
from typing import Optional, Tuple

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
        "rtsp://{username}:{password}@{ip}:554/Streaming/Channels/101",
        "rtsp://{username}:{password}@{ip}:554/Streaming/Channels/102",
    ),
    "dahua": (
        "rtsp://{username}:{password}@{ip}:554/cam/realmonitor?channel=1&subtype=0",
        "rtsp://{username}:{password}@{ip}:554/cam/realmonitor?channel=1&subtype=1",
    ),
    "cp plus": (
        "rtsp://{username}:{password}@{ip}:554/cam/realmonitor?channel=1&subtype=0",
        "rtsp://{username}:{password}@{ip}:554/cam/realmonitor?channel=1&subtype=1",
    ),
    "godrej": (
        "rtsp://{username}:{password}@{ip}:554/Streaming/Channels/101",
        "rtsp://{username}:{password}@{ip}:554/Streaming/Channels/102",
    ),
    "prama": (
        "rtsp://{username}:{password}@{ip}:554/Streaming/Channels/101",
        "rtsp://{username}:{password}@{ip}:554/Streaming/Channels/102",
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
        "rtsp://{username}:{password}@{ip}:554/streaming/channels/102",
        "rtsp://{username}:{password}@{ip}:554/streaming/channels/101",
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
        "rtsp://{username}:{password}@{ip}:554/streaming/channels/101",
        "rtsp://{username}:{password}@{ip}:554/streaming/channels/102",
    ),
    "samsung": (
        "rtsp://{username}:{password}@{ip}:554/onvif/profile2",
        "rtsp://{username}:{password}@{ip}:554/onvif/profile1",
    ),
    "pelco": (
        "rtsp://{username}:{password}@{ip}:554/Streaming/Channels/101",
        "rtsp://{username}:{password}@{ip}:554/Streaming/Channels/102",
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
        "rtsp://{username}:{password}@{ip}:554/user={username}_password={password}_channel=1_stream=0.sdp",
        "rtsp://{username}:{password}@{ip}:554/user={username}_password={password}_channel=1_stream=1.sdp",
    ),
    "uniview": (
        "rtsp://{username}:{password}@{ip}:554/streaming/channels/101",
        "rtsp://{username}:{password}@{ip}:554/streaming/channels/102",
    ),
    "tiandy": (
        "rtsp://{username}:{password}@{ip}:554/cam/realmonitor?channel=1&subtype=0",
        "rtsp://{username}:{password}@{ip}:554/cam/realmonitor?channel=1&subtype=1",
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


def _rtsp_urls(
    ip: str,
    model: str,
    username: str,
    password: str,
    manufacturer_override: Optional[str] = None,
    channel: str = "1",
) -> tuple[str, str]:
    """Return (hd_url, low_url) with credentials embedded."""
    if manufacturer_override and manufacturer_override in RTSP_FORMATS:
        manufacturer = manufacturer_override
    else:
        manufacturer = _manufacturer_from_model(model)
    formats = RTSP_FORMATS.get(manufacturer, RTSP_FORMATS["onvif"])
    main_fmt, sub_fmt = formats
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
        hd_url = main_fmt.format(**params)
        low_url = sub_fmt.format(**params)
    except KeyError:
        hd_url = main_fmt.replace("{username}", safe_user).replace(
            "{password}", safe_pass
        ).replace("{ip}", ip)
        low_url = sub_fmt.replace("{username}", safe_user).replace(
            "{password}", safe_pass
        ).replace("{ip}", ip)
    return (hd_url, low_url)


def _load_credentials(vault_path: str = "/opt/ively/agent/camera.vault"):
    """Load and decrypt camera credentials from vault. Returns (user, password) or (None, None)."""
    try:
        from agent.security.vault import decrypt
        with open(vault_path, encoding="utf-8") as f:
            vault = json.load(f)
        return (decrypt(vault["user"]), decrypt(vault["password"]))
    except Exception:
        return (None, None)


def generate(
    cams,
    config_path: str = "/opt/ively/mediamtx/mediamtx.yml",
    username: Optional[str] = None,
    password: Optional[str] = None,
    vault_path: str = "/opt/ively/agent/camera.vault",
    manufacturer_override: Optional[str] = None,
):
    """Generate mediamtx.yml from discovered cameras. One _low and one _hd path per camera."""
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

    cfg = """webrtc: yes
webrtcAddress: :8889

# STUN server (FREE)
webrtcICEServers2:
  - url: stun:stun.l.google.com:19302

paths:
"""
    camera_index = 1
    for c in cams:
        ip = c["ip"]
        model = c.get("model", "")
        channels_count = c.get("channels", 1)
        
        for ch in range(1, channels_count + 1):
            hd_url, low_url = _rtsp_urls(
                ip, model, username, password, manufacturer_override, channel=str(ch)
            )
            cfg += f"""
  {path_label}cam{camera_index}_low:
    source: {low_url}

  {path_label}cam{camera_index}_hd:
    source: {hd_url}
"""
            camera_index += 1
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(cfg)
