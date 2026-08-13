import threading
import time
import unittest
from unittest.mock import patch

from agent.camera.camera_worker import CameraWorker, CameraWorkerManager
from agent.camera.freeze_detector import StreamFreezeDetector, StreamStatus
from agent.camera.stream_recovery import recover_streams


class FreezeDetectorTests(unittest.TestCase):
    def test_zero_bitrate_does_not_stall_fresh_frames(self):
        with patch("agent.camera.freeze_detector.time.monotonic", return_value=0.0):
            detector = StreamFreezeDetector(
                "cam1",
                expected_fps=10.0,
                freeze_timeout_sec=20.0,
                zero_bitrate_grace_sec=30.0,
            )

        with patch("agent.camera.freeze_detector.time.monotonic", return_value=31.0):
            detector.feed_ffmpeg_line("frame=472")
            detector.feed_ffmpeg_line("fps=10.2")
            detector.feed_ffmpeg_line("bitrate=N/A")

        with patch("agent.camera.freeze_detector.time.monotonic", return_value=32.0):
            self.assertFalse(detector.is_zero_bitrate())
            self.assertEqual(StreamStatus.OK, detector.get_status())
            self.assertFalse(detector.needs_restart())

    def test_missing_frame_progress_still_freezes(self):
        with patch("agent.camera.freeze_detector.time.monotonic", return_value=0.0):
            detector = StreamFreezeDetector("cam1", freeze_timeout_sec=20.0)
        with patch("agent.camera.freeze_detector.time.monotonic", return_value=31.0):
            self.assertEqual(StreamStatus.FROZEN, detector.get_status())
            self.assertTrue(detector.needs_restart())


class _Worker:
    is_running = True


class _RecoveryManager:
    def __init__(self):
        self.worker = _Worker()
        self.restart_calls = 0

    def health_check_all(self, ready_paths=None):
        return {}

    def get_worker(self, name):
        return self.worker

    def restart_worker(self, name):
        self.restart_calls += 1
        return True


class RecoveryTests(unittest.TestCase):
    @patch("agent.camera.stream_recovery.fetch_mediamtx_ready", return_value={"cam1": False})
    @patch("agent.camera.stream_recovery.load_stream_paths", return_value=["cam1"])
    def test_is_running_property_is_not_called(self, _paths, _ready):
        manager = _RecoveryManager()
        result = recover_streams(manager)
        self.assertEqual(0, manager.restart_calls)
        self.assertTrue(any("not ready" in action for action in result["actions"]))


class RecoverySerializationTests(unittest.TestCase):
    def test_recovery_calls_are_serialized(self):
        started = threading.Event()
        release = threading.Event()
        calls = []

        def slow_recovery(*_args, **_kwargs):
            calls.append(True)
            started.set()
            release.wait(timeout=1)
            return {"actions": ["completed"], "paths": ["cam1"], "ready": {}}

        with patch("agent.camera.stream_recovery._recover_streams", side_effect=slow_recovery):
            first = threading.Thread(target=lambda: recover_streams(_RecoveryManager()))
            first.start()
            self.assertTrue(started.wait(timeout=1))
            second = recover_streams(_RecoveryManager())
            release.set()
            first.join(timeout=1)

        self.assertEqual(["recovery already in progress"], second["actions"])
        self.assertEqual(1, len(calls))


class WorkerReaderOwnershipTests(unittest.TestCase):
    def test_old_reader_cannot_stop_restarted_worker(self):
        class Process:
            stderr = []

        worker = CameraWorker("cam1", "ffmpeg")
        old_process = Process()
        new_process = Process()
        worker._process = new_process
        worker._running = True

        worker._read_stderr(old_process)

        self.assertTrue(worker._running)
        self.assertIs(worker._process, new_process)


class HealthCheckSerializationTests(unittest.TestCase):
    def test_health_checks_do_not_overlap(self):
        manager = CameraWorkerManager()
        active = 0
        max_active = 0
        state_lock = threading.Lock()

        def locked_check(ready_paths=None):
            nonlocal active, max_active
            with state_lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.03)
            with state_lock:
                active -= 1
            return {}

        manager._health_check_all_locked = locked_check
        threads = [threading.Thread(target=manager.health_check_all) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(1, max_active)


if __name__ == "__main__":
    unittest.main()
