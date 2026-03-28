# WireGuard tunnel client — configure, start, stop, status, and health

import json
import os
import subprocess
import time
from typing import Any, Optional

from agent.wireguard.config import (
    DEFAULT_PERSISTENT_KEEPALIVE,
    DEFAULT_VPN_NETWORK,
    WG_CONFIG_PATH,
    WG_INTERFACE,
    WG_STATE_PATH,
)
from agent.wireguard.keys import get_or_create_keypair


# ---------------------------------------------------------------------------
# State helpers — persist VPN assignment from cloud
# ---------------------------------------------------------------------------

def save_state(state: dict) -> None:
    """Save WireGuard state (vpn_ip, server_public_key, endpoint, etc.) to disk."""
    os.makedirs(os.path.dirname(WG_STATE_PATH), exist_ok=True)
    with open(WG_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def load_state() -> Optional[dict]:
    """Load saved WireGuard state. Returns None if not provisioned."""
    try:
        with open(WG_STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# Configuration writer
# ---------------------------------------------------------------------------

def write_config(
    private_key: str,
    vpn_ip: str,
    server_public_key: str,
    endpoint: str,
    allowed_ips: str = DEFAULT_VPN_NETWORK,
    keepalive: int = DEFAULT_PERSISTENT_KEEPALIVE,
) -> str:
    """
    Write /etc/wireguard/wg0.conf for the edge device (client role).

    Returns the path to the written config file.
    """
    config = f"""[Interface]
PrivateKey = {private_key}
Address = {vpn_ip}/16

[Peer]
PublicKey = {server_public_key}
Endpoint = {endpoint}
AllowedIPs = {allowed_ips}
PersistentKeepalive = {keepalive}
"""
    os.makedirs(os.path.dirname(WG_CONFIG_PATH), exist_ok=True)
    with open(WG_CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(config)
    os.chmod(WG_CONFIG_PATH, 0o600)
    return WG_CONFIG_PATH


# ---------------------------------------------------------------------------
# Tunnel control
# ---------------------------------------------------------------------------

def start_tunnel() -> bool:
    """Bring up WireGuard interface. Returns True on success."""
    # Bring down first in case it's already running (idempotent)
    subprocess.run(["wg-quick", "down", WG_INTERFACE], capture_output=True, timeout=15)
    result = subprocess.run(
        ["wg-quick", "up", WG_INTERFACE],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        print(f"WireGuard start failed: {result.stderr.strip()}")
        return False
    print(f"WireGuard tunnel {WG_INTERFACE} is up")
    return True


def stop_tunnel() -> bool:
    """Bring down WireGuard interface. Returns True on success."""
    result = subprocess.run(
        ["wg-quick", "down", WG_INTERFACE],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        print(f"WireGuard stop failed: {result.stderr.strip()}")
        return False
    print(f"WireGuard tunnel {WG_INTERFACE} is down")
    return True


def restart_tunnel() -> bool:
    """Restart WireGuard interface."""
    stop_tunnel()
    time.sleep(1)
    return start_tunnel()


def enable_autostart() -> None:
    """Enable WireGuard to start on boot via systemd."""
    subprocess.run(
        ["systemctl", "enable", f"wg-quick@{WG_INTERFACE}"],
        capture_output=True,
        timeout=10,
    )


def disable_autostart() -> None:
    """Disable WireGuard autostart."""
    subprocess.run(
        ["systemctl", "disable", f"wg-quick@{WG_INTERFACE}"],
        capture_output=True,
        timeout=10,
    )


# ---------------------------------------------------------------------------
# Status / health
# ---------------------------------------------------------------------------

def is_interface_up() -> bool:
    """Check if the WireGuard interface exists and is up."""
    result = subprocess.run(
        ["ip", "link", "show", WG_INTERFACE],
        capture_output=True,
        text=True,
        timeout=5,
    )
    return result.returncode == 0


def get_status() -> dict:
    """
    Get WireGuard interface status. Returns dict with:
      interface_up, latest_handshake, transfer_rx, transfer_tx, endpoint
    """
    status: dict[str, Any] = {
        "interface_up": False,
        "latest_handshake": None,
        "transfer_rx": 0,
        "transfer_tx": 0,
        "endpoint": None,
        "vpn_ip": None,
    }

    if not is_interface_up():
        return status

    status["interface_up"] = True

    # Parse `wg show` output
    try:
        result = subprocess.run(
            ["wg", "show", WG_INTERFACE],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.startswith("endpoint:"):
                    status["endpoint"] = line.split(":", 1)[1].strip()
                elif line.startswith("latest handshake:"):
                    status["latest_handshake"] = line.split(":", 1)[1].strip()
                elif line.startswith("transfer:"):
                    parts = line.split(":", 1)[1].strip()
                    # e.g. "1.23 MiB received, 456 KiB sent"
                    status["transfer_info"] = parts
    except Exception:
        pass

    # Get VPN IP from state
    state = load_state()
    if state:
        status["vpn_ip"] = state.get("vpn_ip")

    return status


def tunnel_healthy(max_handshake_age_sec: int = 180) -> bool:
    """
    Check if the WireGuard tunnel is healthy.
    Healthy = interface up AND handshake within max_handshake_age_sec seconds.
    """
    if not is_interface_up():
        return False

    # Check latest handshake via wg show
    try:
        result = subprocess.run(
            ["wg", "show", WG_INTERFACE, "latest-handshakes"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            # Format: <public_key>\t<unix_timestamp>
            for line in result.stdout.strip().splitlines():
                parts = line.split("\t")
                if len(parts) == 2:
                    ts = int(parts[1])
                    if ts == 0:
                        # No handshake yet
                        return False
                    age = int(time.time()) - ts
                    return age < max_handshake_age_sec
    except Exception:
        pass

    # If we can't determine handshake age, consider it healthy if interface is up
    return True


# ---------------------------------------------------------------------------
# Full provisioning flow (called during device setup)
# ---------------------------------------------------------------------------

def provision_tunnel(
    vpn_ip: str,
    server_public_key: str,
    endpoint: str,
    allowed_ips: str = DEFAULT_VPN_NETWORK,
    keepalive: int = DEFAULT_PERSISTENT_KEEPALIVE,
) -> bool:
    """
    Full WireGuard provisioning:
      1. Generate or load key pair
      2. Write WireGuard config
      3. Save state
      4. Start tunnel
      5. Enable autostart

    Returns True on success.
    """
    try:
        private_key, public_key = get_or_create_keypair()

        write_config(
            private_key=private_key,
            vpn_ip=vpn_ip,
            server_public_key=server_public_key,
            endpoint=endpoint,
            allowed_ips=allowed_ips,
            keepalive=keepalive,
        )

        # Save state for later reference
        save_state({
            "vpn_ip": vpn_ip,
            "server_public_key": server_public_key,
            "endpoint": endpoint,
            "allowed_ips": allowed_ips,
            "public_key": public_key,
        })

        # Start tunnel
        if not start_tunnel():
            return False

        # Enable autostart on boot
        enable_autostart()

        print(f"WireGuard provisioned: VPN IP {vpn_ip}")
        return True

    except Exception as e:
        print(f"WireGuard provisioning failed: {e}")
        return False
