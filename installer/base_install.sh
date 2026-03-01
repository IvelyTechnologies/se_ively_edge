#!/bin/bash

mkdir -p /opt/ively/mediamtx
mkdir -p /recordings

wget -qO /tmp/mediamtx.tar.gz \
https://github.com/bluenviron/mediamtx/releases/latest/download/mediamtx_linux_amd64.tar.gz

tar -xzf /tmp/mediamtx.tar.gz -C /opt/ively
mv /opt/ively/mediamtx* /opt/ively/mediamtx

cp services/*.service /etc/systemd/system/

systemctl daemon-reload
