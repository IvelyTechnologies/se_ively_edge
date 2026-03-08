#!/bin/bash
# Ively SmartEye™ Edge — install using a dedicated venv (optional, for dependency isolation)
# Run as root on the device. Use this if you prefer venv over system-wide pip.
set -e

# Bold cyan banner — aligned box, prominent size (top/mid/bottom same width)
_banner() {
  local B='\033[1m'
  local C='\033[36m'
  local R='\033[0m'
  local msg="$1"
  local fill_width=56
  local content_width=53
  local line pad
  line=$(printf '═%.0s' $(seq 1 "$fill_width"))
  pad=$(printf '%*s' $((content_width - ${#msg})) '')
  echo ""
  echo ""
  echo -e "${C}${B}  ╔${line}╗${R}"
  echo -e "${C}${B}  ║  ${msg}${pad}  ║${R}"
  echo -e "${C}${B}  ╚${line}╝${R}"
  echo ""
  echo ""
}

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo bash install-with-venv.sh"
  exit 1
fi

_banner "Ively SmartEye™ Edge Installer (with venv)"

apt update -y
apt install -y curl git python3 python3-pip python3-venv ffmpeg jq avahi-daemon

mkdir -p /opt/ively

if [ ! -d "/opt/ively/edge" ]; then
  git clone https://github.com/IvelyTechnologies/se_ively_edge.git /opt/ively/edge
else
  (cd /opt/ively/edge && git fetch && git reset --hard origin/main)
fi

cd /opt/ively/edge

# Create venv and install dependencies
python3 -m venv /opt/ively/venv
/opt/ively/venv/bin/pip install --upgrade pip
/opt/ively/venv/bin/pip install -r requirements.txt

bash installer/base_install.sh

# Override systemd services to use venv Python
PYVENV="/opt/ively/venv/bin/python3"
sed "s|/usr/bin/python3|$PYVENV|g" services/ively-agent.service > /etc/systemd/system/ively-agent.service
cat > /etc/systemd/system/ively-provision.service << EOF
[Unit]
Description=Ively SmartEye™ Provision UI
After=network.target

[Service]
WorkingDirectory=/opt/ively/edge/provision-ui
Environment="PATH=/opt/ively/venv/bin:/usr/local/bin:/usr/bin"
ExecStart=$PYVENV -m uvicorn main:app --host 0.0.0.0 --port 2025
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload

systemctl daemon-reload
systemctl enable ively-provision ively-agent mediamtx
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
echo "=== Install complete (venv) ==="
echo "Python: /opt/ively/venv/bin/python3"
DEVICE_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
[ -z "$DEVICE_IP" ] && DEVICE_IP=$(ip -4 route get 1 2>/dev/null | awk '{print $7; exit}')
[ -z "$DEVICE_IP" ] && DEVICE_IP="<device-ip>"
echo "Open http://edge.local or http://${DEVICE_IP}:2025 to provision."
echo "After setup, stream viewer: http://${DEVICE_IP}:8080/view"
echo "If connection fails: (1) sudo journalctl -u ively-provision -n 40 --no-pager  (2) sudo ufw allow 2025/tcp"
