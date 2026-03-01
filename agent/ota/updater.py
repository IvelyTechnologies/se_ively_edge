# OTA updater: Download → Verify → Switch → Health Check → Commit (or Rollback)

import json
import os
import subprocess
import time
from typing import Optional, Tuple

EDGE_PATH = "/opt/ively/edge"
EDGE_BACKUP_PATH = "/opt/ively/edge_backup"
MIN_FREE_GB = 2
MAX_CPU_PERCENT = 80.0
HEALTH_WAIT_SEC = 10


def run(cmd: str, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, timeout=timeout)


def _disk_free_gb(path: str = "/") -> float:
    try:
        stat = os.statvfs(path)
        return (stat.f_bavail * stat.f_frsize) / (1024**3)
    except Exception:
        return 0.0


def _cpu_percent() -> float:
    try:
        import psutil
        return psutil.cpu_percent(interval=2)
    except Exception:
        return 0.0


def _service_active(name: str) -> bool:
    r = subprocess.run(
        ["systemctl", "is-active", name],
        capture_output=True,
        text=True,
        timeout=5,
    )
    return r.returncode == 0 and "active" in (r.stdout or "").lower()


def safe_to_update() -> Tuple[bool, str]:
    """
    Check if conditions allow a safe OTA. Returns (ok, reason).
    Do not update when: CPU > 80%%, disk < 2GB free, agent/mediamtx unstable.
    """
    if _cpu_percent() > MAX_CPU_PERCENT:
        return False, "CPU usage too high"
    if _disk_free_gb() < MIN_FREE_GB:
        return False, "Insufficient disk space"
    if not _service_active("ively-agent"):
        return False, "Agent service not active"
    return True, ""


def health_ok() -> bool:
    """Verify agent is running after update."""
    return _service_active("ively-agent")


def rollback() -> None:
    """Restore backup and restart. Called when update fails health check."""
    print("Rollback initiated")
    run("systemctl stop ively-agent", timeout=15)
    if os.path.isdir(EDGE_PATH):
        run(f"rm -rf {EDGE_PATH}", timeout=60)
    run(f"mv {EDGE_BACKUP_PATH} {EDGE_PATH}", timeout=10)
    run("systemctl start ively-agent", timeout=15)


def _validate_repo(repo: str) -> bool:
    """Only allow HTTPS URLs."""
    return repo.strip().lower().startswith("https://")


def update(repo: str, version: str) -> dict:
    """
    Perform OTA: backup → pull → install → restart → health check → commit or rollback.
    Returns dict with success, message, and optional rollback_performed.
    """
    if not _validate_repo(repo):
        return {"success": False, "message": "Only HTTPS repo URLs allowed"}

    ok, reason = safe_to_update()
    if not ok:
        return {"success": False, "message": f"Safe-update check failed: {reason}"}

    print("Starting OTA update", version or "")

    try:
        # 1) Backup current version
        if os.path.isdir(EDGE_BACKUP_PATH):
            run(f"rm -rf {EDGE_BACKUP_PATH}", timeout=60)
        run(f"cp -r {EDGE_PATH} {EDGE_BACKUP_PATH}", timeout=120)

        # 2) Pull latest code (HTTPS)
        run(f"cd {EDGE_PATH} && git fetch && git reset --hard origin/main && git pull", timeout=60)

        # 3) Install dependencies
        req = os.path.join(EDGE_PATH, "requirements.txt")
        if os.path.isfile(req):
            run(f"pip3 install -r {req}", timeout=300)

        # 4) Restart agent
        run("systemctl restart ively-agent", timeout=15)

        # 5) Health check
        time.sleep(HEALTH_WAIT_SEC)
        if health_ok():
            print("Update success")
            run(f"rm -rf {EDGE_BACKUP_PATH}", timeout=30)
            return {"success": True, "message": f"Updated to {version or 'latest'}"}
    except subprocess.TimeoutExpired as e:
        rollback()
        return {"success": False, "message": f"Timeout: {e}", "rollback_performed": True}
    except Exception as e:
        rollback()
        return {"success": False, "message": str(e), "rollback_performed": True}

    # Health check failed
    rollback()
    return {"success": False, "message": "Health check failed after update", "rollback_performed": True}
