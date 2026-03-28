# WebSocket command handler — dispatch cloud commands (OTA, WireGuard, etc.)

import json

try:
    from agent.ota.updater import update as ota_update
except ImportError:
    ota_update = None

try:
    from agent.wireguard.client import (
        get_status as wg_status,
        restart_tunnel as wg_restart,
        provision_tunnel as wg_provision,
    )
    from agent.wireguard.keys import get_public_key as wg_pubkey
    HAS_WIREGUARD = True
except ImportError:
    HAS_WIREGUARD = False


def _handle_wg_status() -> str:
    """Return current WireGuard tunnel status."""
    if not HAS_WIREGUARD:
        return json.dumps({"success": False, "message": "WireGuard module not available"})
    status = wg_status()
    return json.dumps({"success": True, "wireguard": status})


def _handle_wg_restart() -> str:
    """Restart WireGuard tunnel."""
    if not HAS_WIREGUARD:
        return json.dumps({"success": False, "message": "WireGuard module not available"})
    ok = wg_restart()
    return json.dumps({"success": ok, "message": "Tunnel restarted" if ok else "Restart failed"})


def _handle_wg_provision(cmd: dict) -> str:
    """Provision or re-provision WireGuard tunnel with new config from cloud."""
    if not HAS_WIREGUARD:
        return json.dumps({"success": False, "message": "WireGuard module not available"})

    vpn_ip = cmd.get("vpn_ip")
    server_pub = cmd.get("server_public_key")
    endpoint = cmd.get("endpoint")
    if not all([vpn_ip, server_pub, endpoint]):
        return json.dumps({"success": False, "message": "Missing vpn_ip, server_public_key, or endpoint"})

    ok = wg_provision(
        vpn_ip=vpn_ip,
        server_public_key=server_pub,
        endpoint=endpoint,
        allowed_ips=cmd.get("allowed_ips", "10.20.0.0/16"),
        keepalive=cmd.get("keepalive", 25),
    )
    return json.dumps({"success": ok, "message": "VPN provisioned" if ok else "Provisioning failed"})


def _handle_wg_pubkey() -> str:
    """Return the edge device's WireGuard public key."""
    if not HAS_WIREGUARD:
        return json.dumps({"success": False, "message": "WireGuard module not available"})
    try:
        pub = wg_pubkey()
        return json.dumps({"success": True, "public_key": pub})
    except Exception as e:
        return json.dumps({"success": False, "message": str(e)})


def handle(msg: str) -> str | None:
    """
    Parse JSON command and run the right handler. Returns optional response text.
    """
    try:
        cmd = json.loads(msg)
    except json.JSONDecodeError:
        return None

    action = (cmd.get("action") or "").strip()
    if not action:
        return None

    if action == "ota_update":
        if ota_update is None:
            return json.dumps({"success": False, "message": "OTA module not available"})
        repo = cmd.get("repo") or ""
        version = cmd.get("version") or ""
        result = ota_update(repo, version)
        return json.dumps(result)

    if action == "wg_status":
        return _handle_wg_status()

    if action == "wg_restart":
        return _handle_wg_restart()

    if action == "wg_provision":
        return _handle_wg_provision(cmd)

    if action == "wg_pubkey":
        return _handle_wg_pubkey()

    return None
