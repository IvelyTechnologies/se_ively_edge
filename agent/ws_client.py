# websocket client — cloud connection + command dispatch + heartbeat (includes VPN status)

import asyncio
import json
import os

import websockets
from dotenv import load_dotenv

load_dotenv("/opt/ively/agent/.env")

DEVICE = os.getenv("DEVICE_ID")
CLOUD_URL = (os.getenv("CLOUD_URL") or "cloud.ively.ai").strip().replace("https://", "").replace("http://", "").strip("/")

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


async def _heartbeat(ws):
    """Send periodic heartbeat so cloud can read device version, VPN status, and overall status."""
    while True:
        try:
            await asyncio.sleep(60)
            heartbeat = {
                "type": "heartbeat",
                "version": EDGE_VERSION,
            }
            # Include VPN info
            heartbeat.update(_vpn_info())
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
