"""Live log view for RF Tactical Monitor."""

import logging

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget


class LogSignal(QObject):
    message_emitted = pyqtSignal(str)


class QtLogHandler(logging.Handler):
    """Logging handler that forwards formatted messages via Qt signal."""

    def __init__(self, signal: LogSignal) -> None:
        super().__init__()
        self._signal = signal

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._signal.message_emitted.emit(msg)
        except Exception:
            pass


class LogView(QWidget):
    """Widget that displays live logs."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self._log_output = QPlainTextEdit()
        self._log_output.setReadOnly(True)
        self._log_output.setFont(QFont("Source Code Pro", 9))
        self._log_output.setStyleSheet("background-color: #0A0A0F; color: #BB86FC;")
        layout.addWidget(self._log_output)

        self._signal = LogSignal()
        self._signal.message_emitted.connect(self._append_line)

    def _append_line(self, message: str) -> None:
        self._log_output.appendPlainText(message)
        self._log_output.verticalScrollBar().setValue(
            self._log_output.verticalScrollBar().maximum()
        )

    def attach_logger(self, logger: logging.Logger) -> None:
        handler = QtLogHandler(self._signal)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
        handler.setFormatter(formatter)
        handler.setLevel(logging.DEBUG)
        logger.addHandler(handler)