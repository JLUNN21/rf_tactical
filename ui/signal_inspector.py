"""Signal inspector panel for detailed analysis.

Enhanced with signal classification (FISSURE-inspired) and
multi-mode TX generation from open source repos.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QTextEdit,
    QGroupBox,
    QPushButton,
    QHBoxLayout,
    QComboBox,
    QDoubleSpinBox,
    QSpinBox,
)

from utils.signal_classifier import SignalClassifier
from utils.tx_signal_generator import TxSignalGenerator, TxSignalParams, TxMode


class SignalInspector(QWidget):
    """Detailed signal analysis panel."""

    def __init__(self) -> None:
        super().__init__()
        self.current_signal = None
        self.init_ui()

    def init_ui(self) -> None:
        layout = QVBoxLayout()

        header = QLabel("SIGNAL INSPECTOR")
        header.setStyleSheet("font-size: 13pt; font-weight: bold; color: #D4A0FF;")
        layout.addWidget(header)

        basic_group = QGroupBox("BASIC PARAMETERS")
        basic_layout = QVBoxLayout()

        self.lbl_frequency = QLabel("Frequency: ---")
        self.lbl_bandwidth = QLabel("Bandwidth: ---")
        self.lbl_power = QLabel("Power: ---")
        self.lbl_duration = QLabel("Duration: ---")
        self.lbl_modulation = QLabel("Modulation: ---")

        for lbl in [
            self.lbl_frequency,
            self.lbl_bandwidth,
            self.lbl_power,
            self.lbl_duration,
            self.lbl_modulation,
        ]:
            lbl.setFont(QFont("DejaVu Sans Mono", 10))
            lbl.setStyleSheet("color: #BB86FC; padding: 2px;")
            basic_layout.addWidget(lbl)

        basic_group.setLayout(basic_layout)
        layout.addWidget(basic_group)

        class_group = QGroupBox("CLASSIFICATION")
        class_layout = QVBoxLayout()

        self.lbl_device_type = QLabel("Device Type: ---")
        self.lbl_confidence = QLabel("Confidence: ---")
        self.lbl_description = QLabel("Description: ---")

        for lbl in [self.lbl_device_type, self.lbl_confidence, self.lbl_description]:
            lbl.setFont(QFont("DejaVu Sans Mono", 10))
            lbl.setStyleSheet("color: #BB86FC; padding: 2px;")
            lbl.setWordWrap(True)
            class_layout.addWidget(lbl)

        # Auto-classification labels (FISSURE-inspired)
        self.lbl_band = QLabel("Band: ---")
        self.lbl_protocol = QLabel("Protocol: ---")
        self.lbl_mod_hint = QLabel("Mod Hint: ---")
        self.lbl_threat = QLabel("Threat: ---")
        self.lbl_tags = QLabel("Tags: ---")

        for lbl in [self.lbl_band, self.lbl_protocol, self.lbl_mod_hint, self.lbl_threat, self.lbl_tags]:
            lbl.setFont(QFont("DejaVu Sans Mono", 9))
            lbl.setStyleSheet("color: #80E0FF; padding: 1px;")
            lbl.setWordWrap(True)
            class_layout.addWidget(lbl)

        class_group.setLayout(class_layout)
        layout.addWidget(class_group)

        demod_group = QGroupBox("DEMODULATED DATA")
        demod_layout = QVBoxLayout()

        self.txt_demod = QTextEdit()
        self.txt_demod.setReadOnly(True)
        self.txt_demod.setMaximumHeight(120)
        self.txt_demod.setFont(QFont("DejaVu Sans Mono", 9))
        self.txt_demod.setStyleSheet(
            "QTextEdit {"
            "background-color: #0A0A0F;"
            "color: #BB86FC;"
            "border: 1px solid #2A2A3E;"
            "}"
        )
        demod_layout.addWidget(self.txt_demod)

        demod_group.setLayout(demod_layout)
        layout.addWidget(demod_group)

        # Prominent REPLAY button
        self.btn_replay = QPushButton("▶ REPLAY SIGNAL")
        self.btn_replay.setMinimumHeight(60)
        self.btn_replay.setStyleSheet("""
            QPushButton {
                background-color: #12121A;
                color: #FF8C00;
                font-size: 14pt;
                font-weight: bold;
                border: 3px solid #FF8C00;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #332200;
            }
            QPushButton:pressed {
                background-color: #FF8C00;
                color: #000000;
            }
            QPushButton:disabled {
                color: #664400;
                border-color: #664400;
            }
        """)
        self.btn_replay.clicked.connect(self.on_replay_clicked)
        self.btn_replay.setEnabled(False)  # Disabled until signal selected
        layout.addWidget(self.btn_replay)

        btn_layout = QHBoxLayout()

        self.btn_capture = QPushButton("📸 CAPTURE")
        self.btn_capture.setMinimumHeight(40)
        self.btn_capture.clicked.connect(self.on_capture_clicked)
        btn_layout.addWidget(self.btn_capture)

        self.btn_export = QPushButton("💾 EXPORT")
        self.btn_export.setMinimumHeight(40)
        self.btn_export.clicked.connect(self.on_export_clicked)
        btn_layout.addWidget(self.btn_export)

        layout.addLayout(btn_layout)
        layout.addStretch()

        self.setLayout(layout)
        self.setMinimumWidth(280)

    def update_signal(self, signal_data: dict) -> None:
        """Update display with new signal data.

        Args:
            signal_data: dict with keys:
                - center_freq_hz
                - bandwidth_hz
                - power_dbm
                - duration_sec
                - modulation (optional)
                - device_type (optional)
                - confidence (optional)
                - description (optional)
                - demod_fsk_hex (optional)
                - demod_ook_hex (optional)
                - manchester_hex (optional)
        """
        self.current_signal = signal_data

        self.lbl_frequency.setText(
            f"Frequency: {signal_data.get('center_freq_hz', 0) / 1e6:.3f} MHz"
        )
        self.lbl_bandwidth.setText(
            f"Bandwidth: {signal_data.get('bandwidth_hz', 0) / 1e3:.1f} kHz"
        )
        self.lbl_power.setText(
            f"Power: {signal_data.get('power_dbm', -999):.1f} dBm"
        )
        self.lbl_duration.setText(
            f"Duration: {signal_data.get('duration_sec', 0):.3f} seconds"
        )
        self.lbl_modulation.setText(
            f"Modulation: {signal_data.get('modulation', 'Unknown')}"
        )

        device_type = signal_data.get("device_type", "Unknown")
        confidence = signal_data.get("confidence", 0.0)
        description = signal_data.get("description", "No description")

        self.lbl_device_type.setText(f"Device Type: {device_type}")
        self.lbl_confidence.setText(f"Confidence: {confidence * 100:.1f}%")
        self.lbl_description.setText(f"Description: {description}")

        demod_text = ""

        if "demod_fsk_hex" in signal_data:
            demod_text += f"FSK Demod:\n{signal_data['demod_fsk_hex']}\n\n"

        if "demod_ook_hex" in signal_data:
            demod_text += f"OOK Demod:\n{signal_data['demod_ook_hex']}\n\n"

        if "manchester_hex" in signal_data:
            demod_text += f"Manchester:\n{signal_data['manchester_hex']}\n"

        if not demod_text:
            demod_text = "No demodulated data available"

        self.txt_demod.setText(demod_text)
        
        # Enable REPLAY button when signal is loaded
        self.btn_replay.setEnabled(True)

        # Auto-classify signal using FISSURE-inspired classifier
        self._auto_classify(signal_data)

    def _auto_classify(self, signal_data: dict) -> None:
        """Run FISSURE-inspired auto-classification on the signal."""
        try:
            classifier = SignalClassifier()
            freq_hz = signal_data.get("center_freq_hz", 0)
            bw_hz = signal_data.get("bandwidth_hz", 0)

            result = classifier.classify(freq_hz, bw_hz)

            self.lbl_band.setText(f"Band: {result.band_name}")
            self.lbl_protocol.setText(f"Protocol: {result.protocol or 'Unknown'}")
            self.lbl_mod_hint.setText(f"Mod Hint: {result.modulation_hint}")
            self.lbl_tags.setText(f"Tags: {', '.join(result.tags[:5])}")

            # Color-code threat level
            threat_colors = {
                "none": "#D4A0FF",
                "low": "#FFB000",
                "medium": "#FF8C00",
                "high": "#FF0000",
            }
            color = threat_colors.get(result.threat_level, "#00FF41")
            self.lbl_threat.setText(f"Threat: {result.threat_level.upper()}")
            self.lbl_threat.setStyleSheet(f"color: {color}; padding: 1px; font-weight: bold;")

        except Exception:
            self.lbl_band.setText("Band: ---")
            self.lbl_protocol.setText("Protocol: ---")
            self.lbl_mod_hint.setText("Mod Hint: ---")
            self.lbl_threat.setText("Threat: ---")
            self.lbl_tags.setText("Tags: ---")

    def clear(self) -> None:
        """Clear all displayed data."""
        self.current_signal = None

        for lbl in [
            self.lbl_frequency,
            self.lbl_bandwidth,
            self.lbl_power,
            self.lbl_duration,
            self.lbl_modulation,
            self.lbl_device_type,
            self.lbl_confidence,
            self.lbl_description,
            self.lbl_band,
            self.lbl_protocol,
            self.lbl_mod_hint,
            self.lbl_threat,
            self.lbl_tags,
        ]:
            lbl.setText(lbl.text().split(":")[0] + ": ---")

        self.txt_demod.clear()
        self.btn_replay.setEnabled(False)

    def on_replay_clicked(self) -> None:
        """Handle replay button click - emit signal for parent to handle."""
        if not self.current_signal:
            return
        
        # Emit signal to parent (ISM view will handle actual replay)
        # This is a placeholder - actual implementation will be in ISM view
        print("Replay requested for signal:", self.current_signal.get('device_type', 'Unknown'))

    def on_capture_clicked(self) -> None:
        """Capture current signal for detailed offline analysis."""
        if not self.current_signal:
            return

        print("Capture signal:", self.current_signal)

    def on_export_clicked(self) -> None:
        """Export signal data to file."""
        if not self.current_signal:
            return

        print("Export signal:", self.current_signal)