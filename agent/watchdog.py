# self-healing watchdog — per-camera worker health, service health, disk, internet, VPN, re-discovery
#
# Enterprise-grade watchdog that:
#   - Restarts ONLY failed camera workers (never all of MediaMTX)
#   - Enforces restart cooldown to prevent restart storms
#   - Monitors WireGuard VPN tunnel health
#   - Handles internet recovery gracefully
#   - Periodically re-discovers cameras

import os
import subprocess
import sys
import time
from typing import Optional

try:
    import psutil

    HAS_PSUTIL = True
except ImportError:
    psutil = None  # type: ignore
    HAS_PSUTIL = False
    print("[watchdog] psutil not installed — CPU metrics disabled", file=sys.stderr)

try:
    from dotenv import load_dotenv
    load_dotenv("/opt/ively/agent/.env")
except Exception:
    pass

from agent.config import (
    WATCHDOG_INTERVAL_SEC,
    DISCOVERY_INTERVAL_SEC,
    CPU_THRESHOLD,
    DISK_THRESHOLD,
)

_CLOUD_URL = (os.getenv("CLOUD_URL") or "cloud.ively.ai").strip().replace("https://", "").replace("http://", "").strip("/")

# Camera worker manager (injected from main.py)
_worker_manager = None


def set_worker_manager(manager) -> None:
    """Called by main.py to inject the CameraWorkerManager instance."""
    global _worker_manager
    _worker_manager = manager


# Optional: camera discovery
try:
    from agent.camera.discover import run as run_discovery
except ImportError:
    run_discovery = None

# Optional: disk cleanup
try:
    from agent.disk_manager import cleanup as disk_cleanup
except ImportError:
    disk_cleanup = None

# WireGuard tunnel health
try:
    from agent.wireguard.client import (
        tunnel_healthy as wg_tunnel_healthy,
        restart_tunnel as wg_restart_tunnel,
        load_state as wg_load_state,
        is_interface_up as wg_is_up,
    )
    HAS_WIREGUARD = True
except ImportError:
    HAS_WIREGUARD = False

# Internet check (uses CLOUD_URL from provisioning)
try:
    import requests
    def _internet_ok() -> bool:
        try:
            r = requests.get(f"https://{_CLOUD_URL}", timeout=5)
            return r.status_code < 500
        except Exception:
            return False
except ImportError:
    def _internet_ok() -> bool:
        return False


def check_service(name: str) -> bool:
    r = subprocess.run(
        ["systemctl", "is-active", name],
        capture_output=True,
        text=True,
        timeout=5,
    )
    return r.returncode == 0 and "active" in (r.stdout or "").lower()


def restart_service(name: str) -> None:
    print(f"[watchdog] Restarting service: {name}")
    subprocess.run(["systemctl", "restart", name], timeout=15, check=False)


def _check_wireguard() -> None:
    """Monitor WireGuard tunnel health and restart if unhealthy."""
    if not HAS_WIREGUARD:
        return

    # Only check if WireGuard was provisioned (state file exists)
    state = wg_load_state()
    if state is None:
        return

    if not wg_is_up():
        print("[watchdog] WireGuard interface down — restarting tunnel")
        wg_restart_tunnel()
        return

    if not wg_tunnel_healthy(max_handshake_age_sec=120):
        print("[watchdog] WireGuard tunnel unhealthy (stale handshake) — restarting")
        wg_restart_tunnel()


def _check_camera_workers() -> None:
    """Legacy hook — recovery is handled by stream_recovery.recover_streams."""
    if _worker_manager is None:
        return
    try:
        from agent.camera.stream_recovery import recover_streams

        recover_streams(_worker_manager)
    except Exception as e:
        print(f"[watchdog] Camera recovery error: {e}")


def watchdog_loop(
    interval_sec: int = WATCHDOG_INTERVAL_SEC,
    discovery_interval_sec: int = DISCOVERY_INTERVAL_SEC,
    cpu_threshold: float = CPU_THRESHOLD,
    disk_threshold: float = DISK_THRESHOLD,
) -> None:
    """
    Main loop: check services, per-camera workers, CPU, disk,
    internet, VPN; run re-discovery periodically.

    Key difference from old watchdog:
      - Camera health: restarts individual workers, NOT all of MediaMTX
      - MediaMTX restart: ONLY if the process itself has crashed
      - CPU protection: logs warning instead of blindly restarting MediaMTX
    """
    last_internet_ok = True
    last_discovery_time = 0.0

    while True:
        try:
            # 1) Service health — MediaMTX process
            #    Only restart MediaMTX if the process itself is dead.
            #    Camera stream issues are handled by per-camera workers.
            if not check_service("mediamtx"):
                restart_service("mediamtx")
                time.sleep(5)
                if _worker_manager is not None:
                    try:
                        from agent.camera.stream_recovery import recover_streams

                        recover_streams(_worker_manager)
                    except Exception as e:
                        print(f"[watchdog] Post-MediaMTX recovery error: {e}")

            if not check_service("ively-agent"):
                restart_service("ively-agent")

            # 2) Per-camera recovery — workers + MediaMTX ready + escalation
            if _worker_manager is not None:
                try:
                    from agent.camera.stream_recovery import recover_streams

                    result = recover_streams(_worker_manager)
                    for line in result.get("actions") or []:
                        if line:
                            print(f"[watchdog] Recovery: {line}")
                except Exception as e:
                    print(f"[watchdog] Stream recovery error: {e}")

            # 3) CPU monitoring — log warning, do NOT restart MediaMTX
            if HAS_PSUTIL:
                try:
                    cpu = psutil.cpu_percent(interval=1)
                    if cpu > cpu_threshold:
                        print(
                            f"[watchdog] High CPU: {cpu:.1f}% "
                            f"(threshold: {cpu_threshold}%)"
                        )
                except Exception:
                    pass

            # 4) Disk cleanup
            if disk_cleanup is not None:
                disk_cleanup(threshold_percent=disk_threshold)

            # 5) Internet recovery — when back online, force agent reconnect
            internet_ok = _internet_ok()
            if not last_internet_ok and internet_ok:
                print("[watchdog] Internet back — restarting ively-agent")
                restart_service("ively-agent")
                # Also restart WireGuard tunnel after internet recovery
                if HAS_WIREGUARD and wg_load_state() is not None:
                    print("[watchdog] Internet back — restarting WireGuard tunnel")
                    wg_restart_tunnel()
            last_internet_ok = internet_ok

            # 6) WireGuard tunnel health
            _check_wireguard()

            # 7) Periodic camera re-discovery (e.g. camera unplugged then reappears)
            now = time.monotonic()
            if run_discovery is not None and (now - last_discovery_time) >= discovery_interval_sec:
                last_discovery_time = now
                try:
                    run_discovery(worker_manager=_worker_manager)
                except Exception as e:
                    print("[watchdog] Re-discovery error:", e)

        except Exception as e:
            print("[watchdog] Error:", e, file=sys.stderr)

        time.sleep(interval_sec)
