# stream watch — detect RTSP freeze and trigger MediaMTX restart

import re
import subprocess
import time
from typing import Optional

# Optional: use opencv for frame grab if available
try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


def _first_rtsp_from_config(config_path: str = "/opt/ively/mediamtx/mediamtx.yml") -> Optional[str]:
    """Read first source URL from mediamtx.yml."""
    try:
        with open(config_path, encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return None
    m = re.search(r"source:\s*(rtsp://[^\s]+)", content)
    return m.group(1).strip() if m else None


def stream_ok(url: str, timeout_sec: float = 10.0) -> bool:
    """Try to read one frame from RTSP URL. Returns True if stream is alive."""
    if not HAS_CV2:
        return True  # Skip check if opencv not installed
    cap = None
    try:
        cap = cv2.VideoCapture(url)
        if not cap.isOpened():
            return False
        start = time.monotonic()
        while time.monotonic() - start < timeout_sec:
            ok, _ = cap.read()
            if ok:
                return True
        return False
    except Exception:
        return False
    finally:
        if cap is not None:
            cap.release()


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
