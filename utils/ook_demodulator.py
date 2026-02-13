"""OOK (On-Off Keying) Demodulator for RF Signal Analysis.

Based on research from rtl_433 and real-world garage door signal analysis.
Implements envelope detection, edge detection, and pulse width measurement.
"""

import numpy as np
from scipy import signal
from typing import List, Tuple, Optional


class OOKDemodulator:
    """Demodulates OOK/ASK signals and extracts pulse patterns."""
    
    def __init__(self, sample_rate: float = 2e6):
        """Initialize OOK demodulator.
        
        Args:
            sample_rate: Sample rate in Hz (default 2 MHz)
        """
        self.sample_rate = sample_rate
        
        # Low-pass filter for envelope smoothing
        # Cutoff at 50 kHz to preserve pulse shapes while removing noise
        self.lpf_cutoff = 50000  # Hz
        self.lpf_order = 4
        
        # Design Butterworth low-pass filter
        nyquist = sample_rate / 2
        normalized_cutoff = self.lpf_cutoff / nyquist
        self.lpf_b, self.lpf_a = signal.butter(
            self.lpf_order, 
            normalized_cutoff, 
            btype='low'
        )
        
        # Edge detection parameters
        self.edge_threshold_factor = 0.6  # 60% of max for edge detection
        self.min_pulse_width_us = 50  # Minimum 50 microseconds
        self.max_pulse_width_us = 10000  # Maximum 10 milliseconds
        
    def calculate_envelope(self, iq_samples: np.ndarray) -> np.ndarray:
        """Calculate signal envelope from IQ samples.
        
        This is the magnitude: sqrt(I² + Q²)
        
        Args:
            iq_samples: Complex IQ samples
            
        Returns:
            Envelope (magnitude) as float array
        """
        # Calculate magnitude: sqrt(I² + Q²)
        envelope = np.abs(iq_samples)
        
        # Apply low-pass filter to smooth envelope and remove noise
        envelope_filtered = signal.filtfilt(self.lpf_b, self.lpf_a, envelope)
        
        return envelope_filtered
    
    def detect_edges(self, envelope: np.ndarray) -> Tuple[np.ndarray, np.ndarray, float]:
        """Detect rising and falling edges in envelope.
        
        Args:
            envelope: Signal envelope (magnitude)
            
        Returns:
            Tuple of (rising_edges, falling_edges, threshold)
            - rising_edges: Array of sample indices where signal rises
            - falling_edges: Array of sample indices where signal falls
            - threshold: Threshold value used for edge detection
        """
        # Calculate threshold as percentage of max envelope value
        max_envelope = np.max(envelope)
        threshold = max_envelope * self.edge_threshold_factor
        
        # Create binary signal: 1 where above threshold, 0 where below
        binary = (envelope > threshold).astype(int)
        
        # Find edges by looking at differences
        diff = np.diff(binary)
        
        # Rising edges: 0 -> 1 (diff = 1)
        rising_edges = np.where(diff == 1)[0] + 1  # +1 to get actual edge position
        
        # Falling edges: 1 -> 0 (diff = -1)
        falling_edges = np.where(diff == -1)[0] + 1
        
        return rising_edges, falling_edges, threshold
    
    def measure_pulses(self, rising_edges: np.ndarray, falling_edges: np.ndarray) -> List[dict]:
        """Measure pulse widths and gaps between pulses.
        
        Args:
            rising_edges: Array of rising edge sample indices
            falling_edges: Array of falling edge sample indices
            
        Returns:
            List of pulse dictionaries with:
            - start_sample: Rising edge position
            - end_sample: Falling edge position
            - width_samples: Pulse width in samples
            - width_us: Pulse width in microseconds
            - gap_samples: Gap to next pulse (if any)
            - gap_us: Gap in microseconds
        """
        pulses = []
        
        # Match rising edges with falling edges
        for i, rise in enumerate(rising_edges):
            # Find next falling edge after this rising edge
            fall_candidates = falling_edges[falling_edges > rise]
            
            if len(fall_candidates) == 0:
                break  # No matching falling edge
            
            fall = fall_candidates[0]
            
            # Calculate pulse width
            width_samples = fall - rise
            width_us = (width_samples / self.sample_rate) * 1e6
            
            # Filter out pulses that are too short or too long
            if width_us < self.min_pulse_width_us or width_us > self.max_pulse_width_us:
                continue
            
            # Calculate gap to next pulse
            gap_samples = 0
            gap_us = 0
            if i + 1 < len(rising_edges):
                next_rise = rising_edges[i + 1]
                gap_samples = next_rise - fall
                gap_us = (gap_samples / self.sample_rate) * 1e6
            
            pulses.append({
                'start_sample': int(rise),
                'end_sample': int(fall),
                'width_samples': int(width_samples),
                'width_us': float(width_us),
                'gap_samples': int(gap_samples),
                'gap_us': float(gap_us)
            })
        
        return pulses
    
    def classify_pulses(self, pulses: List[dict]) -> Tuple[str, List[int]]:
        """Classify pulses as short/long and convert to binary pattern.
        
        Uses clustering to automatically determine short vs long pulse widths.
        
        Args:
            pulses: List of pulse dictionaries from measure_pulses()
            
        Returns:
            Tuple of (pattern_string, pulse_classes)
            - pattern_string: Binary pattern like "010101"
            - pulse_classes: List of 0/1 for each pulse
        """
        if len(pulses) < 2:
            return "", []
        
        # Extract pulse widths
        widths = np.array([p['width_us'] for p in pulses])
        
        # Use median as threshold between short and long
        median_width = np.median(widths)
        
        # Classify: 0 for short (below median), 1 for long (above median)
        pulse_classes = (widths > median_width).astype(int).tolist()
        
        # Convert to string pattern
        pattern_string = ''.join(str(c) for c in pulse_classes)
        
        return pattern_string, pulse_classes
    
    def analyze_signal(self, iq_samples: np.ndarray) -> Optional[dict]:
        """Complete OOK signal analysis pipeline.
        
        Args:
            iq_samples: Complex IQ samples
            
        Returns:
            Dictionary with analysis results or None if no valid signal:
            - envelope: Signal envelope
            - threshold: Detection threshold used
            - pulses: List of detected pulses
            - pattern: Binary pattern string
            - pulse_classes: List of pulse classifications
            - num_pulses: Number of valid pulses
            - avg_pulse_width_us: Average pulse width
            - symbol_rate: Estimated symbol rate (pulses/second)
        """
        # Step 1: Calculate envelope
        envelope = self.calculate_envelope(iq_samples)
        
        # Step 2: Detect edges
        rising_edges, falling_edges, threshold = self.detect_edges(envelope)
        
        # Step 3: Measure pulses
        pulses = self.measure_pulses(rising_edges, falling_edges)
        
        if len(pulses) < 2:
            return None  # Not enough pulses for valid signal
        
        # Step 4: Classify pulses
        pattern, pulse_classes = self.classify_pulses(pulses)
        
        # Step 5: Calculate statistics
        avg_pulse_width = np.mean([p['width_us'] for p in pulses])
        total_duration_s = (pulses[-1]['end_sample'] - pulses[0]['start_sample']) / self.sample_rate
        symbol_rate = len(pulses) / total_duration_s if total_duration_s > 0 else 0
        
        return {
            'envelope': envelope,
            'threshold': threshold,
            'pulses': pulses,
            'pattern': pattern,
            'pulse_classes': pulse_classes,
            'num_pulses': len(pulses),
            'avg_pulse_width_us': avg_pulse_width,
            'symbol_rate': symbol_rate,
            'total_duration_us': total_duration_s * 1e6
        }
    
    def is_valid_ook_signal(self, analysis: Optional[dict]) -> bool:
        """Determine if analysis results represent a valid OOK signal.
        
        Checks for:
        - Sufficient number of pulses
        - Consistent pulse widths
        - Valid symbol rate
        - Pattern complexity
        
        Args:
            analysis: Results from analyze_signal()
            
        Returns:
            True if valid OOK signal, False otherwise
        """
        if analysis is None:
            return False
        
        # Require at least 4 pulses for valid signal
        if analysis['num_pulses'] < 4:
            return False
        
        # Check symbol rate is reasonable (100 - 10000 symbols/sec)
        if analysis['symbol_rate'] < 100 or analysis['symbol_rate'] > 10000:
            return False
        
        # Check pattern has some variation (not all 0s or all 1s)
        pattern = analysis['pattern']
        if pattern.count('0') == 0 or pattern.count('1') == 0:
            return False
        
        # Check pulse width consistency (coefficient of variation < 0.5)
        pulse_widths = [p['width_us'] for p in analysis['pulses']]
        cv = np.std(pulse_widths) / np.mean(pulse_widths)
        if cv > 0.5:
            return False  # Too much variation, likely noise
        
        return True
