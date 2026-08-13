# worker_reload - reload CameraWorkerManager after discovery / config changes

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


def _worker_is_running(worker) -> bool:
    """Return True for both property-style and method-style worker APIs."""
    value = getattr(worker, "is_running", False)
    return bool(value() if callable(value) else value)


def _all_planned_workers_running(
    manager: "CameraWorkerManager", planned_names: set[str]
) -> bool:
    """True when every planned stream already has a live worker."""
    with manager._lock:
        workers = {name: manager._workers.get(name) for name in planned_names}
    return bool(planned_names) and all(
        worker is not None and _worker_is_running(worker)
        for worker in workers.values()
    )


def reload_workers(manager: "CameraWorkerManager") -> Dict[str, Any]:
    """
    Stop all workers, replace with configs from current cams.json, start again.
    Regenerates mediamtx.yml first so path names always match worker publish URLs.
    Restarts MediaMTX when config changed or worker/path names drifted.
    Returns summary dict for APIs/logs.
    """
    import subprocess

    from agent.camera.pipeline import apply_camera_config, wait_for_mediamtx
    from agent.camera.stream_watch import load_stream_paths

    if not wait_for_mediamtx(timeout_sec=30):
        print("[worker_reload] WARNING: MediaMTX not ready; starting workers anyway")

    cams = load_cams()
    if not cams:
        manager.stop_all()
        with manager._lock:
            manager._workers.clear()
        print("[worker_reload] No cameras - all workers stopped")
        return {"started": 0, "total": 0, "stream_names": []}

    from agent.config import PROVISIONED_MARKER, load_path_prefix

    path_prefix = load_path_prefix()
    if PROVISIONED_MARKER.exists() and not path_prefix:
        print(
            "[worker_reload] ERROR: device is provisioned but site.json has no path prefix - "
            "set customer and site in /opt/ively/agent/site.json, then reload"
        )

    mtx_changed = apply_camera_config(cams)
    configs = build_worker_configs(cams)
    planned_names = {c["stream_name"] for c in configs}
    # Ignore publisher paths owned by optional local services such as
    # analog-dvr-edge. They are deliberately not CameraWorkerManager workers.
    file_paths = set(load_stream_paths(include_external=False))
    with manager._lock:
        running_names = set(manager._workers.keys())

    paths_changed = planned_names != file_paths
    workers_missing = running_names != planned_names
    need_mtx_restart = mtx_changed or paths_changed

    if not need_mtx_restart and _all_planned_workers_running(manager, planned_names):
        names = [c["stream_name"] for c in configs]
        print(f"[worker_reload] Config unchanged; keeping existing workers -> {names}")
        return {
            "started": len(names),
            "total": len(configs),
            "stream_names": names,
            "mediamtx_config_changed": False,
            "mediamtx_restarted": False,
            "workers_reloaded": False,
            "skipped": True,
        }

    if need_mtx_restart:
        if paths_changed:
            print(
                f"[worker_reload] Path drift: workers={sorted(running_names)} "
                f"planned={sorted(planned_names)} file={sorted(file_paths)}"
            )
        reason = "config changed" if mtx_changed else "path file drift"
        print(f"[worker_reload] Restarting MediaMTX ({reason})")
        subprocess.run(
            ["systemctl", "restart", "mediamtx"],
            check=False,
            timeout=30,
        )
        if not wait_for_mediamtx(timeout_sec=45):
            print("[worker_reload] WARNING: MediaMTX not ready after restart")
    elif workers_missing:
        print(
            f"[worker_reload] Worker set drift only; reloading workers without MediaMTX restart "
            f"workers={sorted(running_names)} planned={sorted(planned_names)}"
        )

    started = manager.reload(configs)
    names = [c["stream_name"] for c in configs]
    print(f"[worker_reload] Reloaded workers: {started}/{len(configs)} started -> {names}")
    return {
        "started": started,
        "total": len(configs),
        "stream_names": names,
        "mediamtx_config_changed": mtx_changed,
        "mediamtx_restarted": need_mtx_restart,
        "workers_reloaded": True,
        "skipped": False,
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
