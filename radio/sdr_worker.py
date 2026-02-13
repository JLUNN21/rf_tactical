"""RF Tactical Monitor - SDR Worker Thread

Connects to HackRF via SoapySDR, reads IQ samples, computes FFT,
and emits waterfall rows via Qt signals.
"""

import time
import numpy as np

try:
    import SoapySDR
    from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_TX, SOAPY_SDR_CF32, SOAPY_SDR_OVERFLOW
    SDR_AVAILABLE = True
except Exception:
    SoapySDR = None
    SOAPY_SDR_RX = None
    SOAPY_SDR_TX = None
    SOAPY_SDR_CF32 = None
    SOAPY_SDR_OVERFLOW = None
    SDR_AVAILABLE = False

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot, QMutex, QMutexLocker

from radio.iq_recorder import IQRecorder
from utils.signal_detector import SignalDetector
from utils.signal_detector_v2 import SignalDetectorV2
from utils.spectrum_analyzer import SpectrumAnalyzer
from utils.tx_signal_generator import TxSignalGenerator, TxSignalParams, TxMode
from utils.flow_tracer import get_flow_tracer

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
        gain_lna: LNA gain (0-40 dB in 8 dB steps).
        gain_vga: VGA gain (0-62 dB in 2 dB steps).
        fft_size: Number of FFT bins.
        fft_avg_count: Number of FFTs to average per output row.
    """

    new_waterfall_row = pyqtSignal(object)
    spectrum_stats_updated = pyqtSignal(object)   # SpectrumStats from analyzer
    signal_event_detected = pyqtSignal(object)    # SignalEvent from V2 detector
    signal_event_closed = pyqtSignal(object)      # Closed SignalEvent with features
    error_occurred = pyqtSignal(str)
    device_connected = pyqtSignal(str)
    device_disconnected = pyqtSignal()
    connection_status = pyqtSignal(str, float)
    recording_status = pyqtSignal(object)
    overflow_count_updated = pyqtSignal(int)
    signal_detected = pyqtSignal(dict)
    tx_progress = pyqtSignal(float)  # 0.0 to 1.0
    tx_complete = pyqtSignal()
    tx_error = pyqtSignal(str)

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
        self._signal_detector = SignalDetector(
            sample_rate=self._sample_rate,
            threshold_db=10,  # 10 dB above noise floor (lowered from 15 for better sensitivity)
            min_duration_sec=0.0001,  # 0.1ms minimum (200 samples at 2 Msps)
            max_duration_sec=0.05  # 50ms maximum
        )
        self._samples_processed = 0
        self._last_detector_log = 0.0
        self._logger = setup_logger(__name__)
        self._tx_stream = None
        self._tx_active = False

        # V2 signal detection pipeline (RFwatch-inspired)
        self._detector_v2 = SignalDetectorV2(
            sample_rate=self._sample_rate,
            fft_size=self._fft_size,
            snr_enter_db=8.0,
            snr_exit_db=4.0,
            bw_threshold_db=6.0,
            max_misses=10,
        )

        # Spectrum analyzer with peak detection, averaging, baseline
        self._spectrum_analyzer = SpectrumAnalyzer(
            fft_size=self._fft_size,
            sample_rate=self._sample_rate,
            window="hanning",
            history_size=50,
        )

    def _open_device(self) -> bool:
        """Open HackRF device via SoapySDR."""
        if not SDR_AVAILABLE:
            self._logger.error("Cannot open device - SoapySDR not available")
            self.error_occurred.emit("SDR OFFLINE")
            self.connection_status.emit("DISCONNECTED", 0.0)
            return False

        try:
            self._logger.info("Opening HackRF device...")
            
            # First enumerate to find the device
            results = SoapySDR.Device.enumerate("driver=hackrf")
            if not results:
                raise RuntimeError("No HackRF devices found during enumeration")
            
            self._logger.info("Found %d HackRF device(s), opening first one", len(results))
            self._logger.info("Device info: %s", results[0])
            
            # Open using the enumeration result
            self._sdr = SoapySDR.Device(results[0])
            return self._configure_device()
        except Exception as exc:
            error_msg = f"Failed to open HackRF: {exc}"
            self._logger.error(error_msg)
            self.error_occurred.emit(error_msg)
            self.connection_status.emit("ERROR", 0.0)
            self._sdr = None
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
                f"HackRF connected -- "
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
        flow = get_flow_tracer()
        flow.enter("ISM", "_read_iq_block", fft_size=self._fft_size)
        
        try:
            samples_needed = self._fft_size
            offset = 0
            
            flow.step("ISM", f"Reading {samples_needed} IQ samples from HackRF")

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
                        flow.warning("ISM", f"Buffer overflow (count: {self._overflow_count})")
                        continue
                    error_msg = SoapySDR.errToStr(ret_code)
                    flow.fail("ISM", f"readStream error: {error_msg}")
                    self._logger.error("readStream error: %s", error_msg)
                    self.error_occurred.emit(f"readStream error: {error_msg}")
                    flow.exit("ISM", "_read_iq_block", "FAILED")
                    return False

                if ret_code == 0:
                    continue

                offset += ret_code
            
            flow.success("ISM", f"Read {offset} samples successfully")

            # Always process samples for signal detection
            flow.step("ISM", "Calling SignalDetector.process_samples()")
            valid_samples = self._iq_buffer[:offset].copy()
            
            try:
                detected = self._signal_detector.process_samples(valid_samples)
                flow.success("ISM", f"Signal detection complete (found {len(detected)} signals)")
            except Exception as e:
                flow.fail("ISM", f"Signal detection failed: {e}")
                detected = []
            
            # Log noise floor every 5 seconds for debugging (time-based)
            now = time.time()
            if now - self._last_detector_log >= 5.0:
                self._last_detector_log = now
                flow.data("ISM", "noise_floor", f"{self._signal_detector.noise_floor_db:.1f} dBm")
                flow.data("ISM", "threshold", f"+{self._signal_detector.threshold_db:.1f} dB")
                flow.data("ISM", "absolute_threshold", f"{self._signal_detector.noise_floor_db + self._signal_detector.threshold_db:.1f} dBm")
                self._logger.info(" Signal Detector: noise_floor=%.1f dBm, threshold=+%.1f dB, absolute_threshold=%.1f dBm",
                                self._signal_detector.noise_floor_db,
                                self._signal_detector.threshold_db,
                                self._signal_detector.noise_floor_db + self._signal_detector.threshold_db)
            
            if detected:
                for sig in detected:
                    timestamp = self._samples_processed / self._sample_rate
                    freq_hz = self._center_freq + sig["center_freq_offset_hz"]
                    
                    flow.success("ISM", f"Signal found: {freq_hz/1e6:.3f} MHz @ {sig['peak_power_dbm']:.1f} dBm")
                    
                    # Log signal detection
                    self._logger.info(" SIGNAL DETECTED: %.3f MHz @ %.1f dBm (duration: %.3fs)",
                                    freq_hz / 1e6, sig["peak_power_dbm"], sig["duration_sec"])
                    
                    # Emit signal detection event
                    self.signal_detected.emit(
                        {
                            "timestamp": timestamp,
                            "frequency": freq_hz,
                            "center_freq_hz": freq_hz,
                            "power": sig["peak_power_dbm"],
                            "peak_power_dbm": sig["peak_power_dbm"],
                            "duration": sig["duration_sec"],
                            "duration_sec": sig["duration_sec"],
                            "bandwidth_hz": sig.get("bandwidth_hz", 50000),
                        }
                    )
                    
                    # If recording, also mark in recording file
                    if self._recorder.recording:
                        self._recorder.mark_signal_event(
                            freq_hz=freq_hz,
                            power_dbm=sig["peak_power_dbm"],
                            duration_sec=sig["duration_sec"],
                        )
            
            # ── V2 Signal Detection Pipeline (RFwatch-inspired) ──
            try:
                v2_result = self._detector_v2.process_chunk(valid_samples)
                
                # Emit active events
                for evt in v2_result.get("active_events", []):
                    self.signal_event_detected.emit(evt)
                
                # Emit closed events (with extracted features)
                for evt in v2_result.get("closed_events", []):
                    self.signal_event_closed.emit(evt)
                    self._logger.info(
                        " Signal event closed: %s | center=%.3f MHz | dur=%.3fs | hits=%d",
                        evt.id,
                        evt.last_center / 1e6 if evt.last_center else 0,
                        evt.duration_sec,
                        evt.hit_count,
                    )
            except Exception as e:
                flow.warning("ISM", f"V2 detector error: {e}")

            # If recording, write samples to file
            if self._recorder.recording:
                self._recorder.write_samples(valid_samples)

            self._samples_processed += offset
            
            flow.exit("ISM", "_read_iq_block", "SUCCESS")
            return True
            
        except Exception as e:
            flow.fail("ISM", f"Unexpected error: {e}")
            flow.exit("ISM", "_read_iq_block", "FAILED")
            return False

    def _compute_fft_db(self) -> np.ndarray:
        """Apply window, compute FFT, return power in linear scale."""
        windowed = self._iq_buffer * self._window
        spectrum = np.fft.fftshift(np.fft.fft(windowed))
        # Normalize by FFT size to get proper power scaling
        power = (np.abs(spectrum) ** 2) / (self._fft_size ** 2)
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
            
            # ── Spectrum Analyzer: update stats, peak detection, baseline ──
            try:
                stats = self._spectrum_analyzer.update(magnitude_db)
                self.spectrum_stats_updated.emit(stats)
            except Exception:
                pass
            
            # Debug: Log min/max values occasionally
            if self._samples_processed % (self._sample_rate * 2) < self._fft_size:  # Every ~2 seconds
                self._logger.debug("FFT dB range: min=%.1f, max=%.1f, mean=%.1f", 
                                 np.min(magnitude_db), np.max(magnitude_db), np.mean(magnitude_db))
            
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
            self._detector_v2.set_sample_rate(sample_rate)
            self._spectrum_analyzer.set_sample_rate(sample_rate)

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

    # ── Spectrum Analyzer & V2 Detector API ─────────────────────

    @property
    def spectrum_analyzer(self) -> SpectrumAnalyzer:
        """Access the spectrum analyzer for peak hold, average, baseline."""
        return self._spectrum_analyzer

    @property
    def detector_v2(self) -> SignalDetectorV2:
        """Access the V2 signal detector for event tracking."""
        return self._detector_v2

    def start_baseline_capture(self):
        """Start capturing baseline spectrum for anomaly detection."""
        self._spectrum_analyzer.start_baseline_capture()
        self._logger.info(" Baseline capture started")

    def finish_baseline_capture(self):
        """Finish baseline capture and return the baseline."""
        baseline = self._spectrum_analyzer.finish_baseline_capture()
        if baseline is not None:
            self._logger.info(" Baseline captured (%d bins)", len(baseline))
        return baseline

    def clear_baseline(self):
        """Clear the baseline spectrum."""
        self._spectrum_analyzer.clear_baseline()

    def reset_peak_hold(self):
        """Reset peak hold max/min in the spectrum analyzer."""
        self._spectrum_analyzer.reset_peak_hold()

    def set_fft_window(self, window_name: str):
        """Change the FFT window function (hanning, hamming, blackman, etc.)."""
        self._spectrum_analyzer.set_window(window_name)
        self._logger.info(" FFT window changed to: %s", window_name)

    def set_v2_thresholds(self, snr_enter_db: float, snr_exit_db: float):
        """Update V2 detector SNR thresholds."""
        self._detector_v2.set_thresholds(snr_enter_db, snr_exit_db)

    def get_v2_statistics(self) -> dict:
        """Get V2 detector statistics."""
        return self._detector_v2.get_statistics()

    @property
    def is_running(self) -> bool:
        """Whether the capture loop is currently active."""
        with QMutexLocker(self._mutex):
            return self._running
    
    def generate_and_transmit(
        self,
        mode: str,
        center_freq: float,
        duration_sec: float = 1.0,
        sample_rate: float = 2e6,
        tx_gain: int = 30,
        **kwargs,
    ):
        """Generate a signal and transmit it in one call.

        Convenience method that uses TxSignalGenerator to create IQ samples
        and then transmits them via HackRF.

        Args:
            mode: TX mode string (e.g. 'fm', 'am', 'noise', 'chirp', 'morse',
                  'barrage_jam', 'spot_jam', 'sweep_jam', etc.)
            center_freq: TX center frequency in Hz.
            duration_sec: Signal duration in seconds.
            sample_rate: Sample rate in Hz.
            tx_gain: TX VGA gain 0-47 dB.
            **kwargs: Additional params passed to TxSignalParams.
        """
        try:
            tx_mode = TxMode(mode)
        except ValueError:
            self.tx_error.emit(f"Unknown TX mode: {mode}")
            return

        params = TxSignalParams(
            mode=tx_mode,
            sample_rate=sample_rate,
            duration_sec=duration_sec,
            **kwargs,
        )

        valid, err = TxSignalGenerator.validate_params(params)
        if not valid:
            self.tx_error.emit(f"Invalid TX params: {err}")
            return

        gen = TxSignalGenerator()
        iq = gen.generate(params)
        self.transmit_signal(iq, center_freq, sample_rate, tx_gain)

    def transmit_signal(self, iq_samples: np.ndarray, center_freq: float, sample_rate: float = 2e6, tx_gain: int = 30):
        """Transmit IQ samples via HackRF TX.
        
        Args:
            iq_samples: Complex IQ samples to transmit (numpy array)
            center_freq: TX frequency in Hz
            sample_rate: TX sample rate in Hz (default 2 MHz)
            tx_gain: TX VGA gain 0-47 dB (default 30 dB for safety)
        """
        if not SDR_AVAILABLE:
            self.tx_error.emit("SoapySDR not available")
            return
        
        if self._tx_active:
            self.tx_error.emit("TX already in progress")
            return
        
        self._tx_active = True
        tx_sdr = None
        tx_stream = None
        
        try:
            self._logger.info(" Starting TX: %.3f MHz, %d samples, %.3f sec",
                            center_freq / 1e6, len(iq_samples), len(iq_samples) / sample_rate)
            
            # Open a separate SDR instance for TX (don't interfere with RX)
            results = SoapySDR.Device.enumerate("driver=hackrf")
            if not results:
                raise RuntimeError("No HackRF devices found")
            
            tx_sdr = SoapySDR.Device(results[0])
            
            # Configure TX
            tx_sdr.setSampleRate(SOAPY_SDR_TX, 0, sample_rate)
            tx_sdr.setFrequency(SOAPY_SDR_TX, 0, center_freq)
            tx_sdr.setGain(SOAPY_SDR_TX, 0, "VGA", min(tx_gain, 47))  # Cap at 47 dB for safety
            tx_sdr.setAntenna(SOAPY_SDR_TX, 0, "TX/RX")
            
            # Setup TX stream
            tx_stream = tx_sdr.setupStream(SOAPY_SDR_TX, SOAPY_SDR_CF32, [0])
            if tx_stream is None:
                raise RuntimeError("Failed to setup TX stream")
            
            # Activate stream
            tx_sdr.activateStream(tx_stream)
            
            # Convert to complex64 if needed
            if iq_samples.dtype != np.complex64:
                iq_samples = iq_samples.astype(np.complex64)
            
            # Transmit in chunks
            chunk_size = 1024
            total_samples = len(iq_samples)
            samples_sent = 0
            
            while samples_sent < total_samples:
                chunk_end = min(samples_sent + chunk_size, total_samples)
                chunk = iq_samples[samples_sent:chunk_end]
                
                # Write samples to TX stream
                sr = tx_sdr.writeStream(tx_stream, [chunk], len(chunk), timeoutUs=1000000)
                
                if sr.ret < 0:
                    error_msg = SoapySDR.errToStr(sr.ret)
                    raise RuntimeError(f"writeStream error: {error_msg}")
                
                samples_sent += sr.ret
                
                # Emit progress
                progress = samples_sent / total_samples
                self.tx_progress.emit(progress)
                
                # Small delay to avoid overwhelming the device
                time.sleep(0.001)
            
            # Deactivate and close TX stream
            tx_sdr.deactivateStream(tx_stream)
            tx_sdr.closeStream(tx_stream)
            tx_stream = None
            tx_sdr = None
            
            self._logger.info("✅ TX complete: %d samples transmitted", samples_sent)
            self.tx_complete.emit()
            
        except Exception as e:
            error_msg = f"TX failed: {str(e)}"
            self._logger.error("[X] %s", error_msg)
            self.tx_error.emit(error_msg)
            
        finally:
            # Cleanup TX resources
            if tx_stream is not None and tx_sdr is not None:
                try:
                    tx_sdr.deactivateStream(tx_stream)
                    tx_sdr.closeStream(tx_stream)
                except Exception:
                    pass
            
            if tx_sdr is not None:
                try:
                    del tx_sdr
                except Exception:
                    pass
            
            self._tx_active = False
