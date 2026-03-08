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

echo ""
echo "=== Install complete ==="
echo "1. Open http://edge.local or http://<this-device-ip>:8080"
echo "2. Enter Cloud URL, Customer, Site, camera credentials, then Start Setup"
echo "3. After provisioning, streams: http://edge.local:8080/view"
