"""RF Tactical Monitor - Scanner View

Waterfall with right-side control panel for manual sweeping.
"""

from PyQt5.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QFrame,
    QFormLayout,
    QSpinBox,
    QSlider,
    QPushButton,
    QCheckBox,
    QComboBox,
    QTextEdit,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from utils.device_presets import DevicePresetManager
from utils.demodulator_v2 import DemodulatorV2, DemodMode
from utils.tx_signal_generator import TxSignalGenerator, TxSignalParams, TxMode


class ScannerView(QWidget):
    """Scanner tab view with waterfall and control panel.

    Enhanced with demodulation mode selector (HackRfDiags-inspired)
    and TX signal generator (multi-mode from open source repos).
    """

    preset_selected = pyqtSignal(float)  # Emits frequency in MHz
    demod_mode_changed = pyqtSignal(str)  # Emits demod mode string
    tx_requested = pyqtSignal(str, dict)  # Emits (tx_mode, params)
    
    def __init__(self, waterfall, band, parent=None) -> None:
        super().__init__(parent)
        self._waterfall = waterfall
        self._band = band
        self._preset_manager = DevicePresetManager()
        self._demodulator = DemodulatorV2()
        self._tx_generator = TxSignalGenerator()
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        layout.addWidget(self._waterfall, 7)

        controls_frame = QFrame()
        controls_frame.setObjectName("scannerControls")
        controls_frame.setStyleSheet(
            "#scannerControls { border: 1px solid #2D1B4E; background: #0A0A0F; }"
        )
        controls_layout = QVBoxLayout(controls_frame)
        controls_layout.setContentsMargins(8, 8, 8, 8)
        controls_layout.setSpacing(8)

        ctrl_font = QFont("Source Code Pro", 10, QFont.Bold)
        section_font = QFont("Source Code Pro", 11, QFont.Bold)

        # Device Preset Selector
        preset_header = QLabel("DEVICE PRESETS")
        preset_header.setFont(section_font)
        preset_header.setStyleSheet("color: #D4A0FF; border: none; background: transparent;")
        controls_layout.addWidget(preset_header)
        
        self.preset_combo = QComboBox()
        self.preset_combo.setFont(ctrl_font)
        self.preset_combo.setMinimumHeight(44)
        self.preset_combo.addItem("-- Select Device --")
        
        # Populate presets grouped by category
        for category in self._preset_manager.get_categories():
            presets = self._preset_manager.get_presets_by_category(category)
            for preset in presets:
                self.preset_combo.addItem(f"[{category}] {preset.name}", preset)
        
        self.preset_combo.currentIndexChanged.connect(self._on_preset_selected)
        controls_layout.addWidget(self.preset_combo)
        
        # Preset info display
        self.preset_info = QTextEdit()
        self.preset_info.setReadOnly(True)
        self.preset_info.setFont(QFont("Source Code Pro", 9))
        self.preset_info.setMaximumHeight(100)
        self.preset_info.setStyleSheet(
            "QTextEdit { "
            "  background: #0A0A0F; "
            "  color: #BB86FC; "
            "  border: 1px solid #2D1B4E; "
            "  padding: 4px; "
            "}"
        )
        self.preset_info.setPlaceholderText("Select a device to see details...")
        controls_layout.addWidget(self.preset_info)
        
        freq_header = QLabel("FREQUENCY CONTROL")
        freq_header.setFont(section_font)
        freq_header.setStyleSheet("color: #D4A0FF; border: none; background: transparent;")
        controls_layout.addWidget(freq_header)

        freq_form = QFormLayout()
        freq_form.setContentsMargins(0, 0, 0, 0)
        freq_form.setSpacing(6)

        self.start_spin = QSpinBox()
        self.start_spin.setRange(100, 6000)
        self.start_spin.setValue(int(self._band.center_freq_hz / 1e6) - 10)
        self.start_spin.setSuffix(" MHz")
        self.start_spin.setFont(ctrl_font)
        self.start_spin.setMinimumHeight(44)
        self.start_spin.setMinimumWidth(140)
        self.start_spin.setFocusPolicy(Qt.StrongFocus)
        freq_form.addRow("Start Freq", self.start_spin)

        self.stop_spin = QSpinBox()
        self.stop_spin.setRange(100, 6000)
        self.stop_spin.setValue(int(self._band.center_freq_hz / 1e6) + 10)
        self.stop_spin.setSuffix(" MHz")
        self.stop_spin.setFont(ctrl_font)
        self.stop_spin.setMinimumHeight(44)
        self.stop_spin.setMinimumWidth(140)
        self.stop_spin.setFocusPolicy(Qt.StrongFocus)
        freq_form.addRow("Stop Freq", self.stop_spin)

        self.step_spin = QSpinBox()
        self.step_spin.setRange(1, 100)
        self.step_spin.setValue(5)
        self.step_spin.setSuffix(" MHz")
        self.step_spin.setFont(ctrl_font)
        self.step_spin.setMinimumHeight(44)
        self.step_spin.setMinimumWidth(140)
        self.step_spin.setFocusPolicy(Qt.StrongFocus)
        freq_form.addRow("Step Size", self.step_spin)

        controls_layout.addLayout(freq_form)

        gain_header = QLabel("GAIN CONTROL")
        gain_header.setFont(section_font)
        gain_header.setStyleSheet("color: #D4A0FF; border: none; background: transparent;")
        controls_layout.addWidget(gain_header)

        self.lna_slider = QSlider(Qt.Horizontal)
        self.lna_slider.setRange(0, 40)
        self.lna_slider.setSingleStep(8)
        self.lna_slider.setPageStep(8)
        self.lna_slider.setValue(32)
        self.lna_slider.setMinimumHeight(44)
        controls_layout.addWidget(self.lna_slider)

        self.lna_value_label = QLabel("LNA Gain: 32")
        self.lna_value_label.setFont(ctrl_font)
        self.lna_value_label.setStyleSheet("color: #D4A0FF; border: none; background: transparent;")
        controls_layout.addWidget(self.lna_value_label)

        self.vga_slider = QSlider(Qt.Horizontal)
        self.vga_slider.setRange(0, 62)
        self.vga_slider.setSingleStep(2)
        self.vga_slider.setPageStep(2)
        self.vga_slider.setValue(40)
        self.vga_slider.setMinimumHeight(44)
        controls_layout.addWidget(self.vga_slider)

        self.vga_value_label = QLabel("VGA Gain: 40")
        self.vga_value_label.setFont(ctrl_font)
        self.vga_value_label.setStyleSheet("color: #D4A0FF; border: none; background: transparent;")
        controls_layout.addWidget(self.vga_value_label)

        self.start_button = QPushButton("START SWEEP")
        self.start_button.setMinimumHeight(44)
        self.start_button.setFont(ctrl_font)
        controls_layout.addWidget(self.start_button)

        self.stop_button = QPushButton("STOP SWEEP")
        self.stop_button.setMinimumHeight(44)
        self.stop_button.setFont(ctrl_font)
        controls_layout.addWidget(self.stop_button)

        detect_header = QLabel("DETECTION")
        detect_header.setFont(section_font)
        detect_header.setStyleSheet("color: #D4A0FF; border: none; background: transparent;")
        controls_layout.addWidget(detect_header)

        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(-100, 0)
        self.threshold_spin.setValue(-60)
        self.threshold_spin.setSuffix(" dB")
        self.threshold_spin.setFont(ctrl_font)
        self.threshold_spin.setMinimumHeight(44)
        self.threshold_spin.setMinimumWidth(140)
        controls_layout.addWidget(self.threshold_spin)

        self.auto_mark_checkbox = QCheckBox("Auto-mark peaks")
        self.auto_mark_checkbox.setFont(ctrl_font)
        self.auto_mark_checkbox.setMinimumHeight(44)
        controls_layout.addWidget(self.auto_mark_checkbox)

        # ── Demodulation Mode (HackRfDiags-inspired) ────────────
        demod_header = QLabel("DEMOD MODE")
        demod_header.setFont(section_font)
        demod_header.setStyleSheet("color: #80E0FF; border: none; background: transparent;")
        controls_layout.addWidget(demod_header)

        self.demod_combo = QComboBox()
        self.demod_combo.setFont(ctrl_font)
        self.demod_combo.setMinimumHeight(44)
        demod_modes = [
            ("None (FFT only)", "none"),
            ("NBFM (5 kHz)", "nbfm"),
            ("WBFM (75 kHz)", "wbfm"),
            ("AM Envelope", "am"),
            ("AM Sync", "am_sync"),
            ("USB (Upper SSB)", "usb"),
            ("LSB (Lower SSB)", "lsb"),
            ("CW (Morse)", "cw"),
        ]
        for label, mode_val in demod_modes:
            self.demod_combo.addItem(label, mode_val)
        self.demod_combo.currentIndexChanged.connect(self._on_demod_changed)
        controls_layout.addWidget(self.demod_combo)

        self.demod_squelch_checkbox = QCheckBox("Squelch enabled")
        self.demod_squelch_checkbox.setFont(ctrl_font)
        self.demod_squelch_checkbox.setMinimumHeight(36)
        controls_layout.addWidget(self.demod_squelch_checkbox)

        # ── TX Signal Generator (multi-mode) ────────────────────
        tx_header = QLabel("TX GENERATOR")
        tx_header.setFont(section_font)
        tx_header.setStyleSheet("color: #FF8C00; border: none; background: transparent;")
        controls_layout.addWidget(tx_header)

        self.tx_mode_combo = QComboBox()
        self.tx_mode_combo.setFont(ctrl_font)
        self.tx_mode_combo.setMinimumHeight(44)
        tx_modes = [
            ("CW (Carrier)", "cw"),
            ("Tone", "tone"),
            ("Multi-Tone", "multi_tone"),
            ("FM Modulated", "fm"),
            ("AM Modulated", "am"),
            ("Noise (Broadband)", "noise"),
            ("Noise (Band-limited)", "noise_band"),
            ("Chirp/Sweep", "chirp"),
            ("Pulse", "pulse"),
            ("Morse Code", "morse"),
            ("OOK", "ook"),
        ]
        for label, mode_val in tx_modes:
            self.tx_mode_combo.addItem(label, mode_val)
        controls_layout.addWidget(self.tx_mode_combo)

        self.tx_duration_spin = QSpinBox()
        self.tx_duration_spin.setRange(1, 30)
        self.tx_duration_spin.setValue(1)
        self.tx_duration_spin.setSuffix(" sec")
        self.tx_duration_spin.setFont(ctrl_font)
        self.tx_duration_spin.setMinimumHeight(36)
        controls_layout.addWidget(self.tx_duration_spin)

        self.tx_button = QPushButton("[!] TRANSMIT")
        self.tx_button.setMinimumHeight(48)
        self.tx_button.setFont(QFont("Source Code Pro", 11, QFont.Bold))
        self.tx_button.setStyleSheet(
            "QPushButton { color: #FF8C00; border: 2px solid #FF8C00; background: #12121A; }"
            "QPushButton:hover { background: #332200; }"
            "QPushButton:pressed { background: #FF8C00; color: #000; }"
        )
        self.tx_button.clicked.connect(self._on_tx_clicked)
        controls_layout.addWidget(self.tx_button)

        controls_layout.addStretch(1)

        layout.addWidget(controls_frame, 3)
    
    def _on_preset_selected(self, index: int) -> None:
        """Handle preset selection from dropdown."""
        if index == 0:  # "-- Select Device --"
            self.preset_info.clear()
            return
        
        preset = self.preset_combo.itemData(index)
        if preset is None:
            return
        
        # Update frequency spinbox
        self.start_spin.setValue(int(preset.frequency_mhz))
        
        # Display preset info
        info_text = (
            f"<b>Device:</b> {preset.name}<br>"
            f"<b>Category:</b> {preset.category}<br>"
            f"<b>Frequency:</b> {preset.frequency_mhz} MHz<br>"
            f"<b>Bandwidth:</b> {preset.bandwidth_mhz} MHz<br>"
            f"<b>Modulation:</b> {preset.modulation}<br>"
            f"<b>Description:</b> {preset.description}<br>"
            f"<b>Notes:</b> {preset.notes}"
        )
        self.preset_info.setHtml(info_text)
        
        # Emit signal for main window to retune SDR
        self.preset_selected.emit(preset.frequency_mhz)

    def _on_demod_changed(self, index: int) -> None:
        """Handle demod mode selection change."""
        mode_val = self.demod_combo.itemData(index)
        if mode_val and mode_val != "none":
            self.demod_mode_changed.emit(mode_val)

    def _on_tx_clicked(self) -> None:
        """Handle TX button click - emit signal with mode and params."""
        mode_val = self.tx_mode_combo.currentData()
        params = {
            "duration_sec": self.tx_duration_spin.value(),
            "frequency_hz": self.start_spin.value() * 1e6,
        }
        self.tx_requested.emit(mode_val, params)

    def update_summary(self) -> None:
        """Update summary statistics label."""
        self.lna_value_label.setText(f"LNA Gain: {self.lna_slider.value()}")
        self.vga_value_label.setText(f"VGA Gain: {self.vga_slider.value()}")

    def clear_data(self) -> None:
        """Clear all displayed data."""
        self.start_spin.setValue(int(self._band.center_freq_hz / 1e6) - 10)
        self.stop_spin.setValue(int(self._band.center_freq_hz / 1e6) + 10)
        self.step_spin.setValue(5)
        self.lna_slider.setValue(32)
        self.vga_slider.setValue(40)
        self.threshold_spin.setValue(-60)
        self.auto_mark_checkbox.setChecked(False)
        self.update_summary()