"""RF Tactical Monitor - Tactical Waterfall Display

Dual-panel FFT spectrum + scrolling waterfall spectrogram widget
built on pyqtgraph. Designed for 800×480 touch display.
"""

import numpy as np
import pyqtgraph as pg
from pyqtgraph import ColorMap

pg.setConfigOption("imageAxisOrder", "row-major")
pg.setConfigOption("background", "#0A0A0A")
pg.setConfigOption("foreground", "#00CC33")


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

    def __init__(
        self,
        fft_size: int = 1024,
        history_size: int = 200,
        center_freq: float = 433.92e6,
        sample_rate: float = 2e6,
        parent=None,
    ):
        super().__init__(parent=parent)

        self._fft_size = fft_size
        self._history_size = history_size
        self._center_freq = center_freq
        self._sample_rate = sample_rate

        self._spectrogram = np.full(
            (self._history_size, self._fft_size), -120.0, dtype=np.float64
        )
        self._current_spectrum = np.full(self._fft_size, -120.0, dtype=np.float64)

        self._freq_axis = self._compute_freq_axis()

        self._db_min = -120.0
        self._db_max = 0.0

        self._colormap = self._build_colormap()
        self._lut = self._colormap.getLookupTable(
            start=0.0, stop=1.0, nPts=256, alpha=False
        )

        self._build_spectrum_plot()
        self.nextRow()
        self._build_waterfall()

    def _compute_freq_axis(self) -> np.ndarray:
        """Compute frequency axis values in MHz from center_freq and sample_rate."""
        freq_hz = np.linspace(
            self._center_freq - self._sample_rate / 2.0,
            self._center_freq + self._sample_rate / 2.0,
            self._fft_size,
            endpoint=False,
        )
        return freq_hz / 1e6

    def _build_colormap(self) -> ColorMap:
        """Build the tactical colormap from black through green to white."""
        return ColorMap(
            pos=np.array(self.COLORMAP_POSITIONS, dtype=np.float64),
            color=np.array(self.COLORMAP_COLORS, dtype=np.ubyte),
        )

    def _build_spectrum_plot(self):
        """Create the top FFT spectrum line plot."""
        self._spectrum_plot = self.addPlot(row=0, col=0)
        self._spectrum_plot.setLabel("left", "Power", units="dB")
        self._spectrum_plot.setLabel("bottom", "Frequency", units="MHz")
        self._spectrum_plot.setYRange(self._db_min, self._db_max, padding=0)
        self._spectrum_plot.setXRange(
            self._freq_axis[0], self._freq_axis[-1], padding=0
        )
        self._spectrum_plot.showGrid(x=True, y=True, alpha=0.3)
        self._spectrum_plot.setMouseEnabled(x=False, y=False)
        self._spectrum_plot.setMenuEnabled(False)
        self._spectrum_plot.hideButtons()

        spectrum_pen = pg.mkPen(color="#00FF41", width=1)
        self._spectrum_curve = self._spectrum_plot.plot(
            self._freq_axis,
            self._current_spectrum,
            pen=spectrum_pen,
        )

        axis_style = {"color": "#00CC33", "font-size": "10px"}
        self._spectrum_plot.getAxis("left").setStyle(tickFont=pg.QtGui.QFont("Source Code Pro", 9))
        self._spectrum_plot.getAxis("bottom").setStyle(tickFont=pg.QtGui.QFont("Source Code Pro", 9))
        self._spectrum_plot.getAxis("left").setTextPen("#00CC33")
        self._spectrum_plot.getAxis("bottom").setTextPen("#00CC33")

    def _build_waterfall(self):
        """Create the bottom scrolling waterfall spectrogram."""
        self._waterfall_plot = self.addPlot(row=1, col=0)
        self._waterfall_plot.setLabel("bottom", "Frequency", units="MHz")
        self._waterfall_plot.setLabel("left", "Time")
        self._waterfall_plot.setMouseEnabled(x=False, y=False)
        self._waterfall_plot.setMenuEnabled(False)
        self._waterfall_plot.hideButtons()
        self._waterfall_plot.getAxis("left").setTicks([])

        self._waterfall_plot.getAxis("bottom").setStyle(
            tickFont=pg.QtGui.QFont("Source Code Pro", 9)
        )
        self._waterfall_plot.getAxis("bottom").setTextPen("#00CC33")
        self._waterfall_plot.getAxis("left").setTextPen("#00CC33")

        self._image_item = pg.ImageItem(axisOrder="row-major")
        self._waterfall_plot.addItem(self._image_item)

        normalized = self._normalize_db(self._spectrogram)
        self._image_item.setImage(normalized, autoLevels=False, levels=[0.0, 1.0])
        self._image_item.setLookupTable(self._lut)

        freq_min = self._freq_axis[0]
        freq_max = self._freq_axis[-1]
        freq_range = freq_max - freq_min

        self._image_item.setRect(
            pg.QtCore.QRectF(
                freq_min,
                0,
                freq_range,
                self._history_size,
            )
        )

        self._waterfall_plot.setXRange(freq_min, freq_max, padding=0)
        self._waterfall_plot.setYRange(0, self._history_size, padding=0)

        self.ci.layout.setRowStretchFactor(0, 2)
        self.ci.layout.setRowStretchFactor(1, 3)

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

        self._spectrogram = np.roll(self._spectrogram, 1, axis=0)
        self._spectrogram[0, :] = row

        np.copyto(self._current_spectrum, row)

        self._spectrum_curve.setData(self._freq_axis, self._current_spectrum)

        normalized = self._normalize_db(self._spectrogram)
        self._image_item.setImage(normalized, autoLevels=False, levels=[0.0, 1.0])

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

        self._image_item.setRect(
            pg.QtCore.QRectF(
                freq_min,
                0,
                freq_range,
                self._history_size,
            )
        )

        self._spectrum_curve.setData(self._freq_axis, self._current_spectrum)

    def set_db_range(self, db_min: float, db_max: float):
        """Update the dB display range.

        Args:
            db_min: Minimum dB value (noise floor).
            db_max: Maximum dB value (peak).
        """
        self._db_min = db_min
        self._db_max = db_max
        self._spectrum_plot.setYRange(self._db_min, self._db_max, padding=0)

    def clear_waterfall(self):
        """Reset the spectrogram and spectrum to empty state."""
        self._spectrogram.fill(-120.0)
        self._current_spectrum.fill(-120.0)
        self._spectrum_curve.setData(self._freq_axis, self._current_spectrum)
        normalized = self._normalize_db(self._spectrogram)
        self._image_item.setImage(normalized, autoLevels=False, levels=[0.0, 1.0])

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
