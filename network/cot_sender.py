"""RF Tactical Monitor - CoT Sender.

Sends CoT messages via UDP multicast on a periodic schedule.
"""

import socket
import time
from typing import Dict, Optional

from PyQt5.QtCore import QObject, QThread, pyqtSignal, pyqtSlot, QMutex, QMutexLocker

from network.cot_templates import build_aircraft_cot, build_sensor_cot
from utils.logger import setup_logger


class CoTSender(QObject):
    """CoT sender that multicasts aircraft and sensor events.

    Signals:
        error_occurred(str): Emitted on send errors.
        sender_started(str): Emitted when sender starts.
        sender_stopped(): Emitted when sender stops.

    Args:
        multicast_group: Multicast group IP.
        multicast_port: Multicast port.
        poll_interval: Poll interval in seconds.
        enabled: Initial enabled state.
        parent: Optional parent QObject.
    """

    error_occurred = pyqtSignal(str)
    sender_started = pyqtSignal(str)
    sender_stopped = pyqtSignal()

    def __init__(
        self,
        multicast_group: str = "239.2.3.1",
        multicast_port: int = 6969,
        poll_interval: float = 5.0,
        enabled: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._multicast_group = multicast_group
        self._multicast_port = multicast_port
        self._poll_interval = poll_interval
        self._enabled = enabled

        self._mutex = QMutex()
        self._running = False
        self._socket: Optional[socket.socket] = None
        self._aircraft: Dict[str, dict] = {}
        self._sensors: Dict[str, dict] = {}
        self._logger = setup_logger(__name__)
        self._last_send_error = 0.0

    def _create_socket(self) -> Optional[socket.socket]:
        """Create UDP multicast socket.

        Returns:
            Configured socket or None on error.
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
            return sock
        except Exception as exc:
            self._logger.exception("CoT socket error")
            self.error_occurred.emit("COT OFFLINE")
            return None

    def _send_payload(self, payload: bytes) -> None:
        """Send a payload via multicast socket."""
        if self._socket is None:
            return
        try:
            self._socket.sendto(payload, (self._multicast_group, self._multicast_port))
        except Exception:
            now = time.time()
            if now - self._last_send_error > 30:
                self._logger.exception("CoT send failed")
                self._last_send_error = now

    def _send_aircraft(self, aircraft: dict) -> None:
        """Send CoT for one aircraft record."""
        lat = aircraft.get("latitude")
        lon = aircraft.get("longitude")
        alt_m = aircraft.get("altitude")
        if lat is None or lon is None or alt_m is None:
            return

        payload = build_aircraft_cot(
            icao=str(aircraft.get("icao", "UNKNOWN")),
            callsign=aircraft.get("callsign"),
            lat=float(lat),
            lon=float(lon),
            alt_m=float(alt_m),
            speed_mps=aircraft.get("velocity"),
            course_deg=aircraft.get("heading"),
            military=bool(aircraft.get("military", False)),
        )
        self._send_payload(payload)

    def _send_sensor(self, sensor: dict) -> None:
        """Send CoT for one sensor record."""
        lat = sensor.get("lat")
        lon = sensor.get("lon")
        if lat is None or lon is None:
            return

        payload = build_sensor_cot(
            uid=str(sensor.get("uid", "sensor")),
            callsign=str(sensor.get("callsign", "SENSOR")),
            lat=float(lat),
            lon=float(lon),
            remarks=sensor.get("remarks"),
        )
        self._send_payload(payload)

    @pyqtSlot()
    def start_sender(self) -> None:
        """Start the sender loop."""
        with QMutexLocker(self._mutex):
            if self._running:
                return
            self._running = True

        self._socket = self._create_socket()
        if self._socket is None:
            with QMutexLocker(self._mutex):
                self._running = False
            self.sender_stopped.emit()
            return

        self.sender_started.emit("COT SENDER ACTIVE")

        while True:
            with QMutexLocker(self._mutex):
                if not self._running:
                    break
                enabled = self._enabled
                aircraft_copy = dict(self._aircraft)
                sensors_copy = dict(self._sensors)

            if enabled:
                for aircraft in aircraft_copy.values():
                    self._send_aircraft(aircraft)
                for sensor in sensors_copy.values():
                    self._send_sensor(sensor)

            sleep_until = time.time() + self._poll_interval
            while time.time() < sleep_until:
                with QMutexLocker(self._mutex):
                    if not self._running:
                        break
                time.sleep(0.2)

        if self._socket is not None:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None

        self.sender_stopped.emit()

    @pyqtSlot()
    def stop_sender(self) -> None:
        """Stop the sender loop."""
        with QMutexLocker(self._mutex):
            self._running = False

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable sending."""
        with QMutexLocker(self._mutex):
            self._enabled = enabled

    def update_aircraft(self, aircraft: Dict[str, dict]) -> None:
        """Update aircraft data dictionary.

        Args:
            aircraft: Dict keyed by ICAO.
        """
        with QMutexLocker(self._mutex):
            self._aircraft = dict(aircraft)

    def update_sensors(self, sensors: Dict[str, dict]) -> None:
        """Update sensor data dictionary.

        Args:
            sensors: Dict keyed by sensor UID.
        """
        with QMutexLocker(self._mutex):
            self._sensors = dict(sensors)

    @property
    def is_running(self) -> bool:
        """Whether the sender is currently active."""
        with QMutexLocker(self._mutex):
            return self._running


class CoTSenderManager(QObject):
    """Manage CoTSender on a dedicated QThread."""

    error_occurred = pyqtSignal(str)
    sender_started = pyqtSignal(str)
    sender_stopped = pyqtSignal()

    def __init__(
        self,
        multicast_group: str = "239.2.3.1",
        multicast_port: int = 6969,
        poll_interval: float = 5.0,
        enabled: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._multicast_group = multicast_group
        self._multicast_port = multicast_port
        self._poll_interval = poll_interval
        self._enabled = enabled

        self._thread: Optional[QThread] = None
        self._sender: Optional[CoTSender] = None

    def _setup_sender(self) -> None:
        """Create sender and thread, wire signals."""
        self._thread = QThread()
        self._thread.setObjectName("CoTSenderThread")

        self._sender = CoTSender(
            multicast_group=self._multicast_group,
            multicast_port=self._multicast_port,
            poll_interval=self._poll_interval,
            enabled=self._enabled,
        )
        self._sender.moveToThread(self._thread)

        self._sender.error_occurred.connect(self.error_occurred)
        self._sender.sender_started.connect(self.sender_started)
        self._sender.sender_stopped.connect(self._on_sender_stopped)

        self._thread.started.connect(self._sender.start_sender)
        self._thread.finished.connect(self._on_thread_finished)

    def _on_sender_stopped(self) -> None:
        """Handle sender stop — stop the thread."""
        self.sender_stopped.emit()
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()

    def _on_thread_finished(self) -> None:
        """Clean up after thread finishes."""
        if self._sender is not None:
            self._sender.deleteLater()
            self._sender = None
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None

    @pyqtSlot()
    def start(self) -> None:
        """Start the CoT sender thread."""
        if self._thread is not None and self._thread.isRunning():
            return

        self._setup_sender()
        self._thread.start()

    @pyqtSlot()
    def stop(self) -> None:
        """Stop the CoT sender."""
        if self._sender is not None:
            self._sender.stop_sender()

        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(5000)

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable sending."""
        self._enabled = enabled
        if self._sender is not None:
            self._sender.set_enabled(enabled)

    def update_aircraft(self, aircraft: Dict[str, dict]) -> None:
        """Update aircraft data for sending."""
        if self._sender is not None:
            self._sender.update_aircraft(aircraft)

    def update_sensors(self, sensors: Dict[str, dict]) -> None:
        """Update sensor data for sending."""
        if self._sender is not None:
            self._sender.update_sensors(sensors)

    @property
    def is_running(self) -> bool:
        """Whether the sender is currently active."""
        if self._thread is not None and self._thread.isRunning():
            return True
        return False

    def shutdown(self) -> None:
        """Forcefully stop and clean up resources."""
        self.stop()
        if self._thread is not None:
            if self._thread.isRunning():
                self._thread.terminate()
                self._thread.wait(2000)
            self._thread = None
        self._sender = None