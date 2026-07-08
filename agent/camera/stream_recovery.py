# stream_recovery — keep paths ready:true; recover worker / MediaMTX / full reload

import json
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Dict, List, Optional

from agent.camera.stream_watch import load_stream_paths, stream_ok
from agent.config import (
    MEDIAMTX_API_PORT,
    RTSP_PORT,
    STREAM_NOT_READY_ESCALATE_SEC,
)

if TYPE_CHECKING:
    from agent.camera.camera_worker import CameraWorkerManager

# How long path may stay not-ready before escalation (seconds)
NOT_READY_ESCALATE_SEC = STREAM_NOT_READY_ESCALATE_SEC
_last_full_reload: float = 0.0
_full_reload_cooldown_sec = 120.0
_not_ready_since: Dict[str, float] = {}
_worker_startup_grace_sec = 15.0


def _worker_is_running(worker) -> bool:
    """Support both property-style and method-style worker APIs safely."""
    value = getattr(worker, "is_running", False)
    return bool(value() if callable(value) else value)


def fetch_mediamtx_ready(timeout_sec: float = 5.0) -> Dict[str, bool]:
    """Query MediaMTX API for per-path publisher readiness."""
    url = f"http://127.0.0.1:{MEDIAMTX_API_PORT}/v3/paths/list"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError):
        return {}
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return {}
    result: Dict[str, bool] = {}
    for item in items:
        if isinstance(item, dict) and item.get("name"):
            result[str(item["name"])] = bool(item.get("ready"))
    return result


def recover_streams(
    manager: "CameraWorkerManager",
    *,
    ffprobe_check: bool = False,
) -> dict:
    """
    Recover streams when workers, publishers, or MediaMTX paths drift.

    Layers (in order):
      1. Worker health_check (crash / freeze / stall)
      2. MediaMTX ready:false while worker running → restart worker
      3. ready:true but ffprobe fails → restart worker (optional)
      4. Stuck not-ready past NOT_READY_ESCALATE_SEC → force restart or full reload
    """
    global _last_full_reload

    worker_issues = manager.health_check_all()
    actions: List[str] = [
        f"{name}: {status}" for name, status in worker_issues.items()
    ]

    paths = load_stream_paths()
    if not paths:
        return {"actions": actions, "paths": [], "ready": {}}

    ready_map = fetch_mediamtx_ready()
    now = time.monotonic()

    for path in paths:
        worker = manager.get_worker(path)
        is_ready = ready_map.get(path, False)

        if is_ready:
            _not_ready_since.pop(path, None)
            if ffprobe_check and worker and worker.is_running:
                url = f"rtsp://127.0.0.1:{RTSP_PORT}/{path}"
                if not stream_ok(url, timeout_sec=6.0):
                    if manager.restart_worker(path):
                        actions.append(f"{path}: ffprobe fail → worker restarted")
                    else:
                        actions.append(f"{path}: ffprobe fail → cooldown")
            continue

        # Path not ready
        if path not in _not_ready_since:
            _not_ready_since[path] = now

        stuck_sec = now - _not_ready_since.get(path, now)

        if worker is None:
            if stuck_sec >= 30 and (now - _last_full_reload) >= _full_reload_cooldown_sec:
                actions.extend(_full_reload(manager, reason=f"{path}: missing worker"))
            continue

        if _worker_is_running(worker):
            uptime = float(getattr(worker, "uptime", _worker_startup_grace_sec) or 0.0)
            if hasattr(worker, "uptime") and uptime < _worker_startup_grace_sec:
                actions.append(f"{path}: not ready during startup grace ({uptime:.1f}s)")
                continue
            if manager.restart_worker(path):
                actions.append(f"{path}: not ready → worker restarted")
            elif stuck_sec >= NOT_READY_ESCALATE_SEC:
                if manager.force_restart_worker(path):
                    actions.append(f"{path}: not ready → force restart (cleared cooldown)")
                elif (now - _last_full_reload) >= _full_reload_cooldown_sec:
                    actions.extend(_full_reload(manager, reason=f"{path}: not ready + cooldown"))
        else:
            if manager.restart_worker(path):
                actions.append(f"{path}: not ready + stopped → worker restarted")
            elif stuck_sec >= NOT_READY_ESCALATE_SEC:
                if manager.force_restart_worker(path):
                    actions.append(f"{path}: stopped → force restart")
                elif (now - _last_full_reload) >= _full_reload_cooldown_sec:
                    actions.extend(_full_reload(manager, reason=f"{path}: stopped + cooldown"))

    return {
        "actions": actions,
        "paths": paths,
        "ready": ready_map,
    }


def _full_reload(manager: "CameraWorkerManager", reason: str) -> List[str]:
    """Regenerate config, restart MediaMTX if needed, reload all workers."""
    global _last_full_reload
    from agent.camera.worker_reload import reload_workers

    print(f"[recovery] Full worker reload: {reason}")
    try:
        result = reload_workers(manager)
        _last_full_reload = time.monotonic()
        _not_ready_since.clear()
        return [
            f"full_reload: {reason}",
            f"started {result.get('started')}/{result.get('total')} "
            f"{result.get('stream_names')}",
        ]
    except Exception as e:
        return [f"full_reload failed: {e}"]
