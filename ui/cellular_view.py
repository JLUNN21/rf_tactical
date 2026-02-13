"""RF Tactical Monitor - Cellular View

Waterfall sweep with detected cellular bands table.
"""

from typing import List

from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHeaderView,
    QLabel,
    QTableView,
)
from PyQt5.QtCore import Qt, QAbstractTableModel, QModelIndex, QVariant, pyqtSlot
from PyQt5.QtGui import QFont, QColor

from ui.waterfall_widget import TacticalWaterfall
from ui.touch_table import TouchTableView, DetailDialog
from utils.table_style import TableStyler


class CellularBandTableModel(QAbstractTableModel):
    """Table model for detected cellular towers.

    Columns: Band, Frequency, ARFCN, Power, Operator, Last Seen.
    """

    COLUMNS = [
        "BAND",
        "FREQUENCY",
        "ARFCN",
        "POWER",
        "OPERATOR",
        "LAST SEEN",
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._bands: List[dict] = []
        self._sort_column = 3
        self._sort_order = Qt.DescendingOrder

    def rowCount(self, parent=QModelIndex()) -> int:
        """Return number of detected bands."""
        if parent.isValid():
            return 0
        return len(self._bands)

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

        if row < 0 or row >= len(self._bands):
            return QVariant()

        band = self._bands[row]

        if role == Qt.DisplayRole:
            return self._get_display_value(band, col)
        elif role == Qt.TextAlignmentRole:
            return Qt.AlignCenter
        elif role == Qt.ForegroundRole:
            return QColor("#D4A0FF")
        elif role == Qt.BackgroundRole:
            return QColor("#0A0A0F")
        return QVariant()

    def _get_display_value(self, band: dict, col: int) -> str:
        """Get formatted display value.

        Args:
            band: Band data dictionary.
            col: Column index.

        Returns:
            Value for display.
        """
        if col == 0:
            return band.get("band", "---")
        if col == 1:
            freq = band.get("frequency_hz")
            if freq is not None:
                return f"{freq / 1e6:.3f} MHz"
            return "---"
        if col == 2:
            return band.get("arfcn", "---")
        if col == 3:
            power = band.get("power_dbm")
            if power is not None:
                return f"{power:.1f} dBm"
            return "---"
        if col == 4:
            return band.get("operator", "---")
        if col == 5:
            last_seen = band.get("last_seen")
            if last_seen is not None:
                return f"{last_seen}s"
            return "---"
        return "---"

    @pyqtSlot(list)
    def update_bands(self, bands: List[dict]) -> None:
        """Update band list.

        Args:
            bands: List of detected band dictionaries.
        """
        self.beginResetModel()
        self._bands = list(bands)
        self._sort_bands()
        self.endResetModel()

    def sort(self, column: int, order: Qt.SortOrder = Qt.DescendingOrder) -> None:
        self._sort_column = column
        self._sort_order = order
        self.layoutAboutToBeChanged.emit()
        self._sort_bands()
        self.layoutChanged.emit()

    def _sort_bands(self) -> None:
        reverse = self._sort_order == Qt.DescendingOrder
        self._bands = sorted(
            self._bands,
            key=lambda entry: self._sort_key(entry, reverse),
            reverse=reverse,
        )

    def _sort_key(self, band: dict, reverse: bool):
        def numeric(value):
            if value is None:
                return float("-inf") if reverse else float("inf")
            return value

        if self._sort_column == 0:
            return (band.get("band") or "").upper()
        if self._sort_column == 1:
            return numeric(band.get("frequency_hz"))
        if self._sort_column == 2:
            return numeric(band.get("arfcn"))
        if self._sort_column == 3:
            return numeric(band.get("power_dbm"))
        if self._sort_column == 4:
            return (band.get("operator") or "").upper()
        if self._sort_column == 5:
            return numeric(band.get("last_seen"))
        return 0

    def clear(self) -> None:
        """Clear band data."""
        self.beginResetModel()
        self._bands = []
        self.endResetModel()


class CellularView(QWidget):
    """Cellular view with sweep waterfall and detected bands table.

    Args:
        waterfall: TacticalWaterfall widget configured for sweep range.
        parent: Optional parent QWidget.
    """

    def __init__(self, waterfall: TacticalWaterfall, parent=None) -> None:
        super().__init__(parent)
        self._waterfall = waterfall
        self._model = CellularBandTableModel()
        self._status_label = QLabel("AWAITING CELLULAR SWEEP")
        self._build_ui()

    def _build_ui(self) -> None:
        """Construct the UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        layout.addWidget(self._waterfall, 3)

        self._summary_label = QLabel("Towers detected: 0 | Strongest: N/A")
        self._summary_label.setFont(QFont("DejaVu Sans Mono", 11, QFont.Bold))
        self._summary_label.setStyleSheet("color: #FF8C00; background: transparent; border: none;")
        self._summary_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._summary_label.setFixedHeight(22)
        layout.addWidget(self._summary_label)

        table_view = QTableView()
        table_view = TouchTableView()
        table_view.setFont(QFont("DejaVu Sans Mono", 9))
        table_view.setSelectionBehavior(QTableView.SelectRows)
        table_view.setSelectionMode(QTableView.SingleSelection)
        table_view.setAlternatingRowColors(False)
        table_view.setShowGrid(True)
        table_view.setSortingEnabled(False)
        table_view.verticalHeader().setVisible(False)
        table_view.horizontalHeader().setStretchLastSection(True)
        table_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table_view.setModel(self._model)
        table_view.long_press.connect(self._show_details)
        table_view.refresh_requested.connect(self._refresh_requested)

        TableStyler.apply_tactical_style(table_view)
        TableStyler.set_column_widths(
            table_view,
            {
                "BAND": 80,
                "FREQUENCY": 120,
                "ARFCN": 80,
                "POWER": 80,
                "OPERATOR": 140,
                "LAST SEEN": 100,
            },
        )
        table_view.sortByColumn(3, Qt.DescendingOrder)

        layout.addWidget(table_view, 2)

        self._status_label.setFont(QFont("DejaVu Sans Mono", 9))
        self._status_label.setStyleSheet("color: #6C3483; background: transparent; border: none;")
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setFixedHeight(20)
        layout.addWidget(self._status_label)

        self._table_view = table_view

    @pyqtSlot(list)
    def update_bands(self, bands: List[dict]) -> None:
        """Update table with detected bands."""
        self._model.update_bands(bands)
        self._status_label.setText(f"BANDS DETECTED: {len(bands)}")
        self._status_label.setStyleSheet("color: #D4A0FF; background: transparent; border: none;")
        strongest = max((band.get("power_dbm") for band in bands if band.get("power_dbm") is not None), default=None)
        strongest_text = "N/A" if strongest is None else f"{strongest:.1f} dBm"
        if self._summary_label is not None:
            self._summary_label.setText(f"Towers detected: {len(bands)} | Strongest: {strongest_text}")

    def _show_details(self, details: dict) -> None:
        dialog = DetailDialog("CELLULAR BAND DETAILS", details, self)
        dialog.exec_()

    def _refresh_requested(self) -> None:
        self._model.clear()
        self._status_label.setText("REFRESHING CELLULAR...")
        self._status_label.setStyleSheet("color: #D4A0FF; background: transparent; border: none;")

    @pyqtSlot(str)
    def set_status(self, status: str) -> None:
        """Set status label text."""
        self._status_label.setText(status.upper())

    def set_amber_warning(self, message: str) -> None:
        """Set an amber warning status message."""
        self._status_label.setText(message.upper())
        self._status_label.setStyleSheet("color: #FFB000; background: transparent; border: none;")

    @pyqtSlot(str)
    def set_error(self, error: str) -> None:
        """Set error message in status label."""
        self._status_label.setText(f"ERROR: {error.upper()}")
        self._status_label.setStyleSheet("color: #FF0000; background: transparent; border: none;")

    def clear(self) -> None:
        """Clear detected bands and reset status."""
        self._model.clear()
        self._status_label.setText("AWAITING CELLULAR SWEEP")
        self._status_label.setStyleSheet("color: #6C3483; background: transparent; border: none;")
        if self._summary_label is not None:
            self._summary_label.setText("Towers detected: 0 | Strongest: N/A")

    def update_summary(self) -> None:
        """Update summary statistics label."""
        if self._summary_label is not None:
            self._summary_label.setText("Towers detected: 0 | Strongest: N/A")

    def clear_data(self) -> None:
        """Clear all displayed data."""
        self.clear()