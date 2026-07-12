"""EDGE-02 — per-stream heartbeat payload tests."""
from agent.heartbeat_streams import build_streams_from_metrics, stream_metrics_to_heartbeat_entry


def test_stream_entry_maps_fields():
    entry = stream_metrics_to_heartbeat_entry(
        "site_cam1_low",
        {"stream_name": "site_cam1_low", "status": "ok", "fps": 12.3, "last_frame_age_sec": 1.5},
    )
    assert entry["stream_name"] == "site_cam1_low"
    assert entry["status"] == "ok"
    assert entry["fps"] == 12.3
    assert entry["last_frame_age_sec"] == 1.5


def test_mtx_not_ready_marks_degraded():
    entry = stream_metrics_to_heartbeat_entry(
        "cam1_low",
        {"stream_name": "cam1_low", "status": "ok", "fps": 8.0, "last_frame_age_sec": 0.5, "pid": 1234},
        mtx_ready={"cam1_low": False},
    )
    assert entry["status"] == "degraded"


def test_build_streams_sorted():
    metrics = {
        "b": {"stream_name": "b", "status": "frozen", "fps": 0, "last_frame_age_sec": 40},
        "a": {"stream_name": "a", "status": "ok", "fps": 10, "last_frame_age_sec": 1},
    }
    streams = build_streams_from_metrics(metrics)
    assert [s["stream_name"] for s in streams] == ["a", "b"]
    assert streams[1]["status"] == "frozen"
