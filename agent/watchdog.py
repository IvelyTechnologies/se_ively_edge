# self-healing watchdog — service health, stream, disk, internet, VPN, re-discovery

import os
import subprocess
import sys
import time
from typing import Callable

import psutil

try:
    from dotenv import load_dotenv
    load_dotenv("/opt/ively/agent/.env")
except Exception:
    pass

_CLOUD_URL = (os.getenv("CLOUD_URL") or "cloud.ively.ai").strip().replace("https://", "").replace("http://", "").strip("/")

# Optional: only use if agent has these modules on path
try:
    from agent.camera.stream_watch import check_cameras
except ImportError:
    check_cameras = None

try:
    from agent.disk_manager import cleanup as disk_cleanup
except ImportError:
    disk_cleanup = None

try:
    from agent.camera.discover import run as run_discovery
except ImportError:
    run_discovery = None

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


def restart(name: str) -> None:
    print("Restarting", name)
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
        print("WireGuard interface down — restarting tunnel")
        wg_restart_tunnel()
        return

    if not wg_tunnel_healthy(max_handshake_age_sec=120):
        print("WireGuard tunnel unhealthy (stale handshake) — restarting")
        wg_restart_tunnel()


def watchdog_loop(
    interval_sec: int = 30,
    discovery_interval_sec: int = 600,
    cpu_threshold: float = 90.0,
    disk_threshold: float = 85.0,
) -> None:
    """
    Main loop: check services, CPU, stream, disk, internet, VPN; run re-discovery periodically.
    """
    last_internet_ok = True
    last_discovery_time = 0.0

    while True:
        try:
            # 1) Service health — MediaMTX & agent
            if not check_service("mediamtx"):
                restart("mediamtx")
            if not check_service("ively-agent"):
                restart("ively-agent")

            # 2) CPU protection — reduce load by restarting MediaMTX if CPU pegged
            try:
                if psutil.cpu_percent(interval=1) > cpu_threshold:
                    restart("mediamtx")
            except Exception:
                pass

            # 3) Stream watch — if first RTSP stream is stuck, restart MediaMTX
            if check_cameras is not None:
                check_cameras()

            # 4) Disk cleanup
            if disk_cleanup is not None:
                disk_cleanup(threshold_percent=disk_threshold)

            # 5) Internet recovery — when back online, force agent reconnect
            internet_ok = _internet_ok()
            if not last_internet_ok and internet_ok:
                print("Internet back — restarting ively-agent")
                restart("ively-agent")
                # Also restart WireGuard tunnel after internet recovery
                if HAS_WIREGUARD and wg_load_state() is not None:
                    print("Internet back — restarting WireGuard tunnel")
                    wg_restart_tunnel()
            last_internet_ok = internet_ok

            # 6) WireGuard tunnel health
            _check_wireguard()

            # 7) Periodic camera re-discovery (e.g. camera unplugged then reappears)
            now = time.monotonic()
            if run_discovery is not None and (now - last_discovery_time) >= discovery_interval_sec:
                last_discovery_time = now
                try:
                    run_discovery()
                except Exception as e:
                    print("Re-discovery error:", e)

        except Exception as e:
            print("Watchdog error:", e, file=sys.stderr)

        time.sleep(interval_sec)
