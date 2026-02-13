"""RF Tactical Monitor - Table styling utilities."""

from PyQt5.QtWidgets import QAbstractItemView, QHeaderView
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont


class TableStyler:
    """Utility class for consistent tactical table styling."""

    @staticmethod
    def apply_tactical_style(table_widget):
        """Apply consistent tactical styling to any table."""
        header = table_widget.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        table_widget.verticalHeader().setDefaultSectionSize(36)
        table_widget.verticalHeader().setVisible(False)

        table_widget.setSelectionBehavior(QAbstractItemView.SelectRows)
        table_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        table_widget.setAlternatingRowColors(True)
        table_widget.setSortingEnabled(True)

        font = QFont("DejaVu Sans Mono", 10)
        table_widget.setFont(font)

        table_widget.setStyleSheet(
            """
            QTableView {
                gridline-color: #2D1B4E;
                background-color: #0A0A0F;
                color: #BB86FC;
                border: 1px solid #2A2A3E;
            }
            QTableView::item:selected {
                background-color: #2D1B4E;
                color: #D4A0FF;
            }
            QHeaderView::section {
                background-color: #12121A;
                color: #BB86FC;
                padding: 8px;
                border: 1px solid #2A2A3E;
                font-weight: bold;
            }
            """
        )

    @staticmethod
    def set_column_widths(table_widget, widths_dict):
        """Set specific column widths by name."""
        header = table_widget.horizontalHeader()
        model = table_widget.model()
        if model is None:
            return
        for col_name, width in widths_dict.items():
            for i in range(model.columnCount()):
                item = model.headerData(i, header.orientation(), Qt.DisplayRole)
                if item == col_name:
                    table_widget.setColumnWidth(i, width)