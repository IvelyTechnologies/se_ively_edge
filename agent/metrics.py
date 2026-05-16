# metrics — SQLite-based per-camera and system health database
#
# Lightweight edge metrics store: tracks FPS, bitrate, reconnects, uptime,
# CPU, memory, disk, tunnel health per 30-second interval.
# Auto-prunes records older than METRICS_RETENTION_DAYS.

import json
import os
import sqlite3
import threading
import time
from typing import Dict, List, Optional

from agent.config import METRICS_DB_PATH, METRICS_RETENTION_DAYS


_db_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None


def _get_db() -> sqlite3.Connection:
    """Get or create the SQLite connection (thread-safe singleton)."""
    global _conn
    if _conn is not None:
        return _conn

    with _db_lock:
        if _conn is not None:
            return _conn
        os.makedirs(os.path.dirname(str(METRICS_DB_PATH)), exist_ok=True)
        _conn = sqlite3.connect(str(METRICS_DB_PATH), check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA synchronous=NORMAL")
        _init_schema(_conn)
        return _conn


def _init_schema(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS camera_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            camera_name TEXT NOT NULL,
            fps REAL DEFAULT 0,
            bitrate_kbps REAL DEFAULT 0,
            reconnect_count INTEGER DEFAULT 0,
            uptime_sec REAL DEFAULT 0,
            status TEXT DEFAULT 'unknown',
            error_count INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS system_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            cpu_percent REAL DEFAULT 0,
            memory_percent REAL DEFAULT 0,
            disk_percent REAL DEFAULT 0,
            tunnel_up INTEGER DEFAULT 0,
            active_cameras INTEGER DEFAULT 0,
            total_cameras INTEGER DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_cam_ts
            ON camera_metrics(timestamp);
        CREATE INDEX IF NOT EXISTS idx_cam_name_ts
            ON camera_metrics(camera_name, timestamp);
        CREATE INDEX IF NOT EXISTS idx_sys_ts
            ON system_metrics(timestamp);
    """)
    conn.commit()


def record_camera_metrics(metrics_list: List[dict]) -> None:
    """
    Insert per-camera metrics snapshot.
    Each dict should have: camera_name, fps, bitrate_kbps, reconnect_count,
    uptime_sec, status, error_count.
    """
    if not metrics_list:
        return

    db = _get_db()
    now = time.time()
    rows = []
    for m in metrics_list:
        rows.append((
            now,
            m.get("stream_name") or m.get("camera_name", "unknown"),
            m.get("fps", 0),
            m.get("bitrate_kbps", 0),
            m.get("restart_count", 0),
            m.get("uptime_sec", 0),
            m.get("status", "unknown"),
            m.get("error_count", 0),
        ))

    with _db_lock:
        db.executemany("""
            INSERT INTO camera_metrics
                (timestamp, camera_name, fps, bitrate_kbps, reconnect_count,
                 uptime_sec, status, error_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        db.commit()


def record_system_metrics(
    cpu_percent: float = 0,
    memory_percent: float = 0,
    disk_percent: float = 0,
    tunnel_up: bool = False,
    active_cameras: int = 0,
    total_cameras: int = 0,
) -> None:
    """Insert a system metrics snapshot."""
    db = _get_db()
    now = time.time()
    with _db_lock:
        db.execute("""
            INSERT INTO system_metrics
                (timestamp, cpu_percent, memory_percent, disk_percent,
                 tunnel_up, active_cameras, total_cameras)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (now, cpu_percent, memory_percent, disk_percent,
              1 if tunnel_up else 0, active_cameras, total_cameras))
        db.commit()


def get_camera_latest(camera_name: Optional[str] = None) -> List[dict]:
    """Get the most recent metric for each camera (or a specific camera)."""
    db = _get_db()
    if camera_name:
        rows = db.execute("""
            SELECT camera_name, fps, bitrate_kbps, reconnect_count,
                   uptime_sec, status, error_count, timestamp
            FROM camera_metrics
            WHERE camera_name = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (camera_name,)).fetchall()
    else:
        rows = db.execute("""
            SELECT cm.camera_name, cm.fps, cm.bitrate_kbps, cm.reconnect_count,
                   cm.uptime_sec, cm.status, cm.error_count, cm.timestamp
            FROM camera_metrics cm
            INNER JOIN (
                SELECT camera_name, MAX(timestamp) AS max_ts
                FROM camera_metrics
                GROUP BY camera_name
            ) latest ON cm.camera_name = latest.camera_name
                     AND cm.timestamp = latest.max_ts
        """).fetchall()

    return [
        {
            "camera_name": r[0],
            "fps": r[1],
            "bitrate_kbps": r[2],
            "reconnect_count": r[3],
            "uptime_sec": r[4],
            "status": r[5],
            "error_count": r[6],
            "timestamp": r[7],
        }
        for r in rows
    ]


def get_system_latest() -> Optional[dict]:
    """Get the most recent system metrics snapshot."""
    db = _get_db()
    row = db.execute("""
        SELECT cpu_percent, memory_percent, disk_percent, tunnel_up,
               active_cameras, total_cameras, timestamp
        FROM system_metrics
        ORDER BY timestamp DESC
        LIMIT 1
    """).fetchone()
    if not row:
        return None
    return {
        "cpu_percent": row[0],
        "memory_percent": row[1],
        "disk_percent": row[2],
        "tunnel_up": bool(row[3]),
        "active_cameras": row[4],
        "total_cameras": row[5],
        "timestamp": row[6],
    }


def get_camera_history(camera_name: str, hours: int = 24) -> List[dict]:
    """Get camera metrics history for the past N hours."""
    db = _get_db()
    cutoff = time.time() - (hours * 3600)
    rows = db.execute("""
        SELECT timestamp, fps, bitrate_kbps, reconnect_count,
               uptime_sec, status, error_count
        FROM camera_metrics
        WHERE camera_name = ? AND timestamp > ?
        ORDER BY timestamp ASC
    """, (camera_name, cutoff)).fetchall()

    return [
        {
            "timestamp": r[0],
            "fps": r[1],
            "bitrate_kbps": r[2],
            "reconnect_count": r[3],
            "uptime_sec": r[4],
            "status": r[5],
            "error_count": r[6],
        }
        for r in rows
    ]


def prune_old_records() -> int:
    """Delete records older than METRICS_RETENTION_DAYS. Returns deleted count."""
    db = _get_db()
    cutoff = time.time() - (METRICS_RETENTION_DAYS * 86400)
    with _db_lock:
        c1 = db.execute("DELETE FROM camera_metrics WHERE timestamp < ?", (cutoff,))
        c2 = db.execute("DELETE FROM system_metrics WHERE timestamp < ?", (cutoff,))
        db.commit()
    total = (c1.rowcount or 0) + (c2.rowcount or 0)
    if total > 0:
        print(f"[metrics] Pruned {total} old records (>{METRICS_RETENTION_DAYS} days)")
    return total


def get_all_metrics_snapshot() -> dict:
    """Return full metrics snapshot for /metrics API endpoint."""
    return {
        "cameras": get_camera_latest(),
        "system": get_system_latest(),
        "retention_days": METRICS_RETENTION_DAYS,
    }
