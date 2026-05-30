# camera worker — persistent per-camera FFmpeg process manager
#
# Replaces MediaMTX runOnDemand architecture. Each camera gets its own
# long-running FFmpeg process that continuously pulls RTSP and publishes
# to MediaMTX. Independent restart, health monitoring, and cooldown per camera.

import os
import shlex
import signal
import subprocess
import threading
import time
from typing import Callable, Dict, List, Optional

from agent.camera.freeze_detector import StreamFreezeDetector, StreamStatus
from agent.config import (
    WORKER_COOLDOWN_SEC,
    WORKER_MAX_RESTARTS,
    FREEZE_TIMEOUT_SEC,
    MIN_FPS_RATIO,
    ZERO_BITRATE_GRACE_SEC,
    WORKER_HEALTH_CHECK_SEC,
)


class RestartTracker:
    """
    Track restart history and enforce cooldown to prevent restart storms.

    If a worker restarts more than MAX_RESTARTS times within COOLDOWN_WINDOW
    seconds, it is marked as in cooldown and no further restarts are allowed
    until the window expires.
    """

    def __init__(
        self,
        max_restarts: int = WORKER_MAX_RESTARTS,
        cooldown_window: float = WORKER_COOLDOWN_SEC,
    ):
        self.max_restarts = max_restarts
        self.cooldown_window = cooldown_window
        self._history: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def can_restart(self, name: str) -> bool:
        """True if the worker is allowed to restart (not in cooldown)."""
        with self._lock:
            self._prune(name)
            return len(self._history.get(name, [])) < self.max_restarts

    def record_restart(self, name: str) -> None:
        """Record a restart event."""
        with self._lock:
            self._prune(name)
            self._history.setdefault(name, []).append(time.monotonic())

    def is_in_cooldown(self, name: str) -> bool:
        """True if the worker has exhausted restart attempts."""
        return not self.can_restart(name)

    def get_unhealthy(self) -> List[str]:
        """Return names of all workers currently in cooldown."""
        with self._lock:
            result = []
            for name in list(self._history.keys()):
                self._prune(name)
                if len(self._history.get(name, [])) >= self.max_restarts:
                    result.append(name)
            return result

    def clear(self, name: str) -> None:
        """Clear restart history for a worker (e.g. after manual intervention)."""
        with self._lock:
            self._history.pop(name, None)

    def _prune(self, name: str) -> None:
        """Remove restart records older than the cooldown window."""
        cutoff = time.monotonic() - self.cooldown_window
        if name in self._history:
            self._history[name] = [t for t in self._history[name] if t > cutoff]


class CameraWorker:
    """
    Persistent FFmpeg worker for a single camera stream.

    Manages the FFmpeg subprocess lifecycle: start, stop, restart, health
    monitoring, and freeze detection. Runs FFmpeg in a background thread
    that reads stderr for progress tracking.
    """

    def __init__(
        self,
        stream_name: str,
        ffmpeg_cmd: str,
        expected_fps: float = 8.0,
        ffmpeg_cmds: Optional[List[str]] = None,
        rtsp_urls: Optional[List[str]] = None,
        restart_tracker: Optional[RestartTracker] = None,
        on_unhealthy: Optional[Callable[["CameraWorker"], None]] = None,
    ):
        self.stream_name = stream_name
        self._ffmpeg_cmds = list(ffmpeg_cmds or [ffmpeg_cmd])
        self._rtsp_urls = list(rtsp_urls or [])
        self._cmd_index = 0
        self.ffmpeg_cmd = self._ffmpeg_cmds[self._cmd_index]
        self.expected_fps = expected_fps
        self._restart_tracker = restart_tracker or RestartTracker()
        self._on_unhealthy = on_unhealthy

        self._process: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()
        self._start_time: float = 0.0
        self._last_run_uptime: float = 0.0
        self._restart_count: int = 0

        self._freeze_detector = StreamFreezeDetector(
            stream_name=stream_name,
            expected_fps=expected_fps,
            freeze_timeout_sec=FREEZE_TIMEOUT_SEC,
            min_fps_ratio=MIN_FPS_RATIO,
            zero_bitrate_grace_sec=ZERO_BITRATE_GRACE_SEC,
        )

    @property
    def is_running(self) -> bool:
        return self._running and self._process is not None and self._process.poll() is None

    @property
    def uptime(self) -> float:
        if self._start_time <= 0:
            return 0.0
        return time.monotonic() - self._start_time

    @property
    def restart_count(self) -> int:
        return self._restart_count

    def _sync_active_cmd(self) -> None:
        self.ffmpeg_cmd = self._ffmpeg_cmds[self._cmd_index]

    def _advance_rtsp_candidate(self) -> None:
        if len(self._ffmpeg_cmds) > 1:
            self._cmd_index = (self._cmd_index + 1) % len(self._ffmpeg_cmds)
            self._sync_active_cmd()

    def start(self) -> bool:
        """Launch FFmpeg subprocess. Returns True on success."""
        with self._lock:
            if self.is_running:
                return True
            self._sync_active_cmd()

            try:
                # Command is pre-resolved (publish URL + input RTSP URL).
                self._process = subprocess.Popen(
                    shlex.split(self.ffmpeg_cmd),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL,
                    preexec_fn=os.setsid if hasattr(os, "setsid") else None,
                )
            except Exception as e:
                print(f"[worker:{self.stream_name}] FFmpeg start failed: {e}")
                return False

            self._running = True
            self._start_time = time.monotonic()
            self._freeze_detector.reset()

            # Start stderr reader thread for freeze detection
            self._reader_thread = threading.Thread(
                target=self._read_stderr,
                name=f"worker-stderr-{self.stream_name}",
                daemon=True,
            )
            self._reader_thread.start()

            url_hint = ""
            if self._rtsp_urls and self._cmd_index < len(self._rtsp_urls):
                url_hint = f" input={self._rtsp_urls[self._cmd_index]}"
            elif len(self._ffmpeg_cmds) > 1:
                url_hint = f" candidate {self._cmd_index + 1}/{len(self._ffmpeg_cmds)}"
            print(
                f"[worker:{self.stream_name}] Started (PID {self._process.pid}){url_hint}"
            )
            return True

    def stop(self, timeout: float = 10.0) -> None:
        """Gracefully stop the FFmpeg process."""
        with self._lock:
            self._running = False
            proc = self._process
            self._process = None

        if proc is None:
            return

        # Graceful: send SIGTERM
        try:
            if hasattr(os, "killpg"):
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            else:
                proc.terminate()
        except (ProcessLookupError, OSError):
            pass

        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Force kill
            try:
                if hasattr(os, "killpg"):
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                else:
                    proc.kill()
            except (ProcessLookupError, OSError):
                pass
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass

        print(f"[worker:{self.stream_name}] Stopped")

    def restart(self) -> bool:
        """
        Restart the worker with cooldown protection.
        Returns True if restart was performed, False if in cooldown.
        """
        if self._restart_tracker.is_in_cooldown(self.stream_name):
            print(
                f"[worker:{self.stream_name}] In cooldown — skipping restart "
                f"(max {WORKER_MAX_RESTARTS} restarts in {WORKER_COOLDOWN_SEC}s)"
            )
            if self._on_unhealthy:
                self._on_unhealthy(self)
            return False

        self._restart_tracker.record_restart(self.stream_name)
        self._restart_count += 1

        # Try next RTSP URL when previous input failed quickly or stream froze.
        if len(self._ffmpeg_cmds) > 1:
            short_run = self._last_run_uptime > 0 and self._last_run_uptime < 30
            if short_run or not self.is_healthy():
                self._advance_rtsp_candidate()

        print(f"[worker:{self.stream_name}] Restarting (attempt #{self._restart_count})")
        self.stop()
        time.sleep(2)  # brief cooldown before restart
        return self.start()

    def is_healthy(self) -> bool:
        """Check if the worker process is alive and stream is not frozen."""
        if not self.is_running:
            return False
        return not self._freeze_detector.needs_restart()

    def get_status(self) -> StreamStatus:
        """Get the current stream status."""
        if not self.is_running:
            return StreamStatus.STOPPED
        return self._freeze_detector.get_status()

    def get_metrics(self) -> dict:
        """Return health metrics for this camera."""
        diag = self._freeze_detector.get_diagnostics()
        return {
            "stream_name": self.stream_name,
            "status": diag.status.value,
            "pid": self._process.pid if self._process else None,
            "uptime_sec": round(self.uptime, 1),
            "fps": round(diag.actual_fps, 1),
            "expected_fps": diag.expected_fps,
            "bitrate_kbps": round(diag.bitrate_kbps, 1),
            "frames_total": diag.frames_total,
            "restart_count": self._restart_count,
            "in_cooldown": self._restart_tracker.is_in_cooldown(self.stream_name),
            "error_count": diag.error_count,
            "last_error": diag.last_error,
            "rtsp_candidate": self._cmd_index + 1,
            "rtsp_candidates": len(self._ffmpeg_cmds),
            "rtsp_url": (
                self._rtsp_urls[self._cmd_index]
                if self._rtsp_urls and self._cmd_index < len(self._rtsp_urls)
                else None
            ),
        }

    def _read_stderr(self) -> None:
        """Background thread: read FFmpeg stderr for freeze detection."""
        proc = self._process
        if proc is None or proc.stderr is None:
            return

        try:
            for raw_line in proc.stderr:
                if not self._running:
                    break
                try:
                    line = raw_line.decode("utf-8", errors="replace").rstrip()
                except Exception:
                    continue
                self._freeze_detector.feed_ffmpeg_line(line)
        except Exception:
            pass
        finally:
            # Process ended — mark as not running
            if self._start_time > 0:
                self._last_run_uptime = time.monotonic() - self._start_time
            if self._running:
                print(
                    f"[worker:{self.stream_name}] FFmpeg process exited "
                    f"(ran {self._last_run_uptime:.1f}s)"
                )
                self._running = False


class CameraWorkerManager:
    """
    Manages all per-camera FFmpeg workers.

    Lifecycle:
      1. load_config() — parse mediamtx.yml or worker config to get commands
      2. start_all()   — launch all workers
      3. health_check() — periodic check, restart unhealthy workers
      4. stop_all()    — clean shutdown
    """

    def __init__(self):
        self._workers: Dict[str, CameraWorker] = {}
        self._restart_tracker = RestartTracker()
        self._lock = threading.Lock()

    @property
    def worker_count(self) -> int:
        return len(self._workers)

    def add_worker(
        self,
        stream_name: str,
        ffmpeg_cmd: str,
        expected_fps: float = 8.0,
        ffmpeg_cmds: Optional[List[str]] = None,
        rtsp_urls: Optional[List[str]] = None,
    ) -> CameraWorker:
        """Register a new camera worker."""
        worker = CameraWorker(
            stream_name=stream_name,
            ffmpeg_cmd=ffmpeg_cmd,
            expected_fps=expected_fps,
            ffmpeg_cmds=ffmpeg_cmds,
            rtsp_urls=rtsp_urls,
            restart_tracker=self._restart_tracker,
        )
        with self._lock:
            self._workers[stream_name] = worker
        return worker

    def start_all(self) -> int:
        """Start all registered workers. Returns count of successfully started."""
        started = 0
        with self._lock:
            workers = list(self._workers.values())
        for w in workers:
            if w.start():
                started += 1
            time.sleep(0.5)  # stagger starts to avoid RTSP burst
        print(f"[manager] Started {started}/{len(workers)} camera workers")
        return started

    def reload(self, configs: List[dict]) -> int:
        """
        Replace all workers with a new config list.
        Each item: {"stream_name", "ffmpeg_cmd", "expected_fps"}.
        Returns count of successfully started workers.
        """
        self.stop_all()
        with self._lock:
            self._workers.clear()

        for cfg in configs:
            self.add_worker(
                stream_name=cfg["stream_name"],
                ffmpeg_cmd=cfg["ffmpeg_cmd"],
                expected_fps=float(cfg.get("expected_fps", 8.0)),
                ffmpeg_cmds=cfg.get("ffmpeg_cmds"),
                rtsp_urls=cfg.get("rtsp_urls"),
            )
        return self.start_all()

    def stop_all(self) -> None:
        """Stop all workers gracefully."""
        with self._lock:
            workers = list(self._workers.values())
        for w in workers:
            w.stop()
        print("[manager] All camera workers stopped")

    def restart_worker(self, name: str) -> bool:
        """Restart a specific worker by stream name."""
        with self._lock:
            worker = self._workers.get(name)
        if worker is None:
            print(f"[manager] Unknown worker: {name}")
            return False
        return worker.restart()

    def force_restart_worker(self, name: str) -> bool:
        """Clear cooldown and restart one worker (escalated recovery)."""
        with self._lock:
            worker = self._workers.get(name)
        if worker is None:
            return False
        self._restart_tracker.clear(name)
        print(f"[manager] Force restart {name} (cooldown cleared)")
        worker.stop()
        time.sleep(1)
        return worker.start()

    def health_check_all(self) -> Dict[str, str]:
        """
        Check all workers. Restart unhealthy ones (with cooldown).
        Returns dict of {stream_name: status} for unhealthy streams.
        """
        unhealthy = {}
        with self._lock:
            workers = list(self._workers.items())

        for name, worker in workers:
            if not worker.is_running:
                # Process exited — restart it
                if worker.restart():
                    unhealthy[name] = "restarted"
                else:
                    unhealthy[name] = "cooldown"
            elif not worker.is_healthy():
                # Stream frozen/stalled — restart worker
                status = worker.get_status()
                print(f"[manager] {name} is {status.value} — restarting worker")
                if worker.restart():
                    unhealthy[name] = f"restarted ({status.value})"
                else:
                    unhealthy[name] = f"cooldown ({status.value})"

        return unhealthy

    def get_all_metrics(self) -> Dict[str, dict]:
        """Return metrics for all workers."""
        with self._lock:
            workers = list(self._workers.items())
        return {name: w.get_metrics() for name, w in workers}

    def get_summary(self) -> dict:
        """Return high-level summary for heartbeat."""
        metrics = self.get_all_metrics()
        total = len(metrics)
        active = sum(1 for m in metrics.values() if m["status"] not in ("stopped",))
        healthy = sum(1 for m in metrics.values() if m["status"] == "ok")
        unhealthy_list = [
            n for n, m in metrics.items() if m["status"] in ("frozen", "stalled", "stopped")
        ]
        in_cooldown = [n for n, m in metrics.items() if m.get("in_cooldown")]

        return {
            "total": total,
            "active": active,
            "healthy": healthy,
            "unhealthy": unhealthy_list,
            "in_cooldown": in_cooldown,
        }

    def get_worker(self, name: str) -> Optional[CameraWorker]:
        """Get a specific worker instance."""
        with self._lock:
            return self._workers.get(name)
