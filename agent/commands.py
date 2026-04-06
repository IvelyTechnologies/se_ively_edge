# WebSocket command handler — dispatch cloud commands (OTA, WireGuard, diagnostics, etc.)

import json
import subprocess

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


# ---------------------------------------------------------------------------
# Safe diagnostic commands that can be executed remotely from the server.
# Each entry maps a short name to the actual shell command (list of args).
# Only commands in this allowlist can be run — no arbitrary shell execution.
# ---------------------------------------------------------------------------
DIAGNOSTIC_COMMANDS: dict[str, list[str]] = {
    "mediamtx_config":  ["grep", "-A5", "paths:", "/opt/mediamtx/mediamtx.yml"],
    "mediamtx_logs":    ["journalctl", "-u", "mediamtx", "--no-pager", "-n", "50"],
    "mediamtx_ports":   ["ss", "-tlnp"],  # caller can grep for 8554/8888/9997
    "mediamtx_paths":   ["curl", "-s", "http://127.0.0.1:9997/v3/paths/list"],
    "agent_logs":       ["journalctl", "-u", "ively-agent", "--no-pager", "-n", "50"],
    "wireguard_status": ["wg", "show"],
    "network_interfaces": ["ip", "-br", "addr"],
    "disk_usage":       ["df", "-h"],
    "memory_usage":     ["free", "-h"],
    "uptime":           ["uptime"],
    "systemctl_status_mediamtx": ["systemctl", "status", "mediamtx", "--no-pager"],
    "systemctl_status_agent":    ["systemctl", "status", "ively-agent", "--no-pager"],
    "ping_cloud":       ["ping", "-c", "3", "-W", "2", "cloud.ively.ai"],
    "dmesg_tail":       ["dmesg", "--no-pager", "-T"],  # last kernel messages
}


def _run_safe_command(name: str, timeout: int = 15) -> dict:
    """Execute a pre-approved diagnostic command and return structured output."""
    args = DIAGNOSTIC_COMMANDS.get(name)
    if args is None:
        return {"command": name, "error": f"Unknown diagnostic command: {name}"}
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "command": name,
            "stdout": result.stdout[-4000:] if result.stdout else "",  # cap at 4KB
            "stderr": result.stderr[-2000:] if result.stderr else "",
            "returncode": result.returncode,
        }
    except FileNotFoundError:
        return {"command": name, "error": f"Command not found: {args[0]}"}
    except subprocess.TimeoutExpired:
        return {"command": name, "error": f"Command timed out after {timeout}s"}
    except Exception as e:
        return {"command": name, "error": str(e)}


def run_diagnostics(commands: list[str] | None = None, timeout: int = 15) -> dict:
    """
    Run one or more diagnostic commands and return results.
    If commands is None, run the default MediaMTX debug bundle.
    """
    if commands is None:
        commands = ["mediamtx_config", "mediamtx_logs", "mediamtx_ports", "mediamtx_paths"]

    results = {}
    for cmd_name in commands:
        results[cmd_name] = _run_safe_command(cmd_name, timeout=timeout)

    return {
        "success": True,
        "diagnostics": results,
        "available_commands": sorted(DIAGNOSTIC_COMMANDS.keys()),
    }


def _handle_diagnose(cmd: dict) -> str:
    """
    Run diagnostic commands on the edge device.
    Payload examples:
      {"action": "diagnose"}                     → runs default MediaMTX debug bundle
      {"action": "diagnose", "commands": ["mediamtx_logs", "disk_usage"]}
      {"action": "diagnose", "commands": ["all"]} → runs every available command
    """
    requested = cmd.get("commands")
    if requested and requested == ["all"]:
        requested = sorted(DIAGNOSTIC_COMMANDS.keys())
    elif requested:
        # Validate requested commands
        invalid = [c for c in requested if c not in DIAGNOSTIC_COMMANDS]
        if invalid:
            return json.dumps({
                "success": False,
                "message": f"Unknown commands: {invalid}",
                "available_commands": sorted(DIAGNOSTIC_COMMANDS.keys()),
            })
    else:
        requested = None  # default bundle

    timeout = cmd.get("timeout", 15)
    result = run_diagnostics(commands=requested, timeout=timeout)
    return json.dumps(result)


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

    if action == "diagnose":
        return _handle_diagnose(cmd)

    return None
