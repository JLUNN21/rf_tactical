"""RF Tactical Monitor - SDR Manager

Manages the QThread lifecycle for the SDRWorker, providing
start/stop/retune controls from the main GUI thread.
"""

from PyQt5.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from radio.sdr_worker import SDRWorker


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
    capture_started = pyqtSignal()
    capture_stopped = pyqtSignal()

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

    def _setup_worker(self):
        """Create the worker and thread, wire up signals."""
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

        self._thread.started.connect(self._worker.start_capture)
        self._thread.finished.connect(self._on_thread_finished)

    def _on_device_disconnected(self):
        """Handle worker signaling device closed — stop the thread."""
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

    @pyqtSlot()
    def start(self):
        """Start SDR capture on a new thread."""
        if self._thread is not None and self._thread.isRunning():
            return

        self._setup_worker()
        self._thread.start()
        self.capture_started.emit()

    @pyqtSlot()
    def stop(self):
        """Stop SDR capture and shut down the thread."""
        if self._worker is not None:
            self._worker.stop_capture()

        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(5000)

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

    @property
    def is_running(self) -> bool:
        """Whether the SDR capture is currently active."""
        if self._thread is not None and self._thread.isRunning():
            return True
        return False

    @property
    def center_freq(self) -> float:
        """Current center frequency in Hz."""
        return self._center_freq

    @property
    def sample_rate(self) -> float:
        """Current sample rate in Hz."""
        return self._sample_rate

    def shutdown(self):
        """Forcefully stop and clean up all resources."""
        self.stop()
        if self._thread is not None:
            if self._thread.isRunning():
                self._thread.terminate()
                self._thread.wait(2000)
            self._thread = None
        self._worker = None
