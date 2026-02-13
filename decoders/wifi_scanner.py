"""RF Tactical Monitor - Wi-Fi Scanner

Scans wlan0 with iwlist, parses results, and emits network updates.
"""

import re
import subprocess
import time
import sys
from typing import Dict, Optional

from PyQt5.QtCore import QObject, QThread, pyqtSignal, pyqtSlot, QMutex, QMutexLocker

from utils.logger import setup_logger


class WiFiScanner(QObject):
    """Wi-Fi scanner using iwlist on wlan0.

    Executes `sudo iwlist wlan0 scan` every 10 seconds, parses
    SSID, BSSID, channel, frequency, signal level, encryption, and
    maintains network state keyed by BSSID.

    Signals:
        networks_updated(dict): Emitted when network data updates.
        error_occurred(str): Emitted on scan errors.
        scanner_started(str): Emitted when scanner starts.
        scanner_stopped(): Emitted when scanner stops.
    """

    networks_updated = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    scanner_started = pyqtSignal(str)
    scanner_stopped = pyqtSignal()

    def __init__(self, scan_interval: float = 10.0, parent=None) -> None:
        super().__init__(parent)
        self._scan_interval = scan_interval
        self._running = False
        self._mutex = QMutex()
        self._networks: Dict[str, dict] = {}
        self._logger = setup_logger(__name__)

        self._cell_re = re.compile(r"Cell \d+ - Address: (?P<bssid>[A-F0-9:]{17})", re.IGNORECASE)
        self._ssid_re = re.compile(r'ESSID:"(?P<ssid>.*)"')
        self._channel_re = re.compile(r"Channel:(?P<channel>\d+)")
        self._freq_re = re.compile(r"Frequency:(?P<freq>[0-9.]+) GHz")
        self._signal_re = re.compile(r"Signal level=(?P<signal>-?\d+) dBm")
        self._encryption_re = re.compile(r"Encryption key:(?P<enc>on|off)")
        self._wpa_re = re.compile(r"IE: WPA Version")
        self._wpa2_re = re.compile(r"IE: IEEE 802.11i/WPA2 Version")

    def _run_scan(self) -> Optional[str]:
        """Run iwlist scan and return output.

        Returns:
            iwlist stdout on success, None on failure.
        """
        if sys.platform != "linux":
            self.error_occurred.emit("DECODER OFFLINE - Not available on Windows")
            return None

        try:
            result = subprocess.run(
                ["sudo", "iwlist", "wlan0", "scan"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                stderr = result.stderr.strip()
                if stderr:
                    self._logger.error("iwlist scan failed: %s", stderr)
                    self.error_occurred.emit("DECODER OFFLINE")
                return None
            return result.stdout
        except FileNotFoundError:
            self._logger.error("iwlist not found")
            self.error_occurred.emit("DECODER OFFLINE")
            return None
        except subprocess.TimeoutExpired:
            self._logger.warning("iwlist scan timed out")
            self.error_occurred.emit("DECODER OFFLINE")
            return None
        except Exception as exc:
            self._logger.exception("iwlist scan error")
            self.error_occurred.emit("DECODER OFFLINE")
            return None

    def _parse_scan_output(self, output: str) -> Dict[str, dict]:
        """Parse iwlist output into network dictionary.

        Args:
            output: Raw iwlist output string.

        Returns:
            Dictionary keyed by BSSID.
        """
        networks: Dict[str, dict] = {}
        current: Optional[dict] = None
        encryption = None

        for line in output.splitlines():
            line = line.strip()

            cell_match = self._cell_re.search(line)
            if cell_match:
                if current and current.get("bssid"):
                    networks[current["bssid"]] = current
                bssid = cell_match.group("bssid").upper()
                current = {
                    "ssid": "<HIDDEN>",
                    "bssid": bssid,
                    "channel": None,
                    "frequency": None,
                    "signal_dbm": None,
                    "encryption": "OPEN",
                    "last_seen": time.time(),
                }
                encryption = None
                continue

            if current is None:
                continue

            ssid_match = self._ssid_re.search(line)
            if ssid_match:
                ssid = ssid_match.group("ssid")
                current["ssid"] = ssid if ssid else "<HIDDEN>"
                continue

            channel_match = self._channel_re.search(line)
            if channel_match:
                current["channel"] = int(channel_match.group("channel"))
                continue

            freq_match = self._freq_re.search(line)
            if freq_match:
                current["frequency"] = float(freq_match.group("freq")) * 1e9
                continue

            signal_match = self._signal_re.search(line)
            if signal_match:
                current["signal_dbm"] = int(signal_match.group("signal"))
                continue

            enc_match = self._encryption_re.search(line)
            if enc_match:
                encryption = "WEP" if enc_match.group("enc") == "on" else "OPEN"
                current["encryption"] = encryption
                continue

            if self._wpa2_re.search(line):
                current["encryption"] = "WPA2"
                continue

            if self._wpa_re.search(line):
                if current.get("encryption") != "WPA2":
                    current["encryption"] = "WPA"

        if current and current.get("bssid"):
            networks[current["bssid"]] = current

        return networks

    @pyqtSlot()
    def start_scanner(self) -> None:
        """Start the Wi-Fi scanner loop."""
        with QMutexLocker(self._mutex):
            if self._running:
                return
            self._running = True

        self.scanner_started.emit("WIFI SCANNER ACTIVE")

        while True:
            with QMutexLocker(self._mutex):
                if not self._running:
                    break

            output = self._run_scan()
            if output:
                parsed = self._parse_scan_output(output)
                now = time.time()
                for bssid, info in parsed.items():
                    info["last_seen"] = now
                    self._networks[bssid] = info

                self.networks_updated.emit(dict(self._networks))

            sleep_until = time.time() + self._scan_interval
            while time.time() < sleep_until:
                with QMutexLocker(self._mutex):
                    if not self._running:
                        break
                time.sleep(0.2)

        self.scanner_stopped.emit()

    @pyqtSlot()
    def stop_scanner(self) -> None:
        """Signal the scanner loop to stop."""
        with QMutexLocker(self._mutex):
            self._running = False

    @property
    def is_running(self) -> bool:
        """Whether the scanner is currently active."""
        with QMutexLocker(self._mutex):
            return self._running


class WiFiScannerManager(QObject):
    """Manage WiFiScanner on a dedicated QThread.

    Signals:
        networks_updated(dict): Forwarded from WiFiScanner.
        error_occurred(str): Forwarded from WiFiScanner.
        scanner_started(str): Forwarded from WiFiScanner.
        scanner_stopped(): Forwarded from WiFiScanner.
    """

    networks_updated = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    scanner_started = pyqtSignal(str)
    scanner_stopped = pyqtSignal()

    def __init__(self, scan_interval: float = 10.0, parent=None) -> None:
        super().__init__(parent)
        self._scan_interval = scan_interval
        self._thread: Optional[QThread] = None
        self._scanner: Optional[WiFiScanner] = None

    def _setup_scanner(self) -> None:
        """Create the scanner and thread, wire up signals."""
        self._thread = QThread()
        self._thread.setObjectName("WiFiScannerThread")

        self._scanner = WiFiScanner(scan_interval=self._scan_interval)
        self._scanner.moveToThread(self._thread)

        self._scanner.networks_updated.connect(self.networks_updated)
        self._scanner.error_occurred.connect(self.error_occurred)
        self._scanner.scanner_started.connect(self.scanner_started)
        self._scanner.scanner_stopped.connect(self._on_scanner_stopped)

        self._thread.started.connect(self._scanner.start_scanner)
        self._thread.finished.connect(self._on_thread_finished)

    def _on_scanner_stopped(self) -> None:
        """Handle scanner stop -- stop the thread."""
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
        """Start Wi-Fi scanner on a new thread."""
        if self._thread is not None and self._thread.isRunning():
            return

        self._setup_scanner()
        self._thread.start()

    @pyqtSlot()
    def stop(self) -> None:
        """Stop Wi-Fi scanner and shut down the thread."""
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