#!/bin/bash
set -e

echo "Installing Ively SmartEye™ Edge..."

apt update -y
apt install -y git python3 python3-pip ffmpeg jq avahi-daemon

mkdir -p /opt/ively

if [ ! -d "/opt/ively/edge" ]; then
  git clone https://github.com/IvelyTechnologies/se_ively_edge.git /opt/ively/edge
fi

cd /opt/ively/edge
pip3 install -r requirements.txt

bash installer/base_install.sh

systemctl enable ively-provision
systemctl start ively-provision

echo "Open http://edge.local"
