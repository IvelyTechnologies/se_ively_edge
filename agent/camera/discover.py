# camera discovery — respects provisioned cams.json (manual overrides) if present

import json
import os

from agent.camera.onvif_scan import scan
from agent.camera.mediamtx_writer import generate

CAMS_JSON_PATH = "/opt/ively/agent/cams.json"


def run():
    """
    Generate mediamtx.yml from cameras.

    Priority:
      1. If cams.json exists (written by the provision UI with user-selected
         and manually-added cameras), use that as the authoritative source.
      2. Otherwise, fall back to a live ONVIF network scan.

    This prevents the watchdog's periodic re-discovery from wiping out
    manually-configured camera entries.
    """
    if os.path.exists(CAMS_JSON_PATH):
        try:
            with open(CAMS_JSON_PATH, "r", encoding="utf-8") as f:
                cams = json.load(f)
            if cams:
                generate(cams)
                print("Configured", len(cams), "cameras (from cams.json)")
                return
        except Exception as e:
            print(f"Error reading cams.json, falling back to scan: {e}")

    # Fallback: live ONVIF scan (no cams.json or it was empty/corrupt)
    cams = scan()
    generate(cams)
    print("Configured", len(cams), "cameras (from ONVIF scan)")


if __name__ == "__main__":
    run()
