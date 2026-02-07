"""IQ playback for RF Tactical Monitor."""

import time
from pathlib import Path

import numpy as np
from PyQt5.QtCore import QObject, pyqtSignal


class IQPlayer(QObject):
    """Plays back IQ recordings via HackRF TX."""

    playback_started = pyqtSignal()
    playback_progress = pyqtSignal(float)
    playback_finished = pyqtSignal()
    playback_error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.playing = False
        self.cancel_requested = False
        self.sdr = None
        self.txStream = None

    def play_recording(self, iq_filepath, metadata):
        """Play back IQ recording via TX.

        Args:
            iq_filepath: Path to .iq file
            metadata: Recording metadata dict
        """
        if self.playing:
            self.playback_error.emit("Already playing")
            return

        try:
            self.playing = True
            self.cancel_requested = False
            self.playback_started.emit()

            iq_path = Path(iq_filepath)
            if not iq_path.exists():
                raise FileNotFoundError(f"IQ file not found: {iq_path}")

            iq_data = np.fromfile(iq_path, dtype=np.complex64)
            total_samples = len(iq_data)

            center_freq = metadata["center_freq_hz"]
            sample_rate = metadata["sample_rate_hz"]
            gain_vga = metadata["gain_vga"]

            import SoapySDR
            from SoapySDR import SOAPY_SDR_TX, SOAPY_SDR_CF32

            self.sdr = SoapySDR.Device(dict(driver="hackrf"))
            self.sdr.setSampleRate(SOAPY_SDR_TX, 0, sample_rate)
            self.sdr.setFrequency(SOAPY_SDR_TX, 0, center_freq)
            self.sdr.setGain(SOAPY_SDR_TX, 0, "VGA", gain_vga)

            self.txStream = self.sdr.setupStream(SOAPY_SDR_TX, SOAPY_SDR_CF32)
            self.sdr.activateStream(self.txStream)

            chunk_size = 16384
            samples_sent = 0

            for i in range(0, total_samples, chunk_size):
                if self.cancel_requested:
                    break

                chunk = iq_data[i : i + chunk_size]

                sr = self.sdr.writeStream(self.txStream, [chunk], len(chunk))
                if sr.ret < 0:
                    raise RuntimeError(f"TX write error: {sr.ret}")

                samples_sent += sr.ret
                progress = samples_sent / total_samples if total_samples else 1.0
                self.playback_progress.emit(progress)

                time.sleep(0.001)

            self._cleanup_stream()
            self.playing = False

            if self.cancel_requested:
                self.playback_error.emit("Playback cancelled")
            else:
                self.playback_finished.emit()

        except Exception as exc:
            self.playing = False
            self.playback_error.emit(str(exc))
            self._cleanup_stream()

    def cancel_playback(self):
        """Cancel ongoing playback."""
        self.cancel_requested = True

    def _cleanup_stream(self):
        if self.txStream and self.sdr:
            try:
                self.sdr.deactivateStream(self.txStream)
                self.sdr.closeStream(self.txStream)
            except Exception:
                pass
        self.txStream = None
        self.sdr = None