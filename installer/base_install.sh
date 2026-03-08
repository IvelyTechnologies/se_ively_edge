#!/bin/bash

mkdir -p /recordings

# Download MediaMTX (retry on failure; avoid incomplete/corrupt downloads)
MEDIAMTX_TGZ="/tmp/mediamtx.tar.gz"
for i in 1 2 3; do
  wget -qO "$MEDIAMTX_TGZ" \
    "https://github.com/bluenviron/mediamtx/releases/latest/download/mediamtx_linux_amd64.tar.gz" \
    && [ -s "$MEDIAMTX_TGZ" ] && break
  echo "Download attempt $i failed or empty, retrying..."
  sleep 2
done
if ! [ -s "$MEDIAMTX_TGZ" ]; then
  echo "ERROR: Failed to download MediaMTX or file is empty."
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
