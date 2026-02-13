"""RF Tactical Monitor - Signal Fingerprint Library

Automatically identify common ISM devices based on signal characteristics.
"""

import json
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict
import logging


@dataclass
class SignalFingerprint:
    """Known ISM signal characteristics."""
    name: str
    device_type: str  # "Weather Station", "Garage Door", "TPMS", "Doorbell", etc.
    frequency_hz: float
    frequency_tolerance_hz: float  # ±tolerance
    bandwidth_hz: float
    bandwidth_tolerance_hz: float
    duration_sec: float
    duration_tolerance_sec: float
    modulation: str  # "OOK", "FSK", "Unknown"
    manufacturer: str = ""
    notes: str = ""
    icon: str = "🔘"  # Emoji icon


class SignalLibrary:
    """Manage known ISM signal database."""
    
    # Pre-populated common devices
    DEFAULT_SIGNALS = [
        # Weather Stations (433 MHz)
        SignalFingerprint(
            name="Acurite Weather Sensor",
            device_type="Weather Station",
            frequency_hz=433920000,
            frequency_tolerance_hz=50000,
            bandwidth_hz=25000,
            bandwidth_tolerance_hz=10000,
            duration_sec=0.3,
            duration_tolerance_sec=0.2,
            modulation="OOK",
            manufacturer="Acurite",
            icon="🌡️"
        ),
        SignalFingerprint(
            name="LaCrosse Temperature Sensor",
            device_type="Weather Station",
            frequency_hz=433920000,
            frequency_tolerance_hz=50000,
            bandwidth_hz=30000,
            bandwidth_tolerance_hz=10000,
            duration_sec=0.4,
            duration_tolerance_sec=0.2,
            modulation="OOK",
            manufacturer="LaCrosse",
            icon="🌡️"
        ),
        SignalFingerprint(
            name="Oregon Scientific Sensor",
            device_type="Weather Station",
            frequency_hz=433920000,
            frequency_tolerance_hz=50000,
            bandwidth_hz=28000,
            bandwidth_tolerance_hz=10000,
            duration_sec=0.35,
            duration_tolerance_sec=0.2,
            modulation="OOK",
            manufacturer="Oregon Scientific",
            icon="🌡️"
        ),
        
        # Garage Doors (315 MHz)
        SignalFingerprint(
            name="Chamberlain Garage Door",
            device_type="Garage Door",
            frequency_hz=315000000,
            frequency_tolerance_hz=100000,
            bandwidth_hz=50000,
            bandwidth_tolerance_hz=20000,
            duration_sec=0.1,
            duration_tolerance_sec=0.05,
            modulation="OOK",
            manufacturer="Chamberlain",
            icon="🚪"
        ),
        SignalFingerprint(
            name="LiftMaster Garage Door",
            device_type="Garage Door",
            frequency_hz=315000000,
            frequency_tolerance_hz=100000,
            bandwidth_hz=45000,
            bandwidth_tolerance_hz=20000,
            duration_sec=0.08,
            duration_tolerance_sec=0.04,
            modulation="OOK",
            manufacturer="LiftMaster",
            icon="🚪"
        ),
        SignalFingerprint(
            name="Genie Garage Door",
            device_type="Garage Door",
            frequency_hz=315000000,
            frequency_tolerance_hz=100000,
            bandwidth_hz=55000,
            bandwidth_tolerance_hz=20000,
            duration_sec=0.12,
            duration_tolerance_sec=0.06,
            modulation="OOK",
            manufacturer="Genie",
            icon="🚪"
        ),
        
        # TPMS (315 MHz & 433 MHz)
        SignalFingerprint(
            name="Tire Pressure Monitor (315 MHz)",
            device_type="TPMS",
            frequency_hz=315000000,
            frequency_tolerance_hz=100000,
            bandwidth_hz=60000,
            bandwidth_tolerance_hz=30000,
            duration_sec=0.05,
            duration_tolerance_sec=0.03,
            modulation="FSK",
            manufacturer="Generic",
            icon="🚗"
        ),
        SignalFingerprint(
            name="Tire Pressure Monitor (433 MHz)",
            device_type="TPMS",
            frequency_hz=433920000,
            frequency_tolerance_hz=100000,
            bandwidth_hz=65000,
            bandwidth_tolerance_hz=30000,
            duration_sec=0.06,
            duration_tolerance_sec=0.03,
            modulation="FSK",
            manufacturer="Generic",
            icon="🚗"
        ),
        
        # Doorbells (433 MHz)
        SignalFingerprint(
            name="Wireless Doorbell",
            device_type="Doorbell",
            frequency_hz=433920000,
            frequency_tolerance_hz=50000,
            bandwidth_hz=35000,
            bandwidth_tolerance_hz=15000,
            duration_sec=0.5,
            duration_tolerance_sec=0.3,
            modulation="OOK",
            manufacturer="Generic",
            icon="🔔"
        ),
        SignalFingerprint(
            name="Ring Doorbell Chime",
            device_type="Doorbell",
            frequency_hz=433920000,
            frequency_tolerance_hz=50000,
            bandwidth_hz=40000,
            bandwidth_tolerance_hz=15000,
            duration_sec=0.6,
            duration_tolerance_sec=0.3,
            modulation="OOK",
            manufacturer="Ring",
            icon="🔔"
        ),
        
        # Key Fobs (315 MHz & 433 MHz)
        SignalFingerprint(
            name="Car Key Fob (315 MHz)",
            device_type="Key Fob",
            frequency_hz=315000000,
            frequency_tolerance_hz=100000,
            bandwidth_hz=40000,
            bandwidth_tolerance_hz=20000,
            duration_sec=0.08,
            duration_tolerance_sec=0.04,
            modulation="OOK",
            manufacturer="Generic",
            icon="🔑"
        ),
        SignalFingerprint(
            name="Car Key Fob (433 MHz)",
            device_type="Key Fob",
            frequency_hz=433920000,
            frequency_tolerance_hz=100000,
            bandwidth_hz=42000,
            bandwidth_tolerance_hz=20000,
            duration_sec=0.09,
            duration_tolerance_sec=0.04,
            modulation="OOK",
            manufacturer="Generic",
            icon="🔑"
        ),
        
        # Security Systems (433 MHz)
        SignalFingerprint(
            name="Window/Door Sensor",
            device_type="Security Sensor",
            frequency_hz=433920000,
            frequency_tolerance_hz=50000,
            bandwidth_hz=32000,
            bandwidth_tolerance_hz=15000,
            duration_sec=0.2,
            duration_tolerance_sec=0.1,
            modulation="OOK",
            manufacturer="Generic",
            icon="🚨"
        ),
        SignalFingerprint(
            name="Motion Detector",
            device_type="Security Sensor",
            frequency_hz=433920000,
            frequency_tolerance_hz=50000,
            bandwidth_hz=30000,
            bandwidth_tolerance_hz=15000,
            duration_sec=0.25,
            duration_tolerance_sec=0.15,
            modulation="OOK",
            manufacturer="Generic",
            icon="🚨"
        ),
    ]
    
    def __init__(self, library_path="config/signal_library.json"):
        """Initialize signal library.
        
        Args:
            library_path: Path to JSON file for persistent storage.
        """
        self.library_path = Path(library_path)
        self.signals: List[SignalFingerprint] = []
        self.logger = logging.getLogger(__name__)
        self.load()
    
    def load(self):
        """Load signal library from JSON or create with defaults."""
        if self.library_path.exists():
            try:
                with open(self.library_path, 'r') as f:
                    data = json.load(f)
                    self.signals = [SignalFingerprint(**s) for s in data]
                self.logger.info("Loaded %d signals from library", len(self.signals))
            except Exception as e:
                self.logger.error("Failed to load signal library: %s", e)
                self.signals = self.DEFAULT_SIGNALS.copy()
        else:
            # First run - create with defaults
            self.signals = self.DEFAULT_SIGNALS.copy()
            self.save()
            self.logger.info("Created signal library with %d default signals", len(self.signals))
    
    def save(self):
        """Save signal library to JSON."""
        self.library_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.library_path, 'w') as f:
                json.dump([asdict(s) for s in self.signals], f, indent=2)
            self.logger.info("Saved signal library")
        except Exception as e:
            self.logger.error("Failed to save signal library: %s", e)
    
    def match_signal(self, freq: float, bw: float, duration: float) -> Optional[Dict]:
        """Find best matching signal in library.
        
        Args:
            freq: Signal center frequency in Hz.
            bw: Signal bandwidth in Hz.
            duration: Signal duration in seconds.
        
        Returns:
            Dict with match info if found with >70% confidence, else None.
            Dict contains: fingerprint, confidence, score_breakdown
        """
        best_match = None
        best_score = 0.0
        best_breakdown = {}
        
        for sig in self.signals:
            # Calculate match score for each parameter
            freq_diff = abs(freq - sig.frequency_hz)
            freq_score = 1.0 if freq_diff <= sig.frequency_tolerance_hz else \
                        max(0, 1.0 - (freq_diff / (sig.frequency_tolerance_hz * 2)))
            
            bw_diff = abs(bw - sig.bandwidth_hz)
            bw_score = 1.0 if bw_diff <= sig.bandwidth_tolerance_hz else \
                      max(0, 1.0 - (bw_diff / (sig.bandwidth_tolerance_hz * 2)))
            
            dur_diff = abs(duration - sig.duration_sec)
            dur_score = 1.0 if dur_diff <= sig.duration_tolerance_sec else \
                       max(0, 1.0 - (dur_diff / (sig.duration_tolerance_sec * 2)))
            
            # Weighted average (frequency most important)
            score = (freq_score * 0.5) + (bw_score * 0.3) + (dur_score * 0.2)
            
            if score > best_score:
                best_score = score
                best_match = sig
                best_breakdown = {
                    'frequency_score': freq_score,
                    'bandwidth_score': bw_score,
                    'duration_score': dur_score,
                }
        
        # Return match if confidence > 70%
        if best_match and best_score > 0.7:
            self.logger.info("Matched signal: %s (%.0f%% confidence)", 
                           best_match.name, best_score * 100)
            return {
                'fingerprint': best_match,
                'confidence': best_score,
                'score_breakdown': best_breakdown,
            }
        
        return None
    
    def add_custom_signal(self, name: str, device_type: str, freq: float, 
                         bw: float, duration: float, modulation: str = "Unknown",
                         manufacturer: str = "Custom", icon: str = "🔘"):
        """Add user-defined signal to library.
        
        Args:
            name: Signal/device name.
            device_type: Type category.
            freq: Center frequency in Hz.
            bw: Bandwidth in Hz.
            duration: Duration in seconds.
            modulation: Modulation type.
            manufacturer: Manufacturer name.
            icon: Emoji icon.
        """
        sig = SignalFingerprint(
            name=name,
            device_type=device_type,
            frequency_hz=freq,
            frequency_tolerance_hz=freq * 0.01,  # 1% tolerance
            bandwidth_hz=bw,
            bandwidth_tolerance_hz=bw * 0.2,  # 20% tolerance
            duration_sec=duration,
            duration_tolerance_sec=duration * 0.3,  # 30% tolerance
            modulation=modulation,
            manufacturer=manufacturer,
            notes="User-added signal",
            icon=icon
        )
        self.signals.append(sig)
        self.save()
        self.logger.info("Added custom signal: %s", name)
    
    def remove_signal(self, name: str) -> bool:
        """Remove signal from library by name.
        
        Args:
            name: Signal name to remove.
        
        Returns:
            True if removed, False if not found.
        """
        original_count = len(self.signals)
        self.signals = [s for s in self.signals if s.name != name]
        
        if len(self.signals) < original_count:
            self.save()
            self.logger.info("Removed signal: %s", name)
            return True
        
        return False
    
    def get_all_signals(self) -> List[SignalFingerprint]:
        """Get all signals in library.
        
        Returns:
            List of all SignalFingerprint objects.
        """
        return self.signals.copy()
    
    def get_signals_by_type(self, device_type: str) -> List[SignalFingerprint]:
        """Get all signals of a specific type.
        
        Args:
            device_type: Device type to filter by.
        
        Returns:
            List of matching SignalFingerprint objects.
        """
        return [s for s in self.signals if s.device_type == device_type]
