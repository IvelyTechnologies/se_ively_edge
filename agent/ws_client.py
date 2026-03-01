# websocket client — cloud connection + command dispatch + heartbeat

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


async def _heartbeat(ws):
    """Send periodic heartbeat so cloud can read device version and status."""
    while True:
        try:
            await asyncio.sleep(60)
            await ws.send(json.dumps({"type": "heartbeat", "version": EDGE_VERSION}))
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
