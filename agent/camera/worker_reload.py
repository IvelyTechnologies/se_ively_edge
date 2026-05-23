# worker_reload — reload CameraWorkerManager after discovery / config changes

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from agent.config import AGENT_HTTP_PORT, CAMS_JSON_PATH

if TYPE_CHECKING:
    from agent.camera.camera_worker import CameraWorkerManager


def load_cams() -> List[dict]:
    """Load camera list from provisioned cams.json."""
    path = str(CAMS_JSON_PATH)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def build_worker_configs(cams: Optional[List[dict]] = None) -> List[dict]:
    """Build FFmpeg worker configs from camera list."""
    if cams is None:
        cams = load_cams()
    if not cams:
        return []
    from agent.camera.mediamtx_writer import generate_worker_configs

    return generate_worker_configs(cams)


def reload_workers(manager: "CameraWorkerManager") -> Dict[str, Any]:
    """
    Stop all workers, replace with configs from current cams.json, start again.
    Returns summary dict for APIs/logs.
    """
    from agent.camera.pipeline import wait_for_mediamtx

    if not wait_for_mediamtx(timeout_sec=30):
        print("[worker_reload] WARNING: MediaMTX not ready; starting workers anyway")

    configs = build_worker_configs()
    if not configs:
        manager.stop_all()
        with manager._lock:
            manager._workers.clear()
        print("[worker_reload] No cameras — all workers stopped")
        return {"started": 0, "total": 0, "stream_names": []}

    started = manager.reload(configs)
    names = [c["stream_name"] for c in configs]
    print(f"[worker_reload] Reloaded workers: {started}/{len(configs)} started")
    return {
        "started": started,
        "total": len(configs),
        "stream_names": names,
    }


def notify_worker_reload(
    timeout_sec: float = 15.0,
    retries: int = 8,
    retry_delay_sec: float = 3.0,
) -> bool:
    """
    Ask the running ively-agent health server to reload workers.
    Used when discovery runs in a separate process (CLI / provision UI subprocess).
    Retries until agent HTTP is up (E2E: discover may finish before agent restart).
    """
    url = f"http://127.0.0.1:{AGENT_HTTP_PORT}/workers/reload"
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, data=b"", method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                print(
                    f"[worker_reload] Agent reload OK ({resp.status}): {body[:200]}"
                )
                return 200 <= resp.status < 300
        except urllib.error.HTTPError as e:
            print(f"[worker_reload] Agent reload HTTP {e.code}: {e.read()[:200]}")
            return False
        except Exception as e:
            if attempt < retries:
                print(
                    f"[worker_reload] Agent not ready (attempt {attempt}/{retries}): {e}"
                )
                time.sleep(retry_delay_sec)
            else:
                print(f"[worker_reload] Agent reload notify failed: {e}")
    return False
