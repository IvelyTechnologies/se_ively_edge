# agent main — orchestrates all edge subsystems
#
# Startup order:
#   1. Migrate legacy configs (DNS line strip)
#   2. Load camera configs and start CameraWorkerManager
#   3. Start metrics collection loop
#   4. Start health HTTP server (port 8080)
#   5. Start watchdog (background thread)
#   6. Start WebSocket cloud connection (blocking, main thread)

import json
import os
import threading
import time

from agent.config import (
    CAMS_JSON_PATH,
    MEDIAMTX_CONFIG,
    METRICS_INTERVAL_SEC,
)

# ---------------------------------------------------------------------------
# 1. One-shot migration: strip stale `DNS = ...` line from wg0.conf
# ---------------------------------------------------------------------------
try:
    from agent.wireguard.client import migrate_strip_dns_line
    migrate_strip_dns_line()
except Exception as _e:
    print("wg0.conf DNS migration skipped:", _e)

# ---------------------------------------------------------------------------
# 2. Camera Worker Manager — persistent per-camera FFmpeg workers
# ---------------------------------------------------------------------------
from agent.camera.camera_worker import CameraWorkerManager

worker_manager = CameraWorkerManager()


def _load_and_start_workers() -> None:
    """
    Load camera configs and start persistent FFmpeg workers.
    Workers publish to MediaMTX (which must already be running).
    """
    # Wait briefly for MediaMTX to be ready
    time.sleep(3)

    cams = []
    cams_path = str(CAMS_JSON_PATH)
    if os.path.exists(cams_path):
        try:
            with open(cams_path, "r", encoding="utf-8") as f:
                cams = json.load(f)
        except Exception as e:
            print(f"[main] Error reading cams.json: {e}")

    if not cams:
        print("[main] No cameras configured — workers will start after provisioning")
        return

    # Generate per-camera FFmpeg commands
    try:
        from agent.camera.mediamtx_writer import generate_worker_configs
        configs = generate_worker_configs(cams)
    except Exception as e:
        print(f"[main] Error generating worker configs: {e}")
        return

    if not configs:
        print("[main] No worker configs generated")
        return

    # Register and start all workers
    for cfg in configs:
        worker_manager.add_worker(
            stream_name=cfg["stream_name"],
            ffmpeg_cmd=cfg["ffmpeg_cmd"],
            expected_fps=cfg["expected_fps"],
        )

    worker_manager.start_all()


# Start workers in a background thread so we don't block the health server
threading.Thread(target=_load_and_start_workers, name="worker-init", daemon=True).start()

# ---------------------------------------------------------------------------
# 3. Metrics collection loop — records camera + system health to SQLite
# ---------------------------------------------------------------------------
def _metrics_loop() -> None:
    """Periodically record camera and system metrics."""
    import psutil
    from agent import metrics

    try:
        from agent.wireguard.client import is_interface_up as wg_is_up
    except ImportError:
        def wg_is_up():
            return False

    # Wait for workers to start
    time.sleep(15)

    while True:
        try:
            # Camera metrics
            all_metrics = worker_manager.get_all_metrics()
            if all_metrics:
                metrics.record_camera_metrics(list(all_metrics.values()))

            # System metrics
            summary = worker_manager.get_summary()
            metrics.record_system_metrics(
                cpu_percent=psutil.cpu_percent(interval=0),
                memory_percent=psutil.virtual_memory().percent,
                disk_percent=psutil.disk_usage("/").percent,
                tunnel_up=wg_is_up(),
                active_cameras=summary.get("active", 0),
                total_cameras=summary.get("total", 0),
            )

            # Prune old records (cheap check, only deletes when needed)
            metrics.prune_old_records()

        except Exception as e:
            print(f"[metrics] Collection error: {e}")

        time.sleep(METRICS_INTERVAL_SEC)


threading.Thread(target=_metrics_loop, name="metrics-collector", daemon=True).start()

# ---------------------------------------------------------------------------
# 4. Inject worker manager into watchdog
# ---------------------------------------------------------------------------
from agent.watchdog import watchdog_loop, set_worker_manager

set_worker_manager(worker_manager)

# Self-healing: run watchdog in background
threading.Thread(target=watchdog_loop, daemon=True).start()

# ---------------------------------------------------------------------------
# 5. Start health HTTP server (port 8080)
# ---------------------------------------------------------------------------
from agent.health import start_health, set_worker_manager as health_set_wm

health_set_wm(worker_manager)
start_health()

# ---------------------------------------------------------------------------
# 6. Inject worker manager into ws_client for enhanced heartbeat
# ---------------------------------------------------------------------------
from agent.ws_client import start_ws, set_worker_manager as ws_set_wm

ws_set_wm(worker_manager)

# ---------------------------------------------------------------------------
# 7. Start WebSocket cloud connection (blocking, main thread)
# ---------------------------------------------------------------------------
start_ws()
