"""RF Tactical Monitor - SDR Worker Thread

Connects to HackRF via SoapySDR, reads IQ samples, computes FFT,
and emits waterfall rows via Qt signals.
"""

import numpy as np
import SoapySDR
from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_CF32

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot, QMutex, QMutexLocker


class SDRWorker(QObject):
    """Worker that reads IQ from HackRF and emits FFT magnitude rows.

    Signals:
        new_waterfall_row(np.ndarray): Emitted with float32 dB magnitude array.
        error_occurred(str): Emitted when an error occurs (e.g., device not found).
        device_connected(str): Emitted with device info string on successful connect.
        device_disconnected(): Emitted when device is closed.

    Args:
        center_freq: Initial center frequency in Hz.
        sample_rate: Initial sample rate in Hz.
        gain_lna: LNA gain (0–40 dB in 8 dB steps).
        gain_vga: VGA gain (0–62 dB in 2 dB steps).
        fft_size: Number of FFT bins.
        fft_avg_count: Number of FFTs to average per output row.
    """

    new_waterfall_row = pyqtSignal(object)
    error_occurred = pyqtSignal(str)
    device_connected = pyqtSignal(str)
    device_disconnected = pyqtSignal()

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

        self._running = False
        self._mutex = QMutex()
        self._sdr = None
        self._stream = None

        self._window = np.hanning(self._fft_size).astype(np.float32)
        self._iq_buffer = np.zeros(self._fft_size, dtype=np.complex64)
        self._power_accum = np.zeros(self._fft_size, dtype=np.float64)

    def _open_device(self) -> bool:
        """Open HackRF via SoapySDR and configure parameters."""
        try:
            results = SoapySDR.Device.enumerate("driver=hackrf")
            if len(results) == 0:
                self.error_occurred.emit("HackRF not found — no SoapySDR devices detected")
                return False

            self._sdr = SoapySDR.Device(dict(driver="hackrf"))

            self._sdr.setSampleRate(SOAPY_SDR_RX, 0, self._sample_rate)
            self._sdr.setFrequency(SOAPY_SDR_RX, 0, self._center_freq)
            self._sdr.setGain(SOAPY_SDR_RX, 0, "LNA", self._gain_lna)
            self._sdr.setGain(SOAPY_SDR_RX, 0, "VGA", self._gain_vga)
            self._sdr.setAntenna(SOAPY_SDR_RX, 0, "TX/RX")

            self._stream = self._sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32, [0])
            self._sdr.activateStream(self._stream)

            info_str = (
                f"HackRF connected — "
                f"{self._center_freq / 1e6:.3f} MHz, "
                f"{self._sample_rate / 1e6:.1f} Msps, "
                f"LNA={self._gain_lna} VGA={self._gain_vga}"
            )
            self.device_connected.emit(info_str)
            return True

        except Exception as exc:
            self.error_occurred.emit(f"HackRF open failed: {exc}")
            self._sdr = None
            self._stream = None
            return False

    def _close_device(self):
        """Deactivate stream and close the SoapySDR device."""
        if self._sdr is not None and self._stream is not None:
            try:
                self._sdr.deactivateStream(self._stream)
                self._sdr.closeStream(self._stream)
            except Exception:
                pass
            self._stream = None

        if self._sdr is not None:
            try:
                self._sdr = None
            except Exception:
                pass

        self.device_disconnected.emit()

    def _read_iq_block(self) -> bool:
        """Read one FFT-sized block of IQ samples into the buffer.

        Returns:
            True if a full block was read, False on error.
        """
        samples_needed = self._fft_size
        offset = 0

        while offset < samples_needed:
            remaining = samples_needed - offset
            sr = self._sdr.readStream(
                self._stream,
                [self._iq_buffer[offset:]],
                remaining,
                timeoutUs=500000,
            )
            ret_code = sr.ret

            if ret_code < 0:
                self.error_occurred.emit(f"readStream error: {SoapySDR.errToStr(ret_code)}")
                return False

            if ret_code == 0:
                continue

            offset += ret_code

        return True

    def _compute_fft_db(self) -> np.ndarray:
        """Apply window, compute FFT, return magnitude in dB as float32."""
        windowed = self._iq_buffer * self._window
        spectrum = np.fft.fftshift(np.fft.fft(windowed))
        power = np.real(spectrum * np.conj(spectrum))
        return power

    @pyqtSlot()
    def start_capture(self):
        """Begin the IQ capture and FFT processing loop."""
        with QMutexLocker(self._mutex):
            if self._running:
                return
            self._running = True

        if not self._open_device():
            with QMutexLocker(self._mutex):
                self._running = False
            return

        while True:
            with QMutexLocker(self._mutex):
                if not self._running:
                    break

            self._power_accum.fill(0.0)
            avg_ok = True

            for _ in range(self._fft_avg_count):
                with QMutexLocker(self._mutex):
                    if not self._running:
                        avg_ok = False
                        break

                if not self._read_iq_block():
                    avg_ok = False
                    break

                self._power_accum += self._compute_fft_db()

            if not avg_ok:
                break

            avg_power = self._power_accum / self._fft_avg_count
            magnitude_db = 10.0 * np.log10(avg_power + 1e-10)
            self.new_waterfall_row.emit(magnitude_db.astype(np.float32))

        self._close_device()

    @pyqtSlot()
    def stop_capture(self):
        """Signal the capture loop to stop."""
        with QMutexLocker(self._mutex):
            self._running = False

    @pyqtSlot(float, float)
    def retune(self, center_freq: float, sample_rate: float):
        """Change center frequency and sample rate without restarting.

        Args:
            center_freq: New center frequency in Hz.
            sample_rate: New sample rate in Hz.
        """
        with QMutexLocker(self._mutex):
            self._center_freq = center_freq
            self._sample_rate = sample_rate

        if self._sdr is not None:
            try:
                self._sdr.setFrequency(SOAPY_SDR_RX, 0, center_freq)
                self._sdr.setSampleRate(SOAPY_SDR_RX, 0, sample_rate)
            except Exception as exc:
                self.error_occurred.emit(f"Retune failed: {exc}")

    @pyqtSlot(int, int)
    def set_gains(self, gain_lna: int, gain_vga: int):
        """Update LNA and VGA gains live.

        Args:
            gain_lna: LNA gain in dB.
            gain_vga: VGA gain in dB.
        """
        with QMutexLocker(self._mutex):
            self._gain_lna = gain_lna
            self._gain_vga = gain_vga

        if self._sdr is not None:
            try:
                self._sdr.setGain(SOAPY_SDR_RX, 0, "LNA", gain_lna)
                self._sdr.setGain(SOAPY_SDR_RX, 0, "VGA", gain_vga)
            except Exception as exc:
                self.error_occurred.emit(f"Gain change failed: {exc}")

    @property
    def is_running(self) -> bool:
        """Whether the capture loop is currently active."""
        with QMutexLocker(self._mutex):
            return self._running
