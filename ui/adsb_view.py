"""RF Tactical Monitor - ADS-B Aircraft Table View

QTableView displaying tracked aircraft with tactical styling.
Columns: ICAO, Callsign, Altitude, Speed, Heading, Distance, Last Seen.
"""

import time
from typing import Dict, List

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHeaderView, QLabel, QTableView
from PyQt5.QtCore import Qt, QAbstractTableModel, QModelIndex, QVariant, pyqtSlot
from ui.touch_table import TouchTableView, DetailDialog
from PyQt5.QtGui import QFont, QColor

from utils.table_style import TableStyler


class ADSBAircraftTableModel(QAbstractTableModel):
    """Table model for ADS-B aircraft data.

    Displays aircraft sorted by distance (closest first).
    Columns: ICAO, Callsign, Altitude, Speed, Heading, Distance, Last Seen.
    """

    COLUMNS = [
        "ICAO",
        "CALLSIGN",
        "ALTITUDE",
        "SPEED",
        "HEADING",
        "DISTANCE",
        "LAST SEEN",
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._aircraft: Dict[str, dict] = {}
        self._sorted_icaos: List[str] = []
        self._sort_column = 5
        self._sort_order = Qt.AscendingOrder

    def rowCount(self, parent=QModelIndex()) -> int:
        """Return number of aircraft."""
        if parent.isValid():
            return 0
        return len(self._sorted_icaos)

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
    ):
        """Return header data for columns."""
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                if 0 <= section < len(self.COLUMNS):
                    return self.COLUMNS[section]
        elif role == Qt.TextAlignmentRole:
            return Qt.AlignCenter
        return QVariant()

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        """Return data for a specific cell."""
        if not index.isValid():
            return QVariant()

        row = index.row()
        col = index.column()

        if row < 0 or row >= len(self._sorted_icaos):
            return QVariant()

        icao = self._sorted_icaos[row]
        aircraft = self._aircraft.get(icao)

        if aircraft is None:
            return QVariant()

        if role == Qt.DisplayRole:
            return self._get_display_value(aircraft, col)
        elif role == Qt.TextAlignmentRole:
            return Qt.AlignCenter
        elif role == Qt.ForegroundRole:
            return self._get_altitude_color(aircraft)
        elif role == Qt.BackgroundRole:
            return QColor("#0A0A0A")

        return QVariant()

    def _get_display_value(self, aircraft: dict, col: int) -> str:
        """Get formatted display value for a specific column.

        Args:
            aircraft: Aircraft data dictionary.
            col: Column index.

        Returns:
            Formatted string for display.
        """
        if col == 0:
            return aircraft.get("icao", "---")

        elif col == 1:
            callsign = aircraft.get("callsign")
            return callsign if callsign else "---"

        elif col == 2:
            altitude = aircraft.get("altitude")
            if altitude is not None:
                altitude_ft = altitude * 3.28084
                return f"{int(altitude_ft)} ft"
            return "---"

        elif col == 3:
            velocity = aircraft.get("velocity")
            if velocity is not None:
                return f"{velocity:.1f} m/s"
            return "---"

        elif col == 4:
            heading = aircraft.get("heading")
            if heading is not None:
                return f"{heading:.0f}°"
            return "---"

        elif col == 5:
            distance = aircraft.get("distance")
            if distance is not None:
                if distance < 1000.0:
                    return f"{int(distance)} m"
                else:
                    return f"{distance / 1000.0:.1f} km"
            return "---"

        elif col == 6:
            last_seen = aircraft.get("last_seen")
            if last_seen is not None:
                elapsed = time.time() - last_seen
                if elapsed < 60.0:
                    return f"{int(elapsed)}s"
                else:
                    return f"{int(elapsed / 60.0)}m"
            return "---"

        return "---"

    @pyqtSlot(dict)
    def update_aircraft(self, aircraft_dict: Dict[str, dict]) -> None:
        """Update the model with new aircraft data.

        Args:
            aircraft_dict: Dictionary of aircraft keyed by ICAO.
        """
        self.beginResetModel()

        self._aircraft = aircraft_dict

        self._sort_aircraft()

        self.endResetModel()

    def sort(self, column: int, order: Qt.SortOrder = Qt.AscendingOrder) -> None:
        self._sort_column = column
        self._sort_order = order
        self.layoutAboutToBeChanged.emit()
        self._sort_aircraft()
        self.layoutChanged.emit()

    def _sort_aircraft(self) -> None:
        reverse = self._sort_order == Qt.DescendingOrder
        aircraft_list = list(self._aircraft.values())
        aircraft_list.sort(key=lambda a: self._sort_key(a, reverse), reverse=reverse)
        self._sorted_icaos = [a["icao"] for a in aircraft_list]

    def _sort_key(self, aircraft: dict, reverse: bool):
        def numeric(value):
            if value is None:
                return float("-inf") if reverse else float("inf")
            return value

        if self._sort_column == 0:
            return (aircraft.get("icao") or "").upper()
        if self._sort_column == 1:
            return (aircraft.get("callsign") or "").upper()
        if self._sort_column == 2:
            return numeric(aircraft.get("altitude"))
        if self._sort_column == 3:
            return numeric(aircraft.get("velocity"))
        if self._sort_column == 4:
            return numeric(aircraft.get("heading"))
        if self._sort_column == 5:
            return numeric(aircraft.get("distance"))
        if self._sort_column == 6:
            return numeric(aircraft.get("last_seen"))
        return 0

    def _get_altitude_color(self, aircraft: dict) -> QColor:
        altitude = aircraft.get("altitude")
        if altitude is None:
            return QColor("#00FF41")
        altitude_ft = altitude * 3.28084
        if altitude_ft < 10000:
            return QColor("#00FF41")
        if altitude_ft <= 25000:
            return QColor("#FFB000")
        return QColor("#80E0FF")

    def clear(self) -> None:
        """Clear all aircraft data."""
        self.beginResetModel()
        self._aircraft.clear()
        self._sorted_icaos.clear()
        self.endResetModel()


class ADSBView(QWidget):
    """ADS-B aircraft table view widget.

    Displays tracked aircraft in a table with tactical styling.
    Automatically updates when aircraft data changes.

    Args:
        parent: Optional parent QWidget.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tracked_count = 0
        self._in_range_count = 0

        self._build_ui()

    def _build_ui(self) -> None:
        """Construct the UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._summary_label = QLabel("Aircraft tracked: 0 | In range: 0")
        self._summary_label.setFont(QFont("DejaVu Sans Mono", 11, QFont.Bold))
        self._summary_label.setStyleSheet("color: #00CC33; background: transparent; border: none;")
        self._summary_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._summary_label.setFixedHeight(24)
        layout.addWidget(self._summary_label)

        self._table_view = TouchTableView()
        self._table_view.setFont(QFont("DejaVu Sans Mono", 10))
        self._table_view.setSelectionBehavior(QTableView.SelectRows)
        self._table_view.setSelectionMode(QTableView.SingleSelection)
        self._table_view.setAlternatingRowColors(False)
        self._table_view.setShowGrid(True)
        self._table_view.setSortingEnabled(False)
        self._table_view.verticalHeader().setVisible(False)
        self._table_view.horizontalHeader().setStretchLastSection(True)
        self._table_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

        self._model = ADSBAircraftTableModel()
        self._table_view.setModel(self._model)
        self._table_view.long_press.connect(self._show_details)
        self._table_view.refresh_requested.connect(self._refresh_requested)

        TableStyler.apply_tactical_style(self._table_view)
        TableStyler.set_column_widths(
            self._table_view,
            {
                "ICAO": 80,
                "CALLSIGN": 100,
                "ALTITUDE": 80,
                "SPEED": 80,
                "HEADING": 80,
                "DISTANCE": 80,
                "LAST SEEN": 120,
            },
        )
        self._table_view.sortByColumn(5, Qt.AscendingOrder)

        layout.addWidget(self._table_view, 7)

        map_container = QWidget()
        map_layout = QVBoxLayout(map_container)
        map_layout.setContentsMargins(0, 0, 0, 0)
        map_layout.setSpacing(4)

        self._map_placeholder = QLabel("MAP VIEW - TBD")
        self._map_placeholder.setFont(QFont("DejaVu Sans Mono", 11, QFont.Bold))
        self._map_placeholder.setStyleSheet(
            "color: #006B1F; background: #121212; border: 1px solid #1A3D1A;"
        )
        self._map_placeholder.setAlignment(Qt.AlignCenter)
        self._map_placeholder.setMinimumHeight(120)
        map_layout.addWidget(self._map_placeholder, 1)

        self._status_label = QLabel("AWAITING ADS-B DATA")
        self._status_label.setFont(QFont("DejaVu Sans Mono", 10))
        self._status_label.setStyleSheet("color: #006B1F; background: transparent; border: none;")
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setFixedHeight(24)
        map_layout.addWidget(self._status_label)

        layout.addWidget(map_container, 3)

    def _show_details(self, details: dict) -> None:
        dialog = DetailDialog("ADS-B DETAILS", details, self)
        dialog.exec_()

    def _refresh_requested(self) -> None:
        self._model.clear()
        self._status_label.setText("REFRESHING ADS-B...")
        self._status_label.setStyleSheet("color: #00FF41; background: transparent; border: none;")

    @pyqtSlot(dict)
    def update_aircraft(self, aircraft_dict: Dict[str, dict]) -> None:
        """Update the table with new aircraft data.

        Args:
            aircraft_dict: Dictionary of aircraft keyed by ICAO.
        """
        self._model.update_aircraft(aircraft_dict)

        count = len(aircraft_dict)
        self._tracked_count = count
        self._in_range_count = sum(
            1 for aircraft in aircraft_dict.values() if aircraft.get("distance") is not None
        )
        self.update_summary()
        if count == 0:
            self._status_label.setText("NO AIRCRAFT DETECTED")
            self._status_label.setStyleSheet("color: #006B1F; background: transparent; border: none;")
        else:
            self._status_label.setText(f"TRACKING {count} AIRCRAFT")
            self._status_label.setStyleSheet("color: #00FF41; background: transparent; border: none;")

    @pyqtSlot(str)
    def set_status(self, status: str) -> None:
        """Set the status label text.

        Args:
            status: Status message to display.
        """
        self._status_label.setText(status.upper())

    def set_amber_warning(self, message: str) -> None:
        """Set an amber warning status message."""
        self._status_label.setText(message.upper())
        self._status_label.setStyleSheet("color: #FFB000; background: transparent; border: none;")

    @pyqtSlot(str)
    def set_error(self, error: str) -> None:
        """Set an error message in the status label.

        Args:
            error: Error message to display.
        """
        self._status_label.setText(f"ERROR: {error.upper()}")
        self._status_label.setStyleSheet("color: #FF0000; background: transparent; border: none;")

    def clear(self) -> None:
        """Clear all aircraft data from the table."""
        self._model.clear()
        self._tracked_count = 0
        self._in_range_count = 0
        self.update_summary()
        self._status_label.setText("AWAITING ADS-B DATA")
        self._status_label.setStyleSheet("color: #006B1F; background: transparent; border: none;")

    def update_summary(self) -> None:
        """Update summary statistics label."""
        if self._summary_label is not None:
            self._summary_label.setText(
                f"Aircraft tracked: {self._tracked_count} | In range: {self._in_range_count}"
            )

    def clear_data(self) -> None:
        """Clear all displayed data."""
        self.clear()
