"""Signal detector utility for RF Tactical Monitor.

DEPRECATED: This is the V1 signal detector using simple time-domain
threshold detection. Prefer SignalDetectorV2 (signal_detector_v2.py)
which uses frequency-domain segmentation with event tracking.

V1 is still used by SDRWorker for backward compatibility but will
be removed in a future version.
"""

import numpy as np


class SignalDetector:
    """Detects signal bursts in IQ stream."""

    def __init__(self, threshold_db=15, min_duration_sec=0.0001, max_duration_sec=0.05, sample_rate=2e6, hysteresis_samples=50, max_continuous_batches=100):
        """Initialize signal detector.
        
        Args:
            threshold_db: Threshold in dB ABOVE noise floor (default 15 dB - higher to avoid false positives)
            min_duration_sec: Minimum signal duration to detect (default 0.1ms = 200 samples at 2 Msps)
            max_duration_sec: Maximum signal duration to detect (default 50ms - reject longer continuous signals)
            sample_rate: Sample rate in Hz
            hysteresis_samples: Number of samples below threshold before ending signal (default 50)
            max_continuous_batches: Max batches a signal can span before being rejected as continuous (default 100 = ~50ms)
        """
        self.threshold_db = threshold_db  # Relative to noise floor
        self.min_duration_sec = min_duration_sec
        self.max_duration_sec = max_duration_sec
        self.sample_rate = sample_rate
        self.min_duration_samples = int(min_duration_sec * sample_rate)
        self.max_duration_samples = int(max_duration_sec * sample_rate)
        self.hysteresis_samples = hysteresis_samples
        self.max_continuous_batches = max_continuous_batches

        self.in_signal = False
        self.signal_start_sample = 0
        self.signal_samples = []
        self.samples_below_threshold = 0  # Counter for hysteresis
        self.continuous_batch_count = 0  # Track how many batches signal has spanned
        self.cooldown_batches = 0  # Cooldown after rejecting continuous signal
        
        # Noise floor estimation
        self.noise_floor_db = -100  # Initial estimate
        self.noise_floor_alpha = 0.01  # Smoothing factor

    def process_samples(self, iq_samples):
        """Process IQ samples and detect signal bursts.

        Returns: list of detected signals.
        """
        if iq_samples is None or len(iq_samples) == 0:
            return []

        # Calculate power to match waterfall calculation
        # The waterfall normalizes by FFT size squared, but for time-domain detection
        # we just need the magnitude squared of the IQ samples
        # However, we need to scale to match the dB range shown in waterfall
        power = np.abs(iq_samples) ** 2
        # Convert to dBFS (dB relative to full scale)
        # Assuming input range is normalized to [-1, 1], so full scale power is 1.0
        power_db = 10 * np.log10(power + 1e-10)
        
        # Apply scaling factor to match waterfall dB range
        # Waterfall shows -37 to -22 dBm, but our raw calculation gives much lower values
        # The HackRF has ~8-bit effective resolution, so we need to add an offset
        # Empirically, we need to add about 40 dB to match waterfall scale
        power_db = power_db + 40.0
        
        # Update noise floor estimate (use median for robustness)
        # Use median instead of percentile for more stable noise floor estimation
        noise_estimate = np.median(power_db)
        self.noise_floor_db = (self.noise_floor_alpha * noise_estimate + 
                               (1 - self.noise_floor_alpha) * self.noise_floor_db)
        
        # Detect signals above noise floor + threshold
        absolute_threshold = self.noise_floor_db + self.threshold_db
        above_threshold = power_db > absolute_threshold
        
        # Debug: Log sample statistics (will be visible in flow tracer)
        num_above = np.sum(above_threshold)
        max_power = np.max(power_db)
        from utils.flow_tracer import get_flow_tracer
        flow = get_flow_tracer()
        
        # ALWAYS log detection stats to see what's happening
        flow.data("ISM", "samples_above_threshold", f"{num_above}/{len(power_db)}")
        flow.data("ISM", "max_sample_power", f"{max_power:.1f} dB")
        flow.data("ISM", "current_threshold", f"{absolute_threshold:.1f} dB")
        flow.data("ISM", "in_signal_state", f"{self.in_signal}")
        
        if num_above > 0:
            flow.data("ISM", "detection_active", "YES - samples above threshold detected!")

        detected_this_batch = []
        
        # Handle cooldown period after rejecting continuous signal
        if self.cooldown_batches > 0:
            self.cooldown_batches -= 1
            flow.data("ISM", "cooldown_active", f"{self.cooldown_batches} batches remaining")
            return []  # Skip detection during cooldown

        for i, is_signal in enumerate(above_threshold):
            if is_signal and not self.in_signal:
                # Start of new signal
                self.in_signal = True
                self.signal_start_sample = i
                self.signal_samples = [iq_samples[i]]
                self.samples_below_threshold = 0
                self.continuous_batch_count = 0  # Reset batch counter for new signal
            elif is_signal and self.in_signal:
                # Continue signal - sample above threshold
                self.signal_samples.append(iq_samples[i])
                self.samples_below_threshold = 0  # Reset counter
            elif not is_signal and self.in_signal:
                # Sample below threshold while in signal - use hysteresis
                self.samples_below_threshold += 1
                self.signal_samples.append(iq_samples[i])  # Include in signal
                
                # Only end signal if we've been below threshold for hysteresis_samples
                if self.samples_below_threshold >= self.hysteresis_samples:
                    self.in_signal = False
                    self.samples_below_threshold = 0

                    # Debug logging
                    from utils.flow_tracer import get_flow_tracer
                    flow = get_flow_tracer()
                    
                    duration_sec = len(self.signal_samples) / self.sample_rate
                    
                    # Check duration limits
                    if len(self.signal_samples) < self.min_duration_samples:
                        flow.warning("ISM", f"[X] Signal REJECTED (too short): {len(self.signal_samples)} samples ({duration_sec*1000:.2f}ms) < {self.min_duration_sec*1000:.2f}ms required")
                    elif len(self.signal_samples) > self.max_duration_samples:
                        flow.warning("ISM", f"[X] Signal REJECTED (too long): {len(self.signal_samples)} samples ({duration_sec*1000:.2f}ms) > {self.max_duration_sec*1000:.2f}ms max")
                    else:
                        # Valid duration - accept signal
                        signal_array = np.array(self.signal_samples)
                        peak_power = np.max(np.abs(signal_array) ** 2)
                        # Apply same +40 dB offset as detection calculation
                        peak_power_db = 10 * np.log10(peak_power + 1e-10) + 40.0

                        fft = np.fft.fft(signal_array)
                        fft_freqs = np.fft.fftfreq(len(signal_array), 1 / self.sample_rate)
                        center_freq_offset = fft_freqs[np.argmax(np.abs(fft))]

                        flow.success("ISM", f"[OK] Signal ACCEPTED: {len(self.signal_samples)} samples, {duration_sec*1000:.2f}ms, {peak_power_db:.1f} dB")

                        detected_this_batch.append(
                            {
                                "start_sample": self.signal_start_sample,
                                "duration_sec": duration_sec,
                                "peak_power_dbm": peak_power_db,
                                "center_freq_offset_hz": center_freq_offset,
                            }
                        )

                    self.signal_samples = []
        
        # Handle signal that extends to end of batch
        if self.in_signal:
            self.continuous_batch_count += 1
            
            from utils.flow_tracer import get_flow_tracer
            flow = get_flow_tracer()
            
            # If signal has spanned too many batches, it's continuous background noise - reject it
            if self.continuous_batch_count > self.max_continuous_batches:
                flow.warning("ISM", f"[X] Signal REJECTED (continuous background): {len(self.signal_samples)} samples across {self.continuous_batch_count} batches")
                # Reset and ignore this continuous signal
                self.in_signal = False
                self.signal_samples = []
                self.samples_below_threshold = 0
                self.continuous_batch_count = 0
                # Enter cooldown period to avoid immediate re-detection (50 batches = ~25ms)
                self.cooldown_batches = 50
                flow.data("ISM", "cooldown_started", "50 batches (~25ms)")
            else:
                # Signal continues to next batch - keep accumulating
                flow.data("ISM", "signal_continues", f"{len(self.signal_samples)} samples, batch {self.continuous_batch_count}")

        return detected_this_batch

    def set_threshold(self, threshold_db):
        """Update detection threshold."""
        self.threshold_db = threshold_db

    def set_sample_rate(self, sample_rate):
        """Update sample rate and duration thresholds."""
        self.sample_rate = sample_rate
        self.min_duration_samples = int(self.min_duration_sec * sample_rate)
