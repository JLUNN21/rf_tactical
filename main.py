#!/usr/bin/env python3
"""RF Tactical Monitor - Kiosk Main Entry Point

Integrates SDR capture, waterfall displays, and band switching
into a fullscreen kiosk UI for 800×480 touchscreen.
"""

import sys
import os
from pathlib import Path

# DEBUG: Print environment at startup
print("=" * 60)
print("ENVIRONMENT CHECK AT STARTUP")
print("=" * 60)
print(f"SOAPY_SDR_PLUGIN_PATH: {os.environ.get('SOAPY_SDR_PLUGIN_PATH', 'NOT SET')}")
print(f"PATH contains radioconda: {'radioconda' in os.environ.get('PATH', '')}")
print(f"Python executable: {sys.executable}")
print("=" * 60)
from datetime import datetime, timezone
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QLabel, QVBoxLayout, QHBoxLayout,
    QWidget, QPushButton, QTabWidget, QFrame, QSizePolicy,
    QGraphicsOpacityEffect
)
from PyQt5.QtCore import Qt, QFile, QTextStream, QTimer, QPoint, QEvent
from PyQt5.QtCore import QPropertyAnimation
from PyQt5.QtGui import QCursor, QFont

from ui.waterfall_widget import TacticalWaterfall
from ui.adsb_view import ADSBView
from ui.ism_view import ISMView
from ui.wifi_view import WiFiView
from ui.cellular_view import CellularView
from ui.scanner_view import ScannerView
from ui.settings_dialog import SettingsDialog
from ui.log_view import LogView
from utils.performance import PerformanceMonitor
from utils.logger import setup_logger
from utils.crash_handler import install_crash_handler
from decoders.adsb_decoder import ADSBDecoderManager
from decoders.ism_decoder import ISMDecoderManager
from decoders.wifi_scanner import WiFiScannerManager
from decoders.ble_scanner import BLEScannerManager
from decoders.cellular_scanner import CellularScannerManager
from radio.sdr_manager import SDRManager
from radio.sdr_manager import SDR_AVAILABLE
from utils.config import ConfigManager


# Tab name → band key mapping for tabs that use the SDR waterfall
TAB_BAND_MAP = {
    "ISM": "ism_433",
    "SCANNER": "ism_433",
}


class KioskMainWindow(QMainWindow):
    """Fullscreen frameless kiosk window for tactical RF monitoring."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.Window)
        self._cursor_hidden = True
        self.setCursor(QCursor(Qt.BlankCursor))
        self._apply_screen_geometry()

        self._config = ConfigManager()
        self._logger = setup_logger(debug=bool(os.environ.get("RF_TACTICAL_DEBUG")))
        install_crash_handler(self._logger)
        self._waterfalls = {}
        self._freq_labels = {}
        self._active_tab = None
        self._sdr_manager = None
        self._adsb_manager = None
        self._adsb_view = None
        self._ism_manager = None
        self._ism_view = None
        self._wifi_manager = None
        self._wifi_view = None
        self._ble_manager = None
        self._cellular_manager = None
        self._cellular_view = None
        self._perf_monitor = None
        self._fps_counter = 0
        self._fps_timer = QTimer(self)
        self._fps_timer.setInterval(1000)
        self._fps_timer.timeout.connect(self._update_fps)
        self._touch_start_pos: QPoint = QPoint()
        self._touch_tracking = False
        self._swipe_threshold = 100

        self._gps_status = "N/A"
        self._gps_available = False
        self._recording_start = None
        self._sdr_status = "DISCONNECTED"
        self._sdr_sample_rate = 0.0
        self._cpu_timer = QTimer(self)
        self._cpu_timer.setInterval(2000)
        self._cpu_timer.timeout.connect(self._update_cpu)
        self._prev_idle = None
        self._prev_total = None
        self._cpu_percent = 0

        self._alert_level = "ok"
        self._build_ui()
        self._setup_sdr()
        self._setup_adsb()
        self._setup_ism()
        self._setup_wifi()
        self._setup_ble()
        self._setup_cellular()
        self._setup_performance()
        self._start_clock()
        self._connect_signals()
        self.showMaximized()

    def _build_ui(self):
        """Construct the full UI layout: status bar → tabs → button bar."""
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._build_status_bar(main_layout)
        self._build_tabs(main_layout)
        self._build_button_bar(main_layout)

    def _apply_screen_geometry(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            self.setFixedSize(800, 480)
            return
        geometry = screen.geometry()
        self.setGeometry(geometry)

    def _toggle_cursor(self) -> None:
        self._cursor_hidden = not self._cursor_hidden
        if self._cursor_hidden:
            QApplication.setOverrideCursor(QCursor(Qt.BlankCursor))
            self.cursor_toggle_button.setText("CURSOR")
        else:
            QApplication.restoreOverrideCursor()
            self.cursor_toggle_button.setText("HIDE")

    def _request_close(self) -> None:
        self._allow_close = True
        self.close()

    # ── Status Bar ──────────────────────────────────────────────

    def _build_status_bar(self, parent_layout):
        """Build the top status bar with time, GPS, recording, CPU, and HackRF status."""
        status_frame = QFrame()
        self._status_frame = status_frame
        status_frame.setObjectName("statusBarFrame")
        status_frame.setFixedHeight(44)
        status_frame.setStyleSheet(
            "#statusBarFrame {"
            "  background-color: #0A0A0A;"
            "  border-bottom: 1px solid #1A3D1A;"
            "  border-top: none; border-left: none; border-right: none;"
            "}"
        )

        status_layout = QHBoxLayout(status_frame)
        status_layout.setContentsMargins(10, 6, 10, 6)
        status_layout.setSpacing(12)

        sf = QFont("Source Code Pro", 11, QFont.Bold)

        self.status_label = QLabel("TIME: -- | GPS: -- | REC: -- | CPU: -- | SDR: --")
        self.status_label.setFont(sf)
        self.status_label.setStyleSheet("color: #00CC33; border: none; background: transparent;")
        self.status_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        status_layout.addWidget(self.status_label, 1)

        self.cursor_toggle_button = QPushButton("CURSOR")
        self.cursor_toggle_button.setMinimumHeight(32)
        self.cursor_toggle_button.setFixedWidth(90)
        self.cursor_toggle_button.clicked.connect(self._toggle_cursor)
        status_layout.addWidget(self.cursor_toggle_button)

        self.close_button = QPushButton("EXIT")
        self.close_button.setMinimumHeight(32)
        self.close_button.setFixedWidth(70)
        self.close_button.clicked.connect(self._request_close)
        status_layout.addWidget(self.close_button)

        parent_layout.addWidget(status_frame)

    def _add_status_separator(self, layout):
        """(Deprecated) separator helper retained for compatibility."""
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedWidth(1)
        sep.setFixedHeight(20)
        sep.setStyleSheet("background-color: #1A3D1A; border: none;")
        layout.addWidget(sep)

    # ── Tabs ────────────────────────────────────────────────────

    def _build_tabs(self, parent_layout):
        """Build the 5-tab QTabWidget with waterfalls in ISM, CELLULAR, SCANNER."""
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.North)
        self.tab_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        tab_font = QFont("Source Code Pro", 12, QFont.Bold)
        self.tab_widget.tabBar().setFont(tab_font)

        self.tab_pages = {}

        self._build_adsb_tab()
        self._build_ism_tab()
        self._build_wifi_tab()
        self._build_cellular_tab()
        self._build_scanner_tab()
        self._build_logs_tab()

        parent_layout.addWidget(self.tab_widget, 1)
        self.tab_widget.setAttribute(Qt.WA_AcceptTouchEvents, True)

    def _build_adsb_tab(self):
        """ADS-B tab with aircraft table view."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        self._adsb_view = ADSBView()
        layout.addWidget(self._adsb_view, 1)

        self.tab_pages["ADS-B"] = page
        self.tab_widget.addTab(page, "ADS-B")

    def _build_wifi_tab(self):
        """Wi-Fi tab with scanner table view."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        self._wifi_view = WiFiView()
        layout.addWidget(self._wifi_view, 1)

        self.tab_pages["WI-FI/BLE"] = page
        self.tab_widget.addTab(page, "WI-FI/BLE")

    def _build_ism_tab(self):
        """ISM tab with waterfall and device table."""
        band = self._config.get_band("ism_433")

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        freq_label = QLabel(
            f"{band.name}  \u2502  {band.center_freq_hz / 1e6:.3f} MHz  \u2502  "
            f"BW: {band.bandwidth_hz / 1e6:.1f} MHz  \u2502  "
            f"SR: {band.sample_rate_hz / 1e6:.1f} Msps"
        )
        freq_label.setFont(QFont("Source Code Pro", 10, QFont.Bold))
        freq_label.setStyleSheet("color: #00FF41; border: none; background: transparent;")
        freq_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        freq_label.setFixedHeight(20)
        layout.addWidget(freq_label)
        self._freq_labels["ISM"] = freq_label

        waterfall = TacticalWaterfall(
            fft_size=band.fft_size,
            history_size=self._config.ui.waterfall_history,
            center_freq=band.center_freq_hz,
            sample_rate=band.sample_rate_hz,
        )
        waterfall.set_colormap(self._config.waterfall.colormap)
        self._waterfalls["ISM"] = waterfall
        waterfall.frequency_double_tapped.connect(self._on_waterfall_double_tap)

        self._ism_view = ISMView(waterfall)
        layout.addWidget(self._ism_view, 1)

        self.tab_pages["ISM"] = page
        self.tab_widget.addTab(page, "ISM")

    def _build_cellular_tab(self):
        """CELLULAR tab with sweep waterfall and detected bands table."""
        band = self._config.get_band("cellular_lte")

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        freq_label = QLabel(
            f"{band.name}  \u2502  {band.center_freq_hz / 1e6:.3f} MHz  \u2502  "
            f"BW: {band.bandwidth_hz / 1e6:.1f} MHz  \u2502  "
            f"SR: {band.sample_rate_hz / 1e6:.1f} Msps"
        )
        freq_label.setFont(QFont("Source Code Pro", 10, QFont.Bold))
        freq_label.setStyleSheet("color: #00FF41; border: none; background: transparent;")
        freq_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        freq_label.setFixedHeight(20)
        layout.addWidget(freq_label)
        self._freq_labels["CELLULAR"] = freq_label

        sweep_center_hz = (700_000_000 + 2_700_000_000) / 2
        sweep_sample_rate_hz = 2_000_000_000
        waterfall = TacticalWaterfall(
            fft_size=band.fft_size,
            history_size=self._config.ui.waterfall_history,
            center_freq=sweep_center_hz,
            sample_rate=sweep_sample_rate_hz,
        )
        waterfall.set_colormap(self._config.waterfall.colormap)
        self._waterfalls["CELLULAR"] = waterfall
        waterfall.frequency_double_tapped.connect(self._on_waterfall_double_tap)

        self._cellular_view = CellularView(waterfall)
        layout.addWidget(self._cellular_view, 1)

        self.tab_pages["CELLULAR"] = page
        self.tab_widget.addTab(page, "CELLULAR")

    def _build_waterfall_tab(self, tab_name, band_key):
        """Build a tab with a frequency info label and TacticalWaterfall widget."""
        band = self._config.get_band(band_key)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        freq_label = QLabel(
            f"{band.name}  \u2502  {band.center_freq_hz / 1e6:.3f} MHz  \u2502  "
            f"BW: {band.bandwidth_hz / 1e6:.1f} MHz  \u2502  "
            f"SR: {band.sample_rate_hz / 1e6:.1f} Msps"
        )
        freq_label.setFont(QFont("Source Code Pro", 10, QFont.Bold))
        freq_label.setStyleSheet("color: #00FF41; border: none; background: transparent;")
        freq_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        freq_label.setFixedHeight(20)
        layout.addWidget(freq_label)
        self._freq_labels[tab_name] = freq_label

        waterfall = TacticalWaterfall(
            fft_size=band.fft_size,
            history_size=self._config.ui.waterfall_history,
            center_freq=band.center_freq_hz,
            sample_rate=band.sample_rate_hz,
        )
        waterfall.set_colormap(self._config.waterfall.colormap)
        layout.addWidget(waterfall, 1)
        self._waterfalls[tab_name] = waterfall
        waterfall.frequency_double_tapped.connect(self._on_waterfall_double_tap)

        self.tab_pages[tab_name] = page
        self.tab_widget.addTab(page, tab_name)

    def _build_scanner_tab(self):
        """SCANNER tab with waterfall + frequency/gain controls."""
        band = self._config.get_band("ism_433")
        self._scanner_band = band

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        freq_label = QLabel(
            f"SCANNER  \u2502  {band.center_freq_hz / 1e6:.3f} MHz  \u2502  "
            f"BW: {band.bandwidth_hz / 1e6:.1f} MHz  \u2502  "
            f"SR: {band.sample_rate_hz / 1e6:.1f} Msps"
        )
        freq_label.setFont(QFont("Source Code Pro", 10, QFont.Bold))
        freq_label.setStyleSheet("color: #00FF41; border: none; background: transparent;")
        freq_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        freq_label.setFixedHeight(20)
        layout.addWidget(freq_label)
        self._freq_labels["SCANNER"] = freq_label

        waterfall = TacticalWaterfall(
            fft_size=band.fft_size,
            history_size=self._config.ui.waterfall_history,
            center_freq=band.center_freq_hz,
            sample_rate=band.sample_rate_hz,
        )
        waterfall.set_colormap(self._config.waterfall.colormap)
        self._waterfalls["SCANNER"] = waterfall
        waterfall.frequency_double_tapped.connect(self._on_waterfall_double_tap)
        self._scanner_view = ScannerView(waterfall, band)
        layout.addWidget(self._scanner_view, 1)

        self.tab_pages["SCANNER"] = page
        self.tab_widget.addTab(page, "SCANNER")

    def _build_logs_tab(self):
        """LOGS tab with live system log stream."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        self._log_view = LogView()
        self._log_view.attach_logger(self._logger)
        layout.addWidget(self._log_view, 1)

        self.tab_pages["LOGS"] = page
        self.tab_widget.addTab(page, "LOGS")

    # ── Button Bar ──────────────────────────────────────────────

    def _build_button_bar(self, parent_layout):
        """Build the bottom button bar with 5 action buttons."""
        button_frame = QFrame()
        button_frame.setObjectName("buttonBarFrame")
        button_frame.setFixedHeight(56)
        button_frame.setStyleSheet(
            "#buttonBarFrame {"
            "  background-color: #0A0A0A;"
            "  border-top: 1px solid #1A3D1A;"
            "  border-bottom: none; border-left: none; border-right: none;"
            "}"
        )

        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(4, 4, 4, 4)
        button_layout.setSpacing(4)

        button_font = QFont("Source Code Pro", 12, QFont.Bold)

        button_defs = [
            ("\u25b6 START", "startButton"),
            ("\u2b1b STOP", "stopButton"),
            ("\U0001f4cd MARK", "markButton"),
            ("\u21bb SCAN", "scanButton"),
            ("\u2699 CONFIG", "configButton"),
        ]

        self.buttons = {}
        for label, obj_name in button_defs:
            btn = QPushButton(label)
            btn.setObjectName(obj_name)
            btn.setFont(button_font)
            btn.setMinimumHeight(48)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setFocusPolicy(Qt.NoFocus)
            button_layout.addWidget(btn)
            self.buttons[obj_name] = btn

        parent_layout.addWidget(button_frame)

    # ── SDR Setup ───────────────────────────────────────────────

    def _setup_sdr(self):
        """Initialize the SDR manager with default band settings."""
        default_band = self._config.get_band("ism_433")
        self._sdr_manager = SDRManager(
            center_freq=default_band.center_freq_hz,
            sample_rate=default_band.sample_rate_hz,
            gain_lna=default_band.gain_lna,
            gain_vga=default_band.gain_vga,
            fft_size=default_band.fft_size,
        )

        self._sdr_manager.new_waterfall_row.connect(self._on_waterfall_row)
        self._sdr_manager.overflow_count_updated.connect(self._on_overflow_count)
        self._sdr_manager.error_occurred.connect(self._on_sdr_error)
        self._sdr_manager.device_connected.connect(self._on_sdr_connected)
        self._sdr_manager.device_disconnected.connect(self._on_sdr_disconnected)
        self._sdr_manager.capture_started.connect(self._on_capture_started)
        self._sdr_manager.capture_stopped.connect(self._on_capture_stopped)
        self._sdr_manager.connection_status.connect(self._on_sdr_status)
        self._sdr_manager.recording_status.connect(self._on_recording_status)
        self._sdr_manager.connection_changed.connect(self._on_sdr_connection_changed)
        self._sdr_manager.running_changed.connect(lambda _: self._update_button_states())
        self._update_button_states()

        self._logger.info("SDR available: %s", SDR_AVAILABLE)

        if SDR_AVAILABLE:
            self._update_status_sdr("SDR: IDLE")
        else:
            self._update_status_sdr("SDR: NOT AVAILABLE")

    def _setup_adsb(self):
        """Initialize the ADS-B decoder manager and wire up signals."""
        self._adsb_manager = ADSBDecoderManager()

        if self._adsb_view is not None:
            self._adsb_manager.aircraft_updated.connect(self._adsb_view.update_aircraft)
            self._adsb_manager.decoder_started.connect(self._adsb_view.set_status)
            self._adsb_manager.decoder_stopped.connect(lambda: self._adsb_view.set_status("ADS-B DECODER STOPPED"))
            self._adsb_manager.error_occurred.connect(self._on_adsb_error)
        
        # Auto-start ADS-B decoder on launch (Linux only)
        if sys.platform == "linux":
            QTimer.singleShot(2000, lambda: self._adsb_manager.start(
                center_freq=1090000000,
                sample_rate=2000000
            ))

    def _setup_ism(self):
        """Initialize the ISM decoder manager and wire up signals."""
        ism_band = self._config.get_band("ism_433")
        self._ism_manager = ISMDecoderManager(center_freq_hz=ism_band.center_freq_hz)

        if self._ism_view is not None:
            self._ism_manager.device_detected.connect(self._ism_view.update_device)
            self._ism_manager.decoder_started.connect(self._ism_view.set_status)
            self._ism_manager.decoder_stopped.connect(lambda: self._ism_view.set_status("ISM DECODER STOPPED"))
            self._ism_manager.error_occurred.connect(self._on_ism_error)
        
        # Auto-start ISM decoder on launch (Linux only)
        if sys.platform == "linux":
            QTimer.singleShot(3000, lambda: self._ism_manager.start(
                center_freq=433920000
            ))

    def _setup_wifi(self):
        """Initialize the Wi-Fi scanner manager and wire up signals."""
        self._wifi_manager = WiFiScannerManager()

        if self._wifi_view is not None:
            self._wifi_manager.networks_updated.connect(self._wifi_view.update_networks)
            self._wifi_manager.scanner_started.connect(self._wifi_view.set_status)
            self._wifi_manager.scanner_stopped.connect(lambda: self._wifi_view.set_status("WIFI SCANNER STOPPED"))
            self._wifi_manager.error_occurred.connect(self._on_wifi_error)
        
        # Auto-start Wi-Fi scanner on launch (Linux only)
        if sys.platform == "linux":
            QTimer.singleShot(3500, lambda: self._wifi_manager.start())

    def _setup_ble(self):
        """Initialize the BLE scanner manager and wire up signals."""
        self._ble_manager = BLEScannerManager()

        if self._wifi_view is not None:
            self._ble_manager.devices_updated.connect(self._wifi_view.update_ble_devices)
            self._ble_manager.scanner_started.connect(self._wifi_view.set_ble_status)
            self._ble_manager.scanner_stopped.connect(lambda: self._wifi_view.set_ble_status("BLE SCANNER STOPPED"))
            self._ble_manager.error_occurred.connect(self._on_ble_error)
        
        # Auto-start BLE scanner on launch (Linux only)
        if sys.platform == "linux":
            QTimer.singleShot(4000, lambda: self._ble_manager.start())

    def _setup_cellular(self):
        """Initialize the cellular scanner manager and wire up signals."""
        self._cellular_manager = CellularScannerManager()

        if self._cellular_view is not None:
            self._cellular_manager.bands_detected.connect(self._cellular_view.update_bands)
            self._cellular_manager.sweep_row_ready.connect(self._on_cellular_sweep_row)
            self._cellular_manager.scanner_started.connect(self._cellular_view.set_status)
            self._cellular_manager.scanner_stopped.connect(lambda: self._cellular_view.set_status("CELLULAR SWEEP COMPLETE"))
            self._cellular_manager.error_occurred.connect(self._on_cellular_error)
        
        # Auto-start cellular scanner on launch (Linux only)
        if sys.platform == "linux":
            QTimer.singleShot(4500, lambda: self._cellular_manager.start())

    # ── Signal Wiring ───────────────────────────────────────────

    def _connect_signals(self):
        """Wire up all UI signals to their handlers."""
        self.tab_widget.currentChanged.connect(self._on_tab_changed)

        self.buttons["startButton"].clicked.connect(self._on_start)
        self.buttons["stopButton"].clicked.connect(self._on_stop)
        self.buttons["scanButton"].clicked.connect(self._on_scan)
        self.buttons["markButton"].clicked.connect(self._on_mark)
        self.buttons["configButton"].clicked.connect(self._on_config)

        self._scanner_view.start_spin.valueChanged.connect(self._on_scanner_freq_changed)
        self._scanner_view.lna_slider.valueChanged.connect(self._on_scanner_lna_changed)
        self._scanner_view.vga_slider.valueChanged.connect(self._on_scanner_vga_changed)

        self._active_tab = self._get_current_tab_name()

        self._fps_timer.start()
        self._update_button_states()

    def _get_current_tab_name(self) -> str:
        """Get the name of the currently selected tab."""
        idx = self.tab_widget.currentIndex()
        return self.tab_widget.tabText(idx)

    # ── Tab Switching ───────────────────────────────────────────

    def _on_tab_changed(self, index):
        """Handle tab switch — retune SDR if the new tab has a waterfall."""
        tab_name = self.tab_widget.tabText(index)
        self._active_tab = tab_name

        if tab_name == "ADS-B" and self._sdr_manager is not None and self._sdr_manager.is_running:
            self._sdr_manager.stop()

        if tab_name != "ADS-B" and self._adsb_manager is not None and self._adsb_manager.is_running:
            self._adsb_manager.stop()

        if tab_name != "ISM" and self._ism_manager is not None and self._ism_manager.is_running:
            self._ism_manager.stop()

        if tab_name != "WI-FI/BLE" and self._wifi_manager is not None and self._wifi_manager.is_running:
            self._wifi_manager.stop()

        if tab_name != "WI-FI/BLE" and self._ble_manager is not None and self._ble_manager.is_running:
            self._ble_manager.stop()

        if tab_name != "CELLULAR" and self._cellular_manager is not None and self._cellular_manager.is_running:
            self._cellular_manager.stop()

        if tab_name in TAB_BAND_MAP:
            band_key = TAB_BAND_MAP[tab_name]

            if tab_name == "SCANNER":
                center_freq = self._scanner_view.start_spin.value() * 1e6
                sample_rate = self._scanner_band.sample_rate_hz
            else:
                band = self._config.get_band(band_key)
                center_freq = band.center_freq_hz
                sample_rate = band.sample_rate_hz

            if self._sdr_manager is not None and self._sdr_manager.is_running:
                self._sdr_manager.retune(center_freq, sample_rate)

            if tab_name in self._waterfalls:
                self._waterfalls[tab_name].set_freq_range(center_freq, sample_rate)
                self._waterfalls[tab_name].clear_waterfall()

            self._update_freq_label(tab_name, center_freq, sample_rate)

        self._animate_tab_swipe()

    def _update_freq_label(self, tab_name, center_freq, sample_rate):
        """Update the frequency info label for a given tab."""
        if tab_name in self._freq_labels:
            prefix = tab_name
            if tab_name in TAB_BAND_MAP and tab_name != "SCANNER":
                band = self._config.get_band(TAB_BAND_MAP[tab_name])
                prefix = band.name
            self._freq_labels[tab_name].setText(
                f"{prefix}  \u2502  {center_freq / 1e6:.3f} MHz  \u2502  "
                f"BW: {sample_rate / 1e6:.1f} MHz  \u2502  "
                f"SR: {sample_rate / 1e6:.1f} Msps"
            )

    # ── Waterfall Data ──────────────────────────────────────────

    def _on_waterfall_row(self, magnitude_db):
        """Route incoming FFT data to the active tab's waterfall."""
        self._fps_counter += 1
        
        # Debug: Log first few waterfall rows to verify data flow
        if self._fps_counter <= 3:
            self._logger.info("Waterfall data received: active_tab=%s, data_shape=%s, data_range=[%.2f, %.2f]",
                            self._active_tab, 
                            magnitude_db.shape if hasattr(magnitude_db, 'shape') else 'unknown',
                            float(magnitude_db.min()) if hasattr(magnitude_db, 'min') else 0,
                            float(magnitude_db.max()) if hasattr(magnitude_db, 'max') else 0)
        
        if self._active_tab in self._waterfalls:
            self._waterfalls[self._active_tab].add_fft_row(magnitude_db)
        else:
            # Log if active tab doesn't have a waterfall (expected for ADS-B, WI-FI/BLE, LOGS)
            if self._fps_counter == 1:
                self._logger.debug("Active tab '%s' has no waterfall widget (available: %s)", 
                                 self._active_tab, list(self._waterfalls.keys()))

    # ── SDR Status Handlers ─────────────────────────────────────

    def _on_sdr_error(self, msg):
        """Display SDR error in the status bar."""
        self._logger.error("SDR error: %s", msg)
        self._sdr_status = "ERROR"
        self._recording_start = None
        self._render_status_bar()

    def _on_adsb_error(self, msg: str) -> None:
        """Handle ADS-B decoder errors and log to LOGS tab."""
        self._logger.error(f"ADS-B: {msg}")
        if self._adsb_view is not None:
            self._adsb_view.set_status("DECODER OFFLINE")
            self._adsb_view.set_amber_warning("DECODER OFFLINE")

    def _on_ism_error(self, msg: str) -> None:
        """Handle ISM decoder errors and log to LOGS tab."""
        self._logger.error(f"ISM: {msg}")
        if self._ism_view is not None:
            self._ism_view.set_status("DECODER OFFLINE")
            self._ism_view.set_amber_warning("DECODER OFFLINE")

    def _on_wifi_error(self, msg: str) -> None:
        """Handle Wi-Fi scanner errors and log to LOGS tab."""
        self._logger.error(f"Wi-Fi: {msg}")
        if self._wifi_view is not None:
            self._wifi_view.set_status("DECODER OFFLINE")
            self._wifi_view.set_amber_warning("DECODER OFFLINE")

    def _on_ble_error(self, msg: str) -> None:
        """Handle BLE scanner errors and log to LOGS tab."""
        self._logger.error(f"BLE: {msg}")
        if self._wifi_view is not None:
            self._wifi_view.set_ble_status("DECODER OFFLINE")
            self._wifi_view.set_ble_amber_warning("DECODER OFFLINE")

    def _on_cellular_error(self, msg: str) -> None:
        """Handle cellular scanner errors and log to LOGS tab."""
        self._logger.error(f"Cellular: {msg}")
        if self._cellular_view is not None:
            self._cellular_view.set_status("DECODER OFFLINE")
            self._cellular_view.set_amber_warning("DECODER OFFLINE")

    def _on_sdr_connected(self, info):
        """Update status bar when HackRF connects."""
        self._sdr_status = "IDLE"
        self._render_status_bar()

    def _on_sdr_disconnected(self):
        """Update status bar when HackRF disconnects."""
        self._logger.warning("SDR disconnected")
        self._sdr_status = "DISCONNECTED"
        self._recording_start = None
        self._render_status_bar()

    def _on_capture_started(self):
        """Update UI when capture begins."""
        if self._recording_start is None:
            self._recording_start = time.time()
        self._render_status_bar()
        self._update_button_states()

    def _on_capture_stopped(self):
        """Update UI when capture stops."""
        self._recording_start = None
        self._render_status_bar()
        self._update_button_states()

    # ── Button Handlers ─────────────────────────────────────────

    def _on_start(self):
        """Start SDR capture."""
        self._logger.info("START button pressed - Active tab: %s", self._active_tab)
        
        if self._active_tab == "ADS-B":
            if self._adsb_manager is not None and not self._adsb_manager.is_running:
                if self._sdr_manager is not None and self._sdr_manager.is_running:
                    self._sdr_manager.stop()
                self._logger.info("Starting ADS-B decoder at 1090 MHz")
                self._adsb_manager.start()
            return

        # ISM tab uses SDR waterfall, not decoder
        # (decoder logic removed - ISM tab shows live SDR waterfall)

        if self._active_tab == "WI-FI/BLE":
            if self._wifi_manager is not None and not self._wifi_manager.is_running:
                if self._sdr_manager is not None and self._sdr_manager.is_running:
                    self._sdr_manager.stop()
                if self._adsb_manager is not None and self._adsb_manager.is_running:
                    self._adsb_manager.stop()
                if self._ism_manager is not None and self._ism_manager.is_running:
                    self._ism_manager.stop()
                self._logger.info("Starting Wi-Fi scanner")
                self._wifi_manager.start()
                if self._ble_manager is not None and not self._ble_manager.is_running:
                    self._logger.info("Starting BLE scanner")
                    self._ble_manager.start()
            return

        if self._active_tab == "CELLULAR":
            if self._cellular_manager is not None and not self._cellular_manager.is_running:
                self._logger.info("Starting cellular scanner")
                self._cellular_manager.start()
            return

        if self._sdr_manager is not None:
            if self._adsb_manager is not None and self._adsb_manager.is_running:
                self._adsb_manager.stop()
            tab_name = self._active_tab
            if tab_name in TAB_BAND_MAP:
                if tab_name == "SCANNER":
                    center_freq = self._scanner_view.start_spin.value() * 1e6
                    sample_rate = self._scanner_band.sample_rate_hz
                    self._logger.info("Starting SDR on SCANNER (%.2f MHz, %.2f Msps)", center_freq / 1e6, sample_rate / 1e6)
                else:
                    band = self._config.get_band(TAB_BAND_MAP[tab_name])
                    center_freq = band.center_freq_hz
                    sample_rate = band.sample_rate_hz
                    self._logger.info("Starting SDR on %s (%.2f MHz, %.2f Msps)", band.name, center_freq / 1e6, sample_rate / 1e6)
                self._sdr_manager.retune(center_freq, sample_rate)
            self._sdr_manager.start()

    def _on_stop(self):
        """Stop SDR capture."""
        self._logger.info("STOP button pressed")
        
        if self._sdr_manager is not None:
            self._logger.info("Stopping SDR manager")
            self._sdr_manager.stop()
        if self._adsb_manager is not None:
            self._logger.info("Stopping ADS-B decoder")
            self._adsb_manager.stop()
        if self._ism_manager is not None:
            self._logger.info("Stopping ISM decoder")
            self._ism_manager.stop()
        if self._wifi_manager is not None:
            self._logger.info("Stopping Wi-Fi scanner")
            self._wifi_manager.stop()
        if self._ble_manager is not None:
            self._logger.info("Stopping BLE scanner")
            self._ble_manager.stop()
        if self._cellular_manager is not None:
            self._logger.info("Stopping cellular scanner")
            self._cellular_manager.stop()
        
        self._update_button_states()

    def _on_scan(self):
        """Handle SCAN button actions by tab context."""
        for idx in range(self.tab_widget.count()):
            if self.tab_widget.tabText(idx) == "SCANNER":
                self.tab_widget.setCurrentIndex(idx)
                break
        self._logger.info("SCAN requested - switch to SCANNER tab")
        if self._sdr_manager is not None and not self._sdr_manager.is_running:
            self._sdr_manager.start()

    def _on_mark(self):
        """Mark current timestamp and frequency."""
        timestamp = datetime.now(timezone.utc).isoformat()
        freq = 0.0
        if self._sdr_manager is not None:
            freq = self._sdr_manager.center_freq
        self._logger.info("MARK: %s @ %.3f MHz", timestamp, freq / 1e6)

    def _update_button_states(self):
        """Update button enabled/disabled states and visual feedback based on SDR status."""
        # Get SDR state
        if self._sdr_manager is None:
            sdr_connected = False
            sdr_running = False
        else:
            sdr_connected = self._sdr_manager.is_connected()
            sdr_running = self._sdr_manager.is_running
        
        # Log state changes for debugging (use INFO so it shows in LOGS tab)
        self._logger.info("Button state update: SDR_AVAILABLE=%s, connected=%s, running=%s", 
                          SDR_AVAILABLE, sdr_connected, sdr_running)
        
        # START: enabled if SDR available, connected, and not running
        start_enabled = SDR_AVAILABLE and sdr_connected and not sdr_running
        self.buttons["startButton"].setEnabled(start_enabled)
        if start_enabled:
            self._set_button_style("startButton", "#00FF41", "#00FF41")  # Bright green
        else:
            self._set_button_style("startButton", "#006B1F", "#003310")  # Dark green
        
        # STOP: enabled if SDR running
        stop_enabled = sdr_running
        self.buttons["stopButton"].setEnabled(stop_enabled)
        if stop_enabled:
            self._set_button_style("stopButton", "#FF0000", "#FF0000")  # Bright red
        else:
            self._set_button_style("stopButton", "#660000", "#330000")  # Dark red
        
        # MARK: enabled if SDR running
        mark_enabled = sdr_running
        self.buttons["markButton"].setEnabled(mark_enabled)
        if mark_enabled:
            self._set_button_style("markButton", "#FFB000", "#FFB000")  # Bright amber
        else:
            self._set_button_style("markButton", "#665000", "#332800")  # Dark amber
        
        # SCAN: enabled if SDR available and connected
        scan_enabled = SDR_AVAILABLE and sdr_connected
        self.buttons["scanButton"].setEnabled(scan_enabled)
        if scan_enabled:
            self._set_button_style("scanButton", "#80E0FF", "#80E0FF")  # Bright cyan
        else:
            self._set_button_style("scanButton", "#406070", "#203038")  # Dark cyan
        
        # CONFIG: always enabled
        self.buttons["configButton"].setEnabled(True)
        self._set_button_style("configButton", "#00CC33", "#00CC33")  # Always bright green

    def _set_button_style(self, button_key: str, enabled_color: str, disabled_color: str) -> None:
        """Set button color style for enabled and disabled states.
        
        Args:
            button_key: Button identifier in self.buttons dict
            enabled_color: Color when button is enabled
            disabled_color: Color when button is disabled
        """
        self.buttons[button_key].setStyleSheet(
            f"QPushButton {{ color: {enabled_color}; }}"
            f"QPushButton:disabled {{ color: {disabled_color}; }}"
        )

    def _setup_performance(self):
        """Initialize performance monitoring."""
        self._perf_monitor = PerformanceMonitor()
        self._perf_monitor.performance_updated.connect(self._on_performance_update)
        self._perf_monitor.start()
        self._cpu_timer.start()

    def _on_performance_update(self, stats: dict):
        """Update performance metrics (CPU via /proc/stat)."""
        cpu_percent = stats.get("cpu_percent", 0.0)
        temp_c = stats.get("temp_c")
        alert_level = self._determine_alert_level(cpu_percent, temp_c)
        if alert_level != self._alert_level:
            self._alert_level = alert_level
            self._apply_alert_styles(alert_level)

    def _determine_alert_level(self, cpu_percent: float, temp_c):
        """Determine alert level based on CPU and temperature."""
        if temp_c is None:
            temp_c = 0.0

        if cpu_percent > 95 or temp_c > 80:
            return "alert"
        if cpu_percent > 80 or temp_c > 75:
            return "warn"
        return "ok"

    def _apply_alert_styles(self, alert_level: str):
        """Apply status bar colors for alert levels."""
        if alert_level == "alert":
            self._status_frame.setStyleSheet(
                "#statusBarFrame {"
                "  background-color: #260000;"
                "  border-bottom: 1px solid #FF0000;"
                "  border-top: none; border-left: none; border-right: none;"
                "}"
            )
        elif alert_level == "warn":
            self._status_frame.setStyleSheet(
                "#statusBarFrame {"
                "  background-color: #2B2000;"
                "  border-bottom: 1px solid #FFB000;"
                "  border-top: none; border-left: none; border-right: none;"
                "}"
            )
        else:
            self._status_frame.setStyleSheet(
                "#statusBarFrame {"
                "  background-color: #0A0A0A;"
                "  border-bottom: 1px solid #1A3D1A;"
                "  border-top: none; border-left: none; border-right: none;"
                "}"
            )

    def _update_fps(self):
        """Update FPS values each second."""
        fps = float(self._fps_counter)
        self._fps_counter = 0
        if self._perf_monitor is not None:
            self._perf_monitor.update_fps(fps)
        for waterfall in self._waterfalls.values():
            waterfall.update_fps_overlay(fps)

    def _on_overflow_count(self, count: int):
        """Update performance monitor with overflow count."""
        if self._perf_monitor is not None:
            self._perf_monitor.update_overflow_count(count)

    def _on_config(self):
        """Open the settings dialog."""
        dialog = SettingsDialog(self._config, self)
        dialog.restart_sdr_requested.connect(self._restart_sdr)
        if dialog.exec_():
            self._apply_settings()

    def _apply_settings(self):
        """Apply settings after save."""
        if self._sdr_manager is not None:
            self._sdr_manager.set_gains(
                self._config.sdr.gain_lna,
                self._config.sdr.gain_vga,
            )

        for waterfall in self._waterfalls.values():
            waterfall.set_colormap(self._config.waterfall.colormap)

    def _restart_sdr(self):
        """Restart SDR capture using current settings."""
        if self._sdr_manager is None:
            return

        was_running = self._sdr_manager.is_running
        if was_running:
            self._sdr_manager.stop()

        default_band = self._config.get_band("ism_433")
        self._sdr_manager.retune(default_band.center_freq_hz, default_band.sample_rate_hz)
        self._sdr_manager.set_gains(self._config.sdr.gain_lna, self._config.sdr.gain_vga)

        if was_running:
            self._sdr_manager.start()

    def _on_cellular_sweep_row(self, magnitude_db):
        """Update cellular sweep waterfall with new row."""
        if "CELLULAR" in self._waterfalls:
            self._waterfalls["CELLULAR"].add_fft_row(magnitude_db)

    # ── Scanner Controls ────────────────────────────────────────

    def _on_scanner_freq_changed(self, value_mhz):
        """Handle scanner frequency spinbox change."""
        center_freq = value_mhz * 1e6
        sample_rate = self._scanner_band.sample_rate_hz

        if self._active_tab == "SCANNER":
            if self._sdr_manager is not None and self._sdr_manager.is_running:
                self._sdr_manager.retune(center_freq, sample_rate)
            if "SCANNER" in self._waterfalls:
                self._waterfalls["SCANNER"].set_freq_range(center_freq, sample_rate)
            self._update_freq_label("SCANNER", center_freq, sample_rate)

    def _on_scanner_bw_changed(self, index):
        """Handle scanner bandwidth combo change."""
        return

    def _on_scanner_lna_changed(self, value):
        """Handle LNA gain slider change."""
        snapped = (value // 8) * 8
        if snapped != value:
            self._scanner_view.lna_slider.setValue(snapped)
            return
        if self._scanner_view is not None:
            self._scanner_view.lna_value_label.setText(f"LNA Gain: {snapped}")
        if self._active_tab == "SCANNER" and self._sdr_manager is not None:
            self._sdr_manager.set_gains(snapped, self._scanner_view.vga_slider.value())

    def _on_scanner_vga_changed(self, value):
        """Handle VGA gain slider change."""
        snapped = (value // 2) * 2
        if snapped != value:
            self._scanner_view.vga_slider.setValue(snapped)
            return
        if self._scanner_view is not None:
            self._scanner_view.vga_value_label.setText(f"VGA Gain: {snapped}")
        if self._active_tab == "SCANNER" and self._sdr_manager is not None:
            self._sdr_manager.set_gains(self._scanner_view.lna_slider.value(), snapped)

    # ── Clock ───────────────────────────────────────────────────

    def _start_clock(self):
        """Start a 1-second timer to update the UTC time display."""
        self._update_time()
        self.clock_timer = QTimer(self)
        self.clock_timer.setInterval(1000)
        self.clock_timer.timeout.connect(self._update_time)
        self.clock_timer.start()
        self._init_gps()
        self._render_status_bar()

    def _update_time(self):
        """Update the time label with current UTC time in HH:MM:SS Z format."""
        self._render_status_bar()

    def _init_gps(self):
        try:
            import gpsd  # noqa: F401
            # GPS only available on Linux with gpsd installed
            self._gps_available = True
            self._gps_status = "SEARCHING"
        except Exception:
            self._gps_available = False
            self._gps_status = "N/A"

    def _update_cpu(self):
        cpu = self._get_cpu_usage()
        self._cpu_percent = cpu
        self._render_status_bar()

    def _get_cpu_usage(self):
        proc_stat = Path("/proc/stat")
        if sys.platform != "linux" or not proc_stat.exists():
            return 0

        try:
            with open(proc_stat, "r") as f:
                line = f.readline()
                fields = line.split()
                idle = int(fields[4])
                total = sum(int(f) for f in fields[1:8])
                if self._prev_idle is not None:
                    idle_delta = idle - self._prev_idle
                    total_delta = total - self._prev_total
                    usage = 100.0 * (1.0 - idle_delta / total_delta)
                else:
                    usage = 0.0
                self._prev_idle = idle
                self._prev_total = total
                return int(usage)
        except Exception:
            return 0

    def _on_sdr_status(self, status: str, sample_rate: float):
        self._logger.info("SDR status update: %s (SR %.2f)", status, sample_rate)
        self._sdr_status = status
        self._sdr_sample_rate = sample_rate
        self._render_status_bar()

    def _on_sdr_connection_changed(self, _connected: bool) -> None:
        """Handle SDR connection state changes."""
        self._update_button_states()

    def _update_status_sdr(self, status_text: str) -> None:
        """Update SDR field in status bar."""
        self._sdr_status = status_text
        self._render_status_bar()

    def _on_recording_status(self, status: dict):
        """Handle recording status updates from SDR worker."""
        if status.get("recording"):
            elapsed = status.get("duration_sec", 0)
            self._recording_start = time.time() - elapsed
        else:
            self._recording_start = None
        self._render_status_bar()

    def _render_status_bar(self):
        now_text = datetime.now(timezone.utc).strftime("%H:%M:%S Z")

        gps_text = f"GPS: {self._gps_status}"
        gps_color = "#00FF41" if self._gps_status == "LOCK" else "#FFB000" if self._gps_status == "SEARCHING" else "#006B1F"

        if self._recording_start:
            elapsed = int(time.time() - self._recording_start)
            rec_text = f"REC: {elapsed // 3600:02d}:{(elapsed % 3600) // 60:02d}:{elapsed % 60:02d}"
            rec_color = "#00FF41"
        else:
            rec_text = "REC: IDLE"
            rec_color = "#006B1F"

        cpu_percent = self._cpu_percent
        cpu_text = f"CPU: {cpu_percent}%"
        if cpu_percent > 85:
            cpu_color = "#FF0000"
        elif cpu_percent > 70:
            cpu_color = "#FFB000"
        else:
            cpu_color = "#00FF41"

        if "ACTIVE" in self._sdr_status:
            sdr_text = f"SDR: ACTIVE @ {self._sdr_sample_rate / 1e6:.1f} MSPS"
            sdr_color = "#00FF41"
        elif "IDLE" in self._sdr_status or "CONNECTING" in self._sdr_status:
            sdr_text = "SDR: IDLE"
            sdr_color = "#00CC33"
        elif "DISCONNECTED" in self._sdr_status:
            sdr_text = "SDR: DISCONNECTED"
            sdr_color = "#FFB000"
        elif "NOT AVAILABLE" in self._sdr_status:
            sdr_text = "SDR: NOT AVAILABLE"
            sdr_color = "#006B1F"
        elif "ERROR" in self._sdr_status:
            sdr_text = "SDR: ERROR"
            sdr_color = "#FF0000"
        else:
            sdr_text = self._sdr_status
            sdr_color = "#FF0000"

        html = (
            f"<span style='color:#00FF41'>TIME: {now_text}</span>"
            f" <span style='color:#1A3D1A'>|</span> "
            f"<span style='color:{gps_color}'>{gps_text}</span>"
            f" <span style='color:#1A3D1A'>|</span> "
            f"<span style='color:{rec_color}'>{rec_text}</span>"
            f" <span style='color:#1A3D1A'>|</span> "
            f"<span style='color:{cpu_color}'>{cpu_text}</span>"
            f" <span style='color:#1A3D1A'>|</span> "
            f"<span style='color:{sdr_color}'>{sdr_text}</span>"
        )

        self.status_label.setText(html)

    # ── Kiosk Lockdown ──────────────────────────────────────────

    def closeEvent(self, event):
        """Prevent the window from being closed."""
        if getattr(self, "_allow_close", False):
            event.accept()
            return
        event.ignore()

    def keyPressEvent(self, event):
        """Block Escape, Alt+F4, and Ctrl+C from affecting the window."""
        key = event.key()
        modifiers = event.modifiers()

        if key == Qt.Key_Escape:
            event.ignore()
            return
        if key == Qt.Key_F4 and (modifiers & Qt.AltModifier):
            event.ignore()
            return
        if key == Qt.Key_C and (modifiers & Qt.ControlModifier):
            event.ignore()
            return

        super().keyPressEvent(event)

    def event(self, event):
        if event.type() == QEvent.TouchBegin:
            self._touch_start_pos = event.touchPoints()[0].pos().toPoint()
            self._touch_tracking = True
        elif event.type() == QEvent.TouchEnd and self._touch_tracking:
            end_pos = event.touchPoints()[0].pos().toPoint()
            delta = end_pos - self._touch_start_pos
            if abs(delta.x()) > self._swipe_threshold and abs(delta.x()) > abs(delta.y()):
                if delta.x() < 0:
                    self._switch_tab(1)
                else:
                    self._switch_tab(-1)
            self._touch_tracking = False
        return super().event(event)

    def _switch_tab(self, direction: int):
        count = self.tab_widget.count()
        if count == 0:
            return
        idx = self.tab_widget.currentIndex()
        new_idx = (idx + direction) % count
        self.tab_widget.setCurrentIndex(new_idx)

    def _animate_tab_swipe(self):
        current_widget = self.tab_widget.currentWidget()
        if current_widget is None:
            return
        effect = QGraphicsOpacityEffect(current_widget)
        current_widget.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", current_widget)
        animation.setDuration(200)
        animation.setStartValue(0.3)
        animation.setEndValue(1.0)
        animation.start(QPropertyAnimation.DeleteWhenStopped)

    def _on_waterfall_double_tap(self, freq_hz: float):
        if self._active_tab in self._waterfalls:
            self._waterfalls[self._active_tab].center_on_frequency(freq_hz)


def load_stylesheet(app, path):
    """Load and apply a QSS stylesheet from the given file path."""
    qss_file = QFile(path)
    if qss_file.open(QFile.ReadOnly | QFile.Text):
        stream = QTextStream(qss_file)
        stylesheet = stream.readAll()
        qss_file.close()
        app.setStyleSheet(stylesheet)


def main():
    """Application entry point."""
    app = QApplication(sys.argv)
    app.setApplicationName("RF Tactical Monitor")

    stylesheet_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "config", "theme.qss"
    )
    load_stylesheet(app, stylesheet_path)

    window = KioskMainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
