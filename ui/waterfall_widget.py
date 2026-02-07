"""RF Tactical Monitor - Tactical Waterfall Display

Dual-panel FFT spectrum + scrolling waterfall spectrogram widget
built on pyqtgraph. Designed for 800×480 touch display.
"""

import numpy as np
import pyqtgraph as pg
from pyqtgraph import ColorMap
from PyQt5 import QtCore

from PyQt5.QtWidgets import QLabel
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

pg.setConfigOption("imageAxisOrder", "row-major")
pg.setConfigOption("background", "#0A0A0A")
pg.setConfigOption("foreground", "#00CC33")
pg.setConfigOptions(antialias=True)


class TacticalWaterfall(pg.GraphicsLayoutWidget):
    """Combined FFT spectrum plot and scrolling waterfall spectrogram.

    Args:
        fft_size: Number of FFT bins (determines horizontal resolution).
        history_size: Number of historical FFT rows in the waterfall.
        center_freq: Center frequency in Hz (for axis labeling).
        sample_rate: Sample rate in Hz (for axis labeling).
        parent: Optional parent QWidget.
    """

    COLORMAP_POSITIONS = [0.0, 0.15, 0.35, 0.55, 0.75, 0.9, 1.0]
    COLORMAP_COLORS = [
        (0, 0, 0),          # black   #000000
        (0, 0, 80),         # navy    #000050
        (0, 120, 48),       # dk grn  #007830
        (0, 204, 51),       # green   #00CC33
        (204, 204, 0),      # yellow  #CCCC00
        (255, 0, 0),        # red     #FF0000
        (255, 255, 255),    # white   #FFFFFF
    ]

    PRESET_COLORMAPS = {
        "TACTICAL GREEN": (COLORMAP_POSITIONS, COLORMAP_COLORS),
        "IRONBOW": (
            [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
            [
                (0, 0, 0),
                (32, 0, 64),
                (128, 0, 64),
                (200, 64, 0),
                (255, 160, 0),
                (255, 255, 255),
            ],
        ),
        "PLASMA": (
            [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
            [
                (12, 7, 134),
                (76, 34, 168),
                (139, 60, 150),
                (201, 83, 110),
                (248, 142, 65),
                (252, 253, 191),
            ],
        ),
        "GRAY": (
            [0.0, 1.0],
            [(0, 0, 0), (255, 255, 255)],
        ),
    }

    frequency_double_tapped = pyqtSignal(float)

    def __init__(
        self,
        fft_size: int = 1024,
        history_size: int = 200,
        center_freq: float = 433.92e6,
        sample_rate: float = 2e6,
        parent=None,
    ):
        super().__init__(parent=parent)
        self.setAttribute(Qt.WA_AcceptTouchEvents, True)
        self.grabGesture(Qt.PinchGesture)
        self.grabGesture(Qt.TapGesture)
        self.grabGesture(Qt.TapAndHoldGesture)

        self._fft_size = fft_size
        self._history_size = history_size
        self._center_freq = center_freq
        self._sample_rate = sample_rate

        self._spectrogram = np.full(
            (self._history_size, self._fft_size), -120.0, dtype=np.float64
        )
        self._current_spectrum = np.full(self._fft_size, -120.0, dtype=np.float64)
        self._rows_filled = 0

        self._freq_axis = self._compute_freq_axis()

        self._db_min = -100.0
        self._db_max = 0.0
        self._waterfall_min_db = -80.0

        self._colormap = self._build_colormap()
        self._lut = self._colormap.getLookupTable(
            start=0.0, stop=1.0, nPts=256, alpha=False
        )

        self.ci.layout.setContentsMargins(0, 0, 0, 0)
        self.ci.layout.setSpacing(0)

        self._build_spectrum_plot()
        self.nextRow()
        self._build_waterfall()
        self._build_fps_overlay()

        self._zoom_factor = 1.0

    def _compute_freq_axis(self) -> np.ndarray:
        """Compute frequency axis values in MHz from center_freq and sample_rate."""
        freq_hz = self._center_freq + np.linspace(
            -self._sample_rate / 2.0,
            self._sample_rate / 2.0,
            self._fft_size,
            endpoint=False,
        )
        return freq_hz / 1e6

    def _format_ticks(self, values: np.ndarray, decimals: int) -> list:
        return [(float(v), f"{v:.{decimals}f}") for v in values]

    def _apply_grid_and_ticks(self):
        grid_pen = pg.mkPen("#1A3D1A", width=1, style=Qt.DotLine)
        for plot in (self._spectrum_plot, self._waterfall_plot):
            plot.showGrid(x=True, y=True, alpha=1.0)
            for axis_key in ("bottom", "left"):
                axis = plot.getAxis(axis_key)
                axis.setTextPen("#00CC33")
                axis.setPen("#00CC33")
                axis.setStyle(tickFont=QFont("Source Code Pro", 9))
                axis.gridPen = grid_pen
                axis.setGrid(128)

        self._update_axis_ticks()

    def _update_axis_ticks(self):
        freq_min, freq_max = self._waterfall_plot.viewRange()[0]
        x_ticks = self._format_ticks(np.linspace(freq_min, freq_max, 5), 3)
        y_ticks = self._format_ticks(np.linspace(self._db_min, self._db_max, 4), 0)
        self._spectrum_plot.getAxis("bottom").setTicks([x_ticks])
        self._spectrum_plot.getAxis("left").setTicks([y_ticks])

        time_max = max(1.0, float(self._rows_filled or self._history_size))
        time_ticks = self._format_ticks(np.linspace(0.0, time_max, 4), 0)
        self._waterfall_plot.getAxis("bottom").setTicks([x_ticks])
        self._waterfall_plot.getAxis("left").setTicks([time_ticks])

    def _build_colormap(self, preset: str = "TACTICAL GREEN") -> ColorMap:
        """Build a colormap from presets."""
        positions, colors = self.PRESET_COLORMAPS.get(
            preset, (self.COLORMAP_POSITIONS, self.COLORMAP_COLORS)
        )
        return ColorMap(
            pos=np.array(positions, dtype=np.float64),
            color=np.array(colors, dtype=np.ubyte),
        )

    def _build_spectrum_plot(self):
        """Create the top FFT spectrum line plot."""
        self._spectrum_plot = self.addPlot(row=0, col=0)
        self._spectrum_plot.setLabel("left", "Power (dBm)")
        self._spectrum_plot.setLabel("bottom", "Frequency (MHz)")
        self._spectrum_plot.setYRange(self._db_min, self._db_max, padding=0)
        self._spectrum_plot.setXRange(
            self._freq_axis[0], self._freq_axis[-1], padding=0
        )
        self._spectrum_plot.showGrid(x=True, y=True, alpha=1.0)
        self._spectrum_plot.setMouseEnabled(x=False, y=False)
        self._spectrum_plot.setMenuEnabled(False)
        self._spectrum_plot.hideButtons()

        spectrum_pen = pg.mkPen(color="#00FF41", width=1)
        self._spectrum_curve = self._spectrum_plot.plot(
            self._freq_axis,
            self._current_spectrum,
            pen=spectrum_pen,
        )

        self._apply_grid_and_ticks()

    def _build_waterfall(self):
        """Create the bottom scrolling waterfall spectrogram."""
        self._waterfall_plot = self.addPlot(row=1, col=0)
        self._waterfall_plot.setLabel("bottom", "Frequency (MHz)")
        self._waterfall_plot.setLabel("left", "Time (s)")
        self._waterfall_plot.setMouseEnabled(x=False, y=False)
        self._waterfall_plot.setMenuEnabled(False)
        self._waterfall_plot.hideButtons()

        self._image_item = pg.ImageItem(axisOrder="row-major")
        self._waterfall_plot.addItem(self._image_item)

        self._image_item.setImage(
            self._spectrogram, autoLevels=False, levels=[self._waterfall_min_db, self._db_max]
        )
        self._image_item.setLookupTable(self._lut)

        freq_min = self._freq_axis[0]
        freq_max = self._freq_axis[-1]
        freq_range = freq_max - freq_min

        self._update_waterfall_geometry(freq_min, freq_range)

        self._waterfall_plot.setXRange(freq_min, freq_max, padding=0)
        self._waterfall_plot.setYRange(0, self._history_size, padding=0)

        self.ci.layout.setRowStretchFactor(0, 3)
        self.ci.layout.setRowStretchFactor(1, 7)

        self._apply_grid_and_ticks()

    def _update_waterfall_geometry(self, freq_min: float, freq_range: float):
        history = max(1, self._rows_filled or self._history_size)
        self._image_item.setRect(
            pg.QtCore.QRectF(
                freq_min,
                history,
                freq_range,
                -history,
            )
        )
        self._waterfall_plot.setYRange(0, history, padding=0)
        self._update_axis_ticks()

    def _build_fps_overlay(self):
        """Build FPS overlay label."""
        self._fps_label = QLabel("FPS: --", self)
        self._fps_label.setFont(QFont("Source Code Pro", 9, QFont.Bold))
        self._fps_label.setStyleSheet("color: #00CC33; background: transparent;")
        self._fps_label.setAlignment(Qt.AlignRight | Qt.AlignBottom)
        self._fps_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._fps_label.raise_()

    def _normalize_db(self, data: np.ndarray) -> np.ndarray:
        """Normalize dB values to 0.0–1.0 range for colormap lookup."""
        return np.clip(
            (data - self._db_min) / (self._db_max - self._db_min), 0.0, 1.0
        )

    def add_fft_row(self, magnitude_db: np.ndarray):
        """Add a new FFT magnitude row to the waterfall and update the spectrum.

        Args:
            magnitude_db: Array of FFT magnitude values in dB.
                          Must have length equal to fft_size.
        """
        row = np.asarray(magnitude_db, dtype=np.float64)

        if row.shape[0] != self._fft_size:
            row = np.interp(
                np.linspace(0, 1, self._fft_size),
                np.linspace(0, 1, row.shape[0]),
                row,
            )

        self._spectrogram = np.roll(self._spectrogram, -1, axis=0)
        self._spectrogram[-1, :] = row
        self._rows_filled = min(self._history_size, self._rows_filled + 1)

        np.copyto(self._current_spectrum, row)

        self._spectrum_curve.setData(self._freq_axis, self._current_spectrum)

        self._image_item.setImage(
            self._spectrogram, autoLevels=False, levels=[self._waterfall_min_db, self._db_max]
        )
        self._update_waterfall_geometry(self._freq_axis[0], self._freq_axis[-1] - self._freq_axis[0])

    def update_fps_overlay(self, fps: float):
        """Update the FPS overlay label."""
        if hasattr(self, "_fps_label"):
            self._fps_label.setText(f"FPS: {fps:.0f}")
            self._fps_label.adjustSize()
            margin = 6
            self._fps_label.move(
                self.width() - self._fps_label.width() - margin,
                self.height() - self._fps_label.height() - margin,
            )

    def mouseDoubleClickEvent(self, event):
        freq = self._screen_to_freq(event.pos().x())
        if freq is not None:
            self.frequency_double_tapped.emit(freq)
        super().mouseDoubleClickEvent(event)

    def event(self, event):
        if event.type() == QtCore.QEvent.Gesture:
            return self._handle_gesture(event)
        return super().event(event)

    def _handle_gesture(self, event):
        gesture = event.gesture(Qt.PinchGesture)
        if gesture is not None:
            self._handle_pinch(gesture)

        tap = event.gesture(Qt.TapGesture)
        if tap is not None and tap.state() == Qt.GestureFinished:
            tap_count = getattr(tap, "tapCount", lambda: 1)()
            if tap_count >= 2:
                pos = tap.position() if hasattr(tap, "position") else tap.hotSpot()
                freq = self._screen_to_freq(pos.x())
                if freq is not None:
                    self.frequency_double_tapped.emit(freq)
        return True

    def center_on_frequency(self, center_freq: float):
        """Center the display on a frequency without changing SDR tuning."""
        self._center_freq = center_freq
        self._freq_axis = self._compute_freq_axis()
        self._spectrum_curve.setData(self._freq_axis, self._current_spectrum)
        span = self._sample_rate / self._zoom_factor
        self._apply_zoom(span)

    def _handle_pinch(self, gesture):
        if gesture.state() == Qt.GestureUpdated:
            scale = gesture.scaleFactor()
            if scale <= 0:
                return
            self._zoom_factor = max(0.2, min(5.0, self._zoom_factor * scale))
            span = self._sample_rate / self._zoom_factor
            self._apply_zoom(span)

    def _apply_zoom(self, span: float):
        center_freq = self._center_freq
        freq_min = (center_freq - span / 2.0) / 1e6
        freq_max = (center_freq + span / 2.0) / 1e6
        self._spectrum_plot.setXRange(freq_min, freq_max, padding=0)
        self._waterfall_plot.setXRange(freq_min, freq_max, padding=0)
        self._update_axis_ticks()

    def _screen_to_freq(self, x_pos: float) -> float:
        if self._waterfall_plot is None:
            return None
        view_range = self._waterfall_plot.viewRange()[0]
        if not view_range:
            return None
        min_freq, max_freq = view_range
        width = max(1.0, self.width())
        freq_mhz = min_freq + (x_pos / width) * (max_freq - min_freq)
        return freq_mhz * 1e6

    def set_freq_range(self, center_freq: float, sample_rate: float):
        """Update the frequency axis for a new band.

        Args:
            center_freq: New center frequency in Hz.
            sample_rate: New sample rate in Hz.
        """
        self._center_freq = center_freq
        self._sample_rate = sample_rate
        self._freq_axis = self._compute_freq_axis()

        freq_min = self._freq_axis[0]
        freq_max = self._freq_axis[-1]
        freq_range = freq_max - freq_min

        self._spectrum_plot.setXRange(freq_min, freq_max, padding=0)
        self._waterfall_plot.setXRange(freq_min, freq_max, padding=0)

        self._update_waterfall_geometry(freq_min, freq_range)

        self._spectrum_curve.setData(self._freq_axis, self._current_spectrum)
        self._update_axis_ticks()

    def set_db_range(self, db_min: float, db_max: float):
        """Update the dB display range.

        Args:
            db_min: Minimum dB value (noise floor).
            db_max: Maximum dB value (peak).
        """
        self._db_min = db_min
        self._db_max = db_max
        self._spectrum_plot.setYRange(self._db_min, self._db_max, padding=0)
        self._update_axis_ticks()

    def clear_waterfall(self):
        """Reset the spectrogram and spectrum to empty state."""
        self._spectrogram.fill(-120.0)
        self._current_spectrum.fill(-120.0)
        self._rows_filled = 0
        self._spectrum_curve.setData(self._freq_axis, self._current_spectrum)
        self._image_item.setImage(
            self._spectrogram, autoLevels=False, levels=[self._waterfall_min_db, self._db_max]
        )
        self._update_waterfall_geometry(self._freq_axis[0], self._freq_axis[-1] - self._freq_axis[0])

    def set_colormap(self, preset: str):
        """Update the waterfall colormap preset."""
        self._colormap = self._build_colormap(preset)
        self._lut = self._colormap.getLookupTable(
            start=0.0, stop=1.0, nPts=256, alpha=False
        )
        self._image_item.setLookupTable(self._lut)

    def resizeEvent(self, event):
        """Keep overlay anchored to bottom-right."""
        super().resizeEvent(event)
        if hasattr(self, "_fps_label"):
            margin = 6
            self._fps_label.move(
                self.width() - self._fps_label.width() - margin,
                self.height() - self._fps_label.height() - margin,
            )

    @property
    def fft_size(self) -> int:
        """Current FFT size."""
        return self._fft_size

    @property
    def history_size(self) -> int:
        """Number of waterfall history rows."""
        return self._history_size

    @property
    def center_freq(self) -> float:
        """Current center frequency in Hz."""
        return self._center_freq

    @property
    def sample_rate(self) -> float:
        """Current sample rate in Hz."""
        return self._sample_rate
