# websocket client — cloud connection + command dispatch + enhanced heartbeat
#
# Heartbeat includes per-stream health (EDGE-02), VPN status, system metrics,
# and legacy camera summary for backward compatibility.

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
    """Collect VPN status for heartbeat (spec field: vpn_status)."""
    if not HAS_WIREGUARD:
        return {"vpn": "not_installed", "vpn_status": "not_installed"}
    state = wg_load_state()
    if state is None:
        return {"vpn": "not_configured", "vpn_status": "not_configured"}
    try:
        status = wg_get_status()
        connected = bool(status.get("interface_up"))
        vpn_state = "connected" if connected else "disconnected"
        return {
            "vpn": vpn_state,
            "vpn_status": vpn_state,
            "vpn_ip": status.get("vpn_ip") or state.get("vpn_ip"),
        }
    except Exception:
        return {"vpn": "error", "vpn_status": "error"}


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
    """Legacy aggregate camera summary (kept for dashboards that read it)."""
    if _worker_manager is None:
        return {}
    try:
        return _worker_manager.get_summary()
    except Exception:
        return {}


def _camera_streams() -> list[dict]:
    """Per-stream health array required by se_backend EDGE-02."""
    if _worker_manager is None:
        return []
    try:
        return _worker_manager.get_heartbeat_streams()
    except Exception:
        return []


def build_heartbeat_payload() -> dict:
    """Build full heartbeat JSON for cloud."""
    heartbeat = {
        "type": "heartbeat",
        "version": EDGE_VERSION,
        "uptime": round(_system_uptime(), 0),
    }
    heartbeat.update(_vpn_info())
    heartbeat.update(_system_metrics())

    streams = _camera_streams()
    summary = _camera_summary()
    cameras_payload: dict = {}
    if summary:
        cameras_payload.update(summary)
    if streams:
        cameras_payload["streams"] = streams
    if cameras_payload:
        heartbeat["cameras"] = cameras_payload
    return heartbeat


async def _heartbeat(ws):
    """Send periodic heartbeat so cloud can read device + per-stream health."""
    while True:
        try:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)
            await ws.send(json.dumps(build_heartbeat_payload()))
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
