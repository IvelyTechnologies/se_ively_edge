#!/bin/bash
# Enable the correct Ively edge services for automatic start on boot / after reboot.
# Run as root (installer, provision, or manually after updates).
set -e

PROVISIONED="/opt/ively/.provisioned"
EDGE_DIR="/opt/ively/edge"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo bash $0"
  exit 1
fi

chmod +x "${EDGE_DIR}/installer/run-ively-agent.sh" 2>/dev/null || true

# Core streaming stack — always start on boot once installed
systemctl enable mediamtx.service
systemctl enable ively-agent.service

# WireGuard VPN (after provisioning creates wg0.conf)
if [ -f /etc/wireguard/wg0.conf ]; then
  systemctl enable "wg-quick@wg0.service" 2>/dev/null || true
fi

if [ -f "$PROVISIONED" ]; then
  # Provisioned device: agent + mediamtx + VPN; no provision UI on boot
  systemctl disable ively-provision.service 2>/dev/null || true
  echo "Enabled for boot: mediamtx, ively-agent (device provisioned)"
else
  # Fresh install: provision UI for setup; streaming stack also enabled (idle until configured)
  systemctl enable ively-provision.service
  echo "Enabled for boot: mediamtx, ively-agent, ively-provision (awaiting setup)"
fi

# Optional meta-target (enables grouping; mediamtx+agent enabled directly too)
systemctl enable ively-edge.target 2>/dev/null || true

systemctl daemon-reload
echo "Services will start automatically on next reboot."
