# WireGuard configuration constants

import os

# Paths
WG_CONFIG_DIR = "/etc/wireguard"
WG_CONFIG_PATH = "/etc/wireguard/wg0.conf"
WG_KEYS_DIR = "/opt/ively/agent/wg_keys"
WG_PRIVATE_KEY_PATH = os.path.join(WG_KEYS_DIR, "privatekey")
WG_PUBLIC_KEY_PATH = os.path.join(WG_KEYS_DIR, "publickey")

# VPN interface
WG_INTERFACE = "wg0"

# Cloud VPN gateway settings (overridden by cloud during provisioning)
DEFAULT_VPN_ENDPOINT_PORT = 51820
DEFAULT_VPN_NETWORK = "10.20.0.0/16"
DEFAULT_PERSISTENT_KEEPALIVE = 25

# State file (stores VPN IP, server pubkey, etc. after provisioning)
WG_STATE_PATH = "/opt/ively/agent/wg_state.json"
