"""RF Tactical Monitor - ISM 433 MHz Decoder

Launches rtl_433 with HackRF, parses JSON output, and tracks devices.
"""

import json
import subprocess
import time
from typing import Dict, Optional

from PyQt5.QtCore import QObject, QThread, pyqtSignal, pyqtSlot, QMutex, QMutexLocker

from utils.logger import setup_logger


class ISMDecoder(QObject):
    """ISM band decoder using rtl_433 JSON output.

    Launches rtl_433, reads JSON lines, extracts device info,
    maintains device state, and emits per-event updates.

    Signals:
        device_detected(dict): Emitted for each decoded device event.
        error_occurred(str): Emitted on decoder errors.
        decoder_started(str): Emitted when decoder starts successfully.
        decoder_stopped(): Emitted when decoder stops.

    Args:
        center_freq_hz: Center frequency in Hz (default 433920000).
        parent: Optional parent QObject.
    """

    device_detected = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    decoder_started = pyqtSignal(str)
    decoder_stopped = pyqtSignal()

    def __init__(
        self,
        center_freq_hz: int = 433920000,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self._center_freq_hz = center_freq_hz
        self._running = False
        self._mutex = QMutex()

        self._rtl_process: Optional[subprocess.Popen] = None
        self._devices: Dict[str, dict] = {}
        self._logger = setup_logger(__name__)

    def _launch_rtl_433(self) -> bool:
        """Launch rtl_433 subprocess with HackRF driver.

        Returns:
            True if subprocess started successfully, False otherwise.
        """
        try:
            self._rtl_process = subprocess.Popen(
                [
                    "rtl_433",
                    "-d", "driver=hackrf",
                    "-f", str(self._center_freq_hz),
                    "-F", "json",
                    "-M", "utc",
                    "-M", "level",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                bufsize=1,
                universal_newlines=True,
            )

            time.sleep(1.5)

            if self._rtl_process.poll() is not None:
                stderr_output = self._rtl_process.stderr.read()
                self._logger.error("rtl_433 failed to start: %s", stderr_output)
                self.error_occurred.emit("DECODER OFFLINE")
                return False

            return True

        except FileNotFoundError:
            self._logger.error("rtl_433 not found")
            self.error_occurred.emit("DECODER OFFLINE")
            return False
        except Exception as exc:
            self._logger.exception("rtl_433 launch failed")
            self.error_occurred.emit("DECODER OFFLINE")
            return False

    def _parse_device(self, payload: dict) -> Optional[dict]:
        """Parse a rtl_433 JSON payload into normalized device data.

        Args:
            payload: Raw JSON dictionary from rtl_433.

        Returns:
            Normalized device dictionary or None if insufficient data.
        """
        model = payload.get("model")
        device_id = payload.get("id")
        if model is None or device_id is None:
            return None

        channel = payload.get("channel")
        battery_ok = payload.get("battery_ok")

        temperature = payload.get("temperature_C")
        humidity = payload.get("humidity")

        rssi = payload.get("rssi")
        snr = payload.get("snr")
        frequency = payload.get("freq") or payload.get("frequency") or payload.get("freq_hz")

        timestamp = payload.get("time")

        device_key = f"{model}-{device_id}"
        now = time.time()

        device = self._devices.get(device_key, {})

        device.update({
            "key": device_key,
            "model": str(model),
            "id": str(device_id),
            "frequency": frequency,
            "channel": channel,
            "battery_ok": battery_ok,
            "temperature_C": temperature,
            "humidity": humidity,
            "rssi": rssi,
            "snr": snr,
            "time": timestamp,
            "last_seen": now,
        })

        for key, value in payload.items():
            if key not in device:
                device[key] = value

        self._devices[device_key] = device
        return device

    @pyqtSlot()
    def start_decoder(self) -> None:
        """Start the rtl_433 decoder loop."""
        with QMutexLocker(self._mutex):
            if self._running:
                return
            self._running = True

        if not self._launch_rtl_433():
            with QMutexLocker(self._mutex):
                self._running = False
            return

        self.decoder_started.emit("ISM decoder active — receiving rtl_433 data")

        while True:
            with QMutexLocker(self._mutex):
                if not self._running:
                    break

            if self._rtl_process is None or self._rtl_process.stdout is None:
                break

            line = self._rtl_process.stdout.readline()
            if not line:
                if self._rtl_process.poll() is not None:
                    stderr_output = ""
                    if self._rtl_process.stderr is not None:
                        stderr_output = self._rtl_process.stderr.read()
                    if stderr_output:
                        self._logger.error("rtl_433 exited: %s", stderr_output)
                        self.error_occurred.emit("DECODER OFFLINE")
                    break
                continue

            line = line.strip()
            if not line:
                continue

            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue

            device = self._parse_device(payload)
            if device is not None:
                self.device_detected.emit(device)

        self._stop_rtl_433()
        self.decoder_stopped.emit()

    @pyqtSlot()
    def stop_decoder(self) -> None:
        """Signal the decoder loop to stop."""
        with QMutexLocker(self._mutex):
            self._running = False

    def _stop_rtl_433(self) -> None:
        """Terminate the rtl_433 subprocess."""
        if self._rtl_process is not None:
            try:
                self._rtl_process.terminate()
                self._rtl_process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self._rtl_process.kill()
                self._rtl_process.wait()
            except Exception:
                pass
            self._rtl_process = None

    @property
    def is_running(self) -> bool:
        """Whether the decoder is currently active."""
        with QMutexLocker(self._mutex):
            return self._running


class ISMDecoderManager(QObject):
    """Manages ISMDecoder on a dedicated QThread.

    Signals:
        device_detected(dict): Forwarded from ISMDecoder.
        error_occurred(str): Forwarded from ISMDecoder.
        decoder_started(str): Forwarded from ISMDecoder.
        decoder_stopped(): Forwarded from ISMDecoder.

    Args:
        center_freq_hz: Center frequency in Hz (default 433920000).
        parent: Optional parent QObject.
    """

    device_detected = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    decoder_started = pyqtSignal(str)
    decoder_stopped = pyqtSignal()

    def __init__(
        self,
        center_freq_hz: int = 433920000,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self._center_freq_hz = center_freq_hz
        self._thread: Optional[QThread] = None
        self._decoder: Optional[ISMDecoder] = None

    def _setup_decoder(self) -> None:
        """Create the decoder and thread, wire up signals."""
        self._thread = QThread()
        self._thread.setObjectName("ISMDecoderThread")

        self._decoder = ISMDecoder(center_freq_hz=self._center_freq_hz)
        self._decoder.moveToThread(self._thread)

        self._decoder.device_detected.connect(self.device_detected)
        self._decoder.error_occurred.connect(self.error_occurred)
        self._decoder.decoder_started.connect(self.decoder_started)
        self._decoder.decoder_stopped.connect(self._on_decoder_stopped)

        self._thread.started.connect(self._decoder.start_decoder)
        self._thread.finished.connect(self._on_thread_finished)

    def _on_decoder_stopped(self) -> None:
        """Handle decoder stop — stop the thread."""
        self.decoder_stopped.emit()
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()

    def _on_thread_finished(self) -> None:
        """Clean up after thread finishes."""
        if self._decoder is not None:
            self._decoder.deleteLater()
            self._decoder = None
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None

    @pyqtSlot()
    def start(self) -> None:
        """Start ISM decoder on a new thread."""
        if self._thread is not None and self._thread.isRunning():
            return

        self._setup_decoder()
        self._thread.start()

    @pyqtSlot()
    def stop(self) -> None:
        """Stop ISM decoder and shut down the thread."""
        if self._decoder is not None:
            self._decoder.stop_decoder()

        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(5000)

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