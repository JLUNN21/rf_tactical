"""Signal Replay Utility for RF Tactical Monitor

Regenerates and transmits simple OOK/ASK signals without storing full IQ data.
"""

import numpy as np
import logging
from typing import Dict, Optional


class SignalReplayGenerator:
    """Generates transmittable signals from detected signal parameters."""
    
    def __init__(self):
        self._logger = logging.getLogger(__name__)
    
    def generate_ook_signal(
        self,
        duration_sec: float,
        sample_rate: float = 2e6,
        carrier_amplitude: float = 0.8
    ) -> np.ndarray:
        """Generate a simple OOK (On-Off Keying) signal.
        
        For garage door remotes and similar devices, we generate a continuous
        carrier burst at the detected frequency and duration.
        
        Args:
            duration_sec: Signal duration in seconds
            sample_rate: Sample rate in Hz (default 2 MHz)
            carrier_amplitude: Carrier amplitude 0.0-1.0 (default 0.8)
        
        Returns:
            Complex IQ samples as numpy array
        """
        num_samples = int(duration_sec * sample_rate)
        
        # Generate continuous carrier (OOK "on" state)
        # For OOK, we just need a constant carrier at baseband (0 Hz offset)
        # The HackRF will upconvert this to the target frequency
        
        # Create complex carrier: I + jQ
        # For a simple carrier at baseband, use constant amplitude
        i_samples = np.full(num_samples, carrier_amplitude, dtype=np.float32)
        q_samples = np.zeros(num_samples, dtype=np.float32)
        
        # Combine into complex samples
        iq_samples = i_samples + 1j * q_samples
        
        # Add slight ramp-up/ramp-down to avoid clicks (first/last 10% of signal)
        ramp_samples = int(num_samples * 0.1)
        if ramp_samples > 0:
            # Ramp up
            ramp_up = np.linspace(0, 1, ramp_samples, dtype=np.float32)
            iq_samples[:ramp_samples] *= ramp_up
            
            # Ramp down
            ramp_down = np.linspace(1, 0, ramp_samples, dtype=np.float32)
            iq_samples[-ramp_samples:] *= ramp_down
        
        self._logger.info(
            "Generated OOK signal: %d samples (%.3f sec) at %.1f MSPS",
            num_samples, duration_sec, sample_rate / 1e6
        )
        
        return iq_samples
    
    def generate_from_detection(
        self,
        signal_data: Dict,
        sample_rate: float = 2e6
    ) -> Optional[np.ndarray]:
        """Generate transmittable signal from detected signal parameters.
        
        Args:
            signal_data: Signal detection data dict with keys:
                - duration_sec: Signal duration
                - peak_power_dbm: Peak power (used to scale amplitude)
                - modulation: Modulation type (optional)
            sample_rate: Sample rate in Hz
        
        Returns:
            Complex IQ samples ready for transmission, or None if generation fails
        """
        try:
            duration = signal_data.get('duration_sec', signal_data.get('duration', 0))
            if duration <= 0:
                self._logger.error("Invalid duration: %s", duration)
                return None
            
            # Limit duration to reasonable values (prevent accidents)
            if duration > 5.0:
                self._logger.warning("Duration %.2f sec exceeds 5 sec limit, capping", duration)
                duration = 5.0
            
            # Scale amplitude based on detected power (optional)
            # For safety, always use moderate power
            amplitude = 0.7  # Safe default
            
            # Determine modulation type
            modulation = signal_data.get('modulation', 'OOK').upper()
            
            if modulation in ['OOK', 'ASK', 'ON-OFF KEYING']:
                return self.generate_ook_signal(duration, sample_rate, amplitude)
            else:
                self._logger.warning("Unsupported modulation: %s, using OOK", modulation)
                return self.generate_ook_signal(duration, sample_rate, amplitude)
        
        except Exception as e:
            self._logger.error("Failed to generate signal: %s", e)
            return None
    
    def validate_signal_params(self, signal_data: Dict) -> tuple[bool, str]:
        """Validate signal parameters before transmission.
        
        Args:
            signal_data: Signal parameters dict
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check frequency
        freq = signal_data.get('center_freq_hz', signal_data.get('frequency', 0))
        if freq < 1e6 or freq > 6e9:
            return False, f"Frequency {freq/1e6:.1f} MHz out of range (1-6000 MHz)"
        
        # Check duration
        duration = signal_data.get('duration_sec', signal_data.get('duration', 0))
        if duration <= 0:
            return False, "Duration must be positive"
        if duration > 10.0:
            return False, f"Duration {duration:.1f}s exceeds 10 second safety limit"
        
        # Check if we have minimum required data
        if 'center_freq_hz' not in signal_data and 'frequency' not in signal_data:
            return False, "Missing frequency information"
        
        return True, ""
