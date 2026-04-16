# stream watch — detect RTSP freeze and trigger MediaMTX restart

import re
import subprocess
from typing import Optional


def _first_rtsp_from_config(config_path: str = "/opt/ively/mediamtx/mediamtx.yml") -> Optional[str]:
    """Read first camera RTSP URL from mediamtx.yml (direct source or FFmpeg -i input)."""
    try:
        with open(config_path, encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return None
    m = re.search(r"source:\s*(rtsp://[^\s]+)", content)
    if m:
        return m.group(1).strip()
    m = re.search(r"-i\s+'(rtsp://[^']+)'", content)
    if m:
        return m.group(1).strip()
    m = re.search(r'-i\s+"(rtsp://[^"]+)"', content)
    return m.group(1).strip() if m else None


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


def check_cameras(config_path: str = "/opt/ively/mediamtx/mediamtx.yml") -> bool:
    """
    Check first stream from config. If stuck, restart MediaMTX and return False.
    Returns True if stream ok or no stream to check.
    """
    url = _first_rtsp_from_config(config_path)
    if not url:
        return True

    if stream_ok(url):
        return True

    print("Stream stuck → restarting MediaMTX")
    subprocess.run(["systemctl", "restart", "mediamtx"], check=False, timeout=15)
    return False
