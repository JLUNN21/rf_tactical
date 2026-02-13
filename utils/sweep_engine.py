"""RF Tactical Monitor - Wideband Sweep Engine

Wideband spectrum sweep using hackrf_sweep subprocess, inspired by
QSpectrumAnalyzer's hackrf_sweep backend and hackrf_sweeper's ZeroMQ pattern.

Provides:
- Wideband sweep from 1 MHz to 6 GHz using hackrf_sweep binary
- Binary output parsing (QSpectrumAnalyzer format)
- Per-frequency running statistics (min/max/avg from hackrf_signal_detector)
- Frequency scanner with squelch (HackRfDiags concept)
- Signal activity detection across the full spectrum

This runs hackrf_sweep as a subprocess and parses its binary output,
which is much faster than doing individual tunes with SoapySDR.
"""

import struct
import subprocess
import threading
import time
import numpy as np
from collections import deque
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Callable
import logging


@dataclass
class SweepBin:
    """Per-frequency bin statistics (from hackrf_signal_detector pattern)."""
    frequency_hz: float
    last_power_db: float = -120.0
    min_power_db: float = 200.0
    max_power_db: float = -200.0
    avg_power_db: float = -120.0
    history: deque = field(default_factory=lambda: deque(maxlen=50))

    def update(self, power_db: float) -> None:
        self.last_power_db = power_db
        self.min_power_db = min(self.min_power_db, power_db)
        self.max_power_db = max(self.max_power_db, power_db)
        self.history.append(power_db)
        self.avg_power_db = sum(self.history) / len(self.history)


@dataclass
class SweepResult:
    """Result of one complete sweep."""
    frequencies_hz: np.ndarray
    powers_db: np.ndarray
    timestamp: float
    sweep_time_sec: float
    num_bins: int


@dataclass
class ScannerChannel:
    """A channel in the frequency scanner."""
    frequency_hz: float
    label: str = ""
    squelch_db: float = -60.0
    active: bool = False
    last_power_db: float = -120.0


class SweepEngine:
    """Wideband spectrum sweep using hackrf_sweep.

    From QSpectrumAnalyzer hackrf_sweep backend:
    - Launches hackrf_sweep as subprocess
    - Parses binary output format (record_length + low_edge + high_edge + float32 data)
    - Assembles complete sweeps from partial records
    - Tracks per-frequency statistics

    From hackrf_signal_detector:
    - Running min/max/average per frequency bin
    - Baseline comparison for anomaly detection

    Args:
        start_freq_mhz: Sweep start frequency in MHz.
        stop_freq_mhz: Sweep stop frequency in MHz.
        bin_size_khz: FFT bin size in kHz (3-5000).
        lna_gain: LNA gain (0-40 dB).
        vga_gain: VGA gain (0-62 dB).
        executable: Path to hackrf_sweep binary.
    """

    def __init__(
        self,
        start_freq_mhz: float = 1,
        stop_freq_mhz: float = 6000,
        bin_size_khz: float = 1000,
        lna_gain: int = 32,
        vga_gain: int = 40,
        executable: str = "hackrf_sweep",
    ):
        self._start_freq_mhz = start_freq_mhz
        self._stop_freq_mhz = stop_freq_mhz
        self._bin_size_khz = max(3, min(5000, bin_size_khz))
        self._lna_gain = lna_gain
        self._vga_gain = vga_gain
        self._executable = executable

        self._process: Optional[subprocess.Popen] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._logger = logging.getLogger(__name__)

        # Per-frequency statistics (hackrf_signal_detector pattern)
        self._bins: Dict[int, SweepBin] = {}

        # Sweep assembly buffer
        self._sweep_buffer_x: List[float] = []
        self._sweep_buffer_y: List[float] = []
        self._last_sweep_time = 0.0
        self._sweep_count = 0

        # Callbacks
        self._on_sweep_complete: Optional[Callable[[SweepResult], None]] = None
        self._on_activity_detected: Optional[Callable[[float, float, float], None]] = None

        # Baseline for anomaly detection
        self._baseline: Optional[Dict[int, float]] = None
        self._anomaly_threshold_db = 6.0

        # Scanner channels
        self._scanner_channels: List[ScannerChannel] = []

    def start(self, on_sweep: Optional[Callable] = None, on_activity: Optional[Callable] = None) -> bool:
        """Start the sweep engine.

        Args:
            on_sweep: Callback(SweepResult) called on each complete sweep.
            on_activity: Callback(freq_hz, power_db, excess_db) for anomalies.

        Returns:
            True if started successfully.
        """
        if self._running:
            return False

        self._on_sweep_complete = on_sweep
        self._on_activity_detected = on_activity

        # Distribute gain between LNA and VGA
        # (from QSpectrumAnalyzer hackrf_sweep backend)
        lna = min(self._lna_gain, 40)
        lna = 8 * (lna // 8)  # Round to 8 dB steps
        vga = min(self._vga_gain, 62)
        vga = 2 * (vga // 2)  # Round to 2 dB steps

        cmd = [
            self._executable,
            "-f", f"{int(self._start_freq_mhz)}:{int(self._stop_freq_mhz)}",
            "-B",  # Binary output
            "-w", str(int(self._bin_size_khz * 1000)),
            "-l", str(lna),
            "-g", str(vga),
        ]

        self._logger.info("Starting sweep: %s", " ".join(cmd))

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except FileNotFoundError:
            self._logger.error("hackrf_sweep not found at: %s", self._executable)
            return False
        except Exception as e:
            self._logger.error("Failed to start hackrf_sweep: %s", e)
            return False

        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        """Stop the sweep engine."""
        self._running = False
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=3)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None

        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def _read_loop(self) -> None:
        """Main read loop for hackrf_sweep binary output.

        From QSpectrumAnalyzer hackrf_sweep backend:
        Binary format: [4-byte record_length][record_length bytes of data]
        Record data: [8-byte low_edge_hz][8-byte high_edge_hz][float32 power values...]
        """
        while self._running and self._process:
            try:
                # Read record length (4 bytes, uint32)
                header = self._process.stdout.read(4)
                if not header or len(header) < 4:
                    break

                record_length = struct.unpack('I', header)[0]

                # Read record data
                data = self._process.stdout.read(record_length)
                if not data or len(data) < record_length:
                    break

                self._parse_record(data)

            except Exception as e:
                if self._running:
                    self._logger.error("Sweep read error: %s", e)
                break

        self._running = False
        self._logger.info("Sweep engine stopped (sweeps: %d)", self._sweep_count)

    def _parse_record(self, data: bytes) -> None:
        """Parse one binary record from hackrf_sweep.

        From QSpectrumAnalyzer parse_output:
        - First 16 bytes: low_edge (uint64) + high_edge (uint64)
        - Remaining: float32 power values
        """
        if len(data) < 16:
            return

        low_edge, high_edge = struct.unpack('QQ', data[:16])
        powers = np.frombuffer(data[16:], dtype='<f4')

        if len(powers) == 0:
            return

        step = (high_edge - low_edge) / len(powers)

        # Check if this is the start of a new sweep
        start_freq_hz = self._start_freq_mhz * 1e6
        if low_edge <= start_freq_hz:
            # New sweep - process previous if we have data
            if self._sweep_buffer_x:
                self._complete_sweep()
            self._sweep_buffer_x = []
            self._sweep_buffer_y = []

        # Add this record's data to the sweep buffer
        freqs = np.arange(low_edge + step / 2, high_edge, step)
        for i, freq in enumerate(freqs):
            if i < len(powers):
                self._sweep_buffer_x.append(float(freq))
                self._sweep_buffer_y.append(float(powers[i]))

                # Update per-frequency statistics
                freq_key = int(freq)
                if freq_key not in self._bins:
                    self._bins[freq_key] = SweepBin(frequency_hz=float(freq))
                self._bins[freq_key].update(float(powers[i]))

        # Check if sweep is complete
        stop_freq_hz = self._stop_freq_mhz * 1e6
        if high_edge >= stop_freq_hz:
            self._complete_sweep()

    def _complete_sweep(self) -> None:
        """Process a completed sweep."""
        if not self._sweep_buffer_x:
            return

        now = time.time()
        sweep_time = now - self._last_sweep_time if self._last_sweep_time > 0 else 0
        self._last_sweep_time = now
        self._sweep_count += 1

        # Sort by frequency
        sorted_data = sorted(zip(self._sweep_buffer_x, self._sweep_buffer_y))
        freqs, powers = zip(*sorted_data)

        result = SweepResult(
            frequencies_hz=np.array(freqs),
            powers_db=np.array(powers),
            timestamp=now,
            sweep_time_sec=sweep_time,
            num_bins=len(freqs),
        )

        # Check for anomalies against baseline
        if self._baseline and self._on_activity_detected:
            for freq, power in zip(freqs, powers):
                freq_key = int(freq)
                if freq_key in self._baseline:
                    excess = power - self._baseline[freq_key]
                    if excess > self._anomaly_threshold_db:
                        self._on_activity_detected(freq, power, excess)

        # Update scanner channels
        self._update_scanner(freqs, powers)

        # Emit callback
        if self._on_sweep_complete:
            self._on_sweep_complete(result)

        self._sweep_buffer_x = []
        self._sweep_buffer_y = []

    # ── Baseline Management ─────────────────────────────────────

    def capture_baseline(self, num_sweeps: int = 10) -> Dict[int, float]:
        """Capture baseline by averaging multiple sweeps.

        Returns:
            Dictionary of frequency_hz -> average_power_db.
        """
        self._baseline = {}
        for freq_key, bin_data in self._bins.items():
            if bin_data.history:
                self._baseline[freq_key] = bin_data.avg_power_db
        self._logger.info("Baseline captured: %d frequency bins", len(self._baseline))
        return self._baseline.copy()

    def clear_baseline(self) -> None:
        """Clear the baseline."""
        self._baseline = None

    # ── Frequency Scanner (HackRfDiags concept) ─────────────────

    def add_scanner_channel(self, freq_hz: float, label: str = "", squelch_db: float = -60.0) -> None:
        """Add a channel to the frequency scanner."""
        self._scanner_channels.append(ScannerChannel(
            frequency_hz=freq_hz,
            label=label or f"{freq_hz/1e6:.3f} MHz",
            squelch_db=squelch_db,
        ))

    def clear_scanner_channels(self) -> None:
        """Clear all scanner channels."""
        self._scanner_channels.clear()

    def get_scanner_status(self) -> List[Dict]:
        """Get current scanner channel status."""
        return [
            {
                "frequency_hz": ch.frequency_hz,
                "label": ch.label,
                "squelch_db": ch.squelch_db,
                "active": ch.active,
                "last_power_db": ch.last_power_db,
            }
            for ch in self._scanner_channels
        ]

    def _update_scanner(self, freqs, powers) -> None:
        """Update scanner channels with latest sweep data."""
        for channel in self._scanner_channels:
            # Find closest frequency bin
            target = channel.frequency_hz
            closest_idx = min(range(len(freqs)), key=lambda i: abs(freqs[i] - target))
            power = powers[closest_idx]
            channel.last_power_db = power
            channel.active = power > channel.squelch_db

    # ── Accessors ───────────────────────────────────────────────

    def get_bin_stats(self) -> Dict[int, Dict]:
        """Get per-frequency bin statistics."""
        return {
            freq: {
                "frequency_hz": b.frequency_hz,
                "last_db": b.last_power_db,
                "min_db": b.min_power_db,
                "max_db": b.max_power_db,
                "avg_db": b.avg_power_db,
            }
            for freq, b in self._bins.items()
        }

    def get_top_signals(self, n: int = 20) -> List[Dict]:
        """Get top N strongest signals by last power."""
        sorted_bins = sorted(self._bins.values(), key=lambda b: b.last_power_db, reverse=True)
        return [
            {
                "frequency_hz": b.frequency_hz,
                "frequency_mhz": b.frequency_hz / 1e6,
                "power_db": b.last_power_db,
                "max_db": b.max_power_db,
                "avg_db": b.avg_power_db,
            }
            for b in sorted_bins[:n]
        ]

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def sweep_count(self) -> int:
        return self._sweep_count

    @property
    def num_bins(self) -> int:
        return len(self._bins)

    def reset_stats(self) -> None:
        """Reset all per-frequency statistics."""
        self._bins.clear()
        self._sweep_count = 0
