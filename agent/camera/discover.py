# camera discovery — respects provisioned cams.json (manual overrides) if present

import json
import os

from agent.camera.onvif_scan import scan
from agent.camera.pipeline import apply_camera_config
from agent.camera.worker_reload import notify_worker_reload, reload_workers
from agent.config import CAMS_JSON_PATH


def run(worker_manager=None, reload_workers_after: bool = True):
    """
    Generate mediamtx.yml from cameras.

    Priority:
      1. If cams.json exists (written by the provision UI with user-selected
         and manually-added cameras), use that as the authoritative source.
      2. Otherwise, fall back to a live ONVIF network scan.

    This prevents the watchdog's periodic re-discovery from wiping out
    manually-configured camera entries.

    After MediaMTX config is written, reloads FFmpeg workers so paths are
    published (in-process when worker_manager is passed, else HTTP notify).
    """
    cams_path = str(CAMS_JSON_PATH)
    if os.path.exists(cams_path):
        try:
            with open(cams_path, encoding="utf-8") as f:
                cams = json.load(f)
            if cams:
                apply_camera_config(cams)
                print("Configured", len(cams), "cameras (from cams.json)")
                if reload_workers_after:
                    _reload_workers(worker_manager)
                return
        except Exception as e:
            print(f"Error reading cams.json, falling back to scan: {e}")

    # Fallback: live ONVIF scan (no cams.json or it was empty/corrupt)
    cams = scan()
    apply_camera_config(cams, save_cams_json=bool(cams))
    print("Configured", len(cams), "cameras (from ONVIF scan)")
    if reload_workers_after:
        _reload_workers(worker_manager)


def _reload_workers(worker_manager=None) -> None:
    if worker_manager is not None:
        reload_workers(worker_manager)
    else:
        notify_worker_reload()


if __name__ == "__main__":
    run()
