"""RF Tactical Monitor - Signal Detector V2

Advanced signal detection pipeline inspired by RFwatch architecture.
Replaces the sample-by-sample approach with a proper FFT-based pipeline:

1. Detector: Binary signal presence (power + hysteresis state machine)
2. Segmenter: Frequency segmentation when signal is present
3. EventBuilder: Track signals across time, match segments to events
4. FeatureExtractor: Extract signal characteristics from completed events

This provides much more reliable detection with fewer false positives
and richer signal characterization.
"""

import time
import numpy as np
from collections import deque
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
import logging


# ── Data Classes ────────────────────────────────────────────────

@dataclass
class DetectionResult:
    """Result of signal detection for one chunk (from RFwatch)."""
    present: bool
    power_db: float
    noise_floor_db: float
    snr_db: float


@dataclass
class FrequencySegment:
    """A detected frequency region within the spectrum."""
    low_hz: float
    high_hz: float
    center_hz: float
    bandwidth_hz: float
    peak_db: float
    confidence: float
    bins: int = 0


@dataclass
class SignalEvent:
    """A tracked signal event across time (from RFwatch)."""
    id: str
    start_time: float
    end_time: Optional[float] = None
    active: bool = True
    last_center: float = 0.0
    last_bandwidth: float = 0.0
    last_seen: float = 0.0
    hit_count: int = 0
    miss_count: int = 0

    # History arrays for feature extraction
    center_freq_history: List[float] = field(default_factory=list)
    bandwidth_history: List[float] = field(default_factory=list)
    power_history: List[float] = field(default_factory=list)
    timestamp_history: List[float] = field(default_factory=list)
    present_history: List[bool] = field(default_factory=list)

    # Extracted features (populated on close)
    features: Optional[Dict[str, Any]] = None

    def close(self, timestamp: float) -> None:
        """Close this event."""
        self.end_time = timestamp
        self.active = False

    @property
    def duration_sec(self) -> float:
        """Event duration in seconds."""
        if self.end_time is not None:
            return self.end_time - self.start_time
        return time.time() - self.start_time


# ── Detector (RFwatch pattern) ──────────────────────────────────

class Detector:
    """Binary signal detection using power estimation and hysteresis.

    From RFwatch: This is a gate. Nothing more.
    Uses SNR-based thresholds with hysteresis to prevent flicker.

    - IDLE -> ACTIVE: SNR > snr_enter_db
    - ACTIVE -> IDLE: SNR < snr_exit_db
    """

    def __init__(
        self,
        snr_enter_db: float = 8.0,
        snr_exit_db: float = 4.0,
        noise_history_size: int = 500,
    ):
        self.snr_enter_db = snr_enter_db
        self.snr_exit_db = snr_exit_db
        self.noise_history = deque(maxlen=noise_history_size)
        self.state = "IDLE"
        self.chunk_count = 0
        self.transitions: List[Dict] = []

    def process(self, iq_chunk: np.ndarray) -> DetectionResult:
        """Detect signal presence in IQ chunk.

        Args:
            iq_chunk: Complex IQ samples.

        Returns:
            DetectionResult with presence, power, noise floor, SNR.
        """
        self.chunk_count += 1

        # Step 1: Power estimation (time domain)
        power_linear = np.mean(np.abs(iq_chunk) ** 2)
        power_db = 10.0 * np.log10(power_linear + 1e-20)

        # Step 2: Noise floor estimation (robust median)
        self.noise_history.append(power_db)
        noise_floor_db = float(np.median(list(self.noise_history)))

        # Step 3: SNR calculation
        snr_db = power_db - noise_floor_db

        # Step 4: Presence decision with hysteresis
        present = False

        if self.state == "IDLE":
            if snr_db > self.snr_enter_db:
                self.state = "ACTIVE"
                present = True
                self.transitions.append({
                    "chunk": self.chunk_count,
                    "transition": "IDLE -> ACTIVE",
                    "snr_db": snr_db,
                })
        else:  # ACTIVE
            if snr_db < self.snr_exit_db:
                self.state = "IDLE"
                present = False
                self.transitions.append({
                    "chunk": self.chunk_count,
                    "transition": "ACTIVE -> IDLE",
                    "snr_db": snr_db,
                })
            else:
                present = True

        return DetectionResult(
            present=present,
            power_db=power_db,
            noise_floor_db=noise_floor_db,
            snr_db=snr_db,
        )

    def reset(self) -> None:
        """Reset detector state."""
        self.noise_history.clear()
        self.state = "IDLE"
        self.chunk_count = 0
        self.transitions.clear()

    def get_statistics(self) -> dict:
        return {
            "state": self.state,
            "chunk_count": self.chunk_count,
            "noise_history_size": len(self.noise_history),
            "transitions": len(self.transitions),
            "recent_transitions": self.transitions[-5:],
        }


# ── Segmenter (RFwatch pattern) ────────────────────────────────

class Segmenter:
    """Frequency segmentation of signals via FFT.

    Runs only when detector says present=True.
    Stateless across chunks. Emits frequency segments.

    Pipeline:
    1. Window IQ -> FFT -> PSD (dB)
    2. Noise floor (30th percentile)
    3. Threshold mask
    4. Contiguous bin grouping
    5. Frequency segments with weighted centroid
    """

    def __init__(
        self,
        sample_rate: float = 2e6,
        fft_size: int = 1024,
        bw_threshold_db: float = 6.0,
        min_segment_bins: int = 3,
        psd_smooth_bins: int = 3,
    ):
        self.sample_rate = sample_rate
        self.fft_size = fft_size
        self.bw_threshold_db = bw_threshold_db
        self.min_segment_bins = min_segment_bins
        self.psd_smooth_bins = psd_smooth_bins

        # Cache window and frequency vector
        self._window = np.hanning(fft_size).astype(np.float32)
        self._freqs = np.fft.fftshift(
            np.fft.fftfreq(fft_size, d=1.0 / sample_rate)
        ).astype(np.float64)

        # Store last PSD for UI access
        self.last_psd: Optional[Tuple[np.ndarray, np.ndarray]] = None

    def process(self, iq_chunk: np.ndarray) -> List[FrequencySegment]:
        """Segment IQ chunk into frequency regions.

        Args:
            iq_chunk: Complex IQ samples.

        Returns:
            List of FrequencySegment objects.
        """
        n_in = len(iq_chunk)
        n_fft = min(n_in, self.fft_size)
        if n_fft <= 0:
            return []

        x = iq_chunk[-n_fft:]

        # Resize window if needed
        if len(self._window) != n_fft:
            self._window = np.hanning(n_fft).astype(np.float32)
            self._freqs = np.fft.fftshift(
                np.fft.fftfreq(n_fft, d=1.0 / self.sample_rate)
            ).astype(np.float64)

        # 1. Window and FFT
        windowed = x * self._window
        fft_result = np.fft.fftshift(np.fft.fft(windowed))

        # 2. PSD in dB
        psd = 10.0 * np.log10(np.abs(fft_result) ** 2 + 1e-20)

        # Optional smoothing
        if self.psd_smooth_bins > 1:
            kernel = np.ones(self.psd_smooth_bins, dtype=np.float32) / self.psd_smooth_bins
            psd = np.convolve(psd, kernel, mode="same")

        self.last_psd = (self._freqs.copy(), psd.copy())

        # 3. Noise floor (30th percentile)
        noise_floor = np.percentile(psd, 30)

        # 4. Threshold mask
        mask = psd > (noise_floor + self.bw_threshold_db)

        # 5. Contiguous bin grouping
        segments = []
        in_seg = False
        start = 0

        for i, val in enumerate(mask):
            if val and not in_seg:
                in_seg = True
                start = i
            elif not val and in_seg:
                if i - start >= self.min_segment_bins:
                    seg = self._make_segment(psd, self._freqs, start, i)
                    if seg is not None:
                        segments.append(seg)
                in_seg = False

        # Handle segment at end
        if in_seg and n_fft - start >= self.min_segment_bins:
            seg = self._make_segment(psd, self._freqs, start, n_fft)
            if seg is not None:
                segments.append(seg)

        return segments

    def _make_segment(
        self, psd: np.ndarray, freqs: np.ndarray, start: int, end: int
    ) -> Optional[FrequencySegment]:
        """Create frequency segment from bin range."""
        psd_slice = psd[start:end]
        f_slice = freqs[start:end]
        if len(f_slice) == 0:
            return None

        bin_hz = abs(freqs[1] - freqs[0]) if len(freqs) >= 2 else 0.0

        # Weighted centroid for center frequency
        power_linear = 10.0 ** (psd_slice / 10.0)
        center = np.sum(f_slice * power_linear) / (np.sum(power_linear) + 1e-20)

        peak_db = float(np.max(psd_slice))
        confidence = min(1.0, len(f_slice) / 10.0)

        low_edge = float(f_slice[0] - bin_hz / 2.0)
        high_edge = float(f_slice[-1] + bin_hz / 2.0)
        bandwidth_hz = max(bin_hz, (end - start) * bin_hz)

        return FrequencySegment(
            low_hz=low_edge,
            high_hz=high_edge,
            center_hz=float(center),
            bandwidth_hz=float(bandwidth_hz),
            peak_db=peak_db,
            confidence=confidence,
            bins=end - start,
        )

    def set_sample_rate(self, sample_rate: float) -> None:
        """Update sample rate."""
        self.sample_rate = sample_rate
        self._freqs = np.fft.fftshift(
            np.fft.fftfreq(self.fft_size, d=1.0 / sample_rate)
        ).astype(np.float64)

    def reset(self) -> None:
        self.last_psd = None


# ── Event Builder (RFwatch pattern) ─────────────────────────────

class EventBuilder:
    """Manages signal event lifecycle and matching.

    Turns per-chunk detections + segments into coherent, time-bounded events.
    Matching rule: Two segments belong to the same event if
    |center_new - center_old| < match_bw_factor × bandwidth_old

    Args:
        match_bw_factor: How many bandwidths of tolerance for matching.
        max_misses: How many consecutive misses before closing an event.
    """

    def __init__(
        self,
        match_bw_factor: float = 2.0,
        max_misses: int = 10,
    ):
        self.match_bw_factor = match_bw_factor
        self.max_misses = max_misses
        self.active_events: List[SignalEvent] = []
        self.closed_events: List[SignalEvent] = []
        self._event_counter = 0
        self._logger = logging.getLogger(__name__)

    def process(
        self,
        timestamp: float,
        detected: bool,
        segments: List[FrequencySegment],
    ) -> Dict[str, List[SignalEvent]]:
        """Process one chunk's detection results.

        Args:
            timestamp: Current chunk timestamp.
            detected: Boolean from detector.
            segments: Frequency segments from segmenter.

        Returns:
            Dict with 'active' and 'closed' event lists.
        """
        matched_events = []
        newly_closed = []

        if detected and segments:
            for seg in segments:
                event = self._match_event(seg)
                if event:
                    self._update_event(event, seg, timestamp)
                    if event not in matched_events:
                        matched_events.append(event)
                else:
                    new_event = self._start_event(seg, timestamp)
                    matched_events.append(new_event)

        # Handle misses
        for event in list(self.active_events):
            if event not in matched_events:
                event.miss_count += 1
                event.timestamp_history.append(timestamp)
                event.present_history.append(False)
                if event.miss_count >= self.max_misses:
                    closed = self._close_event(event, timestamp)
                    newly_closed.append(closed)
            else:
                event.miss_count = 0

        return {"active": self.active_events.copy(), "closed": newly_closed}

    def _match_event(self, segment: FrequencySegment) -> Optional[SignalEvent]:
        """Find existing active event matching this segment."""
        for event in self.active_events:
            center_diff = abs(segment.center_hz - event.last_center)
            threshold = self.match_bw_factor * max(event.last_bandwidth, 1000.0)
            if center_diff < threshold:
                return event
        return None

    def _start_event(self, segment: FrequencySegment, timestamp: float) -> SignalEvent:
        """Create new SignalEvent from segment."""
        self._event_counter += 1
        event_id = f"sig_{self._event_counter:06d}"

        event = SignalEvent(
            id=event_id,
            start_time=timestamp,
            active=True,
            last_center=segment.center_hz,
            last_bandwidth=segment.bandwidth_hz,
            last_seen=timestamp,
            hit_count=1,
            miss_count=0,
        )

        event.center_freq_history.append(segment.center_hz)
        event.bandwidth_history.append(segment.bandwidth_hz)
        event.power_history.append(segment.peak_db)
        event.timestamp_history.append(timestamp)
        event.present_history.append(True)

        self.active_events.append(event)
        return event

    def _update_event(
        self, event: SignalEvent, segment: FrequencySegment, timestamp: float
    ) -> None:
        """Update existing event with new observation."""
        event.last_center = segment.center_hz
        event.last_bandwidth = segment.bandwidth_hz
        event.last_seen = timestamp
        event.hit_count += 1

        event.center_freq_history.append(segment.center_hz)
        event.bandwidth_history.append(segment.bandwidth_hz)
        event.power_history.append(segment.peak_db)
        event.timestamp_history.append(timestamp)
        event.present_history.append(True)

    def _close_event(self, event: SignalEvent, timestamp: float) -> SignalEvent:
        """Close an active event and extract features."""
        event.close(timestamp)
        self.active_events.remove(event)
        self.closed_events.append(event)

        # Extract features on close
        try:
            event.features = FeatureExtractor.extract(event)
        except Exception as e:
            self._logger.warning("Feature extraction failed for %s: %s", event.id, e)

        return event

    def get_active_events(self) -> List[SignalEvent]:
        return self.active_events.copy()

    def get_closed_events(self) -> List[SignalEvent]:
        return self.closed_events.copy()

    def reset(self) -> None:
        self.active_events.clear()
        self.closed_events.clear()
        self._event_counter = 0


# ── Feature Extractor (RFwatch pattern) ─────────────────────────

class FeatureExtractor:
    """Extracts signal features from completed events.

    Computes: frequency stats, bandwidth stats, time structure,
    power/noise metrics, signal dynamics, stability, confidence.
    """

    @staticmethod
    def extract(event: SignalEvent) -> Dict[str, Any]:
        """Extract features from a closed event.

        Args:
            event: Closed SignalEvent with history data.

        Returns:
            Feature dictionary with nested categories.
        """
        if event.end_time is None:
            raise ValueError("Feature extraction requires a closed event")

        features = {}
        duration_s = event.end_time - event.start_time

        # Meta
        features["meta"] = {
            "start_time": event.start_time,
            "end_time": event.end_time,
            "duration_s": duration_s,
            "chunks_seen": event.hit_count,
        }

        # Frequency
        cf_hist = event.center_freq_history
        center_hz = float(np.mean(cf_hist)) if cf_hist else 0.0
        freq_std = float(np.std(cf_hist)) if len(cf_hist) > 1 else 0.0

        # Drift estimation
        drift = 0.0
        if len(cf_hist) > 2 and duration_s > 0:
            times = np.linspace(0, duration_s, len(cf_hist))
            try:
                drift = float(np.polyfit(times, cf_hist, 1)[0])
            except Exception:
                drift = 0.0

        features["frequency"] = {
            "center_hz": center_hz,
            "std_hz": freq_std,
            "drift_hz_per_s": drift,
            "min_hz": float(np.min(cf_hist)) if cf_hist else 0.0,
            "max_hz": float(np.max(cf_hist)) if cf_hist else 0.0,
        }

        # Bandwidth
        bw_hist = event.bandwidth_history
        bw_mean = float(np.mean(bw_hist)) if bw_hist else 0.0
        bw_std = float(np.std(bw_hist)) if bw_hist else 0.0
        features["bandwidth"] = {
            "mean_hz": bw_mean,
            "std_hz": bw_std,
            "min_hz": float(np.min(bw_hist)) if bw_hist else 0.0,
            "max_hz": float(np.max(bw_hist)) if bw_hist else 0.0,
            "unstable": (bw_std / bw_mean > 0.3) if bw_mean > 0 else False,
        }

        # Time structure
        total = event.hit_count + event.miss_count
        duty_cycle = event.hit_count / total if total > 0 else 0.0
        burst_type = "continuous" if event.miss_count == 0 else "bursty"

        features["time_structure"] = {
            "burst_type": burst_type,
            "duty_cycle": duty_cycle,
        }

        # Power and noise
        pw_hist = event.power_history
        avg_power = float(np.mean(pw_hist)) if pw_hist else 0.0
        peak_power = float(np.max(pw_hist)) if pw_hist else 0.0
        noise_floor = float(np.percentile(pw_hist, 20)) if pw_hist else 0.0
        snr = avg_power - noise_floor

        features["power"] = {
            "avg_power_db": avg_power,
            "peak_power_db": peak_power,
            "papr_db": peak_power - avg_power,
        }
        features["noise"] = {
            "noise_floor_db": noise_floor,
            "snr_db": snr,
        }

        # Signal dynamics
        power_var = float(np.var(pw_hist)) if pw_hist else 0.0
        features["signal_dynamics"] = {
            "power_var": power_var,
            "fading": "fast" if duration_s < 0.2 and power_var > 0.5 else "slow",
        }

        # Stability score
        drift_score = max(0.0, min(1.0, 1.0 - abs(drift) / 1000.0))
        bw_score = max(0.0, min(1.0, 1.0 - (bw_std / bw_mean))) if bw_mean > 0 else 0.0
        stability = 0.6 * drift_score + 0.4 * bw_score

        features["stability"] = {
            "score": max(0.0, min(1.0, stability)),
        }

        # Confidence
        stability_factor = max(0.0, min(1.0, 1.0 - (bw_std / bw_mean))) if bw_mean > 0 else 0.0
        freq_conf = min(1.0, max(0.0, snr / 5.0)) * stability_factor
        features["confidence"] = {
            "frequency": max(0.0, min(1.0, freq_conf)),
        }

        return features


# ── Integrated Signal Detector V2 ──────────────────────────────

class SignalDetectorV2:
    """Complete signal detection pipeline combining all components.

    This is the main class to use. It integrates:
    - Detector (binary presence with hysteresis)
    - Segmenter (FFT-based frequency analysis)
    - EventBuilder (temporal tracking and matching)
    - FeatureExtractor (signal characterization)

    Usage:
        detector = SignalDetectorV2(sample_rate=2e6)
        results = detector.process_chunk(iq_samples)
        # results contains active events, closed events, detection state

    Args:
        sample_rate: Sample rate in Hz.
        fft_size: FFT size for segmentation.
        snr_enter_db: SNR threshold to enter ACTIVE state.
        snr_exit_db: SNR threshold to exit ACTIVE state.
        bw_threshold_db: dB above noise floor for bandwidth detection.
        max_misses: Consecutive misses before closing an event.
    """

    def __init__(
        self,
        sample_rate: float = 2e6,
        fft_size: int = 1024,
        snr_enter_db: float = 8.0,
        snr_exit_db: float = 4.0,
        bw_threshold_db: float = 6.0,
        max_misses: int = 10,
    ):
        self._sample_rate = sample_rate
        self._fft_size = fft_size
        self._logger = logging.getLogger(__name__)

        self.detector = Detector(
            snr_enter_db=snr_enter_db,
            snr_exit_db=snr_exit_db,
        )
        self.segmenter = Segmenter(
            sample_rate=sample_rate,
            fft_size=fft_size,
            bw_threshold_db=bw_threshold_db,
        )
        self.event_builder = EventBuilder(
            max_misses=max_misses,
        )

        self._chunk_count = 0
        self._start_time = time.time()

    def process_chunk(self, iq_chunk: np.ndarray) -> Dict[str, Any]:
        """Process one chunk of IQ samples through the full pipeline.

        Args:
            iq_chunk: Complex IQ samples.

        Returns:
            Dictionary with:
                'detection': DetectionResult
                'segments': List of FrequencySegment
                'active_events': List of active SignalEvent
                'closed_events': List of newly closed SignalEvent
                'timestamp': Current timestamp
        """
        self._chunk_count += 1
        timestamp = time.time()

        # Step 1: Detect signal presence
        detection = self.detector.process(iq_chunk)

        # Step 2: Segment if signal present
        segments = []
        if detection.present:
            segments = self.segmenter.process(iq_chunk)

        # Step 3: Build/update events
        event_result = self.event_builder.process(timestamp, detection.present, segments)

        return {
            "detection": detection,
            "segments": segments,
            "active_events": event_result["active"],
            "closed_events": event_result["closed"],
            "timestamp": timestamp,
        }

    def get_all_closed_events(self) -> List[SignalEvent]:
        """Get all closed events since last reset."""
        return self.event_builder.get_closed_events()

    def get_active_events(self) -> List[SignalEvent]:
        """Get currently active events."""
        return self.event_builder.get_active_events()

    def set_sample_rate(self, sample_rate: float) -> None:
        """Update sample rate."""
        self._sample_rate = sample_rate
        self.segmenter.set_sample_rate(sample_rate)

    def set_thresholds(self, snr_enter_db: float, snr_exit_db: float) -> None:
        """Update detection thresholds."""
        self.detector.snr_enter_db = snr_enter_db
        self.detector.snr_exit_db = snr_exit_db

    def reset(self) -> None:
        """Reset all components."""
        self.detector.reset()
        self.segmenter.reset()
        self.event_builder.reset()
        self._chunk_count = 0
        self._start_time = time.time()

    def get_statistics(self) -> Dict[str, Any]:
        """Get comprehensive statistics."""
        return {
            "chunk_count": self._chunk_count,
            "detector": self.detector.get_statistics(),
            "active_events": len(self.event_builder.active_events),
            "closed_events": len(self.event_builder.closed_events),
            "uptime_sec": time.time() - self._start_time,
        }

    @property
    def noise_floor_db(self) -> float:
        """Current noise floor estimate."""
        if self.detector.noise_history:
            return float(np.median(list(self.detector.noise_history)))
        return -100.0

    @property
    def threshold_db(self) -> float:
        """Current enter threshold."""
        return self.detector.snr_enter_db
