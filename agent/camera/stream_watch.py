# stream watch — per-camera health checking using proper YAML parsing
#
# Replaces the old approach of checking only the first stream with ffprobe
# and restarting all of MediaMTX. Now checks all cameras individually and
# integrates with CameraWorkerManager for per-camera restart.

import subprocess
from typing import Dict, List, Optional

import yaml

from agent.config import MEDIAMTX_CONFIG


def load_stream_paths(config_path: str = str(MEDIAMTX_CONFIG)) -> List[str]:
    """
    Read stream path names from mediamtx.yml using proper YAML parsing.
    Returns a list like ['customer_site_cam1_low', 'customer_site_cam2_low'].
    """
    _NON_STREAM = {"paths", "rtsp", "hls", "webrtc", "api", "record", "metrics"}
    try:
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            return []
        paths_section = data.get("paths")
        if not isinstance(paths_section, dict):
            return []
        return [k for k in paths_section if k.lower() not in _NON_STREAM]
    except Exception:
        return []


def stream_ok(url: str, timeout_sec: float = 10.0) -> bool:
    """Return True if the RTSP URL yields a readable video stream (works for H.264/H.265)."""
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
            timeout=timeout_sec + 3,
        )
        return r.returncode == 0 and bool((r.stdout or "").strip())
    except Exception:
        return False


def check_all_streams(
    config_path: str = str(MEDIAMTX_CONFIG),
    rtsp_port: int = 8554,
    timeout_sec: float = 10.0,
) -> Dict[str, bool]:
    """
    Check all streams from config individually.
    Returns dict of {stream_name: is_ok}.
    """
    paths = load_stream_paths(config_path)
    results = {}
    for path in paths:
        url = f"rtsp://127.0.0.1:{rtsp_port}/{path}"
        results[path] = stream_ok(url, timeout_sec=timeout_sec)
    return results


def get_rtsp_urls_from_config(
    config_path: str = str(MEDIAMTX_CONFIG),
    rtsp_port: int = 8554,
) -> Dict[str, str]:
    """
    Extract all stream RTSP URLs from mediamtx config.
    Returns dict of {stream_name: rtsp_url}.
    """
    paths = load_stream_paths(config_path)
    return {p: f"rtsp://127.0.0.1:{rtsp_port}/{p}" for p in paths}
