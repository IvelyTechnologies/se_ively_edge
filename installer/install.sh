#!/bin/bash
# Ively SmartEye™ Edge — one-click installer
# Run as root on the device (e.g. MINI PC). Do not run inside a venv.
set -e

# Bold cyan banner (no effect if not a TTY)
_banner() {
  local B='\033[1m'
  local C='\033[36m'
  local R='\033[0m'
  local msg="$1"
  local width=52
  local line
  line=$(printf '═%.0s' $(seq 1 "$width"))
  echo ""
  echo -e "${C}${B}  ╔${line}╗${R}"
  printf "${C}${B}  ║  %-${width}s  ║${R}\n" "$msg"
  echo -e "${C}${B}  ╚${line}╝${R}"
  echo ""
}

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo bash install.sh"
  exit 1
fi

_banner "Ively SmartEye™ Edge Installer"

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

# Allow ports: 2025 = provision UI, 8080 = agent/stream viewer
if command -v ufw >/dev/null 2>&1; then
  ufw allow 2025/tcp 2>/dev/null || true
  ufw allow 8080/tcp 2>/dev/null || true
fi

# Give uvicorn time to bind; detect crash loop
sleep 5
RESTARTS=$(systemctl show ively-provision -p NRestarts --value 2>/dev/null || echo "0")
if [ -n "$RESTARTS" ] && [ "$RESTARTS" -gt 3 ]; then
  echo "WARNING: ively-provision has restarted ${RESTARTS} times (likely crashing). Check logs:"
  echo "  sudo journalctl -u ively-provision -n 40 --no-pager"
elif ! ss -tlnp 2>/dev/null | grep -q ':2025 '; then
  echo "WARNING: Port 2025 may not be listening. Check: systemctl status ively-provision"
  echo "  sudo journalctl -u ively-provision -n 40 --no-pager"
fi

echo ""
echo "=== Install complete ==="
DEVICE_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
[ -z "$DEVICE_IP" ] && DEVICE_IP=$(ip -4 route get 1 2>/dev/null | awk '{print $7; exit}')
[ -z "$DEVICE_IP" ] && DEVICE_IP="<this-device-ip>"
echo "1. Open http://edge.local or http://${DEVICE_IP}:2025"
echo "2. Enter Cloud URL, Customer, Site, camera credentials, then Start Setup"
echo "3. After provisioning, streams: http://edge.local:8080/view"
echo "If connection fails: (1) sudo journalctl -u ively-provision -n 40 --no-pager  (2) sudo ufw allow 2025/tcp"
