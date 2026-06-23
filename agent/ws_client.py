# websocket client — cloud connection + command dispatch + enhanced heartbeat
#
# Heartbeat now includes: version, VPN status, CPU, memory, disk,
# camera health summary, uptime, and tunnel health.

import asyncio
import json
import os
import time

import websockets
from dotenv import load_dotenv

load_dotenv("/opt/ively/agent/.env")

DEVICE = os.getenv("DEVICE_ID")
CLOUD_URL = (os.getenv("CLOUD_URL") or "cloud.ively.ai").strip().replace("https://", "").replace("http://", "").strip("/")

from agent.config import HEARTBEAT_INTERVAL_SEC

try:
    from agent.ota.version import VERSION as EDGE_VERSION
except ImportError:
    EDGE_VERSION = "0.0.0"

try:
    from agent.commands import handle as handle_command
except ImportError:
    handle_command = None

# WireGuard status (optional)
try:
    from agent.wireguard.client import get_status as wg_get_status, load_state as wg_load_state
    HAS_WIREGUARD = True
except ImportError:
    HAS_WIREGUARD = False

# Camera worker manager (injected from main.py)
_worker_manager = None


def set_worker_manager(manager) -> None:
    """Called by main.py to inject the CameraWorkerManager instance."""
    global _worker_manager
    _worker_manager = manager


def _vpn_info() -> dict:
    """Collect VPN status for heartbeat."""
    if not HAS_WIREGUARD:
        return {"vpn": "not_installed"}
    state = wg_load_state()
    if state is None:
        return {"vpn": "not_configured"}
    try:
        status = wg_get_status()
        return {
            "vpn": "connected" if status.get("interface_up") else "disconnected",
            "vpn_ip": status.get("vpn_ip") or state.get("vpn_ip"),
        }
    except Exception:
        return {"vpn": "error"}


def _system_uptime() -> float:
    """System uptime in seconds."""
    try:
        with open("/proc/uptime", "r") as f:
            return float(f.readline().split()[0])
    except Exception:
        return 0.0


def _system_metrics() -> dict:
    """Collect CPU, memory, disk for heartbeat."""
    try:
        import psutil
        return {
            "cpu_percent": round(psutil.cpu_percent(interval=0), 1),
            "memory_percent": round(psutil.virtual_memory().percent, 1),
            "disk_percent": round(psutil.disk_usage("/").percent, 1),
        }
    except Exception:
        return {}


def _camera_summary() -> dict:
    """Collect camera worker health summary for heartbeat."""
    if _worker_manager is None:
        return {}
    try:
        return _worker_manager.get_summary()
    except Exception:
        return {}


async def _heartbeat(ws):
    """
    Send periodic heartbeat so cloud can read device health.

    Enhanced payload includes:
      - version, uptime
      - VPN status + IP
      - CPU, memory, disk percentages
      - Camera health summary (total, active, unhealthy, in_cooldown)
    """
    while True:
        try:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)
            heartbeat = {
                "type": "heartbeat",
                "version": EDGE_VERSION,
                "uptime": round(_system_uptime(), 0),
            }
            # VPN info
            heartbeat.update(_vpn_info())
            # System metrics
            heartbeat.update(_system_metrics())
            # Camera health
            cameras = _camera_summary()
            if cameras:
                heartbeat["cameras"] = cameras
            await ws.send(json.dumps(heartbeat))
        except Exception:
            break


async def run():
    while True:
        try:
            async with websockets.connect(
                f"wss://{CLOUD_URL}/ws/{DEVICE}"
            ) as ws:
                asyncio.create_task(_heartbeat(ws))
                while True:
                    msg = await ws.recv()
                    print("CMD:", msg)
                    if handle_command:
                        # OTA and other handlers may block; run in executor to keep connection alive
                        loop = asyncio.get_event_loop()
                        response = await loop.run_in_executor(None, handle_command, msg)
                        if response:
                            await ws.send(response)
        except Exception:
            await asyncio.sleep(5)


def start_ws():
    asyncio.run(run())
