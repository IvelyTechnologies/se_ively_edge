# agent main

import threading

from agent.watchdog import watchdog_loop
from agent.ws_client import start_ws
from agent.health import start_health

# Self-healing: run watchdog in background (service restart, stream, disk, internet, re-discovery)
threading.Thread(target=watchdog_loop, daemon=True).start()

start_health()
start_ws()
