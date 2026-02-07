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
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont


class ScannerView(QWidget):
    """Scanner tab view with waterfall and control panel."""

    def __init__(self, waterfall, band, parent=None) -> None:
        super().__init__(parent)
        self._waterfall = waterfall
        self._band = band
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        layout.addWidget(self._waterfall, 7)

        controls_frame = QFrame()
        controls_frame.setObjectName("scannerControls")
        controls_frame.setStyleSheet(
            "#scannerControls { border: 1px solid #1A3D1A; background: #0A0A0A; }"
        )
        controls_layout = QVBoxLayout(controls_frame)
        controls_layout.setContentsMargins(8, 8, 8, 8)
        controls_layout.setSpacing(8)

        ctrl_font = QFont("Source Code Pro", 10, QFont.Bold)
        section_font = QFont("Source Code Pro", 11, QFont.Bold)

        freq_header = QLabel("FREQUENCY CONTROL")
        freq_header.setFont(section_font)
        freq_header.setStyleSheet("color: #00FF41; border: none; background: transparent;")
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
        gain_header.setStyleSheet("color: #00FF41; border: none; background: transparent;")
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
        self.lna_value_label.setStyleSheet("color: #00FF41; border: none; background: transparent;")
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
        self.vga_value_label.setStyleSheet("color: #00FF41; border: none; background: transparent;")
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
        detect_header.setStyleSheet("color: #00FF41; border: none; background: transparent;")
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

        controls_layout.addStretch(1)

        layout.addWidget(controls_frame, 3)

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