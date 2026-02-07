"""RF Tactical Monitor - Settings Dialog.

Modal, touch-friendly settings dialog with persistence.
"""

import os

from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QSlider,
    QComboBox,
    QPushButton,
    QCheckBox,
    QGroupBox,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from utils.config import ConfigManager


class SettingsDialog(QDialog):
    """Modal settings dialog for ATAK and decoder controls."""

    restart_sdr_requested = pyqtSignal()

    COLORMAPS = ["TACTICAL GREEN", "IRONBOW", "PLASMA", "GRAY"]

    def __init__(self, config: ConfigManager, parent=None) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle("SETTINGS")
        self.setMinimumSize(740, 440)

        self._config = config
        self._backlight_path = "/sys/class/backlight/rpi_backlight/brightness"

        self._build_ui()
        self._load_from_config()

    def _build_ui(self) -> None:
        """Construct the dialog layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        header = QLabel("ATAK / SYSTEM SETTINGS")
        header.setFont(QFont("DejaVu Sans Mono", 14, QFont.Bold))
        header.setStyleSheet("color: #00FF41; background: transparent;")
        header.setAlignment(Qt.AlignCenter)
        header.setFixedHeight(30)
        layout.addWidget(header)

        layout.addWidget(self._build_atak_group())
        layout.addWidget(self._build_decoder_group())
        layout.addWidget(self._build_sdr_group())
        layout.addWidget(self._build_display_group())

        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)

        self.save_button = QPushButton("SAVE")
        self.save_button.setMinimumHeight(48)
        self.save_button.clicked.connect(self._on_save)
        button_layout.addWidget(self.save_button)

        self.cancel_button = QPushButton("CANCEL")
        self.cancel_button.setMinimumHeight(48)
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)

        layout.addLayout(button_layout)

    def _build_atak_group(self) -> QGroupBox:
        """Build ATAK settings group."""
        group = QGroupBox("ATAK SETTINGS")
        group.setFont(QFont("DejaVu Sans Mono", 11, QFont.Bold))
        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        self.atak_enabled = QCheckBox("ENABLE ATAK")
        self._style_toggle(self.atak_enabled)
        layout.addWidget(self.atak_enabled)

        row = QHBoxLayout()
        row.addWidget(QLabel("MULTICAST GROUP"))
        self.multicast_group = QLineEdit()
        self.multicast_group.setMinimumHeight(44)
        row.addWidget(self.multicast_group)
        layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("MULTICAST PORT"))
        self.multicast_port = QSpinBox()
        self.multicast_port.setRange(1, 65535)
        self.multicast_port.setMinimumHeight(44)
        row.addWidget(self.multicast_port)
        layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("STALE TIME (S)"))
        self.stale_slider = QSlider(Qt.Horizontal)
        self.stale_slider.setRange(30, 600)
        self.stale_slider.setMinimumHeight(44)
        row.addWidget(self.stale_slider, 1)
        layout.addLayout(row)

        return group

    def _build_decoder_group(self) -> QGroupBox:
        """Build decoder toggle group."""
        group = QGroupBox("DECODER ENABLE")
        group.setFont(QFont("DejaVu Sans Mono", 11, QFont.Bold))
        layout = QVBoxLayout(group)

        self.toggle_adsb = self._make_toggle("ADS-B")
        self.toggle_ism = self._make_toggle("ISM")
        self.toggle_wifi = self._make_toggle("WI-FI")
        self.toggle_ble = self._make_toggle("BLE")
        self.toggle_cellular = self._make_toggle("CELLULAR")
        self.toggle_scanner = self._make_toggle("SCANNER")
        self.toggle_cot = self._make_toggle("COT SENDER")

        for toggle in [
            self.toggle_adsb,
            self.toggle_ism,
            self.toggle_wifi,
            self.toggle_ble,
            self.toggle_cellular,
            self.toggle_scanner,
            self.toggle_cot,
        ]:
            layout.addWidget(toggle)

        return group

    def _build_sdr_group(self) -> QGroupBox:
        """Build SDR controls group."""
        group = QGroupBox("SDR GAINS")
        group.setFont(QFont("DejaVu Sans Mono", 11, QFont.Bold))
        layout = QVBoxLayout(group)

        row = QHBoxLayout()
        row.addWidget(QLabel("LNA"))
        self.lna_slider = QSlider(Qt.Horizontal)
        self.lna_slider.setRange(0, 40)
        self.lna_slider.setSingleStep(8)
        self.lna_slider.setPageStep(8)
        self.lna_slider.setMinimumHeight(44)
        row.addWidget(self.lna_slider, 1)
        layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("VGA"))
        self.vga_slider = QSlider(Qt.Horizontal)
        self.vga_slider.setRange(0, 62)
        self.vga_slider.setSingleStep(2)
        self.vga_slider.setPageStep(2)
        self.vga_slider.setMinimumHeight(44)
        row.addWidget(self.vga_slider, 1)
        layout.addLayout(row)

        self.restart_sdr_button = QPushButton("RESTART SDR")
        self.restart_sdr_button.setMinimumHeight(48)
        self.restart_sdr_button.clicked.connect(self.restart_sdr_requested.emit)
        layout.addWidget(self.restart_sdr_button)

        return group

    def _build_display_group(self) -> QGroupBox:
        """Build display controls group."""
        group = QGroupBox("DISPLAY")
        group.setFont(QFont("DejaVu Sans Mono", 11, QFont.Bold))
        layout = QVBoxLayout(group)

        row = QHBoxLayout()
        row.addWidget(QLabel("BRIGHTNESS"))
        self.brightness_slider = QSlider(Qt.Horizontal)
        self.brightness_slider.setRange(0, 255)
        self.brightness_slider.setMinimumHeight(44)
        row.addWidget(self.brightness_slider, 1)
        layout.addLayout(row)

        if not os.path.exists(self._backlight_path):
            self.brightness_slider.setEnabled(False)

        row = QHBoxLayout()
        row.addWidget(QLabel("COLORMAP"))
        self.colormap_combo = QComboBox()
        self.colormap_combo.addItems(self.COLORMAPS)
        self.colormap_combo.setMinimumHeight(44)
        row.addWidget(self.colormap_combo, 1)
        layout.addLayout(row)

        return group

    def _make_toggle(self, label: str) -> QCheckBox:
        toggle = QCheckBox(label)
        self._style_toggle(toggle)
        return toggle

    def _style_toggle(self, toggle: QCheckBox) -> None:
        toggle.setMinimumHeight(44)
        toggle.setFont(QFont("DejaVu Sans Mono", 10, QFont.Bold))

    def _load_from_config(self) -> None:
        """Populate controls from config."""
        self.atak_enabled.setChecked(self._config.atak.enabled)
        self.multicast_group.setText(self._config.atak.cot_multicast_group)
        self.multicast_port.setValue(self._config.atak.cot_multicast_port)
        self.stale_slider.setValue(self._config.atak.cot_stale_seconds)

        self.toggle_adsb.setChecked(self._config.decoder.adsb_enabled)
        self.toggle_ism.setChecked(self._config.decoder.ism_enabled)
        self.toggle_wifi.setChecked(self._config.decoder.wifi_enabled)
        self.toggle_ble.setChecked(self._config.decoder.ble_enabled)
        self.toggle_cellular.setChecked(self._config.decoder.cellular_enabled)
        self.toggle_scanner.setChecked(self._config.decoder.scanner_enabled)
        self.toggle_cot.setChecked(self._config.decoder.cot_enabled)

        self.lna_slider.setValue(self._config.sdr.gain_lna)
        self.vga_slider.setValue(self._config.sdr.gain_vga)

        self.brightness_slider.setValue(self._config.display.brightness)

        idx = self.colormap_combo.findText(self._config.waterfall.colormap)
        if idx >= 0:
            self.colormap_combo.setCurrentIndex(idx)

    def _apply_backlight(self, value: int) -> None:
        """Apply brightness to backlight file if available."""
        if not os.path.exists(self._backlight_path):
            return
        try:
            with open(self._backlight_path, "w", encoding="utf-8") as fh:
                fh.write(str(value))
        except Exception:
            return

    def _on_save(self) -> None:
        """Save settings to config and persist."""
        self._config.atak.enabled = self.atak_enabled.isChecked()
        self._config.atak.cot_multicast_group = self.multicast_group.text().strip()
        self._config.atak.cot_multicast_port = int(self.multicast_port.value())
        self._config.atak.cot_stale_seconds = int(self.stale_slider.value())

        self._config.decoder.adsb_enabled = self.toggle_adsb.isChecked()
        self._config.decoder.ism_enabled = self.toggle_ism.isChecked()
        self._config.decoder.wifi_enabled = self.toggle_wifi.isChecked()
        self._config.decoder.ble_enabled = self.toggle_ble.isChecked()
        self._config.decoder.cellular_enabled = self.toggle_cellular.isChecked()
        self._config.decoder.scanner_enabled = self.toggle_scanner.isChecked()
        self._config.decoder.cot_enabled = self.toggle_cot.isChecked()

        self._config.sdr.gain_lna = int(self.lna_slider.value())
        self._config.sdr.gain_vga = int(self.vga_slider.value())

        self._config.display.brightness = int(self.brightness_slider.value())
        self._config.waterfall.colormap = self.colormap_combo.currentText()

        self._apply_backlight(self._config.display.brightness)
        self._config.save_settings()
        self.accept()