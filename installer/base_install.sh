#!/bin/bash

mkdir -p /recordings

# Download MediaMTX (retry on failure; GitHub redirects require curl -L or wget --redirect)
MEDIAMTX_URL="https://github.com/bluenviron/mediamtx/releases/latest/download/mediamtx_linux_amd64.tar.gz"
MEDIAMTX_TGZ="/tmp/mediamtx.tar.gz"
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
  echo "  Check: 1) Device can reach github.com  2) No proxy/firewall blocking"
  echo "  Manual: curl -fL -o $MEDIAMTX_TGZ $MEDIAMTX_URL"
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

cp services/*.service /etc/systemd/system/

systemctl daemon-reload
