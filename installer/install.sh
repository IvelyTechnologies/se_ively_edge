#!/bin/bash
# Ively SmartEye™ Edge — one-click installer
# Run as root on the device (e.g. MINI PC). Do not run inside a venv.
set -e

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo bash install.sh"
  exit 1
fi

echo "=== Ively SmartEye™ Edge Installer ==="

# Prerequisites
apt update -y
apt install -y curl git python3 python3-pip python3-venv ffmpeg jq avahi-daemon

mkdir -p /opt/ively

# Clone or update repo
if [ ! -d "/opt/ively/edge" ]; then
  git clone https://github.com/IvelyTechnologies/se_ively_edge.git /opt/ively/edge
else
  (cd /opt/ively/edge && git fetch && git reset --hard origin/main)
fi

cd /opt/ively/edge

# Install Python dependencies (system-wide; recommended for edge devices)
pip3 install -r requirements.txt || pip3 install --break-system-packages -r requirements.txt

# MediaMTX + systemd units
bash installer/base_install.sh

# Start provisioning UI (user completes setup in browser)
systemctl daemon-reload
systemctl enable ively-provision
systemctl start ively-provision

# Allow port 2025 so the provision UI is reachable from other machines
if command -v ufw >/dev/null 2>&1; then
  ufw allow 2025/tcp 2>/dev/null || true
fi

# Give uvicorn a moment to bind
sleep 3
if ! ss -tlnp 2>/dev/null | grep -q ':2025 '; then
  echo "WARNING: Port 2025 may not be listening. Check: systemctl status ively-provision"
fi

echo ""
echo "=== Install complete ==="
DEVICE_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
[ -z "$DEVICE_IP" ] && DEVICE_IP=$(ip -4 route get 1 2>/dev/null | awk '{print $7; exit}')
[ -z "$DEVICE_IP" ] && DEVICE_IP="<this-device-ip>"
echo "1. Open http://edge.local or http://${DEVICE_IP}:2025"
echo "2. Enter Cloud URL, Customer, Site, camera credentials, then Start Setup"
echo "3. After provisioning, streams: http://edge.local:2025/view"
echo "If connection fails: sudo systemctl status ively-provision  &&  sudo ufw allow 2025/tcp"
