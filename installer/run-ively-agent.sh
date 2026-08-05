#!/bin/bash
# Start ively-agent with venv Python when available (has all requirements including psutil).
set -e
cd /opt/ively/edge
export PYTHONPATH=/opt/ively/edge
export IVELY_RTSP_STREAM_PROFILE="${IVELY_RTSP_STREAM_PROFILE:-sub}"
export IVELY_SUBSTREAM_ONLY="${IVELY_SUBSTREAM_ONLY:-1}"
export IVELY_RTSP_PROBE_URLS="${IVELY_RTSP_PROBE_URLS:-1}"

if [ -x /opt/ively/venv/bin/python3 ]; then
  exec /opt/ively/venv/bin/python3 -m agent.main
fi
exec /usr/bin/python3 -m agent.main
