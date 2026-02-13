"""RF Tactical Monitor - Signal Classifier

Basic signal classification inspired by FISSURE's signal identification
and protocol discovery capabilities. Uses heuristic rules based on
frequency, bandwidth, modulation characteristics, and timing patterns.

Provides:
- Known frequency band identification
- Modulation type estimation from signal features
- Protocol/service hints based on frequency + bandwidth
- Threat level assessment

This is a rule-based classifier (no ML required). It uses the feature
data from SignalDetectorV2's FeatureExtractor to make classifications.
"""

from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple


@dataclass
class ClassificationResult:
    """Result of signal classification."""
    signal_type: str          # e.g. "WiFi", "Bluetooth", "FM Radio", "Unknown"
    protocol: str             # e.g. "802.11", "BLE", "P25", ""
    band_name: str            # e.g. "ISM 2.4 GHz", "UHF", "VHF"
    modulation_hint: str      # e.g. "OFDM", "GFSK", "FM", "OOK"
    confidence: float         # 0.0 to 1.0
    threat_level: str         # "none", "low", "medium", "high"
    description: str          # Human-readable description
    tags: List[str]           # Classification tags


# ── Known Frequency Bands ───────────────────────────────────────

FREQUENCY_BANDS = [
    # (low_hz, high_hz, name, common_services)
    (87.5e6, 108e6, "FM Broadcast", ["FM Radio"]),
    (108e6, 137e6, "VHF Air Band", ["Aviation", "ATC"]),
    (137e6, 138e6, "NOAA/Weather Sat", ["NOAA APT", "Meteor M2"]),
    (144e6, 148e6, "2m Amateur", ["Ham Radio 2m"]),
    (148e6, 174e6, "VHF High", ["Business", "Marine"]),
    (150e6, 174e6, "VHF Public Safety", ["Police", "Fire", "EMS"]),
    (162.4e6, 162.55e6, "NOAA Weather Radio", ["NWR"]),
    (220e6, 225e6, "1.25m Amateur", ["Ham Radio 1.25m"]),
    (225e6, 400e6, "UHF Military", ["Military UHF"]),
    (315e6, 315e6 + 1e6, "315 MHz ISM", ["Garage Doors", "Key Fobs", "TPMS"]),
    (390e6, 395e6, "390 MHz ISM", ["Car Remotes"]),
    (400e6, 406e6, "UHF Satellite", ["EPIRB", "Satellite"]),
    (420e6, 450e6, "70cm Amateur", ["Ham Radio 70cm"]),
    (433e6, 434.79e6, "433 MHz ISM", ["IoT", "Weather Stations", "Remotes", "LoRa"]),
    (450e6, 470e6, "UHF Business", ["Business Radio"]),
    (462e6, 467e6, "FRS/GMRS", ["FRS", "GMRS"]),
    (470e6, 698e6, "UHF TV", ["Digital TV", "Wireless Mics"]),
    (698e6, 960e6, "Cellular", ["LTE", "4G", "5G"]),
    (868e6, 870e6, "868 MHz ISM (EU)", ["LoRa EU", "IoT EU", "Smart Meters"]),
    (902e6, 928e6, "900 MHz ISM", ["LoRa US", "Z-Wave", "Smart Meters"]),
    (960e6, 1215e6, "L-Band Aero", ["DME", "TACAN", "ADS-B"]),
    (1090e6, 1090e6 + 1e6, "ADS-B", ["ADS-B 1090"]),
    (1176e6, 1176.5e6, "GPS L5", ["GPS L5"]),
    (1227.6e6, 1227.6e6 + 1e6, "GPS L2", ["GPS L2"]),
    (1525e6, 1559e6, "Inmarsat/GPS", ["Inmarsat", "GPS"]),
    (1559e6, 1610e6, "GPS L1", ["GPS L1", "GLONASS"]),
    (1710e6, 2170e6, "AWS/PCS Cellular", ["LTE", "AWS"]),
    (2400e6, 2500e6, "2.4 GHz ISM", ["WiFi", "Bluetooth", "ZigBee", "Microwave"]),
    (2500e6, 2700e6, "BRS/EBS", ["WiMAX", "LTE TDD"]),
    (3300e6, 3800e6, "CBRS/5G", ["5G NR", "CBRS"]),
    (5150e6, 5850e6, "5 GHz ISM", ["WiFi 5GHz", "802.11ac/ax"]),
    (5725e6, 5875e6, "5.8 GHz ISM", ["FPV Drones", "WiFi"]),
]

# ── Modulation Signatures ──────────────────────────────────────

MODULATION_SIGNATURES = {
    # (bandwidth_range_hz, duty_cycle_range, burst_type) -> modulation hint
    "wifi_ofdm": {
        "bw_min": 15e6, "bw_max": 40e6,
        "band_min": 2.4e9, "band_max": 5.9e9,
        "hint": "OFDM", "protocol": "802.11",
    },
    "bluetooth": {
        "bw_min": 500e3, "bw_max": 2e6,
        "band_min": 2.4e9, "band_max": 2.5e9,
        "hint": "GFSK", "protocol": "Bluetooth/BLE",
    },
    "lora": {
        "bw_min": 100e3, "bw_max": 500e3,
        "band_min": 433e6, "band_max": 928e6,
        "hint": "CSS (Chirp)", "protocol": "LoRa",
    },
    "ook_remote": {
        "bw_min": 1e3, "bw_max": 200e3,
        "band_min": 300e6, "band_max": 450e6,
        "hint": "OOK/ASK", "protocol": "ISM Remote",
    },
    "fm_broadcast": {
        "bw_min": 100e3, "bw_max": 300e3,
        "band_min": 87.5e6, "band_max": 108e6,
        "hint": "WBFM", "protocol": "FM Broadcast",
    },
    "nbfm_voice": {
        "bw_min": 5e3, "bw_max": 25e3,
        "band_min": 130e6, "band_max": 520e6,
        "hint": "NBFM", "protocol": "Voice Radio",
    },
    "p25": {
        "bw_min": 10e3, "bw_max": 15e3,
        "band_min": 150e6, "band_max": 900e6,
        "hint": "C4FM/CQPSK", "protocol": "P25",
    },
    "dmr": {
        "bw_min": 10e3, "bw_max": 15e3,
        "band_min": 400e6, "band_max": 480e6,
        "hint": "4FSK", "protocol": "DMR",
    },
    "adsb": {
        "bw_min": 1e6, "bw_max": 5e6,
        "band_min": 1088e6, "band_max": 1092e6,
        "hint": "PPM", "protocol": "ADS-B",
    },
    "cellular_lte": {
        "bw_min": 1.4e6, "bw_max": 20e6,
        "band_min": 698e6, "band_max": 2700e6,
        "hint": "OFDMA", "protocol": "LTE",
    },
}


class SignalClassifier:
    """Classifies detected signals based on frequency, bandwidth, and features.

    Inspired by FISSURE's signal identification approach but uses
    simple heuristic rules instead of ML.

    Usage:
        classifier = SignalClassifier()
        result = classifier.classify(
            center_freq_hz=433.92e6,
            bandwidth_hz=50e3,
            features=event.features,  # From FeatureExtractor
        )
        print(result.signal_type, result.confidence)
    """

    def classify(
        self,
        center_freq_hz: float,
        bandwidth_hz: float = 0,
        features: Optional[Dict[str, Any]] = None,
    ) -> ClassificationResult:
        """Classify a signal based on its characteristics.

        Args:
            center_freq_hz: Center frequency in Hz.
            bandwidth_hz: Estimated bandwidth in Hz.
            features: Optional feature dict from FeatureExtractor.

        Returns:
            ClassificationResult with type, protocol, confidence, etc.
        """
        # Step 1: Identify frequency band
        band_name, band_services = self._identify_band(center_freq_hz)

        # Step 2: Try modulation signature matching
        mod_hint, protocol, mod_confidence = self._match_modulation(
            center_freq_hz, bandwidth_hz, features
        )

        # Step 3: Determine signal type
        signal_type = self._determine_type(
            band_services, protocol, mod_hint, features
        )

        # Step 4: Assess threat level
        threat_level = self._assess_threat(
            center_freq_hz, bandwidth_hz, features
        )

        # Step 5: Build description
        description = self._build_description(
            signal_type, band_name, mod_hint, protocol,
            center_freq_hz, bandwidth_hz, features
        )

        # Step 6: Generate tags
        tags = self._generate_tags(
            band_name, band_services, mod_hint, protocol, features
        )

        # Overall confidence
        confidence = mod_confidence
        if features:
            feat_conf = features.get("confidence", {}).get("frequency", 0)
            confidence = max(confidence, feat_conf)

        return ClassificationResult(
            signal_type=signal_type,
            protocol=protocol,
            band_name=band_name,
            modulation_hint=mod_hint,
            confidence=min(1.0, confidence),
            threat_level=threat_level,
            description=description,
            tags=tags,
        )

    def classify_event(self, event) -> ClassificationResult:
        """Classify a SignalEvent from the V2 detector.

        Args:
            event: SignalEvent with features extracted.

        Returns:
            ClassificationResult.
        """
        center_hz = event.last_center if event.last_center else 0
        bw_hz = event.last_bandwidth if event.last_bandwidth else 0
        features = event.features
        return self.classify(center_hz, bw_hz, features)

    def _identify_band(self, freq_hz: float) -> Tuple[str, List[str]]:
        """Identify which frequency band a signal is in."""
        for low, high, name, services in FREQUENCY_BANDS:
            if low <= freq_hz <= high:
                return name, services

        # Generic band identification
        if freq_hz < 30e6:
            return "HF", ["Shortwave"]
        elif freq_hz < 300e6:
            return "VHF", ["VHF"]
        elif freq_hz < 3e9:
            return "UHF", ["UHF"]
        elif freq_hz < 30e9:
            return "SHF", ["Microwave"]
        return "Unknown Band", []

    def _match_modulation(
        self, freq_hz: float, bw_hz: float, features: Optional[Dict]
    ) -> Tuple[str, str, float]:
        """Try to match signal to known modulation signatures."""
        best_match = ("Unknown", "", 0.0)
        best_score = 0.0

        for sig_name, sig in MODULATION_SIGNATURES.items():
            score = 0.0

            # Frequency band match
            if sig["band_min"] <= freq_hz <= sig["band_max"]:
                score += 0.4

            # Bandwidth match
            if bw_hz > 0 and sig["bw_min"] <= bw_hz <= sig["bw_max"]:
                score += 0.4

            # Feature-based refinement
            if features:
                # Duty cycle hints
                duty = features.get("time_structure", {}).get("duty_cycle", 0)
                burst = features.get("time_structure", {}).get("burst_type", "")

                if sig_name == "wifi_ofdm" and burst == "bursty":
                    score += 0.1
                elif sig_name == "fm_broadcast" and burst == "continuous":
                    score += 0.1
                elif sig_name == "ook_remote" and burst == "bursty" and duty < 0.5:
                    score += 0.1

                # Stability hints
                stability = features.get("stability", {}).get("score", 0)
                if sig_name in ("fm_broadcast", "cellular_lte") and stability > 0.8:
                    score += 0.1

            if score > best_score:
                best_score = score
                best_match = (sig["hint"], sig["protocol"], score)

        return best_match

    def _determine_type(
        self, band_services: List[str], protocol: str,
        mod_hint: str, features: Optional[Dict]
    ) -> str:
        """Determine the signal type from all available info."""
        if protocol:
            return protocol

        if band_services:
            return band_services[0]

        if mod_hint and mod_hint != "Unknown":
            return f"{mod_hint} Signal"

        return "Unknown Signal"

    def _assess_threat(
        self, freq_hz: float, bw_hz: float, features: Optional[Dict]
    ) -> str:
        """Assess potential threat level of a signal.

        Heuristic based on:
        - Unusual frequency usage
        - Very high power
        - Wideband noise (potential jamming)
        - Signals in protected bands
        """
        # Check for potential jamming (very wide bandwidth noise)
        if bw_hz > 1e6 and features:
            stability = features.get("stability", {}).get("score", 1.0)
            if stability < 0.3:
                return "high"  # Possible jammer

        # Check for signals in aviation/emergency bands
        if 108e6 <= freq_hz <= 137e6:  # Aviation
            return "medium"
        if 406e6 <= freq_hz <= 406.1e6:  # Emergency beacon
            return "medium"

        # Check for very high power
        if features:
            peak_power = features.get("power", {}).get("peak_power_db", -100)
            if peak_power > -10:
                return "low"

        return "none"

    def _build_description(
        self, signal_type, band_name, mod_hint, protocol,
        freq_hz, bw_hz, features
    ) -> str:
        """Build human-readable description."""
        parts = [f"{signal_type}"]

        if band_name:
            parts.append(f"in {band_name}")

        parts.append(f"at {freq_hz/1e6:.3f} MHz")

        if bw_hz > 0:
            if bw_hz >= 1e6:
                parts.append(f"({bw_hz/1e6:.1f} MHz wide)")
            else:
                parts.append(f"({bw_hz/1e3:.1f} kHz wide)")

        if mod_hint and mod_hint != "Unknown":
            parts.append(f"[{mod_hint}]")

        if features:
            duration = features.get("meta", {}).get("duration_s", 0)
            if duration > 0:
                parts.append(f"dur={duration:.2f}s")

        return " ".join(parts)

    def _generate_tags(
        self, band_name, band_services, mod_hint, protocol, features
    ) -> List[str]:
        """Generate classification tags."""
        tags = []

        if band_name:
            tags.append(band_name)

        tags.extend(band_services)

        if protocol:
            tags.append(protocol)

        if mod_hint and mod_hint != "Unknown":
            tags.append(mod_hint)

        if features:
            burst = features.get("time_structure", {}).get("burst_type", "")
            if burst:
                tags.append(burst)

            bw_unstable = features.get("bandwidth", {}).get("unstable", False)
            if bw_unstable:
                tags.append("unstable_bw")

        return list(set(tags))  # Deduplicate

    @staticmethod
    def get_band_for_frequency(freq_hz: float) -> str:
        """Quick lookup: get band name for a frequency."""
        for low, high, name, _ in FREQUENCY_BANDS:
            if low <= freq_hz <= high:
                return name
        return "Unknown"

    @staticmethod
    def get_all_bands() -> List[Dict]:
        """Get all known frequency bands."""
        return [
            {
                "low_hz": low,
                "high_hz": high,
                "low_mhz": low / 1e6,
                "high_mhz": high / 1e6,
                "name": name,
                "services": services,
            }
            for low, high, name, services in FREQUENCY_BANDS
        ]
