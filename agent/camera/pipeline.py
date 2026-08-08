# pipeline — E2E camera config: mediamtx.yml + worker reload + service order

import os
import socket
import subprocess
import time
from typing import List, Optional

from agent.config import (
    EDGE_DIR,
    IVELY_RTSP_PROBE_URLS_DEFAULT,
    IVELY_RTSP_STREAM_PROFILE_DEFAULT,
    IVELY_SUBSTREAM_ONLY_DEFAULT,
    RTSP_PORT,
)


def edge_agent_env(extra: Optional[dict] = None) -> dict:
    """Environment for discover/provision subprocesses (matches ively-agent.service)."""
    env = {
        **os.environ,
        "PYTHONPATH": str(EDGE_DIR),
        "IVELY_RTSP_STREAM_PROFILE": IVELY_RTSP_STREAM_PROFILE_DEFAULT,
        "IVELY_SUBSTREAM_ONLY": IVELY_SUBSTREAM_ONLY_DEFAULT,
        "IVELY_RTSP_PROBE_URLS": IVELY_RTSP_PROBE_URLS_DEFAULT,
    }
    if extra:
        env.update(extra)
    return env


def wait_for_mediamtx(timeout_sec: float = 45.0) -> bool:
    """Wait until MediaMTX RTSP port accepts connections."""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", RTSP_PORT), timeout=1.5):
                return True
        except OSError:
            time.sleep(1)
    return False


def apply_camera_config(cams: List[dict], save_cams_json: bool = False) -> bool:
    """
    Write mediamtx.yml from camera list. Optionally persist cams.json.
    Returns True if mediamtx.yml content changed.
    """
    from agent.camera.mediamtx_writer import generate

    if save_cams_json and cams:
        from agent.config import CAMS_JSON_PATH

        os.makedirs(os.path.dirname(str(CAMS_JSON_PATH)), exist_ok=True)
        import json

        with open(CAMS_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(cams, f, indent=2)

    return generate(cams)


def restart_stream_services(
    *,
    restart_mediamtx: bool = True,
    restart_agent: bool = True,
    mediamtx_wait_sec: float = 45.0,
) -> None:
    """
    Correct E2E order: MediaMTX first (publisher paths), then agent (FFmpeg workers).
    """
    if restart_mediamtx:
        subprocess.run(
            ["systemctl", "restart", "mediamtx"],
            check=False,
            timeout=30,
        )
        if not wait_for_mediamtx(mediamtx_wait_sec):
            print("[pipeline] WARNING: MediaMTX RTSP port not ready after restart")

    if restart_agent:
        subprocess.run(
            ["systemctl", "restart", "ively-agent"],
            check=False,
            timeout=30,
        )
