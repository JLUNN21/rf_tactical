"""RF Tactical Monitor - SDR Worker Thread

Connects to HackRF via SoapySDR, reads IQ samples, computes FFT,
and emits waterfall rows via Qt signals.
"""

import time
import numpy as np

try:
    import SoapySDR
    from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_CF32, SOAPY_SDR_OVERFLOW
    SDR_AVAILABLE = True
except Exception:
    SoapySDR = None
    SOAPY_SDR_RX = None
    SOAPY_SDR_CF32 = None
    SOAPY_SDR_OVERFLOW = None
    SDR_AVAILABLE = False

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot, QMutex, QMutexLocker

from radio.iq_recorder import IQRecorder
from utils.signal_detector import SignalDetector

from utils.logger import setup_logger


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
    connection_status = pyqtSignal(str, float)
    recording_status = pyqtSignal(object)
    overflow_count_updated = pyqtSignal(int)
    signal_detected = pyqtSignal(dict)

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
        self._overflow_count = 0
        self._recorder = IQRecorder()
        self._last_record_status = 0.0
        self._signal_detector = SignalDetector(sample_rate=self._sample_rate)
        self._samples_processed = 0
        self._logger = setup_logger(__name__)

    def _open_device(self) -> bool:
        """Open HackRF device via SoapySDR with multiple fallback strategies."""
        if not SDR_AVAILABLE:
            self._logger.error("Cannot open device - SoapySDR not available")
            self.error_occurred.emit("SDR OFFLINE")
            self.connection_status.emit("DISCONNECTED", 0.0)
            return False

        # Try multiple strategies to open the device
        self._sdr = None
        
        # Strategy 1: Try with driver="hackrf"
        self._logger.info("Strategy 1: Opening with driver='hackrf'")
        try:
            self._sdr = SoapySDR.Device(dict(driver="hackrf"))
            if self._sdr is not None:
                self._logger.info("[OK] Strategy 1 succeeded")
                return self._configure_device()
        except Exception as e:
            self._logger.warning("Strategy 1 failed: %s", e)
            self._sdr = None
        
        # Strategy 2: Try with driver="hackrf" and enumerate to get serial
        self._logger.info("Strategy 2: Enumerating to find device with serial number")
        try:
            results = SoapySDR.Device.enumerate("driver=hackrf")
            if results:
                self._logger.info("Found %d HackRF device(s) via enumeration", len(results))
                # Try first device with full args
                device_args = results[0]
                self._logger.info("Trying to open with args: %s", device_args)
                self._sdr = SoapySDR.Device(device_args)
                if self._sdr is not None:
                    self._logger.info("[OK] Strategy 2 succeeded")
                    return self._configure_device()
        except Exception as e:
            self._logger.warning("Strategy 2 failed: %s", e)
            self._sdr = None
        
        # Strategy 3: Try with empty args (let SoapySDR auto-detect)
        self._logger.info("Strategy 3: Opening with empty args (auto-detect)")
        try:
            self._sdr = SoapySDR.Device()
            if self._sdr is not None:
                self._logger.info("[OK] Strategy 3 succeeded")
                return self._configure_device()
        except Exception as e:
            self._logger.warning("Strategy 3 failed: %s", e)
            self._sdr = None
        
        # All strategies failed
        error_msg = "Failed to open HackRF with all strategies"
        self._logger.error(error_msg)
        self._logger.error("Possible causes:")
        self._logger.error("  1. Device is in use by another program (SDR#, GQRX, etc.)")
        self._logger.error("  2. USB driver is incorrect - use Zadig to install WinUSB driver")
        self._logger.error("  3. Insufficient USB permissions")
        self._logger.error("  4. Device is not properly connected")
        self.error_occurred.emit("Failed to open HackRF: " + error_msg)
        self.connection_status.emit("ERROR", 0.0)
        return False

    def _configure_device(self) -> bool:
        """Configure the opened SDR device."""
        try:
            self._logger.info("Configuring SDR device...")
            self._logger.info("  Center freq: %.3f MHz", self._center_freq / 1e6)
            self._logger.info("  Sample rate: %.3f MSPS", self._sample_rate / 1e6)
            self._logger.info("  LNA gain: %d dB", self._gain_lna)
            self._logger.info("  VGA gain: %d dB", self._gain_vga)
            
            self._sdr.setSampleRate(SOAPY_SDR_RX, 0, self._sample_rate)
            self._sdr.setFrequency(SOAPY_SDR_RX, 0, self._center_freq)
            self._sdr.setGain(SOAPY_SDR_RX, 0, "LNA", self._gain_lna)
            self._sdr.setGain(SOAPY_SDR_RX, 0, "VGA", self._gain_vga)
            self._sdr.setAntenna(SOAPY_SDR_RX, 0, "TX/RX")

            self._stream = self._sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32, [0])
            if self._stream is None:
                raise RuntimeError("Failed to setup RX stream")

            self._sdr.activateStream(self._stream)

            info_str = (
                f"HackRF connected — "
                f"{self._center_freq / 1e6:.3f} MHz, "
                f"{self._sample_rate / 1e6:.1f} Msps, "
                f"LNA={self._gain_lna} VGA={self._gain_vga}"
            )
            self.device_connected.emit(info_str)
            self.connection_status.emit("IDLE", self._sample_rate)
            self._logger.info("HackRF device opened successfully")
            return True

        except Exception as exc:
            error_msg = f"Failed to open HackRF: {exc}"
            self._logger.error(error_msg)
            self.error_occurred.emit(error_msg)
            self.connection_status.emit("ERROR", 0.0)

            if self._stream is not None and self._sdr is not None:
                try:
                    self._sdr.closeStream(self._stream)
                except Exception:
                    pass
            self._stream = None
            self._sdr = None
            return False

    def _close_device(self):
        """Deactivate stream and close the SoapySDR device."""
        if self._sdr is not None and self._stream is not None:
            try:
                self._sdr.deactivateStream(self._stream)
                self._sdr.closeStream(self._stream)
            except Exception:
                self._logger.exception("SDR stream close failed")
                pass
            self._stream = None

        if self._sdr is not None:
            try:
                self._sdr = None
            except Exception:
                pass

        self.device_disconnected.emit()
        self.connection_status.emit("DISCONNECTED", 0.0)

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
                if ret_code == SOAPY_SDR_OVERFLOW:
                    self._overflow_count += 1
                    self.overflow_count_updated.emit(self._overflow_count)
                    continue
                self._logger.error("readStream error: %s", SoapySDR.errToStr(ret_code))
                self.error_occurred.emit(f"readStream error: {SoapySDR.errToStr(ret_code)}")
                return False

            if ret_code == 0:
                continue

            offset += ret_code

        if self._recorder.recording:
            valid_samples = self._iq_buffer[:offset].copy()
            self._recorder.write_samples(valid_samples)
            detected = self._signal_detector.process_samples(valid_samples)
            if detected:
                for sig in detected:
                    timestamp = self._samples_processed / self._sample_rate
                    freq_hz = self._center_freq + sig["center_freq_offset_hz"]
                    self._recorder.mark_signal_event(
                        freq_hz=freq_hz,
                        power_dbm=sig["peak_power_dbm"],
                        duration_sec=sig["duration_sec"],
                    )
                    self.signal_detected.emit(
                        {
                            "timestamp": timestamp,
                            "frequency": freq_hz,
                            "power": sig["peak_power_dbm"],
                            "duration": sig["duration_sec"],
                        }
                    )

        self._samples_processed += offset

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

        self.recording_status.emit(self._recorder.get_recording_status())
        self.connection_status.emit("ACTIVE", self._sample_rate)
        self._samples_processed = 0

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

            now = time.time()
            if now - self._last_record_status >= 0.5:
                self._last_record_status = now
                self.recording_status.emit(self._recorder.get_recording_status())

        self._close_device()
        self.recording_status.emit(self._recorder.get_recording_status())

    @pyqtSlot()
    def stop_capture(self):
        """Signal the capture loop to stop."""
        with QMutexLocker(self._mutex):
            self._running = False
        self.recording_status.emit(self._recorder.get_recording_status())

    def start_recording(self, center_freq, sample_rate, gain_lna, gain_vga):
        """Start IQ recording."""
        self._recorder.start_recording(center_freq, sample_rate, gain_lna, gain_vga)
        self.recording_status.emit(self._recorder.get_recording_status())

    def stop_recording(self):
        """Stop IQ recording."""
        paths = self._recorder.stop_recording()
        self.recording_status.emit(self._recorder.get_recording_status())
        return paths

    def mark_signal(self, freq_hz, power_dbm, duration_sec):
        """Mark a signal event during recording."""
        self._recorder.mark_signal_event(freq_hz, power_dbm, duration_sec)

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
            self._signal_detector.set_sample_rate(sample_rate)

        if self._sdr is not None:
            try:
                self._sdr.setFrequency(SOAPY_SDR_RX, 0, center_freq)
                self._sdr.setSampleRate(SOAPY_SDR_RX, 0, sample_rate)
            except Exception as exc:
                self._logger.exception("Retune failed")
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
                self._logger.exception("Gain change failed")
                self.error_occurred.emit(f"Gain change failed: {exc}")

    def set_signal_threshold(self, threshold_db):
        """Update the signal detection threshold."""
        self._signal_detector.set_threshold(threshold_db)

    @property
    def is_running(self) -> bool:
        """Whether the capture loop is currently active."""
        with QMutexLocker(self._mutex):
            return self._running
