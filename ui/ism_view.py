"""RF Tactical Monitor - ISM 433 View

Split layout with TacticalWaterfall and device table.
"""

import time
from typing import Dict, List, Optional

from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
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
)
from PyQt5.QtCore import Qt, QAbstractTableModel, QModelIndex, QVariant, pyqtSlot
from PyQt5.QtGui import QFont, QColor

from ui.signal_inspector import SignalInspector
from ui.touch_table import TouchTableView, DetailDialog
from ui.waterfall_widget import TacticalWaterfall
from utils.table_style import TableStyler


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
            return QColor("#00FF41")
        if role == Qt.BackgroundRole:
            return QColor("#0A0A0A")

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

        self._build_ui()
        self._connect_playback_signals(parent)

    def _build_ui(self) -> None:
        """Construct the UI layout."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(2, 2, 2, 2)
        main_layout.setSpacing(4)

        main_layout.addWidget(self._waterfall, 1)

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
        header_label.setStyleSheet("color: #00FF41; background: transparent; border: none;")
        header_label.setAlignment(Qt.AlignCenter)
        header_label.setFixedHeight(24)
        table_layout.addWidget(header_label)

        self._count_label = QLabel("Devices detected: 0")
        self._count_label.setFont(QFont("DejaVu Sans Mono", 10, QFont.Bold))
        self._count_label.setStyleSheet("color: #00CC33; background: transparent; border: none;")
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
        self._status_label.setStyleSheet("color: #006B1F; background: transparent; border: none;")
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setFixedHeight(22)
        table_layout.addWidget(self._status_label)

        self.signal_inspector = SignalInspector()

        splitter.addWidget(table_container)
        splitter.addWidget(self.signal_inspector)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

        main_layout.addWidget(splitter, 1)

    def _show_details(self, details: dict) -> None:
        dialog = DetailDialog("ISM DEVICE DETAILS", details, self)
        dialog.exec_()

    def _refresh_requested(self) -> None:
        self._model.clear()
        if self._status_label is not None:
            self._status_label.setText("REFRESHING ISM...")
            self._status_label.setStyleSheet("color: #00FF41; background: transparent; border: none;")

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
            self._status_label.setStyleSheet("color: #00FF41; background: transparent; border: none;")

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
            self._status_label.setStyleSheet("color: #006B1F; background: transparent; border: none;")

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
        if self.sdr_manager is not None and hasattr(self.sdr_manager, "signal_detected"):
            try:
                self.sdr_manager.signal_detected.connect(self.on_signal_detected)
            except Exception:
                pass

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
        """Handle newly detected signal."""
        if signal_data is None:
            return

        from utils.signal_classifier import SignalClassifier

        device_type, confidence, description = SignalClassifier.classify_signal(
            signal_data.get("center_freq_hz", 0),
            signal_data.get("bandwidth_hz", 50e3),
            signal_data.get("duration_sec", 0),
        )

        signal_data["device_type"] = device_type
        signal_data["confidence"] = confidence
        signal_data["description"] = description

        if self.signal_inspector is not None:
            self.signal_inspector.update_signal(signal_data)

        if hasattr(self, "add_signal_to_table"):
            try:
                self.add_signal_to_table(signal_data)
            except Exception:
                pass

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
            "background-color: #121212;"
            "color: #00FF41;"
            "}"
            "QProgressBar {"
            "border: 1px solid #2A2A2A;"
            "background-color: #0A0A0A;"
            "text-align: center;"
            "color: #00FF41;"
            "}"
            "QProgressBar::chunk {"
            "background-color: #00FF41;"
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