"""RF Tactical Monitor - Wi-Fi View

Table view for Wi-Fi scan results with signal strength bars.
"""

import time
from typing import Dict, List

from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableView,
    QHeaderView,
    QLabel,
    QStyledItemDelegate,
    QStyleOptionProgressBar,
    QStyle,
    QApplication,
    QSplitter,
)
from PyQt5.QtCore import Qt, QAbstractTableModel, QModelIndex, QVariant, pyqtSlot
from PyQt5.QtGui import QFont, QColor

from ui.touch_table import TouchTableView, DetailDialog
from utils.table_style import TableStyler


class SignalStrengthDelegate(QStyledItemDelegate):
    """Draw signal strength as a color-coded progress bar."""

    def paint(self, painter, option, index) -> None:
        """Paint progress bar for signal strength."""
        value = index.data(Qt.DisplayRole)
        if value is None:
            super().paint(painter, option, index)
            return

        try:
            signal_dbm = int(value)
        except (TypeError, ValueError):
            super().paint(painter, option, index)
            return

        strength = max(-100, min(-30, signal_dbm))
        percent = int((strength + 100) * (100 / 70))

        progress = QStyleOptionProgressBar()
        progress.rect = option.rect
        progress.minimum = 0
        progress.maximum = 100
        progress.progress = percent
        progress.text = f"{signal_dbm} dBm"
        progress.textVisible = True

        if signal_dbm > -50:
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


class WiFiTableModel(QAbstractTableModel):
    """Table model for Wi-Fi networks.

    Columns: SSID, BSSID, Channel, Signal, Encryption, Last Seen.
    """

    COLUMNS = [
        "SSID",
        "BSSID",
        "CHANNEL",
        "SIGNAL",
        "SECURITY",
        "LAST SEEN",
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._networks: Dict[str, dict] = {}
        self._sorted_bssids: List[str] = []
        self._sort_by_signal = True
        self._sort_column = 3
        self._sort_order = Qt.DescendingOrder

    def rowCount(self, parent=QModelIndex()) -> int:
        """Return number of networks."""
        if parent.isValid():
            return 0
        return len(self._sorted_bssids)

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

        if row < 0 or row >= len(self._sorted_bssids):
            return QVariant()

        bssid = self._sorted_bssids[row]
        network = self._networks.get(bssid)
        if network is None:
            return QVariant()

        if role == Qt.DisplayRole:
            return self._get_display_value(network, col)
        elif role == Qt.TextAlignmentRole:
            return Qt.AlignCenter
        elif role == Qt.ForegroundRole:
            return QColor("#D4A0FF")
        elif role == Qt.BackgroundRole:
            return QColor("#0A0A0F")
        return QVariant()

    def _get_display_value(self, network: dict, col: int) -> object:
        """Get formatted display value.

        Args:
            network: Network data.
            col: Column index.

        Returns:
            Value for display.
        """
        if col == 0:
            return network.get("ssid", "<HIDDEN>")
        if col == 1:
            return network.get("bssid", "---")
        if col == 2:
            channel = network.get("channel")
            return str(channel) if channel is not None else "---"
        if col == 3:
            return network.get("signal_dbm")
        if col == 4:
            return network.get("encryption", "OPEN")
        if col == 5:
            last_seen = network.get("last_seen")
            if last_seen is not None:
                elapsed = time.time() - last_seen
                if elapsed < 60.0:
                    return f"{int(elapsed)}s"
                return f"{int(elapsed / 60.0)}m"
            return "---"
        return "---"

    @pyqtSlot(dict)
    def update_networks(self, networks: Dict[str, dict]) -> None:
        """Update the model with network data.

        Args:
            networks: Dict keyed by BSSID.
        """
        self.beginResetModel()
        self._networks = networks
        self._apply_sort()
        self.endResetModel()

    def _apply_sort(self) -> None:
        """Sort by current sort column/order or signal toggle."""
        if self._sort_by_signal:
            self._sort_column = 3
            self._sort_order = Qt.DescendingOrder
        else:
            self._sort_column = 5
            self._sort_order = Qt.DescendingOrder

        reverse = self._sort_order == Qt.DescendingOrder
        self._sorted_bssids = sorted(
            self._networks.keys(),
            key=lambda bssid: self._sort_key(self._networks[bssid], reverse),
            reverse=reverse,
        )

    def sort(self, column: int, order: Qt.SortOrder = Qt.DescendingOrder) -> None:
        self._sort_column = column
        self._sort_order = order
        self._sort_by_signal = column == 3
        self.layoutAboutToBeChanged.emit()
        reverse = order == Qt.DescendingOrder
        self._sorted_bssids = sorted(
            self._networks.keys(),
            key=lambda bssid: self._sort_key(self._networks[bssid], reverse),
            reverse=reverse,
        )
        self.layoutChanged.emit()

    def _sort_key(self, network: dict, reverse: bool):
        def numeric(value):
            if value is None:
                return float("-inf") if reverse else float("inf")
            return value

        if self._sort_column == 0:
            return (network.get("ssid") or "").upper()
        if self._sort_column == 1:
            return (network.get("bssid") or "").upper()
        if self._sort_column == 2:
            return numeric(network.get("channel"))
        if self._sort_column == 3:
            return numeric(network.get("signal_dbm"))
        if self._sort_column == 4:
            return (network.get("encryption") or "").upper()
        if self._sort_column == 5:
            return numeric(network.get("last_seen"))
        return 0

    def toggle_sort(self) -> None:
        """Toggle between signal and last seen sorting."""
        self._sort_by_signal = not self._sort_by_signal
        self._apply_sort()
        self.layoutChanged.emit()

    def clear(self) -> None:
        """Clear all network data."""
        self.beginResetModel()
        self._networks.clear()
        self._sorted_bssids.clear()
        self.endResetModel()

    @property
    def sort_by_signal(self) -> bool:
        """Whether the table is sorted by signal strength."""
        return self._sort_by_signal


class BLETableModel(QAbstractTableModel):
    """Table model for BLE devices.

    Columns: Name, MAC, RSSI, Services, Last Seen.
    """

    COLUMNS = [
        "NAME",
        "ADDRESS",
        "RSSI",
        "SERVICES",
        "LAST SEEN",
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._devices: Dict[str, dict] = {}
        self._sorted_addresses: List[str] = []
        self._sort_column = 2
        self._sort_order = Qt.DescendingOrder

    def rowCount(self, parent=QModelIndex()) -> int:
        """Return number of BLE devices."""
        if parent.isValid():
            return 0
        return len(self._sorted_addresses)

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

        if row < 0 or row >= len(self._sorted_addresses):
            return QVariant()

        address = self._sorted_addresses[row]
        device = self._devices.get(address)
        if device is None:
            return QVariant()

        if role == Qt.DisplayRole:
            return self._get_display_value(device, col)
        elif role == Qt.TextAlignmentRole:
            return Qt.AlignCenter
        elif role == Qt.ForegroundRole:
            return QColor("#D4A0FF")
        elif role == Qt.BackgroundRole:
            return QColor("#0A0A0F")
        return QVariant()

    def _get_display_value(self, device: dict, col: int) -> object:
        """Get formatted display value.

        Args:
            device: BLE device data.
            col: Column index.

        Returns:
            Value for display.
        """
        if col == 0:
            return device.get("name", "<UNKNOWN>")
        if col == 1:
            return device.get("address", "---")
        if col == 2:
            return device.get("rssi")
        if col == 3:
            services = device.get("services", [])
            return ",".join(services[:3]) if services else "---"
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
    def update_devices(self, devices: Dict[str, dict]) -> None:
        """Update BLE device data.

        Args:
            devices: Dict keyed by MAC address.
        """
        self.beginResetModel()
        self._devices = devices
        self._sort_devices()
        self.endResetModel()

    def sort(self, column: int, order: Qt.SortOrder = Qt.DescendingOrder) -> None:
        self._sort_column = column
        self._sort_order = order
        self.layoutAboutToBeChanged.emit()
        self._sort_devices()
        self.layoutChanged.emit()

    def _sort_devices(self) -> None:
        reverse = self._sort_order == Qt.DescendingOrder
        self._sorted_addresses = sorted(
            self._devices.keys(),
            key=lambda addr: self._sort_key(self._devices[addr], reverse),
            reverse=reverse,
        )

    def _sort_key(self, device: dict, reverse: bool):
        def numeric(value):
            if value is None:
                return float("-inf") if reverse else float("inf")
            return value

        if self._sort_column == 0:
            return (device.get("name") or "").upper()
        if self._sort_column == 1:
            return (device.get("address") or "").upper()
        if self._sort_column == 2:
            return numeric(device.get("rssi"))
        if self._sort_column == 3:
            return ",".join(device.get("services", []))
        if self._sort_column == 4:
            return numeric(device.get("last_seen"))
        return 0

    def clear(self) -> None:
        """Clear BLE device data."""
        self.beginResetModel()
        self._devices.clear()
        self._sorted_addresses.clear()
        self.endResetModel()


class WiFiView(QWidget):
    """Wi-Fi/BLE scanner view with tables and status display."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._wifi_model = WiFiTableModel()
        self._ble_model = BLETableModel()
        self._table_view: TouchTableView = TouchTableView()
        self._ble_table_view: TouchTableView = TouchTableView()
        self._status_label: QLabel = QLabel("AWAITING WIFI DATA")
        self._sort_label: QLabel = QLabel("SORT: SIGNAL")
        self._ble_status_label: QLabel = QLabel("AWAITING BLE DATA")
        self._wifi_summary: QLabel = QLabel("Networks: 0 | Strongest: N/A")
        self._ble_summary: QLabel = QLabel("Devices: 0 | Closest: N/A")
        self._build_ui()

    def _build_ui(self) -> None:
        """Construct the UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        splitter = QSplitter(Qt.Vertical)
        splitter.setHandleWidth(2)

        wifi_container = QWidget()
        wifi_layout = QVBoxLayout(wifi_container)
        wifi_layout.setContentsMargins(0, 0, 0, 0)
        wifi_layout.setSpacing(4)

        header_label = QLabel("WI-FI NETWORKS")
        header_label.setFont(QFont("DejaVu Sans Mono", 12, QFont.Bold))
        header_label.setStyleSheet("color: #FFB000; background: transparent; border: none;")
        header_label.setAlignment(Qt.AlignCenter)
        header_label.setFixedHeight(24)
        wifi_layout.addWidget(header_label)

        self._wifi_summary.setFont(QFont("DejaVu Sans Mono", 10, QFont.Bold))
        self._wifi_summary.setStyleSheet("color: #BB86FC; background: transparent; border: none;")
        self._wifi_summary.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._wifi_summary.setFixedHeight(22)
        wifi_layout.addWidget(self._wifi_summary)

        self._table_view.setFont(QFont("DejaVu Sans Mono", 9))
        self._table_view.setSelectionBehavior(QTableView.SelectRows)
        self._table_view.setSelectionMode(QTableView.SingleSelection)
        self._table_view.setAlternatingRowColors(False)
        self._table_view.setShowGrid(True)
        self._table_view.setSortingEnabled(False)
        self._table_view.verticalHeader().setVisible(False)
        self._table_view.horizontalHeader().setStretchLastSection(True)
        self._table_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._table_view.setModel(self._wifi_model)
        self._table_view.setItemDelegateForColumn(3, SignalStrengthDelegate(self._table_view))
        self._table_view.long_press.connect(lambda details: self._show_details("WI-FI DETAILS", details))
        self._table_view.refresh_requested.connect(self._refresh_wifi)

        TableStyler.apply_tactical_style(self._table_view)
        TableStyler.set_column_widths(
            self._table_view,
            {
                "SSID": 150,
                "BSSID": 130,
                "CHANNEL": 60,
                "SIGNAL": 100,
                "SECURITY": 100,
                "LAST SEEN": 120,
            },
        )
        self._table_view.sortByColumn(3, Qt.DescendingOrder)

        wifi_layout.addWidget(self._table_view, 1)

        wifi_footer = QHBoxLayout()
        wifi_footer.setContentsMargins(0, 0, 0, 0)
        wifi_footer.setSpacing(8)
        self._sort_label.setFont(QFont("DejaVu Sans Mono", 9, QFont.Bold))
        self._sort_label.setStyleSheet("color: #D4A0FF; background: transparent; border: none;")
        wifi_footer.addWidget(self._sort_label)
        wifi_footer.addStretch(1)
        self._status_label.setFont(QFont("DejaVu Sans Mono", 9))
        self._status_label.setStyleSheet("color: #6C3483; background: transparent; border: none;")
        wifi_footer.addWidget(self._status_label)
        wifi_layout.addLayout(wifi_footer)

        ble_container = QWidget()
        ble_layout = QVBoxLayout(ble_container)
        ble_layout.setContentsMargins(0, 0, 0, 0)
        ble_layout.setSpacing(4)

        ble_header = QLabel("BLUETOOTH LE DEVICES")
        ble_header.setFont(QFont("DejaVu Sans Mono", 12, QFont.Bold))
        ble_header.setStyleSheet("color: #D4A0FF; background: transparent; border: none;")
        ble_header.setAlignment(Qt.AlignCenter)
        ble_header.setFixedHeight(22)
        ble_layout.addWidget(ble_header)

        self._ble_summary.setFont(QFont("DejaVu Sans Mono", 10, QFont.Bold))
        self._ble_summary.setStyleSheet("color: #BB86FC; background: transparent; border: none;")
        self._ble_summary.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._ble_summary.setFixedHeight(22)
        ble_layout.addWidget(self._ble_summary)

        self._ble_table_view.setFont(QFont("DejaVu Sans Mono", 9))
        self._ble_table_view.setSelectionBehavior(QTableView.SelectRows)
        self._ble_table_view.setSelectionMode(QTableView.SingleSelection)
        self._ble_table_view.setAlternatingRowColors(False)
        self._ble_table_view.setShowGrid(True)
        self._ble_table_view.setSortingEnabled(False)
        self._ble_table_view.verticalHeader().setVisible(False)
        self._ble_table_view.horizontalHeader().setStretchLastSection(True)
        self._ble_table_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._ble_table_view.setModel(self._ble_model)
        self._ble_table_view.setItemDelegateForColumn(2, SignalStrengthDelegate(self._ble_table_view))
        self._ble_table_view.long_press.connect(lambda details: self._show_details("BLE DETAILS", details))
        self._ble_table_view.refresh_requested.connect(self._refresh_ble)

        TableStyler.apply_tactical_style(self._ble_table_view)
        TableStyler.set_column_widths(
            self._ble_table_view,
            {
                "NAME": 150,
                "ADDRESS": 130,
                "RSSI": 80,
                "SERVICES": 200,
                "LAST SEEN": 120,
            },
        )
        self._ble_table_view.sortByColumn(2, Qt.DescendingOrder)

        ble_layout.addWidget(self._ble_table_view, 1)

        ble_footer = QHBoxLayout()
        ble_footer.setContentsMargins(0, 0, 0, 0)
        ble_footer.setSpacing(8)
        self._ble_status_label.setFont(QFont("DejaVu Sans Mono", 9))
        self._ble_status_label.setStyleSheet("color: #6C3483; background: transparent; border: none;")
        ble_footer.addWidget(self._ble_status_label)
        ble_footer.addStretch(1)
        ble_layout.addLayout(ble_footer)

        splitter.addWidget(wifi_container)
        splitter.addWidget(ble_container)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter, 1)

    def _show_details(self, title: str, details: dict) -> None:
        dialog = DetailDialog(title, details, self)
        dialog.exec_()

    def _refresh_wifi(self) -> None:
        self._wifi_model.clear()
        self._status_label.setText("REFRESHING WIFI...")
        self._status_label.setStyleSheet("color: #D4A0FF; background: transparent; border: none;")

    def _refresh_ble(self) -> None:
        self._ble_model.clear()
        self._ble_status_label.setText("REFRESHING BLE...")
        self._ble_status_label.setStyleSheet("color: #D4A0FF; background: transparent; border: none;")

    @pyqtSlot(dict)
    def update_networks(self, networks: Dict[str, dict]) -> None:
        """Update the table with new network data."""
        self._wifi_model.update_networks(networks)
        self._status_label.setText(f"NETWORKS: {len(networks)}")
        self._status_label.setStyleSheet("color: #D4A0FF; background: transparent; border: none;")
        strongest = max(
            (net.get("signal_dbm") for net in networks.values() if net.get("signal_dbm") is not None),
            default=None,
        )
        strongest_text = "N/A" if strongest is None else f"{strongest} dBm"
        self._wifi_summary.setText(f"Networks: {len(networks)} | Strongest: {strongest_text}")

    def toggle_sort(self) -> None:
        """Toggle sorting mode between signal and last seen."""
        self._wifi_model.toggle_sort()
        self._sort_label.setText("SORT: SIGNAL" if self._wifi_model.sort_by_signal else "SORT: LAST SEEN")

    @pyqtSlot(dict)
    def update_ble_devices(self, devices: Dict[str, dict]) -> None:
        """Update the BLE device table."""
        self._ble_model.update_devices(devices)
        self._ble_status_label.setText(f"BLE DEVICES: {len(devices)}")
        self._ble_status_label.setStyleSheet("color: #D4A0FF; background: transparent; border: none;")
        closest = max(
            (dev.get("rssi") for dev in devices.values() if dev.get("rssi") is not None),
            default=None,
        )
        closest_text = "N/A" if closest is None else f"{closest} dBm"
        self._ble_summary.setText(f"Devices: {len(devices)} | Closest: {closest_text}")

    @pyqtSlot(str)
    def set_status(self, status: str) -> None:
        """Set status label text."""
        self._status_label.setText(status.upper())

    def set_amber_warning(self, message: str) -> None:
        """Set an amber warning status message for Wi-Fi."""
        self._status_label.setText(message.upper())
        self._status_label.setStyleSheet("color: #FFB000; background: transparent; border: none;")

    @pyqtSlot(str)
    def set_error(self, error: str) -> None:
        """Set error message in status label."""
        self._status_label.setText(f"ERROR: {error.upper()}")
        self._status_label.setStyleSheet("color: #FF0000; background: transparent; border: none;")

    @pyqtSlot(str)
    def set_ble_status(self, status: str) -> None:
        """Set BLE status label text."""
        self._ble_status_label.setText(status.upper())

    def set_ble_amber_warning(self, message: str) -> None:
        """Set an amber warning status message for BLE."""
        self._ble_status_label.setText(message.upper())
        self._ble_status_label.setStyleSheet("color: #FFB000; background: transparent; border: none;")

    @pyqtSlot(str)
    def set_ble_error(self, error: str) -> None:
        """Set BLE error message in status label."""
        self._ble_status_label.setText(f"ERROR: {error.upper()}")
        self._ble_status_label.setStyleSheet("color: #FF0000; background: transparent; border: none;")

    def clear(self) -> None:
        """Clear all network data."""
        self._wifi_model.clear()
        self._status_label.setText("AWAITING WIFI DATA")
        self._status_label.setStyleSheet("color: #6C3483; background: transparent; border: none;")
        self._wifi_summary.setText("Networks: 0 | Strongest: N/A")
        self._ble_model.clear()
        self._ble_status_label.setText("AWAITING BLE DATA")
        self._ble_status_label.setStyleSheet("color: #6C3483; background: transparent; border: none;")
        self._ble_summary.setText("Devices: 0 | Closest: N/A")

    def update_summary(self) -> None:
        """Update summary statistics label."""
        self._wifi_summary.setText("Networks: 0 | Strongest: N/A")
        self._ble_summary.setText("Devices: 0 | Closest: N/A")

    def clear_data(self) -> None:
        """Clear all displayed data."""
        self.clear()