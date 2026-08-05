# mediamtx writer

import json
import os
import re
import subprocess
import tempfile
import urllib.parse
from typing import Dict, Optional

from agent.config import (
    SITE_CONFIG_PATH,
    ensure_site_path_prefix,
    load_path_prefix,
    stream_path_name,
)

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
        "rtsp://{username}:{password}@{ip}:554/cam/realmonitor?channel={channel}&subtype=0",
        "rtsp://{username}:{password}@{ip}:554/cam/realmonitor?channel={channel}&subtype=1",
    ),
    "cp plus": (
        "rtsp://{username}:{password}@{ip}:554/cam/realmonitor?channel={channel}&subtype=0",
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
    """Stream path prefix from provisioned site.json (see agent.config.load_path_prefix)."""
    prefix = load_path_prefix()
    if not prefix:
        try:
            from agent.config import PROVISIONED_MARKER

            if PROVISIONED_MARKER.exists() or SITE_CONFIG_PATH.exists():
                print(
                    "[mediamtx_writer] WARNING: provisioned device but path prefix empty — "
                    "set customer+site in site.json (paths will be cam1_low until fixed)"
                )
        except Exception:
            pass
    return prefix


def _load_manufacturer_override(path: str = MANUFACTURER_OVERRIDE_PATH) -> Optional[str]:
    """Read manufacturer override from file (set during provisioning). Returns None if not set or 'auto'."""
    try:
        with open(path, encoding="utf-8") as f:
            value = f.read().strip() or None
            return None if value == "auto" else value
    except Exception:
        return None


def _rtsp_host_for_cam(cam: dict) -> str:
    """
    Host for RTSP URL. When the camera is behind an NVR, set rtsp_host or nvr_ip
    to the NVR address (e.g. 192.168.0.195); keep ip as the camera IP for discovery.
    """
    for key in ("rtsp_host", "nvr_ip", "nvr"):
        val = (cam.get(key) or "").strip()
        if val:
            return val
    return (cam.get("ip") or "").strip()


def _rtsp_format_url(fmt: str, params: dict) -> str:
    """Format an RTSP URL template with credential params."""
    try:
        return fmt.format(**params)
    except KeyError:
        return (
            fmt.replace("{username}", params["username"])
            .replace("{password}", params["password"])
            .replace("{ip}", params["ip"])
            .replace("{channel}", params["channel"])
        )


def _selected_rtsp_stream_profile(manufacturer: str) -> str:
    """
    Select exactly one RTSP input profile.

    IVELY_RTSP_STREAM_PROFILE=sub  -> substream only
    IVELY_RTSP_STREAM_PROFILE=main -> main stream only

    Legacy IVELY_SUBSTREAM_ONLY is kept only for older deployments.
    """
    _ = manufacturer  # reserved for future per-brand overrides
    profile = (os.environ.get("IVELY_RTSP_STREAM_PROFILE") or "").strip().lower()
    if profile in ("main", "primary", "hd", "high", "0"):
        return "main"
    if profile in ("sub", "secondary", "low", "1"):
        return "sub"

    legacy = (os.environ.get("IVELY_SUBSTREAM_ONLY") or "1").strip().lower()
    return "sub" if legacy not in ("0", "false", "no") else "main"


def _use_rtsp_probe() -> bool:
    """ffprobe each candidate URL; use only streams that return video (default on)."""
    v = (os.environ.get("IVELY_RTSP_PROBE_URLS") or "1").strip().lower()
    return v not in ("0", "false", "no")


def _rtsp_url_probe_ok(url: str, timeout_sec: float = 10.0) -> bool:
    """True if ffprobe can read at least one video frame from this RTSP URL."""
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-rtsp_transport",
                "tcp",
                "-timeout",
                str(int(timeout_sec * 1_000_000)),
                "-i",
                url,
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "default=nw=1:nk=1",
            ],
            capture_output=True,
            text=True,
            timeout=timeout_sec + 5,
        )
        return r.returncode == 0 and bool((r.stdout or "").strip())
    except Exception:
        return False


def _filter_rtsp_urls_by_probe(urls: list[str]) -> list[str]:
    """Keep only probe-OK URLs; if none OK, return original list for worker retry."""
    if not urls:
        return urls
    working = [u for u in urls if _rtsp_url_probe_ok(u)]
    if working:
        return working
    print(
        "[mediamtx_writer] RTSP probe: no URL passed ffprobe; "
        "keeping all candidates for worker rotation"
    )
    return urls


def _rtsp_low_url_candidates(
    ip: str,
    model: str,
    username: str,
    password: str,
    manufacturer_override: Optional[str] = None,
    channel: str = "1",
    probe: Optional[bool] = None,
) -> list[str]:
    """
    Return the selected RTSP URL for the configured input stream.
    No automatic sub/main fallback is used; the configured profile is authoritative.
    Optionally ffprobe-filter to working URLs (H.265/H.264, no NVR reconfiguration).
    """
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
    selected_profile = _selected_rtsp_stream_profile(manufacturer)
    fmts = (main_fmt,) if selected_profile == "main" else (sub_fmt,)
    urls: list[str] = []
    for fmt in fmts:
        url = _rtsp_format_url(fmt, params)
        if url not in urls:
            urls.append(url)
    if probe if probe is not None else _use_rtsp_probe():
        urls = _filter_rtsp_urls_by_probe(urls)
    return urls


def _rtsp_low_url(
    ip: str,
    model: str,
    username: str,
    password: str,
    manufacturer_override: Optional[str] = None,
    channel: str = "1",
) -> str:
    """Return primary low/sub-stream RTSP URL (first candidate)."""
    urls = _rtsp_low_url_candidates(
        ip, model, username, password, manufacturer_override, channel
    )
    return urls[0] if urls else ""


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


def _ffmpeg_input_shell_quoted(rtsp_input_url: str) -> str:
    """Shell-safe double-quoted -i argument (matches proven MediaMTX runOnDemand lines)."""
    esc = (rtsp_input_url or "").replace("\\", "\\\\").replace('"', '\\"')
    return f'"{esc}"'


def _use_low_latency_rtsp_input_flags() -> bool:
    """
    Opt-in for aggressive RTSP low-latency input flags.
    Disabled by default since some HEVC cameras become unstable with dropped refs.
    """
    v = (os.environ.get("IVELY_FFMPEG_LOW_LATENCY_INPUT") or "").strip().lower()
    return v in ("1", "true", "yes")


def _use_discard_corrupt_packets() -> bool:
    """
    Drop corrupt input packets for smoother output on unstable camera links.
    Enabled by default; set IVELY_FFMPEG_DISCARD_CORRUPT=0 to disable.
    """
    v = (os.environ.get("IVELY_FFMPEG_DISCARD_CORRUPT") or "").strip().lower()
    return v not in ("0", "false", "no")


def _use_ultra_low_profile() -> bool:
    """Enable extra-conservative encoder profile for very weak links."""
    v = (os.environ.get("IVELY_STREAM_ULTRA_LOW") or "").strip().lower()
    return v in ("1", "true", "yes")


def _ffmpeg_input_flags() -> list[str]:
    """
    Build robust FFmpeg input flags for unstable RTSP/HEVC camera links.
    Tolerates H.265 + Smart codec from NVR without requiring NVR menu changes.
    """
    fflags = ["+genpts"]
    if _use_discard_corrupt_packets():
        fflags.append("+discardcorrupt")
    if _use_low_latency_rtsp_input_flags():
        # Optional: lower latency, but can reduce decoder robustness on some HEVC cameras.
        fflags.append("nobuffer")

    flags = [
        "-rtsp_flags",
        "prefer_tcp",
        "-fflags",
        "".join(fflags),
        # HEVC / Smart H.265+: ignore corrupt packets, conceal reference errors.
        "-err_detect",
        "ignore_err",
        "-ec",
        "guess_mvs+deblock",
        # Bad timestamps from NVR smart codec.
        "-use_wallclock_as_timestamps",
        "1",
        "-analyzeduration",
        "5000000",
        "-probesize",
        "5000000",
        # Keep larger reordering tolerance for jittery links.
        "-reorder_queue_size",
        "1024",
        # Limit demuxer waiting to avoid long stalls.
        "-max_delay",
        "500000",
    ]
    if _use_low_latency_rtsp_input_flags():
        flags.extend(["-flags", "low_delay"])
    return flags


DEFAULT_STREAM_PROFILES: Dict[str, Dict[str, str]] = {
    # Published stream (H.264 out): transcode any camera codec (H.265/H.264) to this profile.
    "low": {
        "width": "640",
        "height": "360",
        "fps": "10",
        "bitrate": "512k",
        "maxrate": "580k",
        "bufsize": "1024k",
        "gop": "10",
        "keyint_min": "10",
    },
}


def _hls_segment_seconds() -> float:
    """Parse HLS segment duration for GOP alignment (matches _mediamtx_hls_yaml)."""
    from agent.config import HLS_SEGMENT_DURATION

    raw = (HLS_SEGMENT_DURATION or "1s").strip().lower().rstrip("s")
    try:
        return max(0.5, float(raw))
    except ValueError:
        return 1.0


def _sync_gop_to_hls(profile: Dict[str, str]) -> None:
    """Keyframe interval = HLS segment length → clean cuts, less stall/rebuffer."""
    fps = float(profile.get("fps") or "10")
    gop = max(1, int(round(fps * _hls_segment_seconds())))
    profile["gop"] = str(gop)
    profile["keyint_min"] = str(gop)


def _mediamtx_hls_yaml() -> str:
    """HLS server block — tuned for smooth browser playback."""
    from agent.config import (
        HLS_CDN_SECRET,
        HLS_MUXER_CLOSE_AFTER,
        HLS_SEGMENT_COUNT,
        HLS_SEGMENT_DURATION,
        HLS_VARIANT,
    )

    cdn_secret_line = ""
    if HLS_CDN_SECRET:
        cdn_secret_line = f'hlsCDNSecret: "{HLS_CDN_SECRET}"\n'

    return f"""# HLS server — smooth live (GOP aligned to segment duration in FFmpeg)
# When proxied via api.ivelytech.com /edge-stream/, hlsCDNSecret must match nginx
# Authorization: Bearer (see se_backend documents/UBUNTU_2404_DEPLOYMENT_GUIDE.md §7.3.2).
hls: yes
hlsAddress: :8888
hlsVariant: {HLS_VARIANT}
hlsAlwaysRemux: yes
hlsSegmentDuration: {HLS_SEGMENT_DURATION}
hlsSegmentCount: {HLS_SEGMENT_COUNT}
hlsMuxerCloseAfter: {HLS_MUXER_CLOSE_AFTER}
{cdn_secret_line}hlsAllowOrigins: ['*']
"""


def _load_stream_profiles() -> Dict[str, Dict[str, str]]:
    """
    Load encoder profile overrides from IVELY_STREAM_PROFILES_JSON.
    Must be a JSON object like: {"low": {"fps": "8", "bitrate": "350k"}}
    """
    merged = {name: values.copy() for name, values in DEFAULT_STREAM_PROFILES.items()}
    if _use_ultra_low_profile():
        merged["low"].update(
            {
                "width": "426",
                "height": "240",
                "fps": "6",
                "bitrate": "220k",
                "maxrate": "260k",
                "bufsize": "520k",
                "gop": "12",
                "keyint_min": "6",
            }
        )

    raw = (os.environ.get("IVELY_STREAM_PROFILES_JSON") or "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                override = parsed.get("low")
                if isinstance(override, dict):
                    for key in merged["low"].keys():
                        val = override.get(key)
                        if val is not None:
                            merged["low"][key] = str(val)
        except Exception:
            pass

    _sync_gop_to_hls(merged["low"])
    return merged


def _ffmpeg_transcode_publish_command(
    rtsp_input_url: str,
    profile: Dict[str, str],
    publish_path: Optional[str] = None,
    rtsp_port: int = 8554,
) -> str:
    """
    FFmpeg pulls camera RTSP (H.265/H.264/MJPEG, etc.) and publishes H.264 to this MediaMTX path
    via RTSP (publisher). Output is browser-safe: yuv420p, short GOP, no B-frames (WebRTC/HLS friendly).

    When publish_path is provided, the command uses a resolved localhost URL
    (for persistent CameraWorker mode). When None, uses the legacy
    $RTSP_PORT/$MTX_PATH variables (for runOnDemand compatibility, unused).
    """
    quoted_in = _ffmpeg_input_shell_quoted(rtsp_input_url)
    if publish_path:
        publish_to = f"rtsp://127.0.0.1:{rtsp_port}/{publish_path}"
    else:
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
            "-b:v",
            profile["bitrate"],
            "-maxrate",
            profile["maxrate"],
            "-bufsize",
            profile["bufsize"],
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
            "-b:v",
            profile["bitrate"],
            "-maxrate",
            profile["maxrate"],
            "-bufsize",
            profile["bufsize"],
            "-x264-params",
            "repeat-headers=1:aud=1:nal-hrd=cbr",
        ]

    input_flags = _ffmpeg_input_flags()

    # Use -progress pipe:2 to send machine-readable progress to stderr
    # for the freeze detector to parse (frame count, FPS, bitrate).
    parts = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "repeat+warning",
        "-progress",
        "pipe:2",
        "-rtsp_transport",
        "tcp",
        *input_flags,
        "-i",
        quoted_in,
        "-map",
        "0:v:0",
        "-an",
        *venc,
        "-vf",
        f"scale={profile['width']}:{profile['height']}:force_original_aspect_ratio=decrease",
        "-r",
        profile["fps"],
        "-vsync",
        "cfr",
        "-g",
        profile["gop"],
        "-keyint_min",
        profile["keyint_min"],
        "-sc_threshold",
        "0",
        "-pix_fmt",
        "yuv420p",
        "-pkt_size",
        "1200",
        "-f",
        "rtsp",
        "-rtsp_transport",
        "tcp",
        publish_to,
    ]
    return " ".join(parts)


def _cam_sort_key(cam: dict) -> tuple[str, str, str]:
    """Stable camera ordering avoids path renumbering churn across rediscovery runs."""
    return (
        str(cam.get("ip", "")),
        str(cam.get("model", "")),
        str(cam.get("channels", 1)),
    )


def _channel_sort_key(ch: object) -> tuple[int, str]:
    """
    Sort channels numerically when possible; fallback to string order.
    Keeps generated path names stable.
    """
    try:
        return (0, f"{int(ch):09d}")
    except Exception:
        return (1, str(ch))


def _write_if_changed_atomic(config_path: str, content: str) -> bool:
    """
    Write config only when content changed.
    Returns True if file was updated, False if unchanged.
    """
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            if f.read() == content:
                return False
    except FileNotFoundError:
        pass

    parent = os.path.dirname(config_path) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".mediamtx.", suffix=".yml", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tf:
            tf.write(content)
        os.replace(tmp_path, config_path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
    return True


def generate(
    cams,
    config_path: str = "/opt/ively/mediamtx/mediamtx.yml",
    username: Optional[str] = None,
    password: Optional[str] = None,
    vault_path: str = "/opt/ively/agent/camera.vault",
    manufacturer_override: Optional[str] = None,
) -> bool:
    """
    Generate mediamtx.yml: one publisher path per camera (e.g. `{prefix}_cam1_low`).

    Paths use `source: publisher` — FFmpeg is managed by CameraWorkerManager,
    NOT by MediaMTX runOnDemand. This prevents stream teardown when no consumer
    is watching, eliminates reconnect storms, and allows per-camera restart.

    Returns True if config file content changed, else False.
    """
    if username is None or password is None:
        username, password = _load_credentials(vault_path)
    if not username:
        username = ""
    if not password:
        password = ""
    if manufacturer_override is None:
        manufacturer_override = _load_manufacturer_override()

    prefix = _path_prefix()
    ensure_site_path_prefix(prefix)
    hls_block = _mediamtx_hls_yaml()

    cfg = f"""# --- Ively SmartEye Edge — MediaMTX Configuration ---
# Auto-generated — do not edit manually.
# FFmpeg workers are managed by ively-agent (CameraWorkerManager),
# NOT by MediaMTX runOnDemand.

# RTSP server
rtsp: yes
rtspAddress: :8554

{hls_block}
# WebRTC — enabled for low-latency browser viewing
webrtc: yes
webrtcAddress: :8889
webrtcLocalUDPAddress: :8189
webrtcLocalTCPAddress: :8189
webrtcIPsFromInterfaces: yes
webrtcICEServers2:
  - url: stun:stun.l.google.com:19302

# Control API — paths/list, stream status (curl http://127.0.0.1:9997/v3/paths/list)
api: yes
apiAddress: :9997

# Camera paths — FFmpeg publishes H.264 (browser-safe for HLS/WebRTC).
# Source may be H.265/HEVC from camera; FFmpeg transcodes.

paths:
"""
    camera_index = 1
    stream_profiles = _load_stream_profiles()
    for c in sorted(cams, key=_cam_sort_key):
        ip = c["ip"]
        model = c.get("model", "")

        # Support both formats:
        #   - "selected_channels": [1, 2]  (from provision UI / manual override)
        #   - "channels": 4                (from auto-discovery count)
        selected_channels = c.get("selected_channels")
        if selected_channels:
            channel_list = sorted(selected_channels, key=_channel_sort_key)
        else:
            channels_count = c.get("channels", 1)
            channel_list = list(range(1, channels_count + 1))

        for ch in channel_list:
            path_name = stream_path_name(camera_index, prefix)
            cfg += f"""
  {path_name}:
    source: publisher
"""
            camera_index += 1
    changed = _write_if_changed_atomic(config_path, cfg)
    if changed:
        print("MediaMTX config updated:", config_path)
    else:
        print("MediaMTX config unchanged:", config_path)
    return changed


def generate_worker_configs(
    cams,
    username: Optional[str] = None,
    password: Optional[str] = None,
    vault_path: str = "/opt/ively/agent/camera.vault",
    manufacturer_override: Optional[str] = None,
    rtsp_port: int = 8554,
) -> list:
    """
    Generate per-camera FFmpeg commands for CameraWorkerManager.

    Returns a list of dicts:
      [{"stream_name": "...", "ffmpeg_cmd": "...", "expected_fps": 8.0}, ...]
    """
    if username is None or password is None:
        username, password = _load_credentials(vault_path)
    if not username:
        username = ""
    if not password:
        password = ""
    if manufacturer_override is None:
        manufacturer_override = _load_manufacturer_override()

    prefix = _path_prefix()

    configs = []
    camera_index = 1
    stream_profiles = _load_stream_profiles()

    for c in sorted(cams, key=_cam_sort_key):
        model = c.get("model", "")
        rtsp_host = _rtsp_host_for_cam(c)

        selected_channels = c.get("selected_channels")
        if selected_channels:
            channel_list = sorted(selected_channels, key=_channel_sort_key)
        else:
            channels_count = c.get("channels", 1)
            channel_list = list(range(1, channels_count + 1))

        for ch in channel_list:
            stream_name = stream_path_name(camera_index, prefix)
            # Optional per-camera override from provision UI / cams.json
            override_url = (c.get("rtsp_url") or "").strip()
            if override_url:
                rtsp_urls = [override_url]
            else:
                rtsp_urls = _rtsp_low_url_candidates(
                    rtsp_host,
                    model,
                    username,
                    password,
                    manufacturer_override,
                    channel=str(ch),
                )
            ffmpeg_cmds = [
                _ffmpeg_transcode_publish_command(
                    url,
                    stream_profiles["low"],
                    publish_path=stream_name,
                    rtsp_port=rtsp_port,
                )
                for url in rtsp_urls
            ]
            configs.append({
                "stream_name": stream_name,
                "ffmpeg_cmd": ffmpeg_cmds[0],
                "ffmpeg_cmds": ffmpeg_cmds,
                "rtsp_urls": rtsp_urls,
                "expected_fps": float(stream_profiles["low"]["fps"]),
            })
            camera_index += 1

    return configs
