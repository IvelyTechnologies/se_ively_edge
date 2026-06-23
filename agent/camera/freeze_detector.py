# freeze detector — real stream health monitoring beyond simple ffprobe reachability
#
# Tracks per-camera: frame timestamps, FPS, bitrate, packet counts.
# Detects: frozen frames, stalled decoder, zero bitrate, low FPS.

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class StreamStatus(Enum):
    OK = "ok"
    STARTING = "starting"
    DEGRADED = "degraded"
    FROZEN = "frozen"
    STALLED = "stalled"
    STOPPED = "stopped"


@dataclass
class StreamDiagnostics:
    """Snapshot of stream health metrics."""
    status: StreamStatus = StreamStatus.STARTING
    actual_fps: float = 0.0
    expected_fps: float = 8.0
    bitrate_kbps: float = 0.0
    frames_total: int = 0
    last_frame_time: float = 0.0
    uptime_sec: float = 0.0
    error_count: int = 0
    last_error: str = ""


# Regex patterns for parsing FFmpeg stderr progress lines
# FFmpeg stderr: frame=  123 fps= 8.0 ... bitrate= 300.5kbits/s ...
_RE_FRAME = re.compile(r"frame=\s*(\d+)")
_RE_FPS = re.compile(r"fps=\s*([\d.]+)")
_RE_BITRATE = re.compile(r"bitrate=\s*([\d.]+)\s*kbits/s")
# FFmpeg error/warning lines
_RE_ERROR = re.compile(r"(error|failed|refused|timeout|broken|reset by peer)", re.IGNORECASE)


class StreamFreezeDetector:
    """
    Detect frozen / stalled streams by tracking FFmpeg progress output.

    Usage:
        detector = StreamFreezeDetector("cam1_low", expected_fps=8)
        # In the FFmpeg stderr reader loop:
        detector.feed_ffmpeg_line(line)
        # In the health check loop:
        if detector.is_frozen():
            restart_worker()
    """

    def __init__(
        self,
        stream_name: str,
        expected_fps: float = 8.0,
        freeze_timeout_sec: float = 20.0,
        min_fps_ratio: float = 0.3,
        zero_bitrate_grace_sec: float = 30.0,
    ):
        self.stream_name = stream_name
        self.expected_fps = expected_fps
        self.freeze_timeout_sec = freeze_timeout_sec
        self.min_fps_ratio = min_fps_ratio
        self.zero_bitrate_grace_sec = zero_bitrate_grace_sec

        self._start_time: float = time.monotonic()
        self._last_frame_count: int = 0
        self._last_frame_time: float = time.monotonic()
        self._current_fps: float = 0.0
        self._current_bitrate: float = 0.0
        self._total_frames: int = 0
        self._error_count: int = 0
        self._last_error: str = ""
        self._last_progress_time: float = time.monotonic()

    def reset(self) -> None:
        """Reset detector state (e.g. after a worker restart)."""
        now = time.monotonic()
        self._start_time = now
        self._last_frame_count = 0
        self._last_frame_time = now
        self._current_fps = 0.0
        self._current_bitrate = 0.0
        self._total_frames = 0
        self._error_count = 0
        self._last_error = ""
        self._last_progress_time = now

    @property
    def uptime(self) -> float:
        return time.monotonic() - self._start_time

    def feed_ffmpeg_line(self, line: str) -> None:
        """
        Parse a single line from FFmpeg stderr and update internal state.
        Typical progress line:
          frame=  150 fps= 8.0 q=28.0 size=   1024kB time=00:00:18.75
          bitrate= 300.5kbits/s dup=0 drop=0 speed=1.00x
        """
        if not line:
            return

        now = time.monotonic()

        # Parse frame count
        m = _RE_FRAME.search(line)
        if m:
            new_count = int(m.group(1))
            if new_count > self._last_frame_count:
                self._last_frame_count = new_count
                self._last_frame_time = now
                self._total_frames = new_count
            self._last_progress_time = now

        # Parse FPS
        m = _RE_FPS.search(line)
        if m:
            self._current_fps = float(m.group(1))

        # Parse bitrate
        m = _RE_BITRATE.search(line)
        if m:
            self._current_bitrate = float(m.group(1))

        # Track errors
        if _RE_ERROR.search(line):
            self._error_count += 1
            self._last_error = line.strip()[:200]

    def is_frozen(self) -> bool:
        """
        True if no new frames have been produced for longer than freeze_timeout_sec.
        Ignores the first freeze_timeout_sec of uptime (startup grace period).
        """
        if self.uptime < self.freeze_timeout_sec:
            return False  # still starting up
        elapsed = time.monotonic() - self._last_frame_time
        return elapsed > self.freeze_timeout_sec

    def is_low_fps(self) -> bool:
        """True if actual FPS is below min_fps_ratio of expected FPS."""
        if self.uptime < self.freeze_timeout_sec:
            return False  # startup grace
        if self._current_fps <= 0:
            return self._total_frames > 0  # had frames then stopped
        return self._current_fps < (self.expected_fps * self.min_fps_ratio)

    def is_zero_bitrate(self) -> bool:
        """True if bitrate has been zero for longer than grace period."""
        if self.uptime < self.zero_bitrate_grace_sec:
            return False
        return self._current_bitrate <= 0 and self._total_frames > 0

    def is_stalled(self) -> bool:
        """
        True if FFmpeg has stopped producing any progress output.
        Different from frozen: FFmpeg may not be outputting progress at all
        (e.g. process hung, decoder stalled).
        """
        if self.uptime < self.freeze_timeout_sec:
            return False
        return (time.monotonic() - self._last_progress_time) > self.freeze_timeout_sec * 1.5

    def get_status(self) -> StreamStatus:
        """Return current stream health status."""
        if self.uptime < self.freeze_timeout_sec:
            return StreamStatus.STARTING
        if self.is_frozen() or self.is_stalled():
            return StreamStatus.FROZEN
        if self.is_zero_bitrate():
            return StreamStatus.STALLED
        if self.is_low_fps():
            return StreamStatus.DEGRADED
        return StreamStatus.OK

    def needs_restart(self) -> bool:
        """True if the stream is unhealthy enough to warrant a worker restart."""
        status = self.get_status()
        return status in (StreamStatus.FROZEN, StreamStatus.STALLED)

    def get_diagnostics(self) -> StreamDiagnostics:
        """Return full health snapshot for metrics / dashboard."""
        return StreamDiagnostics(
            status=self.get_status(),
            actual_fps=self._current_fps,
            expected_fps=self.expected_fps,
            bitrate_kbps=self._current_bitrate,
            frames_total=self._total_frames,
            last_frame_time=self._last_frame_time,
            uptime_sec=self.uptime,
            error_count=self._error_count,
            last_error=self._last_error,
        )
