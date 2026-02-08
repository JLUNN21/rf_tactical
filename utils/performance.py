"""RF Tactical Monitor - Performance Monitoring Utilities."""

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PyQt5.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot


class PerformanceMonitor(QObject):
    """Monitor CPU, memory, temperature, FPS, and overflow counts."""

    performance_updated = pyqtSignal(dict)

    def __init__(self, poll_interval_ms: int = 1000, parent=None) -> None:
        super().__init__(parent)
        self._poll_interval_ms = poll_interval_ms
        self._timer = QTimer(self)
        self._timer.setInterval(self._poll_interval_ms)
        self._timer.timeout.connect(self._poll)

        self._last_cpu_times: Optional[Dict[str, Tuple[int, int]]] = None
        self._fps = 0.0
        self._overflow_count = 0

    def start(self) -> None:
        """Start polling performance metrics."""
        self._last_cpu_times = self._read_cpu_times()
        self._timer.start()

    def stop(self) -> None:
        """Stop polling performance metrics."""
        self._timer.stop()

    @pyqtSlot(float)
    def update_fps(self, fps: float) -> None:
        """Update latest UI FPS estimate."""
        self._fps = fps

    @pyqtSlot(int)
    def update_overflow_count(self, count: int) -> None:
        """Update SDR buffer overflow count."""
        self._overflow_count = count

    def _poll(self) -> None:
        cpu_percent, cpu_per_core = self._read_cpu_percent()
        mem_mb = self._read_memory_mb()
        temp_c = self._read_temperature()

        payload = {
            "cpu_percent": cpu_percent,
            "cpu_per_core": cpu_per_core,
            "mem_mb": mem_mb,
            "temp_c": temp_c,
            "fps": self._fps,
            "overflow_count": self._overflow_count,
        }
        self.performance_updated.emit(payload)

    def _read_cpu_times(self) -> Optional[Dict[str, Tuple[int, int]]]:
        """Read CPU times from /proc/stat.

        Returns:
            Dict mapping cpu label to (idle, total) times.
        """
        proc_stat = Path("/proc/stat")
        if sys.platform != "linux" or not proc_stat.exists():
            return None

        cpu_times: Dict[str, Tuple[int, int]] = {}
        try:
            with open(proc_stat, "r", encoding="utf-8") as fh:
                for line in fh:
                    if not line.startswith("cpu"):
                        continue
                    parts = line.split()
                    label = parts[0]
                    values = [int(v) for v in parts[1:8]]
                    if len(values) < 4:
                        continue
                    user, nice, system, idle, iowait, irq, softirq = values[:7]
                    idle_total = idle + iowait
                    total = user + nice + system + idle + iowait + irq + softirq
                    cpu_times[label] = (idle_total, total)
        except Exception:
            return None

        return cpu_times

    def _read_cpu_percent(self) -> Tuple[float, List[float]]:
        """Compute CPU usage percentages since last poll."""
        current = self._read_cpu_times()
        if current is None or self._last_cpu_times is None:
            self._last_cpu_times = current
            return 0.0, []

        def usage(prev_idle, prev_total, idle, total) -> float:
            delta_total = total - prev_total
            delta_idle = idle - prev_idle
            if delta_total <= 0:
                return 0.0
            return max(0.0, min(100.0, 100.0 * (delta_total - delta_idle) / delta_total))

        cpu_percent = 0.0
        cpu_per_core: List[float] = []

        if "cpu" in current and "cpu" in self._last_cpu_times:
            prev_idle, prev_total = self._last_cpu_times["cpu"]
            idle, total = current["cpu"]
            cpu_percent = usage(prev_idle, prev_total, idle, total)

        core_keys = sorted([k for k in current.keys() if k.startswith("cpu") and k != "cpu"])
        for key in core_keys:
            if key not in self._last_cpu_times:
                continue
            prev_idle, prev_total = self._last_cpu_times[key]
            idle, total = current[key]
            cpu_per_core.append(usage(prev_idle, prev_total, idle, total))

        self._last_cpu_times = current
        return cpu_percent, cpu_per_core

    def _read_memory_mb(self) -> Optional[int]:
        """Read memory usage in MB from /proc/meminfo."""
        meminfo = Path("/proc/meminfo")
        if sys.platform != "linux" or not meminfo.exists():
            return None

        mem_total = None
        mem_available = None
        try:
            with open(meminfo, "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("MemTotal"):
                        mem_total = int(line.split()[1])
                    elif line.startswith("MemAvailable"):
                        mem_available = int(line.split()[1])
            if mem_total is None or mem_available is None:
                return None
            used_kb = mem_total - mem_available
            return int(used_kb / 1024)
        except Exception:
            return None

    def _read_temperature(self) -> Optional[float]:
        """Read CPU temperature from the thermal zone file."""
        temp_path = Path("/sys/class/thermal/thermal_zone0/temp")
        if sys.platform != "linux" or not temp_path.exists():
            return None
        try:
            with open(temp_path, "r", encoding="utf-8") as fh:
                raw = fh.read().strip()
            value = float(raw) / 1000.0
            return value
        except Exception:
            return None