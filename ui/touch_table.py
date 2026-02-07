"""RF Tactical Monitor - Touch-enabled table view utilities."""

from typing import Dict

from PyQt5.QtWidgets import QTableView, QDialog, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt, QTimer, QPoint, pyqtSignal
from PyQt5.QtGui import QFont


class DetailDialog(QDialog):
    """Dialog showing details for a table row."""

    def __init__(self, title: str, details: Dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumSize(360, 280)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        header = QLabel(title)
        header.setFont(QFont("DejaVu Sans Mono", 13, QFont.Bold))
        header.setStyleSheet("color: #00FF41; background: transparent;")
        header.setAlignment(Qt.AlignCenter)
        header.setMinimumHeight(28)
        layout.addWidget(header)

        for key, value in details.items():
            line = QLabel(f"{key}: {value}")
            line.setFont(QFont("DejaVu Sans Mono", 10))
            line.setStyleSheet("color: #00CC33; background: transparent;")
            line.setMinimumHeight(24)
            layout.addWidget(line)


class TouchTableView(QTableView):
    """Table view with long-press and pull-down refresh gestures."""

    long_press = pyqtSignal(dict)
    refresh_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_AcceptTouchEvents, True)
        self.verticalHeader().setDefaultSectionSize(44)
        self.horizontalHeader().setMinimumHeight(44)
        self._press_pos: QPoint = QPoint()
        self._long_press_timer = QTimer(self)
        self._long_press_timer.setSingleShot(True)
        self._long_press_timer.timeout.connect(self._emit_long_press)
        self._long_press_threshold_ms = 600
        self._pull_threshold_px = 60
        self._pull_ready = False

    def mousePressEvent(self, event):
        self._press_pos = event.pos()
        self._pull_ready = False
        if event.button() == Qt.LeftButton:
            self._long_press_timer.start(self._long_press_threshold_ms)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self._press_pos.isNull():
            delta = event.pos() - self._press_pos
            if abs(delta.x()) > 10 or abs(delta.y()) > 10:
                self._long_press_timer.stop()

            if delta.y() > self._pull_threshold_px and self.verticalScrollBar().value() == 0:
                self._pull_ready = True
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._long_press_timer.stop()
        if self._pull_ready:
            self._pull_ready = False
            self.refresh_requested.emit()
        self._press_pos = QPoint()
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        self._long_press_timer.stop()
        self._press_pos = QPoint()
        self._pull_ready = False
        super().leaveEvent(event)

    def _emit_long_press(self) -> None:
        index = self.indexAt(self._press_pos)
        if not index.isValid():
            return
        model = self.model()
        if model is None:
            return

        row = index.row()
        details = {}
        for col in range(model.columnCount()):
            header = model.headerData(col, Qt.Horizontal, Qt.DisplayRole)
            value = model.index(row, col).data(Qt.DisplayRole)
            details[str(header)] = "---" if value is None else str(value)

        self.long_press.emit(details)