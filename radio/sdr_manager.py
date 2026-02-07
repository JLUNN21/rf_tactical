"""RF Tactical Monitor - SDR Manager

Manages the QThread lifecycle for the SDRWorker, providing
start/stop/retune controls from the main GUI thread.
"""

import SoapySDR
from PyQt5.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from radio.sdr_worker import SDRWorker
from radio.iq_player import IQPlayer


class SDRManager(QObject):
    """Manages SDRWorker on a dedicated QThread.

    Provides high-level start/stop/retune interface for the GUI.
    All SoapySDR operations run on the worker thread; signals
    bridge data back to the main thread.

    Signals:
        new_waterfall_row(object): Forwarded from SDRWorker — float32 dB array.
        error_occurred(str): Forwarded from SDRWorker — error messages.
        device_connected(str): Forwarded from SDRWorker — connection info.
        device_disconnected(): Forwarded from SDRWorker — device closed.
        capture_started(): Emitted when capture begins.
        capture_stopped(): Emitted when capture ends and thread is idle.

    Args:
        center_freq: Initial center frequency in Hz.
        sample_rate: Initial sample rate in Hz.
        gain_lna: LNA gain in dB.
        gain_vga: VGA gain in dB.
        fft_size: Number of FFT bins.
        fft_avg_count: Number of FFTs to average per display row.
        parent: Optional parent QObject.
    """

    new_waterfall_row = pyqtSignal(object)
    error_occurred = pyqtSignal(str)
    device_connected = pyqtSignal(str)
    device_disconnected = pyqtSignal()
    overflow_count_updated = pyqtSignal(int)
    capture_started = pyqtSignal()
    capture_stopped = pyqtSignal()
    connection_status = pyqtSignal(str, float)
    recording_status = pyqtSignal(object)
    signal_detected = pyqtSignal(dict)
    playback_started = pyqtSignal()
    playback_progress = pyqtSignal(float)
    playback_finished = pyqtSignal()
    playback_error = pyqtSignal(str)
    connection_changed = pyqtSignal(bool)
    running_changed = pyqtSignal(bool)

    def __init__(
        self,
        center_freq: float = 433.92e6,
        sample_rate: float = 2e6,
        gain_lna: int = 32,
        gain_vga: int = 40,
        fft_size: int = 1024,
        fft_avg_count: int = 64,
        parent=None,
    ):
        super().__init__(parent)

        self._center_freq = center_freq
        self._sample_rate = sample_rate
        self._gain_lna = gain_lna
        self._gain_vga = gain_vga
        self._fft_size = fft_size
        self._fft_avg_count = fft_avg_count

        self._thread = None
        self._worker = None
        self._player = None
        self._player_thread = None
        self._is_connected = False
        self._set_connected(self._probe_device())

    def _setup_worker(self):
        """Create the worker and thread, wire up signals."""
        if not self._is_connected:
            self._set_connected(self._probe_device())
        self._thread = QThread()
        self._thread.setObjectName("SDRWorkerThread")

        self._worker = SDRWorker(
            center_freq=self._center_freq,
            sample_rate=self._sample_rate,
            gain_lna=self._gain_lna,
            gain_vga=self._gain_vga,
            fft_size=self._fft_size,
            fft_avg_count=self._fft_avg_count,
        )

        self._worker.moveToThread(self._thread)

        self._worker.new_waterfall_row.connect(self.new_waterfall_row)
        self._worker.error_occurred.connect(self.error_occurred)
        self._worker.device_connected.connect(self.device_connected)
        self._worker.device_disconnected.connect(self._on_device_disconnected)
        self._worker.overflow_count_updated.connect(self.overflow_count_updated)
        self._worker.connection_status.connect(self.connection_status)
        self._worker.recording_status.connect(self.recording_status)
        self._worker.signal_detected.connect(self.signal_detected)
        self._worker.connection_status.connect(self._on_connection_status)

        self._thread.started.connect(self._worker.start_capture)
        self._thread.finished.connect(self._on_thread_finished)

    def _on_device_disconnected(self):
        """Handle worker signaling device closed — stop the thread."""
        self._set_connected(False)
        self.device_disconnected.emit()
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()

    def _on_thread_finished(self):
        """Clean up after the thread finishes."""
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None
        self.capture_stopped.emit()
        self.running_changed.emit(False)

    @pyqtSlot()
    def start(self):
        """Start SDR capture on a new thread."""
        if self._thread is not None and self._thread.isRunning():
            return

        if not self._is_connected:
            self._set_connected(self._probe_device())
        if not self._is_connected:
            self.error_occurred.emit("HackRF not detected")
            return

        self._setup_worker()
        self._thread.start()
        self.capture_started.emit()
        self.running_changed.emit(True)

    @pyqtSlot()
    def stop(self):
        """Stop SDR capture and shut down the thread."""
        if self._worker is not None:
            self._worker.stop_capture()

        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(5000)
        self.running_changed.emit(False)

    def play_recording(self, iq_filepath, metadata):
        """Play back recording via TX (runs in separate thread)."""
        if self._player_thread is not None and self._player_thread.isRunning():
            self.playback_error.emit("Playback already in progress")
            return

        self._player = IQPlayer()
        self._player_thread = QThread()
        self._player.moveToThread(self._player_thread)

        self._player.playback_started.connect(self.playback_started)
        self._player.playback_progress.connect(self.playback_progress)
        self._player.playback_finished.connect(self._on_playback_finished)
        self._player.playback_error.connect(self._on_playback_error)

        self._player_thread.started.connect(
            lambda: self._player.play_recording(iq_filepath, metadata)
        )
        self._player_thread.start()

    def stop_playback(self):
        """Stop ongoing playback."""
        if self._player is not None:
            self._player.cancel_playback()

    @pyqtSlot(float, float)
    def retune(self, center_freq: float, sample_rate: float):
        """Change center frequency and sample rate without restarting.

        Args:
            center_freq: New center frequency in Hz.
            sample_rate: New sample rate in Hz.
        """
        self._center_freq = center_freq
        self._sample_rate = sample_rate

        if self._worker is not None:
            self._worker.retune(center_freq, sample_rate)

    @pyqtSlot(int, int)
    def set_gains(self, gain_lna: int, gain_vga: int):
        """Update LNA and VGA gains live.

        Args:
            gain_lna: LNA gain in dB.
            gain_vga: VGA gain in dB.
        """
        self._gain_lna = gain_lna
        self._gain_vga = gain_vga

        if self._worker is not None:
            self._worker.set_gains(gain_lna, gain_vga)

    def start_recording(self):
        """Start IQ recording on the worker thread."""
        if self._worker is not None:
            self._worker.start_recording(
                self._center_freq,
                self._sample_rate,
                self._gain_lna,
                self._gain_vga,
            )

    def stop_recording(self):
        """Stop IQ recording on the worker thread."""
        if self._worker is not None:
            return self._worker.stop_recording()
        return None

    def mark_signal(self, freq_hz, power_dbm, duration_sec):
        """Mark a signal event during recording."""
        if self._worker is not None:
            self._worker.mark_signal(freq_hz, power_dbm, duration_sec)

    def _on_playback_finished(self):
        self.playback_finished.emit()
        self._cleanup_player()

    def _on_playback_error(self, message: str):
        self.playback_error.emit(message)
        self._cleanup_player()

    def _cleanup_player(self):
        if self._player_thread is not None:
            self._player_thread.quit()
            self._player_thread.wait(2000)
            self._player_thread.deleteLater()
            self._player_thread = None
        if self._player is not None:
            self._player.deleteLater()
            self._player = None

    @property
    def is_running(self) -> bool:
        """Whether the SDR capture is currently active."""
        if self._thread is not None and self._thread.isRunning():
            return True
        return False

    def is_connected(self) -> bool:
        """Whether the SDR device is connected."""
        return self._is_connected

    @property
    def center_freq(self) -> float:
        """Current center frequency in Hz."""
        return self._center_freq

    @property
    def sample_rate(self) -> float:
        """Current sample rate in Hz."""
        return self._sample_rate

    def _set_connected(self, connected: bool) -> None:
        if self._is_connected == connected:
            return
        self._is_connected = connected
        self.connection_changed.emit(connected)

    def _on_connection_status(self, status: str, _sample_rate: float) -> None:
        if status in {"ACTIVE", "IDLE"}:
            self._set_connected(True)
        elif status in {"DISCONNECTED", "ERROR"}:
            self._set_connected(False)

    def _probe_device(self) -> bool:
        try:
            results = SoapySDR.Device.enumerate("driver=hackrf")
            return len(results) > 0
        except Exception:
            return False

    def shutdown(self):
        """Forcefully stop and clean up all resources."""
        self.stop_playback()
        self.stop()
        if self._thread is not None:
            if self._thread.isRunning():
                self._thread.terminate()
                self._thread.wait(2000)
            self._thread = None
        self._worker = None
