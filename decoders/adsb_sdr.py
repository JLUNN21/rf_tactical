"""RF Tactical Monitor - ADS-B SDR Decoder

Pure-Python ADS-B decoder that uses HackRF via SoapySDR to receive
1090 MHz Mode S signals directly. No dump1090 needed.

Tunes HackRF to 1090 MHz, captures IQ at 2 Msps, detects Mode S
preambles via magnitude envelope, extracts bits, and decodes with pyModeS.

Only accepts DF17/18 (ADS-B Extended Squitter) with CRC=0 to avoid
false positives. Aircraft must have at least one real data field
(callsign, altitude, or position) to be displayed.
"""

import time
import numpy as np
from typing import Optional, List, Dict
from PyQt5.QtCore import QObject, QThread, pyqtSignal, pyqtSlot, QMutex, QMutexLocker

from utils.logger import setup_logger

try:
    import SoapySDR
    from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_CF32
    SOAPY_AVAILABLE = True
except (ImportError, AttributeError):
    SOAPY_AVAILABLE = False

try:
    import pyModeS as pms
    PYMODES_AVAILABLE = True
except ImportError:
    PYMODES_AVAILABLE = False


# Mode S constants
ADSB_FREQ = 1090e6
SAMPLE_RATE = 2e6
SAMPLES_PER_BIT = 2
PREAMBLE_SAMPLES = 16
LONG_MSG_BITS = 112
LONG_MSG_SAMPLES = LONG_MSG_BITS * SAMPLES_PER_BIT
BUFFER_SIZE = 65536       # Smaller buffer = less lag, fewer overflows

# Preamble sample positions (at 2 Msps)
HIGH_POS = np.array([0, 1, 4, 5, 9, 10, 14, 15])
LOW_POS = np.array([2, 3, 7, 8, 11, 12, 13])


class ADSBSDRDecoder(QObject):
    """ADS-B decoder using HackRF via SoapySDR.

    Only decodes DF17/18 (ADS-B) with strict CRC validation.
    """

    aircraft_updated = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    decoder_started = pyqtSignal(str)
    decoder_stopped = pyqtSignal()
    stats_updated = pyqtSignal(dict)

    def __init__(self, observer_lat: float = 0.0, observer_lon: float = 0.0,
                 stale_timeout: float = 30.0, parent=None):
        super().__init__(parent)
        self._observer_lat = observer_lat
        self._observer_lon = observer_lon
        self._stale_timeout = stale_timeout
        self._running = False
        self._mutex = QMutex()
        self._aircraft: Dict[str, dict] = {}
        self._logger = setup_logger(__name__)
        self._sdr = None
        self._rx_stream = None
        self._stop_requested = False

        # Stats
        self._total_msgs = 0
        self._total_crc_pass = 0
        self._total_crc_fail = 0
        self._msg_rate = 0.0

    def _open_sdr(self) -> bool:
        """Open HackRF via SoapySDR for 1090 MHz RX."""
        if not SOAPY_AVAILABLE:
            self.error_occurred.emit("SoapySDR not available")
            return False

        try:
            # Suppress SoapySDR overflow messages
            try:
                SoapySDR.setLogLevel(SoapySDR.SOAPY_SDR_WARNING)
            except Exception:
                pass

            results = SoapySDR.Device.enumerate("driver=hackrf")
            if len(results) == 0:
                self.error_occurred.emit("No HackRF device found")
                return False

            self._sdr = SoapySDR.Device(results[0])
            self._sdr.setSampleRate(SOAPY_SDR_RX, 0, SAMPLE_RATE)
            self._sdr.setFrequency(SOAPY_SDR_RX, 0, ADSB_FREQ)

            # High gains needed for 1090 MHz ADS-B (weak signals)
            # Based on AirRadar project: LNA=40, VGA=62 works well
            self._sdr.setGain(SOAPY_SDR_RX, 0, "LNA", 40)
            self._sdr.setGain(SOAPY_SDR_RX, 0, "VGA", 62)
            self._sdr.setGain(SOAPY_SDR_RX, 0, "AMP", 14)
            self._sdr.setBandwidth(SOAPY_SDR_RX, 0, 1.75e6)

            self._rx_stream = self._sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
            self._sdr.activateStream(self._rx_stream)

            self._logger.info("HackRF opened: 1090 MHz, 2 Msps, LNA=40 VGA=62 AMP=14")
            return True

        except Exception as e:
            self._logger.exception("Failed to open HackRF for ADS-B")
            self.error_occurred.emit("HackRF open failed: %s" % str(e))
            return False

    def _close_sdr(self):
        """Close HackRF SDR safely."""
        try:
            if self._rx_stream is not None and self._sdr is not None:
                self._sdr.deactivateStream(self._rx_stream)
                self._sdr.closeStream(self._rx_stream)
        except Exception:
            pass
        self._rx_stream = None
        self._sdr = None

    def _detect_adsb_messages(self, mag: np.ndarray) -> List[str]:
        """Detect ADS-B (DF17/18 only) messages with strict CRC validation.

        Returns only messages that pass CRC=0 check.
        """
        messages = []
        n = len(mag)
        min_len = PREAMBLE_SAMPLES + LONG_MSG_SAMPLES
        if n < min_len:
            return messages

        # Adaptive threshold: above noise floor but sensitive enough for weak signals
        noise_floor = np.median(mag)
        peak = np.max(mag)
        if peak <= noise_floor * 1.3:
            return messages  # No signals above noise
        threshold = noise_floor * 2.0  # Require 2x noise floor (was 3x, too strict)

        i = 0
        while i < n - min_len:
            # Quick reject: must be well above noise
            if mag[i] < threshold:
                i += 1
                continue

            # Check preamble pattern with strict ratio
            high_avg = np.mean(mag[i + HIGH_POS])
            low_avg = np.mean(mag[i + LOW_POS])

            # Require high pulses > 2x low gaps (strict)
            if high_avg < threshold or low_avg > high_avg * 0.45:
                i += 1
                continue

            # Extract 112-bit message (DF17/18 = ADS-B only)
            msg_start = i + PREAMBLE_SAMPLES
            if msg_start + LONG_MSG_SAMPLES > n:
                break

            # PPM bit extraction using vectorized numpy
            indices = np.arange(LONG_MSG_BITS) * SAMPLES_PER_BIT + msg_start
            first_samples = mag[indices]
            second_samples = mag[indices + 1]
            bits = (first_samples > second_samples).astype(np.uint8)

            # Convert bits to hex
            hex_msg = self._bits_to_hex(bits)
            if hex_msg is None:
                i += 2
                continue

            # STRICT validation: only DF17/18 with CRC=0
            try:
                df = pms.df(hex_msg)
                if df not in (17, 18):
                    i += 2
                    continue

                crc = pms.crc(hex_msg)
                if crc != 0:
                    self._total_crc_fail += 1
                    i += 2
                    continue

                # Valid ADS-B message!
                self._total_crc_pass += 1
                messages.append(hex_msg)
                i = msg_start + LONG_MSG_SAMPLES  # Skip past this message

            except Exception:
                i += 2
                continue

        return messages

    def _bits_to_hex(self, bits: np.ndarray) -> Optional[str]:
        """Convert numpy bit array to hex string."""
        if len(bits) != 112:
            return None
        # Pack bits into nibbles efficiently
        hex_chars = []
        for j in range(0, 112, 4):
            nibble = (bits[j] << 3) | (bits[j+1] << 2) | (bits[j+2] << 1) | bits[j+3]
            hex_chars.append(format(int(nibble), 'X'))
        return ''.join(hex_chars)

    def _decode_message(self, msg_hex: str) -> None:
        """Decode ADS-B DF17/18 message and update aircraft state."""
        try:
            icao = pms.icao(msg_hex)
            if icao is None or len(icao) != 6:
                return

            now = time.time()
            self._total_msgs += 1

            if icao not in self._aircraft:
                self._aircraft[icao] = {
                    "icao": icao, "callsign": None,
                    "altitude": None, "latitude": None, "longitude": None,
                    "velocity": None, "heading": None, "vertical_rate": None,
                    "squawk": None, "last_seen": now, "distance": None,
                    "cpr_even": None, "cpr_even_time": None,
                    "cpr_odd": None, "cpr_odd_time": None,
                    "military": False, "msg_count": 0,
                }

            ac = self._aircraft[icao]
            ac["last_seen"] = now
            ac["msg_count"] = ac.get("msg_count", 0) + 1

            tc = pms.adsb.typecode(msg_hex)

            # Callsign (TC 1-4)
            if 1 <= tc <= 4:
                cs = pms.adsb.callsign(msg_hex)
                if cs:
                    cs = cs.strip()
                    if cs and cs != '________':  # Filter blank callsigns
                        ac["callsign"] = cs

            # Airborne position (TC 9-18)
            elif 9 <= tc <= 18:
                alt = pms.adsb.altitude(msg_hex)
                if alt is not None:
                    ac["altitude"] = float(alt) * 0.3048  # ft -> m

                # CPR position decoding
                oe = pms.adsb.oe_flag(msg_hex)
                if oe == 0:
                    ac["cpr_even"] = msg_hex
                    ac["cpr_even_time"] = now
                else:
                    ac["cpr_odd"] = msg_hex
                    ac["cpr_odd_time"] = now

                # Decode position if we have both even and odd
                if (ac["cpr_even"] and ac["cpr_odd"] and
                        ac["cpr_even_time"] and ac["cpr_odd_time"] and
                        abs(ac["cpr_even_time"] - ac["cpr_odd_time"]) < 10.0):
                    try:
                        lat, lon = pms.adsb.position(
                            ac["cpr_even"], ac["cpr_odd"],
                            ac["cpr_even_time"], ac["cpr_odd_time"],
                            self._observer_lat, self._observer_lon)
                        if lat is not None and lon is not None:
                            # Sanity check: reject impossible positions
                            if -90 <= lat <= 90 and -180 <= lon <= 180:
                                ac["latitude"] = float(lat)
                                ac["longitude"] = float(lon)
                                ac["distance"] = self._calc_distance(lat, lon)
                    except Exception:
                        pass

            # Velocity (TC 19)
            elif tc == 19:
                vel = pms.adsb.velocity(msg_hex)
                if vel:
                    speed_kts = float(vel[0])
                    heading_deg = float(vel[1])
                    vrate_fpm = float(vel[2])
                    # Sanity check velocity
                    if 0 <= speed_kts <= 1000:
                        ac["velocity"] = speed_kts * 0.514444  # kts -> m/s
                    if 0 <= heading_deg <= 360:
                        ac["heading"] = heading_deg
                    if -10000 <= vrate_fpm <= 10000:
                        ac["vertical_rate"] = vrate_fpm * 0.00508  # ft/min -> m/s

            # Military classification
            ac["military"] = self._is_military(ac.get("callsign", ""))

        except Exception:
            pass

    MILITARY_PREFIXES = (
        "RCH", "REACH", "EVAC", "RRR", "DUKE", "KING", "JOLLY", "PEDRO",
        "TOPCAT", "NAVY", "ARMY", "PAT", "SAM", "EXEC", "AF1", "AF2",
        "SPAR", "ASCOT", "RAFR", "GAF", "FAF", "IAM", "CASA", "BAF",
        "RNL", "SUI", "HAF", "PLF", "HUF", "CFC", "CANF", "RAAF",
    )

    @classmethod
    def _is_military(cls, callsign: Optional[str]) -> bool:
        if not callsign:
            return False
        cs = callsign.strip().upper()
        return any(cs.startswith(p) for p in cls.MILITARY_PREFIXES)

    def _calc_distance(self, lat: float, lon: float) -> float:
        """Haversine distance in meters."""
        lat1 = np.radians(self._observer_lat)
        lon1 = np.radians(self._observer_lon)
        lat2 = np.radians(lat)
        lon2 = np.radians(lon)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
        return 6371000.0 * 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))

    def _remove_stale(self):
        """Remove aircraft not seen in stale_timeout seconds."""
        now = time.time()
        stale = [k for k, v in self._aircraft.items()
                 if now - v["last_seen"] > self._stale_timeout]
        for k in stale:
            del self._aircraft[k]

    def _get_displayable_aircraft(self) -> Dict[str, dict]:
        """Return only aircraft with at least one real data field.
        
        Filters out ICAO-only entries that have no callsign, altitude, or position.
        These are likely false positives or Mode S replies with no useful data.
        """
        result = {}
        for icao, ac in self._aircraft.items():
            has_callsign = ac.get("callsign") is not None
            has_altitude = ac.get("altitude") is not None
            has_position = ac.get("latitude") is not None and ac.get("longitude") is not None
            has_velocity = ac.get("velocity") is not None
            # Must have at least one real data field AND more than 1 message
            if (has_callsign or has_altitude or has_position or has_velocity) and ac.get("msg_count", 0) >= 2:
                result[icao] = ac
        return result

    @pyqtSlot()
    def start_decoder(self):
        """Main decode loop: open HackRF, capture IQ, detect & decode."""
        with QMutexLocker(self._mutex):
            if self._running:
                return
            self._running = True
            self._stop_requested = False

        if not PYMODES_AVAILABLE:
            self.error_occurred.emit("pyModeS not installed")
            with QMutexLocker(self._mutex):
                self._running = False
            return

        if not self._open_sdr():
            with QMutexLocker(self._mutex):
                self._running = False
            return

        self.decoder_started.emit("ADS-B ACTIVE -- HackRF direct 1090 MHz")
        self._logger.info("ADS-B SDR decoder started on 1090 MHz")

        buf = np.zeros(BUFFER_SIZE, dtype=np.complex64)
        last_stale = time.time()
        last_emit = time.time()
        last_stats = time.time()
        msgs_this_sec = 0
        sec_start = time.time()

        try:
            while True:
                with QMutexLocker(self._mutex):
                    if not self._running:
                        break

                try:
                    sr = self._sdr.readStream(self._rx_stream, [buf], BUFFER_SIZE,
                                               timeoutUs=500000)  # 500ms timeout
                    if sr.ret <= 0:
                        continue

                    samples = buf[:sr.ret]
                    mag = np.abs(samples)

                    # Detect only DF17/18 ADS-B with CRC=0
                    hex_msgs = self._detect_adsb_messages(mag)

                    for msg in hex_msgs:
                        self._decode_message(msg)
                        msgs_this_sec += 1

                except Exception:
                    time.sleep(0.01)
                    continue

                now = time.time()

                # Message rate
                if now - sec_start >= 1.0:
                    self._msg_rate = msgs_this_sec / (now - sec_start)
                    msgs_this_sec = 0
                    sec_start = now

                # Remove stale aircraft
                if now - last_stale > 5.0:
                    self._remove_stale()
                    last_stale = now

                # Emit displayable aircraft at 2 Hz
                if now - last_emit > 0.5:
                    displayable = self._get_displayable_aircraft()
                    self.aircraft_updated.emit(displayable)
                    last_emit = now

                # Emit stats every 2 seconds
                if now - last_stats > 2.0:
                    displayable = self._get_displayable_aircraft()
                    self.stats_updated.emit({
                        "total_msgs": self._total_msgs,
                        "total_crc_pass": self._total_crc_pass,
                        "total_crc_fail": self._total_crc_fail,
                        "msg_rate": self._msg_rate,
                        "aircraft_count": len(displayable),
                        "raw_icao_count": len(self._aircraft),
                    })
                    last_stats = now

        finally:
            # Always close SDR, even on exception
            self._close_sdr()
            self.decoder_stopped.emit()
            self._logger.info("ADS-B SDR decoder stopped (total: %d msgs, %d CRC pass, %d CRC fail)",
                            self._total_msgs, self._total_crc_pass, self._total_crc_fail)

    @pyqtSlot()
    def stop_decoder(self):
        """Signal the decoder loop to stop."""
        with QMutexLocker(self._mutex):
            self._running = False
            self._stop_requested = True

    @pyqtSlot(float, float)
    def set_observer_position(self, lat: float, lon: float):
        with QMutexLocker(self._mutex):
            self._observer_lat = lat
            self._observer_lon = lon

    @property
    def is_running(self) -> bool:
        with QMutexLocker(self._mutex):
            return self._running


class ADSBSDRManager(QObject):
    """Manages ADSBSDRDecoder on a dedicated QThread.

    Drop-in replacement for ADSBDecoderManager that uses HackRF directly.
    """

    aircraft_updated = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    decoder_started = pyqtSignal(str)
    decoder_stopped = pyqtSignal()
    stats_updated = pyqtSignal(dict)

    def __init__(self, observer_lat: float = 0.0, observer_lon: float = 0.0,
                 stale_timeout: float = 30.0, parent=None):
        super().__init__(parent)
        self._observer_lat = observer_lat
        self._observer_lon = observer_lon
        self._stale_timeout = stale_timeout
        self._thread: Optional[QThread] = None
        self._decoder: Optional[ADSBSDRDecoder] = None

    def _setup(self):
        self._thread = QThread()
        self._thread.setObjectName("ADSBSDRThread")
        self._decoder = ADSBSDRDecoder(
            observer_lat=self._observer_lat,
            observer_lon=self._observer_lon,
            stale_timeout=self._stale_timeout,
        )
        self._decoder.moveToThread(self._thread)
        self._decoder.aircraft_updated.connect(self.aircraft_updated)
        self._decoder.error_occurred.connect(self.error_occurred)
        self._decoder.decoder_started.connect(self.decoder_started)
        self._decoder.decoder_stopped.connect(self._on_stopped)
        self._decoder.stats_updated.connect(self.stats_updated)
        self._thread.started.connect(self._decoder.start_decoder)
        self._thread.finished.connect(self._on_finished)

    def _on_stopped(self):
        self.decoder_stopped.emit()
        if self._thread and self._thread.isRunning():
            self._thread.quit()

    def _on_finished(self):
        if self._decoder:
            self._decoder.deleteLater()
            self._decoder = None
        if self._thread:
            self._thread.deleteLater()
            self._thread = None

    @pyqtSlot()
    def start(self):
        if self._thread and self._thread.isRunning():
            return
        self._setup()
        self._thread.start()

    @pyqtSlot()
    def stop(self):
        """Stop the decoder (non-blocking -- thread cleans up via signals)."""
        if self._decoder:
            self._decoder.stop_decoder()
        # Don't block the GUI thread waiting for the SDR thread to finish.
        # The thread will emit decoder_stopped -> _on_stopped -> quit.
        # If it doesn't stop within 5s, a safety timer will force-terminate.
        if self._thread and self._thread.isRunning():
            QTimer = __import__('PyQt5.QtCore', fromlist=['QTimer']).QTimer
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(self._force_stop)
            timer.start(5000)
            self._stop_timer = timer  # prevent GC

    def _force_stop(self):
        """Force-terminate the thread if it didn't stop cleanly."""
        if self._thread and self._thread.isRunning():
            self._thread.terminate()
            self._thread.wait(1000)
        self._stop_timer = None

    @pyqtSlot(float, float)
    def set_observer_position(self, lat: float, lon: float):
        self._observer_lat = lat
        self._observer_lon = lon
        if self._decoder:
            self._decoder.set_observer_position(lat, lon)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def shutdown(self):
        """Forcefully stop and clean up all resources."""
        self.stop()
        self._thread = None
        self._decoder = None
