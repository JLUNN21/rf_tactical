"""RF Tactical Monitor - ADS-B Decoder

Launches dump1090 subprocess, connects to Beast binary feed,
decodes ADS-B messages with pyModeS, and maintains aircraft state.
"""

import socket
import subprocess
import time
import sys
from typing import Dict, Optional, Tuple

import numpy as np
from PyQt5.QtCore import QObject, QThread, pyqtSignal, pyqtSlot, QMutex, QMutexLocker

from utils.logger import setup_logger

try:
    import pyModeS as pms
    PYMODE_S_AVAILABLE = True
except ImportError:
    PYMODE_S_AVAILABLE = False


class ADSBDecoder(QObject):
    """ADS-B decoder using dump1090 and pyModeS.

    Manages dump1090 subprocess, connects to Beast binary feed on port 30005,
    decodes messages, maintains aircraft state dictionary, and emits updates.

    Signals:
        aircraft_updated(dict): Emitted when aircraft data changes. Dict contains
                                all tracked aircraft keyed by ICAO hex string.
        error_occurred(str): Emitted on decoder errors.
        decoder_started(str): Emitted when decoder successfully starts.
        decoder_stopped(): Emitted when decoder stops.

    Args:
        observer_lat: Observer latitude in degrees (for distance calculation).
        observer_lon: Observer longitude in degrees (for distance calculation).
        stale_timeout: Seconds before removing stale aircraft (default 60).
        parent: Optional parent QObject.
    """

    aircraft_updated = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    decoder_started = pyqtSignal(str)
    decoder_stopped = pyqtSignal()

    def __init__(
        self,
        observer_lat: float = 0.0,
        observer_lon: float = 0.0,
        stale_timeout: float = 60.0,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self._observer_lat = observer_lat
        self._observer_lon = observer_lon
        self._stale_timeout = stale_timeout

        self._running = False
        self._mutex = QMutex()

        self._dump1090_process: Optional[subprocess.Popen] = None
        self._socket: Optional[socket.socket] = None

        self._aircraft: Dict[str, dict] = {}
        self._logger = setup_logger(__name__)

    def _launch_dump1090(self) -> bool:
        """Launch dump1090 subprocess with HackRF device type.

        Returns:
            True if subprocess started successfully, False otherwise.
        """
        if sys.platform != "linux":
            self.error_occurred.emit("DECODER OFFLINE - Not available on Windows")
            return False

        try:
            self._dump1090_process = subprocess.Popen(
                [
                    "dump1090",
                    "--device-type", "hackrf",
                    "--net",
                    "--quiet",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
            )

            time.sleep(2.0)

            if self._dump1090_process.poll() is not None:
                stderr_output = self._dump1090_process.stderr.read().decode("utf-8", errors="ignore")
                self._logger.error("dump1090 failed to start: %s", stderr_output)
                self.error_occurred.emit("DECODER OFFLINE")
                return False

            return True

        except FileNotFoundError:
            self._logger.error("dump1090 not found")
            self.error_occurred.emit("DECODER OFFLINE")
            return False
        except Exception as exc:
            self._logger.exception("dump1090 launch failed")
            self.error_occurred.emit("DECODER OFFLINE")
            return False

    def _connect_beast_feed(self) -> bool:
        """Connect to dump1090 Beast binary feed on localhost:30005.

        Returns:
            True if connection successful, False otherwise.
        """
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(5.0)
            self._socket.connect(("127.0.0.1", 30005))
            self._socket.settimeout(1.0)
            return True

        except socket.timeout:
            self._logger.warning("Beast feed connection timeout")
            self.error_occurred.emit("DECODER OFFLINE")
            return False
        except ConnectionRefusedError:
            self._logger.warning("Beast feed connection refused")
            self.error_occurred.emit("DECODER OFFLINE")
            return False
        except Exception as exc:
            self._logger.exception("Beast feed connection failed")
            self.error_occurred.emit("DECODER OFFLINE")
            return False

    def _read_beast_message(self) -> Optional[bytes]:
        """Read one Beast binary message from the socket.

        Beast format: <0x1A> <type> <6-byte timestamp> <signal> <message bytes>

        Returns:
            Raw ADS-B message bytes (7 or 14 bytes), or None on error/timeout.
        """
        try:
            escape_byte = self._socket.recv(1)
            if len(escape_byte) == 0:
                return None
            if escape_byte[0] != 0x1A:
                return None

            msg_type = self._socket.recv(1)
            if len(msg_type) == 0:
                return None

            timestamp = self._socket.recv(6)
            if len(timestamp) < 6:
                return None

            signal = self._socket.recv(1)
            if len(signal) == 0:
                return None

            if msg_type[0] == 0x32:
                msg_len = 7
            elif msg_type[0] == 0x33:
                msg_len = 14
            else:
                return None

            message = self._socket.recv(msg_len)
            if len(message) < msg_len:
                return None

            return message

        except socket.timeout:
            return None
        except Exception:
            return None

    def _decode_message(self, msg: bytes) -> None:
        """Decode ADS-B message with pyModeS and update aircraft state.

        Args:
            msg: Raw ADS-B message bytes (7 or 14 bytes).
        """
        if not PYMODE_S_AVAILABLE:
            return

        try:
            msg_hex = msg.hex().upper()
            df = pms.df(msg_hex)

            if df not in [4, 5, 11, 17, 18, 20, 21]:
                return

            icao = pms.icao(msg_hex)
            if icao is None:
                return

            now = time.time()

            if icao not in self._aircraft:
                self._aircraft[icao] = {
                    "icao": icao,
                    "callsign": None,
                    "altitude": None,
                    "latitude": None,
                    "longitude": None,
                    "velocity": None,
                    "heading": None,
                    "vertical_rate": None,
                    "squawk": None,
                    "last_seen": now,
                    "distance": None,
                    "cpr_even": None,
                    "cpr_even_time": None,
                    "cpr_odd": None,
                    "cpr_odd_time": None,
                }

            aircraft = self._aircraft[icao]
            aircraft["last_seen"] = now

            if df in [17, 18]:
                tc = pms.adsb.typecode(msg_hex)

                if 1 <= tc <= 4:
                    callsign = pms.adsb.callsign(msg_hex)
                    if callsign:
                        aircraft["callsign"] = callsign.strip()

                elif 9 <= tc <= 18:
                    altitude_ft = pms.adsb.altitude(msg_hex)
                    if altitude_ft is not None:
                        aircraft["altitude"] = float(altitude_ft) * 0.3048

                    position = self._update_position(aircraft, msg_hex, now)
                    if position is not None:
                        aircraft["latitude"] = position[0]
                        aircraft["longitude"] = position[1]

                elif tc == 19:
                    velocity = pms.adsb.velocity(msg_hex)
                    if velocity is not None:
                        aircraft["velocity"] = float(velocity[0]) * 0.514444
                        aircraft["heading"] = float(velocity[1])
                        aircraft["vertical_rate"] = float(velocity[2]) * 0.00508

                elif 5 <= tc <= 8:
                    pass

            elif df in [4, 20]:
                altitude_ft = pms.common.altcode(msg_hex)
                if altitude_ft is not None:
                    aircraft["altitude"] = float(altitude_ft) * 0.3048

            elif df in [5, 21]:
                squawk = pms.common.idcode(msg_hex)
                if squawk is not None:
                    aircraft["squawk"] = squawk

            if aircraft["latitude"] is not None and aircraft["longitude"] is not None:
                aircraft["distance"] = self._calculate_distance(
                    aircraft["latitude"],
                    aircraft["longitude"],
                )

        except Exception:
            self._logger.exception("ADS-B decode error")

    def _calculate_distance(self, lat: float, lon: float) -> float:
        """Calculate great circle distance from observer to aircraft.

        Args:
            lat: Aircraft latitude in degrees.
            lon: Aircraft longitude in degrees.

        Returns:
            Distance in meters.
        """
        lat1 = np.radians(self._observer_lat)
        lon1 = np.radians(self._observer_lon)
        lat2 = np.radians(lat)
        lon2 = np.radians(lon)

        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
        c = 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))

        earth_radius = 6371000.0
        return earth_radius * c

    def _remove_stale_aircraft(self) -> None:
        """Remove aircraft that haven't been seen within stale_timeout."""
        now = time.time()
        stale_icaos = [
            icao
            for icao, aircraft in self._aircraft.items()
            if (now - aircraft["last_seen"]) > self._stale_timeout
        ]

        for icao in stale_icaos:
            del self._aircraft[icao]

    def _update_position(
        self,
        aircraft: dict,
        msg_hex: str,
        timestamp: float,
    ) -> Optional[Tuple[float, float]]:
        """Update position using CPR even/odd message pairs.

        Args:
            aircraft: Aircraft data dictionary to update.
            msg_hex: ADS-B message hex string.
            timestamp: Unix timestamp of message receipt.

        Returns:
            (lat, lon) tuple in degrees if position decoded, otherwise None.
        """
        try:
            oe_flag = pms.adsb.oe_flag(msg_hex)
            if oe_flag == 0:
                aircraft["cpr_even"] = msg_hex
                aircraft["cpr_even_time"] = timestamp
            else:
                aircraft["cpr_odd"] = msg_hex
                aircraft["cpr_odd_time"] = timestamp

            even_msg = aircraft.get("cpr_even")
            odd_msg = aircraft.get("cpr_odd")
            t_even = aircraft.get("cpr_even_time")
            t_odd = aircraft.get("cpr_odd_time")

            if not even_msg or not odd_msg or t_even is None or t_odd is None:
                return None

            if abs(t_even - t_odd) > 10.0:
                return None

            lat, lon = pms.adsb.position(
                even_msg,
                odd_msg,
                t_even,
                t_odd,
                self._observer_lat,
                self._observer_lon,
            )

            if lat is None or lon is None:
                return None

            return float(lat), float(lon)

        except Exception:
            self._logger.exception("Position decode error")
            return None

    @pyqtSlot()
    def start_decoder(self) -> None:
        """Start the ADS-B decoder: launch dump1090, connect to Beast feed, decode loop."""
        with QMutexLocker(self._mutex):
            if self._running:
                return
            self._running = True

        if not PYMODE_S_AVAILABLE:
            self._logger.error("pyModeS not installed")
            self.error_occurred.emit("DECODER OFFLINE")
            with QMutexLocker(self._mutex):
                self._running = False
            return

        if not self._launch_dump1090():
            with QMutexLocker(self._mutex):
                self._running = False
            return

        time.sleep(3.0)

        if not self._connect_beast_feed():
            self._stop_dump1090()
            with QMutexLocker(self._mutex):
                self._running = False
            return

        self.decoder_started.emit("ADS-B decoder active — receiving Beast feed")

        last_stale_check = time.time()
        last_emit = time.time()

        while True:
            with QMutexLocker(self._mutex):
                if not self._running:
                    break

            msg = self._read_beast_message()
            if msg is not None:
                self._decode_message(msg)

            now = time.time()

            if (now - last_stale_check) > 5.0:
                self._remove_stale_aircraft()
                last_stale_check = now

            if (now - last_emit) > 0.5:
                self.aircraft_updated.emit(dict(self._aircraft))
                last_emit = now

        self._disconnect_beast_feed()
        self._stop_dump1090()
        self.decoder_stopped.emit()

    @pyqtSlot()
    def stop_decoder(self) -> None:
        """Signal the decoder loop to stop."""
        with QMutexLocker(self._mutex):
            self._running = False

    def _disconnect_beast_feed(self) -> None:
        """Close the Beast feed socket."""
        if self._socket is not None:
            try:
                self._socket.close()
            except Exception:
                self._logger.exception("Beast feed close failed")
            self._socket = None

    def _stop_dump1090(self) -> None:
        """Terminate the dump1090 subprocess."""
        if self._dump1090_process is not None:
            try:
                self._dump1090_process.terminate()
                self._dump1090_process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self._dump1090_process.kill()
                self._dump1090_process.wait()
            except Exception:
                self._logger.exception("dump1090 stop failed")
            self._dump1090_process = None

    @pyqtSlot(float, float)
    def set_observer_position(self, lat: float, lon: float) -> None:
        """Update observer position for distance calculations.

        Args:
            lat: Observer latitude in degrees.
            lon: Observer longitude in degrees.
        """
        with QMutexLocker(self._mutex):
            self._observer_lat = lat
            self._observer_lon = lon

    @property
    def is_running(self) -> bool:
        """Whether the decoder is currently active."""
        with QMutexLocker(self._mutex):
            return self._running

    @property
    def aircraft_count(self) -> int:
        """Number of currently tracked aircraft."""
        return len(self._aircraft)


class ADSBDecoderManager(QObject):
    """Manages ADSBDecoder on a dedicated QThread.

    Provides high-level start/stop interface for the GUI.

    Signals:
        aircraft_updated(dict): Forwarded from ADSBDecoder.
        error_occurred(str): Forwarded from ADSBDecoder.
        decoder_started(str): Forwarded from ADSBDecoder.
        decoder_stopped(): Forwarded from ADSBDecoder.

    Args:
        observer_lat: Observer latitude in degrees.
        observer_lon: Observer longitude in degrees.
        stale_timeout: Seconds before removing stale aircraft.
        parent: Optional parent QObject.
    """

    aircraft_updated = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    decoder_started = pyqtSignal(str)
    decoder_stopped = pyqtSignal()

    def __init__(
        self,
        observer_lat: float = 0.0,
        observer_lon: float = 0.0,
        stale_timeout: float = 60.0,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self._observer_lat = observer_lat
        self._observer_lon = observer_lon
        self._stale_timeout = stale_timeout

        self._thread: Optional[QThread] = None
        self._decoder: Optional[ADSBDecoder] = None

    def _setup_decoder(self) -> None:
        """Create the decoder and thread, wire up signals."""
        self._thread = QThread()
        self._thread.setObjectName("ADSBDecoderThread")

        self._decoder = ADSBDecoder(
            observer_lat=self._observer_lat,
            observer_lon=self._observer_lon,
            stale_timeout=self._stale_timeout,
        )

        self._decoder.moveToThread(self._thread)

        self._decoder.aircraft_updated.connect(self.aircraft_updated)
        self._decoder.error_occurred.connect(self.error_occurred)
        self._decoder.decoder_started.connect(self.decoder_started)
        self._decoder.decoder_stopped.connect(self._on_decoder_stopped)

        self._thread.started.connect(self._decoder.start_decoder)
        self._thread.finished.connect(self._on_thread_finished)

    def _on_decoder_stopped(self) -> None:
        """Handle decoder signaling stopped — stop the thread."""
        self.decoder_stopped.emit()
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()

    def _on_thread_finished(self) -> None:
        """Clean up after the thread finishes."""
        if self._decoder is not None:
            self._decoder.deleteLater()
            self._decoder = None
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None

    @pyqtSlot()
    def start(self) -> None:
        """Start ADS-B decoder on a new thread."""
        if self._thread is not None and self._thread.isRunning():
            return

        self._setup_decoder()
        self._thread.start()

    @pyqtSlot()
    def stop(self) -> None:
        """Stop ADS-B decoder and shut down the thread."""
        if self._decoder is not None:
            self._decoder.stop_decoder()

        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(5000)

    @pyqtSlot(float, float)
    def set_observer_position(self, lat: float, lon: float) -> None:
        """Update observer position for distance calculations.

        Args:
            lat: Observer latitude in degrees.
            lon: Observer longitude in degrees.
        """
        self._observer_lat = lat
        self._observer_lon = lon

        if self._decoder is not None:
            self._decoder.set_observer_position(lat, lon)

    @property
    def is_running(self) -> bool:
        """Whether the decoder is currently active."""
        if self._thread is not None and self._thread.isRunning():
            return True
        return False

    def shutdown(self) -> None:
        """Forcefully stop and clean up all resources."""
        self.stop()
        if self._thread is not None:
            if self._thread.isRunning():
                self._thread.terminate()
                self._thread.wait(2000)
            self._thread = None
        self._decoder = None
