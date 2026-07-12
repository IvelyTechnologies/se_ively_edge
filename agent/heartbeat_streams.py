"""Build per-stream heartbeat payload for cloud (EDGE-02 / Phase 4)."""
from __future__ import annotations

import time
from typing import Any


def stream_metrics_to_heartbeat_entry(name: str, metrics: dict[str, Any], mtx_ready: dict[str, bool] | None = None) -> dict:
    """Map worker metrics to EDGE_HEARTBEAT_SPEC stream object."""
    status = str(metrics.get("status") or "stopped")
    if metrics.get("pid") and mtx_ready is not None and mtx_ready.get(name) is False and status == "ok":
        status = "degraded"

    return {
        "stream_name": metrics.get("stream_name") or name,
        "status": status,
        "fps": round(float(metrics.get("fps") or 0.0), 1),
        "last_frame_age_sec": round(float(metrics.get("last_frame_age_sec") or 0.0), 1),
    }


def build_streams_from_metrics(
    metrics_by_name: dict[str, dict],
    mtx_ready: dict[str, bool] | None = None,
) -> list[dict]:
    return [
        stream_metrics_to_heartbeat_entry(name, m, mtx_ready)
        for name, m in sorted(metrics_by_name.items())
    ]
