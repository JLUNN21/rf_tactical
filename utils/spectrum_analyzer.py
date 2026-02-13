"""RF Tactical Monitor - Spectrum Analyzer

Advanced spectrum analysis with peak detection, averaging, peak hold,
and baseline comparison. Inspired by QSpectrumAnalyzer and pyspectrum.

Provides:
- Configurable FFT windowing with gain compensation
- Running average, peak hold max/min tracking
- Automatic peak detection with prominence filtering
- Baseline capture and anomaly detection
- Smoothing (Hanning, Hamming, etc.)
"""

import numpy as np
from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict


# ── Window Functions with Gain Compensation ─────────────────────

WINDOW_FUNCTIONS = {
    "hanning": {"func": np.hanning, "gain_compensation": 1.0 / 0.68},
    "hamming": {"func": np.hamming, "gain_compensation": 1.0 / 0.67},
    "blackman": {"func": np.blackman, "gain_compensation": 1.0 / 0.55},
    "bartlett": {"func": np.bartlett, "gain_compensation": 1.0 / 0.55},
    "rectangular": {"func": None, "gain_compensation": 1.0},
    "kaiser_16": {"func": lambda n: np.kaiser(n, 16), "gain_compensation": 1.0 / 0.48},
}


@dataclass
class SpectrumPeak:
    """Detected peak in the spectrum."""
    frequency_hz: float
    power_db: float
    prominence_db: float
    bandwidth_hz: float
    bin_index: int
    snr_db: float = 0.0


@dataclass
class SpectrumStats:
    """Statistics for the current spectrum state."""
    noise_floor_db: float = -120.0
    peak_power_db: float = -120.0
    mean_power_db: float = -120.0
    num_peaks: int = 0
    peaks: List[SpectrumPeak] = field(default_factory=list)
    anomaly_bins: int = 0


class SpectrumAnalyzer:
    """Advanced spectrum analysis engine.

    Provides FFT computation with proper windowing, running statistics
    (average, peak hold, min hold), peak detection, and baseline comparison.

    Inspired by:
    - QSpectrumAnalyzer: DataStorage pattern with history buffer, peak hold, averaging
    - pyspectrum: Configurable window functions with gain compensation
    - hackrf_signal_detector: Running per-frequency averages for anomaly detection

    Args:
        fft_size: Number of FFT bins.
        sample_rate: Sample rate in Hz.
        window: Window function name (hanning, hamming, blackman, etc.).
        history_size: Number of spectra to keep in history buffer.
        avg_count: Number of FFTs to average per output row.
    """

    def __init__(
        self,
        fft_size: int = 1024,
        sample_rate: float = 2e6,
        window: str = "hanning",
        history_size: int = 50,
        avg_count: int = 1,
    ):
        self._fft_size = fft_size
        self._sample_rate = sample_rate
        self._avg_count = avg_count
        self._history_size = history_size

        # Window
        self._window_name = window
        self._window = self._build_window(window, fft_size)

        # History ring buffer (like QSpectrumAnalyzer's HistoryBuffer)
        self._history = np.full((history_size, fft_size), -120.0, dtype=np.float64)
        self._history_count = 0
        self._history_index = 0

        # Running statistics
        self._average = np.full(fft_size, -120.0, dtype=np.float64)
        self._peak_hold_max = np.full(fft_size, -200.0, dtype=np.float64)
        self._peak_hold_min = np.full(fft_size, 200.0, dtype=np.float64)
        self._update_count = 0

        # Baseline for anomaly detection (from hackrf_signal_detector pattern)
        self._baseline: Optional[np.ndarray] = None
        self._baseline_count = 0
        self._baseline_accumulator: Optional[np.ndarray] = None
        self._anomaly_threshold_db = 6.0  # dB above baseline to flag

        # Peak detection parameters
        self._peak_min_prominence_db = 6.0
        self._peak_min_distance_bins = 5
        self._peak_min_snr_db = 3.0

        # Frequency axis
        self._freq_axis = self._compute_freq_axis()

    def _build_window(self, name: str, size: int) -> np.ndarray:
        """Build window function with gain compensation."""
        name_lower = name.lower()
        if name_lower not in WINDOW_FUNCTIONS:
            name_lower = "hanning"

        winfo = WINDOW_FUNCTIONS[name_lower]
        if winfo["func"] is None:
            # Rectangular window
            return np.ones(size, dtype=np.float32)

        win = winfo["func"](size).astype(np.float32)
        win *= winfo["gain_compensation"]
        return win

    def _compute_freq_axis(self) -> np.ndarray:
        """Compute frequency axis in Hz."""
        return np.fft.fftshift(
            np.fft.fftfreq(self._fft_size, d=1.0 / self._sample_rate)
        )

    def set_window(self, name: str) -> None:
        """Change the FFT window function."""
        self._window_name = name
        self._window = self._build_window(name, self._fft_size)

    def set_fft_size(self, fft_size: int) -> None:
        """Change FFT size and reset all buffers."""
        self._fft_size = fft_size
        self._window = self._build_window(self._window_name, fft_size)
        self._freq_axis = self._compute_freq_axis()
        self.reset()

    def set_sample_rate(self, sample_rate: float) -> None:
        """Update sample rate."""
        self._sample_rate = sample_rate
        self._freq_axis = self._compute_freq_axis()

    # ── Core FFT Computation ────────────────────────────────────

    def compute_fft_db(self, iq_samples: np.ndarray) -> np.ndarray:
        """Compute FFT magnitude in dB with proper windowing.

        Uses the pyspectrum approach: window with gain compensation,
        then magnitude squared, then convert to dB with normalization.

        Args:
            iq_samples: Complex IQ samples (length must equal fft_size).

        Returns:
            Power spectrum in dB (float64 array of length fft_size).
        """
        if len(iq_samples) != self._fft_size:
            # Resize if needed
            if len(iq_samples) > self._fft_size:
                iq_samples = iq_samples[:self._fft_size]
            else:
                padded = np.zeros(self._fft_size, dtype=np.complex64)
                padded[:len(iq_samples)] = iq_samples
                iq_samples = padded

        # Apply window
        windowed = iq_samples * self._window

        # FFT and shift
        spectrum = np.fft.fftshift(np.fft.fft(windowed))

        # Magnitude squared (faster than abs() then squaring)
        mag_sq = spectrum.real ** 2 + spectrum.imag ** 2

        # Convert to dB with normalization by FFT size
        # (from pyspectrum's get_powers pattern)
        scale = self._fft_size ** 2
        power_db = 10.0 * np.log10(mag_sq / scale + 1e-20)

        return power_db

    def compute_averaged_fft_db(self, iq_block: np.ndarray) -> np.ndarray:
        """Compute averaged FFT from a larger IQ block.

        Splits the block into fft_size chunks, computes FFT for each,
        and averages in linear power domain (more accurate than dB averaging).

        Args:
            iq_block: Complex IQ samples (length should be multiple of fft_size).

        Returns:
            Averaged power spectrum in dB.
        """
        num_segments = max(1, len(iq_block) // self._fft_size)
        power_accum = np.zeros(self._fft_size, dtype=np.float64)

        for i in range(num_segments):
            start = i * self._fft_size
            end = start + self._fft_size
            segment = iq_block[start:end]

            if len(segment) < self._fft_size:
                break

            windowed = segment * self._window
            spectrum = np.fft.fftshift(np.fft.fft(windowed))
            mag_sq = spectrum.real ** 2 + spectrum.imag ** 2
            power_accum += mag_sq

        # Average in linear domain, then convert to dB
        avg_power = power_accum / num_segments
        scale = self._fft_size ** 2
        power_db = 10.0 * np.log10(avg_power / scale + 1e-20)

        return power_db

    # ── Statistics Tracking (QSpectrumAnalyzer pattern) ─────────

    def update(self, power_db: np.ndarray) -> SpectrumStats:
        """Update all running statistics with a new spectrum row.

        This follows the QSpectrumAnalyzer DataStorage pattern:
        updates history, running average, peak hold max/min.

        Args:
            power_db: New spectrum in dB (length must equal fft_size).

        Returns:
            SpectrumStats with current analysis results.
        """
        if len(power_db) != self._fft_size:
            power_db = np.interp(
                np.linspace(0, 1, self._fft_size),
                np.linspace(0, 1, len(power_db)),
                power_db,
            )

        self._update_count += 1

        # Update history ring buffer
        self._history[self._history_index] = power_db
        self._history_index = (self._history_index + 1) % self._history_size
        self._history_count = min(self._history_count + 1, self._history_size)

        # Update running average (exponential moving average)
        if self._update_count == 1:
            self._average = power_db.copy()
        else:
            alpha = 2.0 / (min(self._update_count, self._history_size) + 1)
            self._average = alpha * power_db + (1 - alpha) * self._average

        # Update peak hold max/min
        self._peak_hold_max = np.maximum(self._peak_hold_max, power_db)
        self._peak_hold_min = np.minimum(self._peak_hold_min, power_db)

        # Update baseline accumulator if capturing
        if self._baseline_accumulator is not None:
            self._baseline_accumulator += power_db
            self._baseline_count += 1

        # Compute statistics
        return self._compute_stats(power_db)

    def _compute_stats(self, power_db: np.ndarray) -> SpectrumStats:
        """Compute spectrum statistics including peak detection."""
        noise_floor = float(np.percentile(power_db, 30))
        peak_power = float(np.max(power_db))
        mean_power = float(np.mean(power_db))

        # Detect peaks
        peaks = self.detect_peaks(power_db, noise_floor)

        # Count anomaly bins (above baseline)
        anomaly_bins = 0
        if self._baseline is not None:
            diff = power_db - self._baseline
            anomaly_bins = int(np.sum(diff > self._anomaly_threshold_db))

        return SpectrumStats(
            noise_floor_db=noise_floor,
            peak_power_db=peak_power,
            mean_power_db=mean_power,
            num_peaks=len(peaks),
            peaks=peaks,
            anomaly_bins=anomaly_bins,
        )

    # ── Peak Detection ──────────────────────────────────────────

    def detect_peaks(
        self,
        power_db: np.ndarray,
        noise_floor_db: Optional[float] = None,
    ) -> List[SpectrumPeak]:
        """Detect peaks in the spectrum with prominence filtering.

        Uses a simple local maximum approach with minimum prominence
        and minimum distance constraints.

        Args:
            power_db: Power spectrum in dB.
            noise_floor_db: Noise floor estimate (auto-computed if None).

        Returns:
            List of SpectrumPeak objects sorted by power (strongest first).
        """
        if noise_floor_db is None:
            noise_floor_db = float(np.percentile(power_db, 30))

        n = len(power_db)
        min_dist = self._peak_min_distance_bins
        peaks = []

        # Find local maxima
        for i in range(min_dist, n - min_dist):
            # Check if this bin is a local maximum
            window = power_db[i - min_dist:i + min_dist + 1]
            if power_db[i] != np.max(window):
                continue

            # Calculate prominence (height above surrounding valleys)
            left_min = np.min(power_db[max(0, i - min_dist * 3):i])
            right_min = np.min(power_db[i + 1:min(n, i + min_dist * 3 + 1)])
            prominence = power_db[i] - max(left_min, right_min)

            if prominence < self._peak_min_prominence_db:
                continue

            # Calculate SNR
            snr = power_db[i] - noise_floor_db
            if snr < self._peak_min_snr_db:
                continue

            # Estimate bandwidth (-3dB width)
            half_power = power_db[i] - 3.0
            bw_bins = 0
            for j in range(i, min(n, i + min_dist * 5)):
                if power_db[j] < half_power:
                    break
                bw_bins += 1
            for j in range(i, max(0, i - min_dist * 5), -1):
                if power_db[j] < half_power:
                    break
                bw_bins += 1

            bin_hz = self._sample_rate / self._fft_size
            bandwidth_hz = bw_bins * bin_hz
            frequency_hz = self._freq_axis[i]

            peaks.append(SpectrumPeak(
                frequency_hz=frequency_hz,
                power_db=float(power_db[i]),
                prominence_db=float(prominence),
                bandwidth_hz=bandwidth_hz,
                bin_index=i,
                snr_db=float(snr),
            ))

        # Sort by power (strongest first)
        peaks.sort(key=lambda p: p.power_db, reverse=True)
        return peaks[:20]  # Limit to top 20 peaks

    # ── Baseline Management (hackrf_signal_detector pattern) ────

    def start_baseline_capture(self) -> None:
        """Start capturing baseline spectrum for anomaly detection."""
        self._baseline_accumulator = np.zeros(self._fft_size, dtype=np.float64)
        self._baseline_count = 0

    def finish_baseline_capture(self) -> Optional[np.ndarray]:
        """Finish baseline capture and compute average baseline.

        Returns:
            Baseline spectrum in dB, or None if no data captured.
        """
        if self._baseline_accumulator is None or self._baseline_count == 0:
            return None

        self._baseline = self._baseline_accumulator / self._baseline_count
        self._baseline_accumulator = None
        self._baseline_count = 0
        return self._baseline.copy()

    def set_baseline(self, baseline_db: np.ndarray) -> None:
        """Set baseline spectrum directly."""
        if len(baseline_db) == self._fft_size:
            self._baseline = baseline_db.copy()

    def clear_baseline(self) -> None:
        """Clear the baseline spectrum."""
        self._baseline = None
        self._baseline_accumulator = None
        self._baseline_count = 0

    def get_anomalies(self, power_db: np.ndarray) -> List[Tuple[float, float, float]]:
        """Find frequency bins that exceed the baseline by threshold.

        Args:
            power_db: Current spectrum in dB.

        Returns:
            List of (frequency_hz, current_db, excess_db) tuples.
        """
        if self._baseline is None:
            return []

        diff = power_db - self._baseline
        anomaly_mask = diff > self._anomaly_threshold_db
        anomaly_indices = np.where(anomaly_mask)[0]

        anomalies = []
        for idx in anomaly_indices:
            anomalies.append((
                float(self._freq_axis[idx]),
                float(power_db[idx]),
                float(diff[idx]),
            ))

        return anomalies

    # ── Smoothing ───────────────────────────────────────────────

    @staticmethod
    def smooth(data: np.ndarray, window_len: int = 11, window: str = "hanning") -> np.ndarray:
        """Smooth spectrum data using a window function.

        From QSpectrumAnalyzer's utils.smooth pattern.

        Args:
            data: Input data array.
            window_len: Smoothing window length (must be odd).
            window: Window type (hanning, hamming, blackman, flat).

        Returns:
            Smoothed data array (same length as input).
        """
        if len(data) < window_len:
            return data

        if window_len < 3:
            return data

        if window_len % 2 == 0:
            window_len += 1

        # Extend data at edges to reduce boundary effects
        s = np.r_[data[window_len - 1:0:-1], data, data[-2:-window_len - 1:-1]]

        if window == "flat":
            w = np.ones(window_len, dtype=np.float64)
        elif window == "hanning":
            w = np.hanning(window_len)
        elif window == "hamming":
            w = np.hamming(window_len)
        elif window == "blackman":
            w = np.blackman(window_len)
        else:
            w = np.hanning(window_len)

        y = np.convolve(w / w.sum(), s, mode="valid")

        # Trim to original length
        trim = (len(y) - len(data)) // 2
        return y[trim:trim + len(data)]

    # ── Accessors ───────────────────────────────────────────────

    @property
    def average(self) -> np.ndarray:
        """Running average spectrum in dB."""
        return self._average.copy()

    @property
    def peak_hold_max(self) -> np.ndarray:
        """Peak hold maximum spectrum in dB."""
        return self._peak_hold_max.copy()

    @property
    def peak_hold_min(self) -> np.ndarray:
        """Peak hold minimum spectrum in dB."""
        return self._peak_hold_min.copy()

    @property
    def baseline(self) -> Optional[np.ndarray]:
        """Baseline spectrum in dB (None if not captured)."""
        return self._baseline.copy() if self._baseline is not None else None

    @property
    def freq_axis(self) -> np.ndarray:
        """Frequency axis in Hz."""
        return self._freq_axis.copy()

    @property
    def freq_axis_mhz(self) -> np.ndarray:
        """Frequency axis in MHz."""
        return self._freq_axis / 1e6

    def get_history(self) -> np.ndarray:
        """Get the history buffer (most recent spectra)."""
        if self._history_count < self._history_size:
            return self._history[:self._history_count].copy()
        return self._history.copy()

    def reset(self) -> None:
        """Reset all statistics and history."""
        self._history.fill(-120.0)
        self._history_count = 0
        self._history_index = 0
        self._average.fill(-120.0)
        self._peak_hold_max.fill(-200.0)
        self._peak_hold_min.fill(200.0)
        self._update_count = 0

    def reset_peak_hold(self) -> None:
        """Reset only peak hold max/min."""
        self._peak_hold_max.fill(-200.0)
        self._peak_hold_min.fill(200.0)

    @property
    def fft_size(self) -> int:
        return self._fft_size

    @property
    def sample_rate(self) -> float:
        return self._sample_rate

    @property
    def window_name(self) -> str:
        return self._window_name

    @property
    def update_count(self) -> int:
        return self._update_count
