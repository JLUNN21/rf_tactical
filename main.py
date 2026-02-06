#!/usr/bin/env python3
"""RF Tactical Monitor - Kiosk Main Entry Point

Integrates SDR capture, waterfall displays, and band switching
into a fullscreen kiosk UI for 800×480 touchscreen.
"""

import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QLabel, QVBoxLayout, QHBoxLayout,
    QWidget, QPushButton, QTabWidget, QFrame, QSizePolicy,
    QSpinBox, QComboBox, QSlider, QGroupBox
)
from PyQt5.QtCore import Qt, QFile, QTextStream, QTimer
from PyQt5.QtGui import QCursor, QFont

from ui.waterfall_widget import TacticalWaterfall
from radio.sdr_manager import SDRManager
from utils.config import ConfigManager


# Tab name → band key mapping for tabs that use the SDR waterfall
TAB_BAND_MAP = {
    "ISM": "ism_433",
    "CELLULAR": "cellular_lte",
    "SCANNER": "ism_433",
}


class KioskMainWindow(QMainWindow):
    """Fullscreen frameless kiosk window for tactical RF monitoring."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setCursor(QCursor(Qt.BlankCursor))
        self.setFixedSize(800, 480)

        self._config = ConfigManager()
        self._waterfalls = {}
        self._freq_labels = {}
        self._active_tab = None
        self._sdr_manager = None

        self._build_ui()
        self._setup_sdr()
        self._start_clock()
        self._connect_signals()
        self.showFullScreen()

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

    # ── Status Bar ──────────────────────────────────────────────

    def _build_status_bar(self, parent_layout):
        """Build the top status bar with time, GPS, recording, CPU, and HackRF status."""
        status_frame = QFrame()
        status_frame.setObjectName("statusBarFrame")
        status_frame.setFixedHeight(32)
        status_frame.setStyleSheet(
            "#statusBarFrame {"
            "  background-color: #0A0A0A;"
            "  border-bottom: 1px solid #1A3D1A;"
            "  border-top: none; border-left: none; border-right: none;"
            "}"
        )

        status_layout = QHBoxLayout(status_frame)
        status_layout.setContentsMargins(8, 2, 8, 2)
        status_layout.setSpacing(12)

        sf = QFont("Source Code Pro", 11, QFont.Bold)

        self.time_label = QLabel("00:00:00 Z")
        self.time_label.setFont(sf)
        self.time_label.setStyleSheet("color: #00FF41; border: none; background: transparent;")
        status_layout.addWidget(self.time_label)

        status_layout.addStretch(1)

        for attr, text in [
            ("gps_label", "GPS: ---"),
            ("rec_label", "REC: ---"),
            ("cpu_label", "CPU: ---"),
            ("hackrf_label", "HACKRF: ---"),
        ]:
            if attr != "gps_label":
                self._add_status_separator(status_layout)
            lbl = QLabel(text)
            lbl.setFont(sf)
            lbl.setStyleSheet("color: #006B1F; border: none; background: transparent;")
            lbl.setAlignment(Qt.AlignVCenter | Qt.AlignCenter)
            setattr(self, attr, lbl)
            status_layout.addWidget(lbl)

        parent_layout.addWidget(status_frame)

    def _add_status_separator(self, layout):
        """Add a thin vertical separator line between status labels."""
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
        self._build_waterfall_tab("ISM", "ism_433")
        self._build_wifi_ble_tab()
        self._build_waterfall_tab("CELLULAR", "cellular_lte")
        self._build_scanner_tab()

        parent_layout.addWidget(self.tab_widget, 1)

    def _build_adsb_tab(self):
        """ADS-B tab — placeholder for ADS-B decoder display."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        lbl = QLabel("ADS-B DECODER — AWAITING DATA")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setFont(QFont("Source Code Pro", 16, QFont.Bold))
        lbl.setStyleSheet("color: #80E0FF; border: none; background: transparent;")
        layout.addWidget(lbl)
        self.tab_pages["ADS-B"] = page
        self.tab_widget.addTab(page, "ADS-B")

    def _build_wifi_ble_tab(self):
        """WI-FI/BLE tab — placeholder for BLE scanner display."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        lbl = QLabel("WI-FI / BLE SCANNER — AWAITING DATA")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setFont(QFont("Source Code Pro", 16, QFont.Bold))
        lbl.setStyleSheet("color: #FFB000; border: none; background: transparent;")
        layout.addWidget(lbl)
        self.tab_pages["WI-FI/BLE"] = page
        self.tab_widget.addTab(page, "WI-FI/BLE")

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
        layout.addWidget(waterfall, 1)
        self._waterfalls[tab_name] = waterfall

        self.tab_pages[tab_name] = page
        self.tab_widget.addTab(page, tab_name)

    def _build_scanner_tab(self):
        """SCANNER tab with waterfall + frequency/gain controls."""
        band = self._config.get_band("ism_433")

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
        layout.addWidget(waterfall, 1)
        self._waterfalls["SCANNER"] = waterfall

        controls_frame = QFrame()
        controls_frame.setObjectName("scannerControls")
        controls_frame.setFixedHeight(64)
        controls_frame.setStyleSheet(
            "#scannerControls { border: 1px solid #1A3D1A; background: #0A0A0A; }"
        )
        controls_layout = QHBoxLayout(controls_frame)
        controls_layout.setContentsMargins(4, 2, 4, 2)
        controls_layout.setSpacing(8)

        ctrl_font = QFont("Source Code Pro", 10, QFont.Bold)

        freq_lbl = QLabel("FREQ MHz:")
        freq_lbl.setFont(ctrl_font)
        freq_lbl.setStyleSheet("color: #00CC33; border: none; background: transparent;")
        controls_layout.addWidget(freq_lbl)

        self.scanner_freq_spin = QSpinBox()
        self.scanner_freq_spin.setRange(1, 6000)
        self.scanner_freq_spin.setValue(int(band.center_freq_hz / 1e6))
        self.scanner_freq_spin.setSuffix(" MHz")
        self.scanner_freq_spin.setFont(ctrl_font)
        self.scanner_freq_spin.setMinimumHeight(44)
        self.scanner_freq_spin.setMinimumWidth(100)
        self.scanner_freq_spin.setFocusPolicy(Qt.StrongFocus)
        controls_layout.addWidget(self.scanner_freq_spin)

        bw_lbl = QLabel("BW:")
        bw_lbl.setFont(ctrl_font)
        bw_lbl.setStyleSheet("color: #00CC33; border: none; background: transparent;")
        controls_layout.addWidget(bw_lbl)

        self.scanner_bw_combo = QComboBox()
        self.scanner_bw_combo.setFont(ctrl_font)
        self.scanner_bw_combo.setMinimumHeight(44)
        self.scanner_bw_combo.setMinimumWidth(90)
        bw_options = [
            ("0.5 MHz", 500000),
            ("1 MHz", 1000000),
            ("2 MHz", 2000000),
            ("5 MHz", 5000000),
            ("8 MHz", 8000000),
            ("10 MHz", 10000000),
            ("20 MHz", 20000000),
        ]
        for label, val in bw_options:
            self.scanner_bw_combo.addItem(label, val)
        self.scanner_bw_combo.setCurrentIndex(2)
        controls_layout.addWidget(self.scanner_bw_combo)

        lna_lbl = QLabel("LNA:")
        lna_lbl.setFont(ctrl_font)
        lna_lbl.setStyleSheet("color: #00CC33; border: none; background: transparent;")
        controls_layout.addWidget(lna_lbl)

        self.scanner_lna_slider = QSlider(Qt.Horizontal)
        self.scanner_lna_slider.setRange(0, 40)
        self.scanner_lna_slider.setSingleStep(8)
        self.scanner_lna_slider.setPageStep(8)
        self.scanner_lna_slider.setValue(32)
        self.scanner_lna_slider.setMinimumHeight(44)
        self.scanner_lna_slider.setMinimumWidth(80)
        controls_layout.addWidget(self.scanner_lna_slider)

        self.scanner_lna_val = QLabel("32")
        self.scanner_lna_val.setFont(ctrl_font)
        self.scanner_lna_val.setFixedWidth(28)
        self.scanner_lna_val.setStyleSheet("color: #00FF41; border: none; background: transparent;")
        controls_layout.addWidget(self.scanner_lna_val)

        vga_lbl = QLabel("VGA:")
        vga_lbl.setFont(ctrl_font)
        vga_lbl.setStyleSheet("color: #00CC33; border: none; background: transparent;")
        controls_layout.addWidget(vga_lbl)

        self.scanner_vga_slider = QSlider(Qt.Horizontal)
        self.scanner_vga_slider.setRange(0, 62)
        self.scanner_vga_slider.setSingleStep(2)
        self.scanner_vga_slider.setPageStep(2)
        self.scanner_vga_slider.setValue(40)
        self.scanner_vga_slider.setMinimumHeight(44)
        self.scanner_vga_slider.setMinimumWidth(80)
        controls_layout.addWidget(self.scanner_vga_slider)

        self.scanner_vga_val = QLabel("40")
        self.scanner_vga_val.setFont(ctrl_font)
        self.scanner_vga_val.setFixedWidth(28)
        self.scanner_vga_val.setStyleSheet("color: #00FF41; border: none; background: transparent;")
        controls_layout.addWidget(self.scanner_vga_val)

        layout.addWidget(controls_frame)

        self.tab_pages["SCANNER"] = page
        self.tab_widget.addTab(page, "SCANNER")

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
        self._sdr_manager.error_occurred.connect(self._on_sdr_error)
        self._sdr_manager.device_connected.connect(self._on_sdr_connected)
        self._sdr_manager.device_disconnected.connect(self._on_sdr_disconnected)
        self._sdr_manager.capture_started.connect(self._on_capture_started)
        self._sdr_manager.capture_stopped.connect(self._on_capture_stopped)

    # ── Signal Wiring ───────────────────────────────────────────

    def _connect_signals(self):
        """Wire up all UI signals to their handlers."""
        self.tab_widget.currentChanged.connect(self._on_tab_changed)

        self.buttons["startButton"].clicked.connect(self._on_start)
        self.buttons["stopButton"].clicked.connect(self._on_stop)

        self.scanner_freq_spin.valueChanged.connect(self._on_scanner_freq_changed)
        self.scanner_bw_combo.currentIndexChanged.connect(self._on_scanner_bw_changed)
        self.scanner_lna_slider.valueChanged.connect(self._on_scanner_lna_changed)
        self.scanner_vga_slider.valueChanged.connect(self._on_scanner_vga_changed)

        self._active_tab = self._get_current_tab_name()

    def _get_current_tab_name(self) -> str:
        """Get the name of the currently selected tab."""
        idx = self.tab_widget.currentIndex()
        return self.tab_widget.tabText(idx)

    # ── Tab Switching ───────────────────────────────────────────

    def _on_tab_changed(self, index):
        """Handle tab switch — retune SDR if the new tab has a waterfall."""
        tab_name = self.tab_widget.tabText(index)
        self._active_tab = tab_name

        if tab_name in TAB_BAND_MAP:
            band_key = TAB_BAND_MAP[tab_name]

            if tab_name == "SCANNER":
                center_freq = self.scanner_freq_spin.value() * 1e6
                sample_rate = self.scanner_bw_combo.currentData()
                if sample_rate is None:
                    sample_rate = 2e6
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
        if self._active_tab in self._waterfalls:
            self._waterfalls[self._active_tab].add_fft_row(magnitude_db)

    # ── SDR Status Handlers ─────────────────────────────────────

    def _on_sdr_error(self, msg):
        """Display SDR error in the status bar."""
        self.hackrf_label.setText("HACKRF: ERR")
        self.hackrf_label.setStyleSheet("color: #FF0000; border: none; background: transparent;")

    def _on_sdr_connected(self, info):
        """Update status bar when HackRF connects."""
        self.hackrf_label.setText("HACKRF: ON")
        self.hackrf_label.setStyleSheet("color: #00FF41; border: none; background: transparent;")

    def _on_sdr_disconnected(self):
        """Update status bar when HackRF disconnects."""
        self.hackrf_label.setText("HACKRF: OFF")
        self.hackrf_label.setStyleSheet("color: #006B1F; border: none; background: transparent;")

    def _on_capture_started(self):
        """Update UI when capture begins."""
        self.rec_label.setText("REC: LIVE")
        self.rec_label.setStyleSheet("color: #FF0000; border: none; background: transparent;")

    def _on_capture_stopped(self):
        """Update UI when capture stops."""
        self.rec_label.setText("REC: ---")
        self.rec_label.setStyleSheet("color: #006B1F; border: none; background: transparent;")

    # ── Button Handlers ─────────────────────────────────────────

    def _on_start(self):
        """Start SDR capture."""
        if self._sdr_manager is not None:
            tab_name = self._active_tab
            if tab_name in TAB_BAND_MAP:
                if tab_name == "SCANNER":
                    center_freq = self.scanner_freq_spin.value() * 1e6
                    sample_rate = self.scanner_bw_combo.currentData() or 2e6
                else:
                    band = self._config.get_band(TAB_BAND_MAP[tab_name])
                    center_freq = band.center_freq_hz
                    sample_rate = band.sample_rate_hz
                self._sdr_manager.retune(center_freq, sample_rate)
            self._sdr_manager.start()

    def _on_stop(self):
        """Stop SDR capture."""
        if self._sdr_manager is not None:
            self._sdr_manager.stop()

    # ── Scanner Controls ────────────────────────────────────────

    def _on_scanner_freq_changed(self, value_mhz):
        """Handle scanner frequency spinbox change."""
        center_freq = value_mhz * 1e6
        sample_rate = self.scanner_bw_combo.currentData() or 2e6

        if self._active_tab == "SCANNER":
            if self._sdr_manager is not None and self._sdr_manager.is_running:
                self._sdr_manager.retune(center_freq, sample_rate)
            if "SCANNER" in self._waterfalls:
                self._waterfalls["SCANNER"].set_freq_range(center_freq, sample_rate)
            self._update_freq_label("SCANNER", center_freq, sample_rate)

    def _on_scanner_bw_changed(self, index):
        """Handle scanner bandwidth combo change."""
        sample_rate = self.scanner_bw_combo.currentData()
        if sample_rate is None:
            return
        center_freq = self.scanner_freq_spin.value() * 1e6

        if self._active_tab == "SCANNER":
            if self._sdr_manager is not None and self._sdr_manager.is_running:
                self._sdr_manager.retune(center_freq, sample_rate)
            if "SCANNER" in self._waterfalls:
                self._waterfalls["SCANNER"].set_freq_range(center_freq, sample_rate)
            self._update_freq_label("SCANNER", center_freq, sample_rate)

    def _on_scanner_lna_changed(self, value):
        """Handle LNA gain slider change."""
        snapped = (value // 8) * 8
        if snapped != value:
            self.scanner_lna_slider.setValue(snapped)
            return
        self.scanner_lna_val.setText(str(snapped))
        if self._active_tab == "SCANNER" and self._sdr_manager is not None:
            self._sdr_manager.set_gains(snapped, self.scanner_vga_slider.value())

    def _on_scanner_vga_changed(self, value):
        """Handle VGA gain slider change."""
        snapped = (value // 2) * 2
        if snapped != value:
            self.scanner_vga_slider.setValue(snapped)
            return
        self.scanner_vga_val.setText(str(snapped))
        if self._active_tab == "SCANNER" and self._sdr_manager is not None:
            self._sdr_manager.set_gains(self.scanner_lna_slider.value(), snapped)

    # ── Clock ───────────────────────────────────────────────────

    def _start_clock(self):
        """Start a 1-second timer to update the UTC time display."""
        self._update_time()
        self.clock_timer = QTimer(self)
        self.clock_timer.setInterval(1000)
        self.clock_timer.timeout.connect(self._update_time)
        self.clock_timer.start()

    def _update_time(self):
        """Update the time label with current UTC time in HH:MM:SS Z format."""
        utc_now = datetime.now(timezone.utc)
        self.time_label.setText(utc_now.strftime("%H:%M:%S Z"))

    # ── Kiosk Lockdown ──────────────────────────────────────────

    def closeEvent(self, event):
        """Prevent the window from being closed."""
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
    app.setOverrideCursor(QCursor(Qt.BlankCursor))

    stylesheet_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "config", "theme.qss"
    )
    load_stylesheet(app, stylesheet_path)

    window = KioskMainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
