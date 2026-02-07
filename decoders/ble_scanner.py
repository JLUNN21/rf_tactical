"""RF Tactical Monitor - BLE Scanner

Runs BleakScanner in an asyncio loop inside a QThread to collect BLE devices.
"""

import asyncio
import time
from typing import Dict, Optional

from PyQt5.QtCore import QObject, QThread, pyqtSignal, pyqtSlot, QMutex, QMutexLocker

from utils.logger import setup_logger

try:
    from bleak import BleakScanner
    BLEAK_AVAILABLE = True
except ImportError:
    BLEAK_AVAILABLE = False


class BLEScanner(QObject):
    """BLE scanner using BleakScanner.

    Runs an asyncio loop in a worker thread and emits device updates.

    Signals:
        devices_updated(dict): Emitted with dict of devices keyed by MAC.
        error_occurred(str): Emitted on scanner errors.
        scanner_started(str): Emitted when scanner starts.
        scanner_stopped(): Emitted when scanner stops.
    """

    devices_updated = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    scanner_started = pyqtSignal(str)
    scanner_stopped = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._running = False
        self._mutex = QMutex()
        self._devices: Dict[str, dict] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._logger = setup_logger(__name__)

    async def _scan_loop(self) -> None:
        """Async BLE scan loop."""
        if not BLEAK_AVAILABLE:
            self._logger.error("bleak not installed")
            self.error_occurred.emit("DECODER OFFLINE")
            return

        def detection_callback(device, advertisement_data):
            now = time.time()
            name = device.name or "<UNKNOWN>"
            address = device.address
            rssi = device.rssi
            services = advertisement_data.service_uuids or []
            manufacturer_data = advertisement_data.manufacturer_data or {}

            self._devices[address] = {
                "name": name,
                "address": address,
                "rssi": rssi,
                "services": services,
                "manufacturer_data": manufacturer_data,
                "last_seen": now,
            }

            self.devices_updated.emit(dict(self._devices))

        scanner = BleakScanner(detection_callback=detection_callback)

        await scanner.start()
        self.scanner_started.emit("BLE SCANNER ACTIVE")

        try:
            while True:
                with QMutexLocker(self._mutex):
                    if not self._running:
                        break
                await asyncio.sleep(0.5)
        finally:
            await scanner.stop()

    @pyqtSlot()
    def start_scanner(self) -> None:
        """Start BLE scanning in asyncio loop."""
        with QMutexLocker(self._mutex):
            if self._running:
                return
            self._running = True

        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._scan_loop())
        except Exception as exc:
            self._logger.exception("BLE scan error")
            self.error_occurred.emit("DECODER OFFLINE")
        finally:
            if self._loop is not None:
                self._loop.stop()
                self._loop.close()
                self._loop = None
            self.scanner_stopped.emit()

    @pyqtSlot()
    def stop_scanner(self) -> None:
        """Signal the BLE scanner loop to stop."""
        with QMutexLocker(self._mutex):
            self._running = False

    @property
    def is_running(self) -> bool:
        """Whether the scanner is currently active."""
        with QMutexLocker(self._mutex):
            return self._running


class BLEScannerManager(QObject):
    """Manage BLEScanner on a dedicated QThread."""

    devices_updated = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    scanner_started = pyqtSignal(str)
    scanner_stopped = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._thread: Optional[QThread] = None
        self._scanner: Optional[BLEScanner] = None

    def _setup_scanner(self) -> None:
        """Create scanner and thread, wire signals."""
        self._thread = QThread()
        self._thread.setObjectName("BLEScannerThread")

        self._scanner = BLEScanner()
        self._scanner.moveToThread(self._thread)

        self._scanner.devices_updated.connect(self.devices_updated)
        self._scanner.error_occurred.connect(self.error_occurred)
        self._scanner.scanner_started.connect(self.scanner_started)
        self._scanner.scanner_stopped.connect(self._on_scanner_stopped)

        self._thread.started.connect(self._scanner.start_scanner)
        self._thread.finished.connect(self._on_thread_finished)

    def _on_scanner_stopped(self) -> None:
        """Handle scanner stop — stop the thread."""
        self.scanner_stopped.emit()
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()

    def _on_thread_finished(self) -> None:
        """Clean up after thread finishes."""
        if self._scanner is not None:
            self._scanner.deleteLater()
            self._scanner = None
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None

    @pyqtSlot()
    def start(self) -> None:
        """Start BLE scanner on a new thread."""
        if self._thread is not None and self._thread.isRunning():
            return

        self._setup_scanner()
        self._thread.start()

    @pyqtSlot()
    def stop(self) -> None:
        """Stop BLE scanner and shut down the thread."""
        if self._scanner is not None:
            self._scanner.stop_scanner()

        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(5000)

    @property
    def is_running(self) -> bool:
        """Whether the scanner is currently active."""
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
        self._scanner = None