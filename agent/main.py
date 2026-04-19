# agent main

import threading

from agent.watchdog import watchdog_loop
from agent.ws_client import start_ws
from agent.health import start_health

# One-shot migration: strip stale `DNS = ...` line from wg0.conf on older
# deployments. Safe no-op if the line isn't there. See
# agent/wireguard/client.py::migrate_strip_dns_line for rationale.
try:
    from agent.wireguard.client import migrate_strip_dns_line
    migrate_strip_dns_line()
except Exception as _e:
    print("wg0.conf DNS migration skipped:", _e)

# Self-healing: run watchdog in background (service restart, stream, disk, internet, re-discovery)
threading.Thread(target=watchdog_loop, daemon=True).start()

start_health()
start_ws()
