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
        "SQUAWK",
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
            return QColor("#0A0A0F")

        return QVariant()

    # Emergency squawk codes
    EMERGENCY_SQUAWKS = {
        "7500": "HIJACK",
        "7600": "RADIO FAIL",
        "7700": "EMERGENCY",
    }

    def _get_display_value(self, aircraft: dict, col: int) -> str:
        """Get formatted display value for a specific column.

        Args:
            aircraft: Aircraft data dictionary.
            col: Column index.

        Returns:
            Formatted string for display.
        """
        if col == 0:  # ICAO
            return aircraft.get("icao", "---")

        elif col == 1:  # CALLSIGN (with military indicator)
            callsign = aircraft.get("callsign")
            if not callsign:
                return "---"
            if aircraft.get("military"):
                return f"\u2605 {callsign}"  # ★ prefix for military
            return callsign

        elif col == 2:  # ALTITUDE (ft) with vertical rate arrow
            altitude = aircraft.get("altitude")
            if altitude is not None:
                altitude_ft = altitude * 3.28084
                vr = aircraft.get("vertical_rate")
                arrow = ""
                if vr is not None:
                    if vr > 1.0:
                        arrow = " \u2191"  # ↑ climbing
                    elif vr < -1.0:
                        arrow = " \u2193"  # ↓ descending
                    else:
                        arrow = " \u2192"  # -> level
                return f"{int(altitude_ft)}{arrow}"
            return "---"

        elif col == 3:  # SPEED (knots, aviation standard)
            velocity = aircraft.get("velocity")
            if velocity is not None:
                speed_kts = velocity * 1.94384  # m/s -> knots
                return f"{int(speed_kts)} kt"
            return "---"

        elif col == 4:  # HEADING with compass direction
            heading = aircraft.get("heading")
            if heading is not None:
                compass = self._heading_to_compass(heading)
                return f"{heading:.0f}\u00b0 {compass}"
            return "---"

        elif col == 5:  # SQUAWK
            squawk = aircraft.get("squawk")
            if squawk is not None:
                emergency = self.EMERGENCY_SQUAWKS.get(str(squawk))
                if emergency:
                    return f"\u26a0 {squawk}"  # ⚠ prefix for emergency
                return str(squawk)
            return "---"

        elif col == 6:  # DISTANCE
            distance = aircraft.get("distance")
            if distance is not None:
                if distance < 1000.0:
                    return f"{int(distance)} m"
                elif distance < 10000.0:
                    return f"{distance / 1000.0:.1f} km"
                else:
                    nm = distance / 1852.0  # nautical miles
                    return f"{nm:.1f} nm"
            return "---"

        elif col == 7:  # LAST SEEN
            last_seen = aircraft.get("last_seen")
            if last_seen is not None:
                elapsed = time.time() - last_seen
                if elapsed < 60.0:
                    return f"{int(elapsed)}s"
                else:
                    return f"{int(elapsed / 60.0)}m"
            return "---"

        return "---"

    @staticmethod
    def _heading_to_compass(heading: float) -> str:
        """Convert heading degrees to compass direction."""
        directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        idx = int((heading + 22.5) / 45.0) % 8
        return directions[idx]

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
            return (aircraft.get("squawk") or "")
        if self._sort_column == 6:
            return numeric(aircraft.get("distance"))
        if self._sort_column == 7:
            return numeric(aircraft.get("last_seen"))
        return 0

    def _get_altitude_color(self, aircraft: dict) -> QColor:
        """Get row color based on squawk emergency status and altitude band."""
        # Emergency squawk codes get red highlighting
        squawk = aircraft.get("squawk")
        if squawk is not None and str(squawk) in self.EMERGENCY_SQUAWKS:
            return QColor("#FF0000")

        altitude = aircraft.get("altitude")
        if altitude is None:
            return QColor("#D4A0FF")
        altitude_ft = altitude * 3.28084
        if altitude_ft < 10000:
            return QColor("#D4A0FF")  # Low altitude -- bright purple
        if altitude_ft <= 25000:
            return QColor("#FFB000")  # Mid altitude -- amber
        return QColor("#80E0FF")  # High altitude -- cyan

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
        self._summary_label.setStyleSheet("color: #BB86FC; background: transparent; border: none;")
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
                "ICAO": 70,
                "CALLSIGN": 90,
                "ALTITUDE": 80,
                "SPEED": 70,
                "HEADING": 80,
                "SQUAWK": 70,
                "DISTANCE": 70,
                "LAST SEEN": 60,
            },
        )
        self._table_view.sortByColumn(6, Qt.AscendingOrder)

        layout.addWidget(self._table_view, 7)

        # Emergency alert banner (hidden by default)
        self._alert_banner = QLabel("")
        self._alert_banner.setFont(QFont("DejaVu Sans Mono", 12, QFont.Bold))
        self._alert_banner.setStyleSheet(
            "color: #FFFFFF; background: #CC0000; border: 2px solid #FF0000;"
            "padding: 4px; border-radius: 4px;"
        )
        self._alert_banner.setAlignment(Qt.AlignCenter)
        self._alert_banner.setFixedHeight(32)
        self._alert_banner.setVisible(False)
        layout.addWidget(self._alert_banner)

        # Stats panel (replaces map placeholder)
        from PyQt5.QtWidgets import QHBoxLayout, QFrame
        stats_container = QFrame()
        stats_container.setStyleSheet(
            "QFrame { background: #12121A; border: 1px solid #2D1B4E; border-radius: 4px; }"
        )
        stats_layout = QHBoxLayout(stats_container)
        stats_layout.setContentsMargins(8, 4, 8, 4)
        stats_layout.setSpacing(16)

        stat_font = QFont("DejaVu Sans Mono", 10, QFont.Bold)

        self._stat_closest = QLabel("CLOSEST: ---")
        self._stat_closest.setFont(stat_font)
        self._stat_closest.setStyleSheet("color: #D4A0FF; background: transparent; border: none;")
        stats_layout.addWidget(self._stat_closest)

        self._stat_highest = QLabel("HIGHEST: ---")
        self._stat_highest.setFont(stat_font)
        self._stat_highest.setStyleSheet("color: #80E0FF; background: transparent; border: none;")
        stats_layout.addWidget(self._stat_highest)

        self._stat_fastest = QLabel("FASTEST: ---")
        self._stat_fastest.setFont(stat_font)
        self._stat_fastest.setStyleSheet("color: #FFB000; background: transparent; border: none;")
        stats_layout.addWidget(self._stat_fastest)

        self._stat_messages = QLabel("MSGS: 0")
        self._stat_messages.setFont(stat_font)
        self._stat_messages.setStyleSheet("color: #BB86FC; background: transparent; border: none;")
        stats_layout.addWidget(self._stat_messages)

        layout.addWidget(stats_container)

        self._status_label = QLabel("AWAITING ADS-B DATA")
        self._status_label.setFont(QFont("DejaVu Sans Mono", 10))
        self._status_label.setStyleSheet("color: #6C3483; background: transparent; border: none;")
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setFixedHeight(24)
        layout.addWidget(self._status_label)

        self._total_messages = 0

    def _show_details(self, details: dict) -> None:
        dialog = DetailDialog("ADS-B DETAILS", details, self)
        dialog.exec_()

    def _refresh_requested(self) -> None:
        self._model.clear()
        self._status_label.setText("REFRESHING ADS-B...")
        self._status_label.setStyleSheet("color: #D4A0FF; background: transparent; border: none;")

    @pyqtSlot(dict)
    def update_aircraft(self, aircraft_dict: Dict[str, dict]) -> None:
        """Update the table with new aircraft data.

        Args:
            aircraft_dict: Dictionary of aircraft keyed by ICAO.
        """
        self._model.update_aircraft(aircraft_dict)
        self._total_messages += 1

        count = len(aircraft_dict)
        self._tracked_count = count
        self._in_range_count = sum(
            1 for aircraft in aircraft_dict.values() if aircraft.get("distance") is not None
        )
        self._military_count = sum(
            1 for aircraft in aircraft_dict.values() if aircraft.get("military")
        )
        self.update_summary()
        self._update_stats_panel(aircraft_dict)
        self._check_emergencies(aircraft_dict)

        if count == 0:
            self._status_label.setText("NO AIRCRAFT DETECTED")
            self._status_label.setStyleSheet("color: #6C3483; background: transparent; border: none;")
        else:
            self._status_label.setText(f"TRACKING {count} AIRCRAFT")
            self._status_label.setStyleSheet("color: #D4A0FF; background: transparent; border: none;")

    def _update_stats_panel(self, aircraft_dict: Dict[str, dict]) -> None:
        """Update the stats panel with closest/highest/fastest aircraft."""
        if not aircraft_dict:
            self._stat_closest.setText("CLOSEST: ---")
            self._stat_highest.setText("HIGHEST: ---")
            self._stat_fastest.setText("FASTEST: ---")
            self._stat_messages.setText(f"MSGS: {self._total_messages}")
            return

        # Find closest aircraft
        closest = None
        closest_dist = float("inf")
        for ac in aircraft_dict.values():
            dist = ac.get("distance")
            if dist is not None and dist < closest_dist:
                closest_dist = dist
                closest = ac

        if closest is not None:
            callsign = closest.get("callsign") or closest.get("icao", "?")
            if closest_dist < 1000:
                self._stat_closest.setText(f"CLOSEST: {callsign} {int(closest_dist)}m")
            elif closest_dist < 10000:
                self._stat_closest.setText(f"CLOSEST: {callsign} {closest_dist/1000:.1f}km")
            else:
                nm = closest_dist / 1852.0
                self._stat_closest.setText(f"CLOSEST: {callsign} {nm:.1f}nm")
        else:
            self._stat_closest.setText("CLOSEST: ---")

        # Find highest aircraft
        highest = None
        highest_alt = float("-inf")
        for ac in aircraft_dict.values():
            alt = ac.get("altitude")
            if alt is not None and alt > highest_alt:
                highest_alt = alt
                highest = ac

        if highest is not None:
            callsign = highest.get("callsign") or highest.get("icao", "?")
            alt_ft = int(highest_alt * 3.28084)
            self._stat_highest.setText(f"HIGHEST: {callsign} FL{alt_ft // 100}")
        else:
            self._stat_highest.setText("HIGHEST: ---")

        # Find fastest aircraft
        fastest = None
        fastest_spd = float("-inf")
        for ac in aircraft_dict.values():
            spd = ac.get("velocity")
            if spd is not None and spd > fastest_spd:
                fastest_spd = spd
                fastest = ac

        if fastest is not None:
            callsign = fastest.get("callsign") or fastest.get("icao", "?")
            speed_kts = int(fastest_spd * 1.94384)
            self._stat_fastest.setText(f"FASTEST: {callsign} {speed_kts}kt")
        else:
            self._stat_fastest.setText("FASTEST: ---")

        self._stat_messages.setText(f"MSGS: {self._total_messages}")

    def _check_emergencies(self, aircraft_dict: Dict[str, dict]) -> None:
        """Check for emergency squawk codes and show/hide alert banner."""
        emergencies = []
        for ac in aircraft_dict.values():
            squawk = ac.get("squawk")
            if squawk is not None and str(squawk) in ADSBAircraftTableModel.EMERGENCY_SQUAWKS:
                callsign = ac.get("callsign") or ac.get("icao", "UNKNOWN")
                alert_type = ADSBAircraftTableModel.EMERGENCY_SQUAWKS[str(squawk)]
                emergencies.append(f"\u26a0 {callsign}: {alert_type} (SQUAWK {squawk})")

        if emergencies:
            self._alert_banner.setText(" | ".join(emergencies))
            self._alert_banner.setVisible(True)
        else:
            self._alert_banner.setVisible(False)

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
        self._status_label.setStyleSheet("color: #6C3483; background: transparent; border: none;")

    def update_summary(self) -> None:
        """Update summary statistics label."""
        if self._summary_label is not None:
            mil = getattr(self, '_military_count', 0)
            parts = [
                f"Tracked: {self._tracked_count}",
                f"In range: {self._in_range_count}",
            ]
            if mil > 0:
                parts.append(f"\u2605 MIL: {mil}")
            self._summary_label.setText(" | ".join(parts))

    def clear_data(self) -> None:
        """Clear all displayed data."""
        self.clear()
