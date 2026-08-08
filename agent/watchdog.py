# self-healing watchdog - per-camera worker health, service health, disk, internet, VPN, re-discovery
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
    print("[watchdog] psutil not installed - CPU metrics disabled", file=sys.stderr)

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
_WG_RESTART_COOLDOWN_SEC = int(os.getenv("IVELY_WG_RESTART_COOLDOWN_SEC", "300"))
_WG_STALE_RESTART_AFTER = int(os.getenv("IVELY_WG_STALE_RESTART_AFTER", "3"))
_last_wg_restart_at = 0.0
_wg_stale_count = 0

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

def _restart_wireguard(reason: str) -> None:
    """Restart WireGuard with cooldown to avoid tunnel flapping storms."""
    global _last_wg_restart_at
    now = time.monotonic()
    elapsed = now - _last_wg_restart_at
    if _last_wg_restart_at and elapsed < _WG_RESTART_COOLDOWN_SEC:
        remaining = _WG_RESTART_COOLDOWN_SEC - elapsed
        print(
            f"[watchdog] WireGuard unhealthy ({reason}) but restart cooldown active "
            f"({remaining:.0f}s remaining)"
        )
        return
    print(f"[watchdog] WireGuard unhealthy ({reason}) - restarting")
    wg_restart_tunnel()
    _last_wg_restart_at = time.monotonic()

def _check_wireguard() -> None:
    """Monitor WireGuard tunnel health and restart if unhealthy."""
    global _wg_stale_count
    if not HAS_WIREGUARD:
        return

    # Only check if WireGuard was provisioned (state file exists)
    state = wg_load_state()
    if state is None:
        return

    if not wg_is_up():
        _wg_stale_count = 0
        _restart_wireguard("interface down")
        return

    if not wg_tunnel_healthy(max_handshake_age_sec=120):
        _wg_stale_count += 1
        print(
            f"[watchdog] WireGuard stale handshake "
            f"({_wg_stale_count}/{_WG_STALE_RESTART_AFTER})"
        )
        if _wg_stale_count >= _WG_STALE_RESTART_AFTER:
            _restart_wireguard("stale handshake")
            _wg_stale_count = 0
        return

    _wg_stale_count = 0

def _check_camera_workers() -> None:
    """Legacy hook - recovery is handled by stream_recovery.recover_streams."""
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
            # 1) Service health - MediaMTX process
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

            # 2) Per-camera recovery - workers + MediaMTX ready + escalation
            if _worker_manager is not None:
                try:
                    from agent.camera.stream_recovery import recover_streams

                    result = recover_streams(_worker_manager)
                    for line in result.get("actions") or []:
                        if line:
                            print(f"[watchdog] Recovery: {line}")
                except Exception as e:
                    print(f"[watchdog] Stream recovery error: {e}")

            # 3) CPU monitoring - log warning, do NOT restart MediaMTX
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

            # 5) Internet recovery - when back online, force agent reconnect
            internet_ok = _internet_ok()
            if not last_internet_ok and internet_ok:
                print("[watchdog] Internet back - restarting ively-agent")
                restart_service("ively-agent")
                # Also restart WireGuard tunnel after internet recovery
                if HAS_WIREGUARD and wg_load_state() is not None:
                    _restart_wireguard("internet recovered")
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
