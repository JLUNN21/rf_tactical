"""RF Tactical Monitor - Cellular Scanner

Runs hackrf_sweep for a one-shot sweep, detects cellular bands, and emits results.
"""

import subprocess
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from PyQt5.QtCore import QObject, QThread, pyqtSignal, pyqtSlot, QMutex, QMutexLocker

from utils.logger import setup_logger


@dataclass(frozen=True)
class CellularBand:
    """Cellular band definition."""
    name: str
    start_hz: int
    end_hz: int
    operator: str


CELLULAR_BANDS: List[CellularBand] = [
    CellularBand("BAND 12", 729_000_000, 746_000_000, "LOW-BAND LTE"),
    CellularBand("BAND 13", 746_000_000, 756_000_000, "LOW-BAND LTE"),
    CellularBand("BAND 5", 824_000_000, 849_000_000, "LOW-BAND LTE"),
    CellularBand("BAND 4", 1_710_000_000, 1_755_000_000, "AWS-1"),
    CellularBand("BAND 66", 1_710_000_000, 1_780_000_000, "AWS-3"),
    CellularBand("BAND 2", 1_850_000_000, 1_910_000_000, "PCS"),
    CellularBand("BAND 25", 1_850_000_000, 1_915_000_000, "PCS EXT"),
    CellularBand("BAND 41", 2_496_000_000, 2_690_000_000, "BRS/EBS"),
]


class CellularScanner(QObject):
    """Cellular scanner using hackrf_sweep.

    Signals:
        bands_detected(list): List of detected bands.
        sweep_row_ready(object): FFT-like magnitude row for waterfall display.
        error_occurred(str): Emitted on scan errors.
        scanner_started(str): Emitted when scan starts.
        scanner_stopped(): Emitted when scan stops.
    """

    bands_detected = pyqtSignal(list)
    sweep_row_ready = pyqtSignal(object)
    error_occurred = pyqtSignal(str)
    scanner_started = pyqtSignal(str)
    scanner_stopped = pyqtSignal()

    def __init__(
        self,
        start_hz: int = 700_000_000,
        end_hz: int = 2_700_000_000,
        bin_hz: int = 1_000_000,
        threshold_dbm: float = -50.0,
        fft_size: int = 2048,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._start_hz = start_hz
        self._end_hz = end_hz
        self._bin_hz = bin_hz
        self._threshold_dbm = threshold_dbm
        self._fft_size = fft_size
        self._mutex = QMutex()
        self._running = False
        self._process: Optional[subprocess.Popen] = None
        self._logger = setup_logger(__name__)

    def _run_sweep(self) -> Optional[List[Tuple[float, float]]]:
        """Run hackrf_sweep and return list of (frequency_hz, power_dbm)."""
        try:
            self._process = subprocess.Popen(
                [
                    "hackrf_sweep",
                    "-f", f"{self._start_hz}:{self._end_hz}",
                    "-w", str(self._bin_hz),
                    "-1",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            points: List[Tuple[float, float]] = []
            if self._process.stdout is None:
                return None

            for line in self._process.stdout:
                with QMutexLocker(self._mutex):
                    if not self._running:
                        if self._process is not None:
                            self._process.terminate()
                        break

                parsed = self._parse_sweep_line(line)
                if parsed:
                    points.extend(parsed)

            if self._process is not None:
                self._process.wait(timeout=5)

            if self._process.returncode and self._process.returncode != 0:
                stderr = ""
                if self._process.stderr is not None:
                    stderr = self._process.stderr.read().strip()
                if stderr:
                    self._logger.error("hackrf_sweep failed: %s", stderr)
                    self.error_occurred.emit("DECODER OFFLINE")
                return None

            return points if points else None

        except FileNotFoundError:
            self._logger.error("hackrf_sweep not found")
            self.error_occurred.emit("DECODER OFFLINE")
            return None
        except Exception as exc:
            self._logger.exception("hackrf_sweep error")
            self.error_occurred.emit("DECODER OFFLINE")
            return None
        finally:
            self._process = None

    def _parse_sweep_line(self, line: str) -> List[Tuple[float, float]]:
        """Parse a hackrf_sweep CSV line into frequency/power points."""
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 7:
            return []

        start_index = 0
        try:
            if "-" in parts[0] and ":" in parts[1]:
                start_index = 2

            start_hz = float(parts[start_index])
            end_hz = float(parts[start_index + 1])
            bin_hz = float(parts[start_index + 2])
            power_values = parts[start_index + 4:]
        except (ValueError, IndexError):
            return []

        if not power_values:
            return []

        points: List[Tuple[float, float]] = []
        for idx, power_str in enumerate(power_values):
            try:
                power = float(power_str)
            except ValueError:
                continue
            freq = start_hz + (idx * bin_hz)
            if freq > end_hz:
                break
            points.append((freq, power))

        return points

    def _detect_bands(self, points: List[Tuple[float, float]]) -> List[dict]:
        """Detect cellular bands from sweep points."""
        detections: Dict[str, dict] = {}

        for freq, power in points:
            if power < self._threshold_dbm:
                continue
            for band in CELLULAR_BANDS:
                if band.start_hz <= freq <= band.end_hz:
                    entry = detections.get(band.name)
                    if entry is None:
                        entry = {
                            "band": band.name,
                            "range_hz": (band.start_hz, band.end_hz),
                            "peak_dbm": power,
                            "operator": band.operator,
                        }
                        detections[band.name] = entry
                    else:
                        if power > entry["peak_dbm"]:
                            entry["peak_dbm"] = power

        return list(detections.values())

    def _build_sweep_row(self, points: List[Tuple[float, float]]) -> List[float]:
        """Build a waterfall row for the sweep."""
        if not points:
            return [self._threshold_dbm] * self._fft_size

        freqs, powers = zip(*points)
        min_freq = min(freqs)
        max_freq = max(freqs)

        if max_freq <= min_freq:
            return [self._threshold_dbm] * self._fft_size

        step = (max_freq - min_freq) / self._fft_size
        row = []
        for idx in range(self._fft_size):
            target_freq = min_freq + idx * step
            nearest = min(points, key=lambda fp: abs(fp[0] - target_freq))
            row.append(nearest[1])
        return row

    @pyqtSlot()
    def start_scan(self) -> None:
        """Run a one-shot sweep and emit detected bands."""
        with QMutexLocker(self._mutex):
            self._running = True
        self.scanner_started.emit("CELLULAR SWEEP ACTIVE")

        points = self._run_sweep()
        if points is None:
            self.scanner_stopped.emit()
            return

        bands = self._detect_bands(points)
        self.bands_detected.emit(bands)

        row = self._build_sweep_row(points)
        self.sweep_row_ready.emit(row)

        self.scanner_stopped.emit()
        with QMutexLocker(self._mutex):
            self._running = False

    @pyqtSlot()
    def stop_scan(self) -> None:
        """Signal the sweep to stop early."""
        with QMutexLocker(self._mutex):
            self._running = False
        if self._process is not None:
            try:
                self._process.terminate()
            except Exception:
                pass


class CellularScannerManager(QObject):
    """Manage CellularScanner on a dedicated QThread."""

    bands_detected = pyqtSignal(list)
    sweep_row_ready = pyqtSignal(object)
    error_occurred = pyqtSignal(str)
    scanner_started = pyqtSignal(str)
    scanner_stopped = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._thread: Optional[QThread] = None
        self._scanner: Optional[CellularScanner] = None

    def _setup_scanner(self) -> None:
        """Create scanner and thread, wire signals."""
        self._thread = QThread()
        self._thread.setObjectName("CellularScannerThread")

        self._scanner = CellularScanner()
        self._scanner.moveToThread(self._thread)

        self._scanner.bands_detected.connect(self.bands_detected)
        self._scanner.sweep_row_ready.connect(self.sweep_row_ready)
        self._scanner.error_occurred.connect(self.error_occurred)
        self._scanner.scanner_started.connect(self.scanner_started)
        self._scanner.scanner_stopped.connect(self._on_scanner_stopped)

        self._thread.started.connect(self._scanner.start_scan)
        self._thread.finished.connect(self._on_thread_finished)

    def _on_scanner_stopped(self) -> None:
        """Handle scanner stop — stop the thread."""
        self.scanner_stopped.emit()
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()

    def _on_thread_finished(self) -> None:
        """Clean up after thread finishes."""
        if self._scanner is not None:
            self._scanner.deleteLater()
            self._scanner = None
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None

    @pyqtSlot()
    def start(self) -> None:
        """Start cellular sweep on a new thread."""
        if self._thread is not None and self._thread.isRunning():
            return

        self._setup_scanner()
        self._thread.start()

    @pyqtSlot()
    def stop(self) -> None:
        """Stop cellular sweep and shut down the thread."""
        if self._scanner is not None:
            self._scanner.stop_scan()

        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(5000)

    @property
    def is_running(self) -> bool:
        """Whether the scanner is currently active."""
        if self._thread is not None and self._thread.isRunning():
            return True
        return False

    def shutdown(self) -> None:
        """Forcefully stop and clean up resources."""
        self.stop()
        if self._thread is not None:
            if self._thread.isRunning():
                self._thread.terminate()
                self._thread.wait(2000)
            self._thread = None
        self._scanner = None