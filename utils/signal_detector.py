"""Signal detector utility for RF Tactical Monitor."""

import numpy as np


class SignalDetector:
    """Detects signal bursts in IQ stream."""

    def __init__(self, threshold_db=-50, min_duration_sec=0.01, sample_rate=2e6):
        self.threshold_db = threshold_db
        self.min_duration_sec = min_duration_sec
        self.sample_rate = sample_rate
        self.min_duration_samples = int(min_duration_sec * sample_rate)

        self.in_signal = False
        self.signal_start_sample = 0
        self.signal_samples = []

    def process_samples(self, iq_samples):
        """Process IQ samples and detect signal bursts.

        Returns: list of detected signals.
        """
        if iq_samples is None or len(iq_samples) == 0:
            return []

        power = np.abs(iq_samples) ** 2
        power_db = 10 * np.log10(power + 1e-10)
        above_threshold = power_db > self.threshold_db

        detected_this_batch = []

        for i, is_signal in enumerate(above_threshold):
            if is_signal and not self.in_signal:
                self.in_signal = True
                self.signal_start_sample = i
                self.signal_samples = [iq_samples[i]]
            elif is_signal and self.in_signal:
                self.signal_samples.append(iq_samples[i])
            elif not is_signal and self.in_signal:
                self.in_signal = False

                if len(self.signal_samples) >= self.min_duration_samples:
                    signal_array = np.array(self.signal_samples)
                    peak_power = np.max(np.abs(signal_array) ** 2)
                    peak_power_db = 10 * np.log10(peak_power + 1e-10)

                    fft = np.fft.fft(signal_array)
                    fft_freqs = np.fft.fftfreq(len(signal_array), 1 / self.sample_rate)
                    center_freq_offset = fft_freqs[np.argmax(np.abs(fft))]

                    duration_sec = len(self.signal_samples) / self.sample_rate

                    detected_this_batch.append(
                        {
                            "start_sample": self.signal_start_sample,
                            "duration_sec": duration_sec,
                            "peak_power_dbm": peak_power_db,
                            "center_freq_offset_hz": center_freq_offset,
                        }
                    )

                self.signal_samples = []

        return detected_this_batch

    def set_threshold(self, threshold_db):
        """Update detection threshold."""
        self.threshold_db = threshold_db

    def set_sample_rate(self, sample_rate):
        """Update sample rate and duration thresholds."""
        self.sample_rate = sample_rate
        self.min_duration_samples = int(self.min_duration_sec * sample_rate)