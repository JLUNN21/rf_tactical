"""RF Tactical Monitor - ISM 433 View

Split layout with TacticalWaterfall and device table.
"""

import time
import logging
from typing import Dict, List, Optional

from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QHeaderView,
    QTableView,
    QLabel,
    QStyledItemDelegate,
    QStyleOptionProgressBar,
    QStyle,
    QApplication,
    QSplitter,
    QProgressDialog,
    QMessageBox,
    QGroupBox,
    QPushButton,
    QDialog,
)
from PyQt5.QtCore import Qt, QAbstractTableModel, QModelIndex, QVariant, pyqtSlot, QTimer
from PyQt5.QtGui import QFont, QColor
from pathlib import Path

from ui.signal_inspector import SignalInspector
from ui.touch_table import TouchTableView, DetailDialog
from ui.waterfall_widget import TacticalWaterfall
from utils.table_style import TableStyler
from utils.signal_library import SignalLibrary


class SignalStrengthDelegate(QStyledItemDelegate):
    """Draw signal strength as a progress bar."""

    def paint(self, painter, option, index) -> None:
        value = index.data(Qt.DisplayRole)
        if value is None:
            super().paint(painter, option, index)
            return

        try:
            signal_dbm = float(value)
        except (TypeError, ValueError):
            super().paint(painter, option, index)
            return

        strength = max(-120, min(-20, signal_dbm))
        percent = int((strength + 120) * (100 / 100))

        progress = QStyleOptionProgressBar()
        progress.rect = option.rect
        progress.minimum = 0
        progress.maximum = 100
        progress.progress = percent
        progress.text = f"{signal_dbm:.0f} dBm"
        progress.textVisible = True

        if signal_dbm >= -50:
            progress.palette.setColor(progress.palette.Highlight, QColor("#00FF41"))
        elif signal_dbm >= -70:
            progress.palette.setColor(progress.palette.Highlight, QColor("#FFB000"))
        else:
            progress.palette.setColor(progress.palette.Highlight, QColor("#FF0000"))

        style = option.widget.style() if option.widget else QApplication.style()
        if style is not None:
            style.drawControl(QStyle.CE_ProgressBar, progress, painter)
        else:
            super().paint(painter, option, index)


class ISMDeviceTableModel(QAbstractTableModel):
    """Table model for decoded ISM devices.

    Columns: Model, ID, Temp, Humidity, Battery, RSSI, Last Seen.
    """

    COLUMNS = [
        "FREQUENCY",
        "DEVICE TYPE",
        "SIGNAL",
        "BATTERY",
        "LAST SEEN",
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._devices: Dict[str, dict] = {}
        self._sorted_keys: List[str] = []
        self._sort_column = 4
        self._sort_order = Qt.DescendingOrder

    def rowCount(self, parent=QModelIndex()) -> int:
        """Return number of devices."""
        if parent.isValid():
            return 0
        return len(self._sorted_keys)

    def columnCount(self, parent=QModelIndex()) -> int:
        """Return number of columns."""
        if parent.isValid():
            return 0
        return len(self.COLUMNS)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.DisplayRole,
    ) -> QVariant:
        """Return header data for columns."""
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal and 0 <= section < len(self.COLUMNS):
                return self.COLUMNS[section]
        elif role == Qt.TextAlignmentRole:
            return Qt.AlignCenter
        return QVariant()

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> QVariant:
        """Return data for a specific cell."""
        if not index.isValid():
            return QVariant()

        row = index.row()
        col = index.column()

        if row < 0 or row >= len(self._sorted_keys):
            return QVariant()

        device_key = self._sorted_keys[row]
        device = self._devices.get(device_key)
        if device is None:
            return QVariant()

        if role == Qt.DisplayRole:
            return self._get_display_value(device, col)
        if role == Qt.TextAlignmentRole:
            return Qt.AlignCenter
        if role == Qt.ForegroundRole:
            return QColor("#D4A0FF")
        if role == Qt.BackgroundRole:
            return QColor("#0A0A0F")

        return QVariant()

    def _get_display_value(self, device: dict, col: int) -> str:
        """Get formatted display value for a column.

        Args:
            device: Device data dictionary.
            col: Column index.

        Returns:
            Formatted string for display.
        """
        if col == 0:
            freq = device.get("frequency")
            if freq is not None:
                return f"{float(freq) / 1e6:.3f} MHz"
            return "---"
        if col == 1:
            return device.get("model", "---")
        if col == 2:
            return device.get("rssi")
        if col == 3:
            battery_ok = device.get("battery_ok")
            if battery_ok is None:
                return "---"
            return "OK" if battery_ok else "LOW"
        if col == 4:
            last_seen = device.get("last_seen")
            if last_seen is not None:
                elapsed = time.time() - last_seen
                if elapsed < 60.0:
                    return f"{int(elapsed)}s"
                return f"{int(elapsed / 60.0)}m"
            return "---"
        return "---"

    @pyqtSlot(dict)
    def update_device(self, device: Dict[str, dict]) -> None:
        """Update device model with new device event.

        Args:
            device: Device dictionary from decoder.
        """
        device_key = device.get("key")
        if device_key is None:
            return

        self._devices[device_key] = device

        self._sort_devices()
        self.layoutChanged.emit()

    def sort(self, column: int, order: Qt.SortOrder = Qt.DescendingOrder) -> None:
        self._sort_column = column
        self._sort_order = order
        self.layoutAboutToBeChanged.emit()
        self._sort_devices()
        self.layoutChanged.emit()

    def _sort_devices(self) -> None:
        reverse = self._sort_order == Qt.DescendingOrder
        self._sorted_keys = sorted(
            self._devices.keys(),
            key=lambda key: self._sort_key(self._devices[key], reverse),
            reverse=reverse,
        )

    def _sort_key(self, device: dict, reverse: bool):
        def numeric(value):
            if value is None:
                return float("-inf") if reverse else float("inf")
            return value

        if self._sort_column == 0:
            return numeric(device.get("frequency"))
        if self._sort_column == 1:
            return (device.get("model") or "").upper()
        if self._sort_column == 2:
            return numeric(device.get("rssi"))
        if self._sort_column == 3:
            battery_ok = device.get("battery_ok")
            if battery_ok is None:
                return float("-inf") if reverse else float("inf")
            return 1 if battery_ok else 0
        if self._sort_column == 4:
            return numeric(device.get("last_seen"))
        return 0

    def clear(self) -> None:
        """Clear all device data."""
        self.beginResetModel()
        self._devices.clear()
        self._sorted_keys.clear()
        self.endResetModel()


class ISMView(QWidget):
    """ISM view with waterfall and device table.

    Args:
        waterfall: TacticalWaterfall widget for the ISM band.
        parent: Optional parent QWidget.
    """

    def __init__(self, waterfall: TacticalWaterfall, parent=None) -> None:
        super().__init__(parent)
        self._waterfall = waterfall
        self._model = ISMDeviceTableModel()
        self._status_label: Optional[QLabel] = None
        self._table_view: Optional[TouchTableView] = None
        self._count_label: Optional[QLabel] = None
        self.signal_inspector: Optional[SignalInspector] = None
        self._device_count = 0
        self._tx_banner: Optional[QLabel] = None
        self.playback_dialog = None
        self.sdr_manager = None
        self.signal_library = SignalLibrary()
        self._logger = logging.getLogger(__name__)
        self.rec_timer = None
        self.recording_start_time = None

        self._build_ui()
        self._connect_playback_signals(parent)

    def _build_ui(self) -> None:
        """Construct the UI layout."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(2, 2, 2, 2)
        main_layout.setSpacing(4)

        main_layout.addWidget(self._waterfall, 1)
        
        # Initialize signal_count_label early to prevent AttributeError
        self.signal_count_label = QLabel("Signals detected: 0")
        self.signal_count_label.setStyleSheet("color: #BB86FC; font-size: 12pt;")

        # Add control bar with LISTEN button, signal count, and CLEAR ALL
        control_bar = self._build_control_bar()
        main_layout.addWidget(control_bar)

        self._tx_banner = QLabel("TX ACTIVE - TRANSMITTING")
        self._tx_banner.setStyleSheet(
            "QLabel {"
            "background-color: #FF0000;"
            "color: #FFFFFF;"
            "font-size: 16pt;"
            "font-weight: bold;"
            "padding: 10px;"
            "border: 2px solid #FFFFFF;"
            "}"
        )
        self._tx_banner.setAlignment(Qt.AlignCenter)
        self._tx_banner.hide()
        main_layout.addWidget(self._tx_banner)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(2)

        table_container = QWidget()
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(4)

        header_label = QLabel("ISM DEVICES")
        header_label.setFont(QFont("DejaVu Sans Mono", 12, QFont.Bold))
        header_label.setStyleSheet("color: #D4A0FF; background: transparent; border: none;")
        header_label.setAlignment(Qt.AlignCenter)
        header_label.setFixedHeight(24)
        table_layout.addWidget(header_label)

        self._count_label = QLabel("Devices detected: 0")
        self._count_label.setFont(QFont("DejaVu Sans Mono", 10, QFont.Bold))
        self._count_label.setStyleSheet("color: #BB86FC; background: transparent; border: none;")
        self._count_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._count_label.setFixedHeight(22)
        table_layout.addWidget(self._count_label)

        self._table_view = TouchTableView()
        self._table_view.setFont(QFont("DejaVu Sans Mono", 9))
        self._table_view.setSelectionBehavior(QTableView.SelectRows)
        self._table_view.setSelectionMode(QTableView.SingleSelection)
        self._table_view.setAlternatingRowColors(False)
        self._table_view.setShowGrid(True)
        self._table_view.setSortingEnabled(False)
        self._table_view.verticalHeader().setVisible(False)
        self._table_view.horizontalHeader().setStretchLastSection(True)
        self._table_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._table_view.setModel(self._model)
        self._table_view.long_press.connect(self._show_details)
        self._table_view.refresh_requested.connect(self._refresh_requested)
        self._table_view.setItemDelegateForColumn(2, SignalStrengthDelegate(self._table_view))

        TableStyler.apply_tactical_style(self._table_view)
        TableStyler.set_column_widths(
            self._table_view,
            {
                "FREQUENCY": 100,
                "DEVICE TYPE": 150,
                "SIGNAL": 80,
                "BATTERY": 60,
                "LAST SEEN": 120,
            },
        )
        self._table_view.sortByColumn(4, Qt.DescendingOrder)

        table_layout.addWidget(self._table_view, 1)

        self._status_label = QLabel("AWAITING ISM DATA")
        self._status_label.setFont(QFont("DejaVu Sans Mono", 9))
        self._status_label.setStyleSheet("color: #6C3483; background: transparent; border: none;")
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setFixedHeight(22)
        table_layout.addWidget(self._status_label)

        self.signal_inspector = SignalInspector()
        
        # Connect signal inspector replay button to our handler
        self.signal_inspector.btn_replay.clicked.disconnect()  # Remove default handler
        self.signal_inspector.btn_replay.clicked.connect(self._on_replay_signal)

        splitter.addWidget(table_container)
        splitter.addWidget(self.signal_inspector)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

        main_layout.addWidget(splitter, 1)

    def _build_control_bar(self):
        """Create simplified control bar with LISTEN button."""
        bar = QWidget()
        bar.setStyleSheet("background-color: #0A0A0F;")
        layout = QHBoxLayout()
        layout.setContentsMargins(10, 5, 10, 5)
        
        # Status indicator
        self.listen_status = QLabel("⬤ IDLE")
        self.listen_status.setStyleSheet("color: #6C3483; font-size: 14pt; font-weight: bold;")
        layout.addWidget(self.listen_status)
        
        # LISTEN button (combines START + auto-record)
        self.btn_listen = QPushButton("LISTEN")
        self.btn_listen.setMinimumHeight(60)
        self.btn_listen.setMinimumWidth(180)
        self.btn_listen.setStyleSheet("""
            QPushButton {
                background-color: #12121A;
                color: #D4A0FF;
                font-size: 16pt;
                font-weight: bold;
                border: 3px solid #D4A0FF;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #2D1B4E;
            }
            QPushButton:pressed {
                background-color: #D4A0FF;
                color: #000000;
            }
            QPushButton:disabled {
                color: #6C3483;
                border-color: #6C3483;
            }
        """)
        self.btn_listen.clicked.connect(self._on_listen_clicked)
        self.btn_listen.setCheckable(True)  # Toggle on/off
        layout.addWidget(self.btn_listen)
        
        # Signal count
        self.signal_count_label = QLabel("Signals detected: 0")
        self.signal_count_label.setStyleSheet("color: #BB86FC; font-size: 12pt;")
        layout.addWidget(self.signal_count_label)
        
        layout.addStretch()
        
        # Clear all button
        self.btn_clear_all = QPushButton("🗑️ CLEAR ALL")
        self.btn_clear_all.setMinimumHeight(50)
        self.btn_clear_all.setMinimumWidth(150)
        self.btn_clear_all.setStyleSheet("""
            QPushButton {
                background-color: #12121A;
                color: #FF6666;
                font-size: 12pt;
                font-weight: bold;
                border: 2px solid #FF6666;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #331111;
            }
        """)
        self.btn_clear_all.clicked.connect(self._on_clear_all)
        layout.addWidget(self.btn_clear_all)
        
        bar.setLayout(layout)
        bar.setMaximumHeight(80)
        return bar

    def _on_listen_clicked(self):
        """Toggle listening mode (START SDR + auto-capture signals)."""
        if self.btn_listen.isChecked():
            # Start listening
            if not self.sdr_manager:
                QMessageBox.warning(self, "Cannot Listen", "SDR manager not available.\n\nCheck system configuration.")
                self.btn_listen.setChecked(False)
                return
            
            try:
                # Start SDR on ISM-433 band
                from utils.config import ConfigManager
                config = ConfigManager()
                band = config.get_band('ism_433')
                
                self.sdr_manager.start(
                    center_freq=band.center_freq_hz,
                    sample_rate=band.sample_rate_hz,
                    lna_gain=band.gain_lna,
                    vga_gain=band.gain_vga
                )
                
                # Update UI
                self.listen_status.setText("⬤ LISTENING")
                self.listen_status.setStyleSheet("color: #D4A0FF; font-size: 14pt; font-weight: bold;")
                self.btn_listen.setText("STOP")
                self.btn_listen.setStyleSheet("""
                    QPushButton {
                        background-color: #12121A;
                        color: #FF0000;
                        font-size: 16pt;
                        font-weight: bold;
                        border: 3px solid #FF0000;
                        border-radius: 8px;
                    }
                    QPushButton:hover {
                        background-color: #331111;
                    }
                    QPushButton:pressed {
                        background-color: #FF0000;
                        color: #000000;
                    }
                """)
                
                self._logger.info("Started listening on ISM-433")
            except Exception as e:
                self._logger.error("Failed to start listening: %s", e)
                QMessageBox.critical(self, "Listen Error", f"Failed to start:\n{e}")
                self.btn_listen.setChecked(False)
        else:
            # Stop listening
            try:
                self.sdr_manager.stop()
                
                # Update UI
                self.listen_status.setText("⬤ IDLE")
                self.listen_status.setStyleSheet("color: #6C3483; font-size: 14pt; font-weight: bold;")
                self.btn_listen.setText("LISTEN")
                self.btn_listen.setStyleSheet("""
                    QPushButton {
                        background-color: #12121A;
                        color: #D4A0FF;
                        font-size: 16pt;
                        font-weight: bold;
                        border: 3px solid #D4A0FF;
                        border-radius: 8px;
                    }
                    QPushButton:hover {
                        background-color: #2D1B4E;
                    }
                    QPushButton:pressed {
                        background-color: #D4A0FF;
                        color: #000000;
                    }
                """)
                
                self._logger.info("Stopped listening")
            except Exception as e:
                self._logger.error("Failed to stop listening: %s", e)

    def _on_clear_all(self):
        """Clear all detected signals from list."""
        reply = QMessageBox.question(
            self,
            "Clear All Signals",
            "Delete all detected signals?\n\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self._model.clear()
            self.signal_count_label.setText("Signals detected: 0")
            self._device_count = 0
            self._logger.info("Cleared all signals")

    def _on_replay_signal(self):
        """Handle replay button click from signal inspector."""
        if not self.signal_inspector or not self.signal_inspector.current_signal:
            return
        
        signal_data = self.signal_inspector.current_signal
        device_type = signal_data.get('device_type', 'Unknown')
        freq_mhz = signal_data.get('center_freq_hz', 0) / 1e6
        duration = signal_data.get('duration_sec', 0)
        
        # Validate signal parameters
        from utils.signal_replay import SignalReplayGenerator
        generator = SignalReplayGenerator()
        is_valid, error_msg = generator.validate_signal_params(signal_data)
        
        if not is_valid:
            QMessageBox.critical(
                self,
                "Invalid Signal",
                f"Cannot replay signal:\n\n{error_msg}"
            )
            return
        
        # Confirmation dialog
        reply = QMessageBox.question(
            self,
            "⚠️ CONFIRM TRANSMISSION",
            f"<b>TRANSMIT THIS SIGNAL?</b><br><br>"
            f"<b>Device:</b> {device_type}<br>"
            f"<b>Frequency:</b> {freq_mhz:.3f} MHz<br>"
            f"<b>Duration:</b> {duration:.3f}s<br>"
            f"<b>Modulation:</b> OOK/ASK<br><br>"
            f"<font color='#FF0000'><b>⚠️ WARNING ⚠️</b></font><br>"
            f"This will TRANSMIT RF energy!<br>"
            f"Only use in controlled environment!<br>"
            f"Ensure compliance with local regulations!",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self._transmit_signal(signal_data, generator)
    
    def _transmit_signal(self, signal_data, generator):
        """Generate and transmit signal via HackRF.
        
        Args:
            signal_data: Signal parameters dict
            generator: SignalReplayGenerator instance
        """
        try:
            # Check if SDR manager is available
            if not self.sdr_manager:
                QMessageBox.critical(
                    self,
                    "TX Not Available",
                    "SDR manager not available.\n\nCannot transmit signal."
                )
                return
            
            # Generate signal from parameters
            self._logger.info("Generating signal for transmission...")
            iq_samples = generator.generate_from_detection(signal_data, sample_rate=2e6)
            
            if iq_samples is None:
                QMessageBox.critical(
                    self,
                    "Generation Failed",
                    "Failed to generate signal.\n\nCheck logs for details."
                )
                return
            
            # Get frequency
            freq_hz = signal_data.get('center_freq_hz', signal_data.get('frequency', 0))
            
            # Show TX banner
            if self._tx_banner:
                self._tx_banner.show()
            
            # Create progress dialog
            progress = QProgressDialog(
                "Transmitting signal...",
                "Cancel",
                0,
                100,
                self
            )
            progress.setWindowTitle("⚠️ TX IN PROGRESS")
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)
            progress.setStyleSheet("""
                QProgressDialog {
                    background-color: #1A0000;
                    color: #FF0000;
                    font-weight: bold;
                }
                QProgressBar {
                    border: 2px solid #FF0000;
                    background-color: #0A0A0A;
                    text-align: center;
                    color: #FF0000;
                }
                QProgressBar::chunk {
                    background-color: #FF0000;
                }
            """)
            progress.show()
            
            # Transmit via SDR manager worker
            self._logger.info("Transmitting at %.3f MHz for %.3f sec", freq_hz/1e6, len(iq_samples)/2e6)
            
            # Check if SDR is running (more reliable than checking worker directly)
            if not self.sdr_manager or not self.sdr_manager.is_running:
                QMessageBox.critical(
                    self,
                    "TX Not Available",
                    "SDR is not running.\n\nStart SDR first, then try replay."
                )
                progress.close()
                if self._tx_banner:
                    self._tx_banner.hide()
                return
            
            # Get worker reference - it should exist if SDR is running
            worker = self.sdr_manager._worker
            if worker is None:
                QMessageBox.critical(
                    self,
                    "TX Not Available",
                    "SDR worker not available.\n\nTry stopping and restarting SDR."
                )
                progress.close()
                if self._tx_banner:
                    self._tx_banner.hide()
                return
            
            def on_tx_progress(prog):
                progress.setValue(int(prog * 100))
            
            def on_tx_complete():
                progress.close()
                if self._tx_banner:
                    self._tx_banner.hide()
                QMessageBox.information(
                    self,
                    "✅ Transmission Complete",
                    f"Signal transmitted successfully!\n\n"
                    f"Frequency: {freq_hz/1e6:.3f} MHz\n"
                    f"Duration: {len(iq_samples)/2e6:.3f}s\n"
                    f"Samples: {len(iq_samples)}"
                )
                # Disconnect signals
                try:
                    worker.tx_progress.disconnect(on_tx_progress)
                    worker.tx_complete.disconnect(on_tx_complete)
                    worker.tx_error.disconnect(on_tx_error)
                except:
                    pass
            
            def on_tx_error(error_msg):
                progress.close()
                if self._tx_banner:
                    self._tx_banner.hide()
                QMessageBox.critical(
                    self,
                    "[X] Transmission Failed",
                    f"TX error:\n\n{error_msg}"
                )
                # Disconnect signals
                try:
                    worker.tx_progress.disconnect(on_tx_progress)
                    worker.tx_complete.disconnect(on_tx_complete)
                    worker.tx_error.disconnect(on_tx_error)
                except:
                    pass
            
            # Connect signals
            worker.tx_progress.connect(on_tx_progress)
            worker.tx_complete.connect(on_tx_complete)
            worker.tx_error.connect(on_tx_error)
            
            # Start actual transmission via SDR manager
            self.sdr_manager.transmit_signal(
                iq_samples=iq_samples,
                center_freq=freq_hz,
                sample_rate=2e6,
                tx_gain=30  # Safe default TX gain
            )
            
            self._logger.info("Real-time TX initiated via HackRF")
            
        except Exception as e:
            self._logger.error("Transmission failed: %s", e)
            if self._tx_banner:
                self._tx_banner.hide()
            QMessageBox.critical(
                self,
                "Transmission Error",
                f"Failed to transmit signal:\n\n{str(e)}"
            )

    def _build_recording_panel(self):
        """DEPRECATED - Use _build_control_bar() instead."""
        panel = QGroupBox("🔴 RECORDING CONTROLS")
        panel.setStyleSheet("""
            QGroupBox {
                font-size: 12pt;
                font-weight: bold;
                color: #D4A0FF;
                border: 2px solid #2A2A3E;
                border-radius: 5px;
                margin-top: 10px;
                padding: 10px;
                background-color: #0A0A0F;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        
        layout = QHBoxLayout()
        
        # Recording status label
        self.rec_status = QLabel("⬤ IDLE")
        self.rec_status.setStyleSheet("color: #6C3483; font-size: 14pt; font-weight: bold;")
        layout.addWidget(self.rec_status)
        
        # Record button
        self.btn_record = QPushButton("🔴 RECORD")
        self.btn_record.setMinimumHeight(50)
        self.btn_record.setMinimumWidth(140)
        self.btn_record.setStyleSheet("""
            QPushButton {
                background-color: #12121A;
                color: #FF0000;
                font-size: 14pt;
                font-weight: bold;
                border: 2px solid #FF0000;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #330000;
            }
            QPushButton:pressed {
                background-color: #FF0000;
                color: #000000;
            }
            QPushButton:disabled {
                color: #660000;
                border-color: #660000;
            }
        """)
        self.btn_record.clicked.connect(self._on_record_clicked)
        layout.addWidget(self.btn_record)
        
        # Stop recording button
        self.btn_stop_rec = QPushButton("⬛ STOP")
        self.btn_stop_rec.setMinimumHeight(50)
        self.btn_stop_rec.setMinimumWidth(140)
        self.btn_stop_rec.setEnabled(False)
        self.btn_stop_rec.setStyleSheet("""
            QPushButton {
                background-color: #12121A;
                color: #FFB000;
                font-size: 14pt;
                font-weight: bold;
                border: 2px solid #FFB000;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #332800;
            }
            QPushButton:pressed {
                background-color: #FFB000;
                color: #000000;
            }
            QPushButton:disabled {
                color: #665000;
                border-color: #665000;
            }
        """)
        self.btn_stop_rec.clicked.connect(self._on_stop_rec_clicked)
        layout.addWidget(self.btn_stop_rec)
        
        # Recording info (time, size)
        self.rec_info = QLabel("Duration: 0s | Size: 0 MB")
        self.rec_info.setStyleSheet("color: #BB86FC; font-size: 11pt;")
        layout.addWidget(self.rec_info)
        
        layout.addStretch()
        
        # Browse recordings button
        self.btn_browse = QPushButton("📂 RECORDINGS")
        self.btn_browse.setMinimumHeight(50)
        self.btn_browse.setMinimumWidth(180)
        self.btn_browse.setStyleSheet("""
            QPushButton {
                background-color: #12121A;
                color: #80E0FF;
                font-size: 12pt;
                font-weight: bold;
                border: 2px solid #80E0FF;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #1A3D4A;
            }
        """)
        self.btn_browse.clicked.connect(self._on_browse_recordings)
        layout.addWidget(self.btn_browse)
        
        panel.setLayout(layout)
        panel.setMaximumHeight(100)
        return panel

    def _on_record_clicked(self):
        """Start recording IQ samples."""
        if not self.sdr_manager or not self.sdr_manager.is_running():
            QMessageBox.warning(self, "Cannot Record", "SDR must be running to record signals.\n\nClick START button first.")
            return
        
        # Start recording
        try:
            self.sdr_manager.start_recording()
            
            # Update UI
            self.btn_record.setEnabled(False)
            self.btn_stop_rec.setEnabled(True)
            self.rec_status.setText("⬤ RECORDING")
            self.rec_status.setStyleSheet("color: #FF0000; font-size: 14pt; font-weight: bold;")
            
            # Start timer to update recording info
            if not self.rec_timer:
                self.rec_timer = QTimer()
                self.rec_timer.timeout.connect(self._update_rec_info)
            self.recording_start_time = time.time()
            self.rec_timer.start(500)
            
            self._logger.info("Started IQ recording")
        except Exception as e:
            self._logger.error("Failed to start recording: %s", e)
            QMessageBox.critical(self, "Recording Error", f"Failed to start recording:\n{e}")

    def _on_stop_rec_clicked(self):
        """Stop recording."""
        try:
            paths = self.sdr_manager.stop_recording()
            
            # Update UI
            self.btn_record.setEnabled(True)
            self.btn_stop_rec.setEnabled(False)
            self.rec_status.setText("⬤ IDLE")
            self.rec_status.setStyleSheet("color: #6C3483; font-size: 14pt; font-weight: bold;")
            
            if self.rec_timer:
                self.rec_timer.stop()
            
            self.rec_info.setText("Duration: 0s | Size: 0 MB")
            self.recording_start_time = None
            
            # Show confirmation
            if paths:
                iq_path = paths[0] if isinstance(paths, tuple) else paths
                filename = Path(iq_path).name
                QMessageBox.information(self, "Recording Saved", 
                    f"Recording saved:\n\n{filename}\n\nLocation: recordings/")
                self._logger.info("Saved recording: %s", filename)
        except Exception as e:
            self._logger.error("Failed to stop recording: %s", e)
            QMessageBox.critical(self, "Recording Error", f"Failed to stop recording:\n{e}")

    def _update_rec_info(self):
        """Update recording duration and size display."""
        if not self.recording_start_time:
            return
        
        try:
            duration = time.time() - self.recording_start_time
            
            # Estimate file size (2 MSPS * 8 bytes per complex sample)
            size_mb = (duration * 2e6 * 8) / (1024 * 1024)
            
            self.rec_info.setText(f"Duration: {int(duration)}s | Size: {size_mb:.1f} MB")
        except Exception as e:
            self._logger.debug("Could not update recording info: %s", e)

    def _on_browse_recordings(self):
        """Open recordings directory."""
        import subprocess
        import sys
        
        recordings_dir = Path("recordings")
        recordings_dir.mkdir(exist_ok=True)
        
        # Open folder in file explorer
        try:
            if sys.platform == "win32":
                subprocess.Popen(['explorer', str(recordings_dir.absolute())])
            elif sys.platform == "darwin":
                subprocess.Popen(['open', str(recordings_dir.absolute())])
            else:
                subprocess.Popen(['xdg-open', str(recordings_dir.absolute())])
            
            self._logger.info("Opened recordings directory")
        except Exception as e:
            self._logger.error("Failed to open recordings directory: %s", e)
            QMessageBox.information(self, "Recordings Location", 
                f"Recordings are saved to:\n\n{recordings_dir.absolute()}")

    def _show_details(self, details: dict) -> None:
        dialog = DetailDialog("ISM DEVICE DETAILS", details, self)
        dialog.exec_()

    def _refresh_requested(self) -> None:
        self._model.clear()
        if self._status_label is not None:
            self._status_label.setText("REFRESHING ISM...")
            self._status_label.setStyleSheet("color: #D4A0FF; background: transparent; border: none;")

    @pyqtSlot(dict)
    def update_device(self, device: Dict[str, dict]) -> None:
        """Update the table with a new device event.

        Args:
            device: Device data from decoder.
        """
        self._model.update_device(device)
        self._device_count = self._model.rowCount()
        self.update_summary()
        if self._status_label is not None:
            self._status_label.setText("ISM DATA ACTIVE")
            self._status_label.setStyleSheet("color: #D4A0FF; background: transparent; border: none;")

    @pyqtSlot(str)
    def set_status(self, status: str) -> None:
        """Set the status label text.

        Args:
            status: Status message to display.
        """
        if self._status_label is not None:
            self._status_label.setText(status.upper())

    def set_amber_warning(self, message: str) -> None:
        """Set an amber warning status message."""
        if self._status_label is not None:
            self._status_label.setText(message.upper())
            self._status_label.setStyleSheet("color: #FFB000; background: transparent; border: none;")

    @pyqtSlot(str)
    def set_error(self, error: str) -> None:
        """Set an error message in the status label.

        Args:
            error: Error message to display.
        """
        if self._status_label is not None:
            self._status_label.setText(f"ERROR: {error.upper()}")
            self._status_label.setStyleSheet("color: #FF0000; background: transparent; border: none;")

    def clear(self) -> None:
        """Clear device table and reset status."""
        self._model.clear()
        self._device_count = 0
        self.update_summary()
        if self._status_label is not None:
            self._status_label.setText("AWAITING ISM DATA")
            self._status_label.setStyleSheet("color: #6C3483; background: transparent; border: none;")

    def update_summary(self) -> None:
        """Update summary statistics label."""
        if self._count_label is not None:
            self._count_label.setText(f"Devices detected: {self._device_count}")

    def clear_data(self) -> None:
        """Clear all displayed data."""
        self.clear()

    def _connect_playback_signals(self, parent) -> None:
        if parent is not None:
            if hasattr(parent, "_sdr_manager"):
                self.sdr_manager = parent._sdr_manager
                self._attach_playback_signals()
            elif hasattr(parent, "sdr_manager"):
                self.sdr_manager = parent.sdr_manager
                self._attach_playback_signals()

        if hasattr(self, "recording_browser"):
            try:
                self.recording_browser.recording_selected.connect(self.on_recording_selected)
            except Exception:
                pass

        if self.sdr_manager is not None and hasattr(self.sdr_manager, "signal_detected"):
            try:
                self.sdr_manager.signal_detected.connect(self.on_signal_detected)
            except Exception:
                pass

    def set_sdr_manager(self, sdr_manager) -> None:
        self.sdr_manager = sdr_manager
        self._attach_playback_signals()
        
        # Connect signal detection from SDR manager
        if self.sdr_manager is not None:
            try:
                self.sdr_manager.signal_detected.connect(self.on_signal_detected)
                self._logger.info("Connected signal_detected from SDR manager to ISM view")
            except Exception as e:
                self._logger.error("Failed to connect signal_detected: %s", e)

    def _attach_playback_signals(self) -> None:
        if self.sdr_manager is None:
            return
        self.sdr_manager.playback_started.connect(self.on_playback_started)
        self.sdr_manager.playback_progress.connect(self.on_playback_progress)
        self.sdr_manager.playback_finished.connect(self.on_playback_finished)
        self.sdr_manager.playback_error.connect(self.on_playback_error)

    def on_recording_selected(self, filepath, metadata):
        """Handle recording selection from browser."""
        return

    def on_signal_detected(self, signal_data):
        """Handle newly detected signal with auto-identification."""
        if signal_data is None:
            return

        # Extract signal characteristics
        freq = signal_data.get("frequency", signal_data.get("center_freq_hz", 0))
        bw = signal_data.get("bandwidth_hz", 50000)
        duration = signal_data.get("duration", signal_data.get("duration_sec", 0))
        
        # Try to match against library
        match = self.signal_library.match_signal(freq, bw, duration)
        
        if match:
            # Use library identification
            fingerprint = match['fingerprint']
            signal_data["device_type"] = f"{fingerprint.icon} {fingerprint.name}"
            signal_data["manufacturer"] = fingerprint.manufacturer
            signal_data["confidence"] = match['confidence']
            signal_data["modulation"] = fingerprint.modulation
            signal_data["description"] = f"{fingerprint.device_type} - {fingerprint.manufacturer}"
        else:
            # Unknown device - use generic classification
            signal_data["device_type"] = "🔘 Unknown Device"
            signal_data["manufacturer"] = "Unknown"
            signal_data["confidence"] = 0.5
            signal_data["description"] = f"Unidentified signal at {freq/1e6:.3f} MHz"

        # Update signal inspector
        if self.signal_inspector is not None:
            self.signal_inspector.update_signal(signal_data)

        # Add to device table
        device_entry = {
            "key": f"{freq}_{int(time.time() * 1000)}",
            "frequency": freq,
            "model": signal_data["device_type"],
            "rssi": f"{signal_data.get('power', signal_data.get('peak_power_dbm', -80)):.1f} dBm",
            "battery_ok": None,  # Not available from raw signal
            "last_seen": time.time(),
        }
        self.update_device(device_entry)
        
        # Update signal count
        self.signal_count_label.setText(f"Signals detected: {self._device_count}")

    def on_replay_clicked(self):
        """Handle replay button click from RecordingBrowser."""
        if self.sdr_manager is None or not hasattr(self, "recording_browser"):
            return

        current_item = self.recording_browser.file_list.currentItem()
        if not current_item:
            return

        filepath = current_item.data(Qt.UserRole)
        metadata = current_item.data(Qt.UserRole + 1)

        if not filepath or not metadata:
            return

        freq_mhz = metadata["center_freq_hz"] / 1e6
        duration = metadata["duration_seconds"]

        msg = (
            f"Replay recording on {freq_mhz:.2f} MHz?\n\n"
            f"Duration: {duration:.2f} seconds\n"
            f"Sample Rate: {metadata['sample_rate_hz'] / 1e6:.1f} MSPS\n"
            f"TX Gain: {metadata['gain_vga']} dB\n\n"
            "WARNING: This will TRANSMIT RF energy.\n"
            "Ensure you are in a controlled environment."
        )

        reply = QMessageBox.question(
            self,
            "Confirm Replay",
            msg,
            QMessageBox.Yes | QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            self.sdr_manager.play_recording(filepath, metadata)

    def on_playback_started(self):
        """Show progress dialog when playback starts."""
        if self._tx_banner is not None:
            self._tx_banner.show()

        self.playback_dialog = QProgressDialog(
            "Transmitting recording...",
            "Cancel",
            0,
            100,
            self,
        )
        self.playback_dialog.setWindowTitle("TX In Progress")
        self.playback_dialog.setWindowModality(Qt.WindowModal)
        self.playback_dialog.setMinimumDuration(0)
        self.playback_dialog.canceled.connect(self.on_playback_cancel)
        self.playback_dialog.setStyleSheet(
            "QProgressDialog {"
            "background-color: #12121A;"
            "color: #D4A0FF;"
            "}"
            "QProgressBar {"
            "border: 1px solid #2A2A3E;"
            "background-color: #0A0A0F;"
            "text-align: center;"
            "color: #D4A0FF;"
            "}"
            "QProgressBar::chunk {"
            "background-color: #BB86FC;"
            "}"
        )
        self.playback_dialog.show()

    def on_playback_progress(self, progress):
        """Update progress dialog."""
        if self.playback_dialog:
            self.playback_dialog.setValue(int(progress * 100))

    def on_playback_finished(self):
        """Handle successful playback completion."""
        if self._tx_banner is not None:
            self._tx_banner.hide()
        if self.playback_dialog:
            self.playback_dialog.close()
            self.playback_dialog = None

        QMessageBox.information(
            self,
            "Playback Complete",
            "Recording transmitted successfully.",
        )

    def on_playback_error(self, error_msg):
        """Handle playback error."""
        if self._tx_banner is not None:
            self._tx_banner.hide()
        if self.playback_dialog:
            self.playback_dialog.close()
            self.playback_dialog = None

        QMessageBox.critical(
            self,
            "Playback Error",
            f"Failed to transmit recording:\n\n{error_msg}",
        )

    def on_playback_cancel(self):
        """Handle user cancellation."""
        if self.sdr_manager is not None:
            self.sdr_manager.stop_playback()