# disk manager — auto cleanup when disk is full

import os
import subprocess

import psutil

RECORD = "/recordings"


def cleanup(threshold_percent: float = 85.0, delete_count: int = 10):
    """If disk usage above threshold, remove oldest files in RECORD."""
    try:
        usage = psutil.disk_usage("/").percent
    except Exception:
        return

    if usage <= threshold_percent:
        return

    print("Disk full — cleaning")

    if not os.path.isdir(RECORD):
        os.makedirs(RECORD, exist_ok=True)
        return

    try:
        files = [
            os.path.join(RECORD, f)
            for f in os.listdir(RECORD)
            if os.path.isfile(os.path.join(RECORD, f))
        ]
    except OSError:
        return

    if len(files) == 0:
        return

    files.sort(key=os.path.getctime)
    for f in files[:delete_count]:
        try:
            os.remove(f)
            print("Removed", f)
        except OSError:
            pass
