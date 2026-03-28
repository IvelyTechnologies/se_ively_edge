#!/bin/bash

mkdir -p /recordings

# ---------------------------------------------------------------------------
# Install WireGuard (secure VPN tunnel to cloud)
# ---------------------------------------------------------------------------
echo "Installing WireGuard..."
if apt install -y wireguard wireguard-tools 2>/dev/null; then
  echo "WireGuard installed successfully"
else
  echo "WARNING: WireGuard installation failed — VPN tunnel will not be available."
  echo "  You can install it later: sudo apt install -y wireguard wireguard-tools"
fi

# Enable IP forwarding (required for VPN)
if ! grep -q "^net.ipv4.ip_forward=1" /etc/sysctl.conf 2>/dev/null; then
  echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
  sysctl -w net.ipv4.ip_forward=1 2>/dev/null || true
fi

# Create WireGuard keys directory
mkdir -p /opt/ively/agent/wg_keys
chmod 700 /opt/ively/agent/wg_keys

# Download MediaMTX — resolve latest version (assets are named mediamtx_vX.Y.Z_linux_amd64.tar.gz)
MEDIAMTX_TGZ="/tmp/mediamtx.tar.gz"
MEDIAMTX_TAG=""
for i in 1 2 3; do
  if command -v curl >/dev/null 2>&1; then
    MEDIAMTX_TAG=$(curl -sL "https://api.github.com/repos/bluenviron/mediamtx/releases/latest" | grep '"tag_name"' | sed 's/.*"tag_name": *"\([^"]*\)".*/\1/')
  fi
  [ -n "$MEDIAMTX_TAG" ] && break
  echo "Resolve attempt $i failed, retrying in 2s..."
  sleep 2
done
if [ -z "$MEDIAMTX_TAG" ]; then
  echo "ERROR: Could not resolve MediaMTX latest release (check api.github.com)."
  exit 1
fi
MEDIAMTX_URL="https://github.com/bluenviron/mediamtx/releases/download/${MEDIAMTX_TAG}/mediamtx_${MEDIAMTX_TAG}_linux_amd64.tar.gz"

download_ok=
for i in 1 2 3; do
  if command -v curl >/dev/null 2>&1; then
    curl -fL -o "$MEDIAMTX_TGZ" "$MEDIAMTX_URL" 2>/dev/null && [ -s "$MEDIAMTX_TGZ" ] && download_ok=1
  else
    wget -q -O "$MEDIAMTX_TGZ" "$MEDIAMTX_URL" 2>/dev/null && [ -s "$MEDIAMTX_TGZ" ] && download_ok=1
  fi
  [ -n "$download_ok" ] && break
  echo "Download attempt $i failed or empty, retrying in 3s..."
  sleep 3
done
if ! [ -s "$MEDIAMTX_TGZ" ]; then
  echo "ERROR: Failed to download MediaMTX (file missing or empty)."
  echo "  URL: $MEDIAMTX_URL"
  echo "  Check: 1) Device can reach github.com  2) No proxy/firewall blocking"
  exit 1
fi

# Extract to /tmp then move the single top-level dir to /opt/ively/mediamtx
# (avoids "mv to subdirectory of itself" when /opt/ively/mediamtx already exists)
rm -rf /opt/ively/mediamtx
tar -xzf "$MEDIAMTX_TGZ" -C /tmp || { echo "ERROR: MediaMTX archive corrupt or invalid."; exit 1; }
EXTRACTED=$(tar -tf "$MEDIAMTX_TGZ" | head -1 | cut -d/ -f1)
if [ -z "$EXTRACTED" ]; then
  echo "ERROR: Unexpected MediaMTX archive layout."
  exit 1
fi
if [ -d "/tmp/$EXTRACTED" ]; then
  mv "/tmp/$EXTRACTED" /opt/ively/mediamtx
else
  # Tarball has no top-level dir (flat mediamtx + mediamtx.yml)
  mkdir -p /opt/ively/mediamtx
  tar -xzf "$MEDIAMTX_TGZ" -C /opt/ively/mediamtx
fi
rm -f "$MEDIAMTX_TGZ"

# Overwrite default mediamtx.yml so no placeholder hostnames (e.g. my_camera) are used
cat > /opt/ively/mediamtx/mediamtx.yml << 'MTXEOF'
webrtc: yes
webrtcAddress: :8889
webrtcICEServers:
  - urls: [stun:stun.l.google.com:19302]
sourceOnDemand: no
paths:
MTXEOF

cp services/*.service /etc/systemd/system/

systemctl daemon-reload
