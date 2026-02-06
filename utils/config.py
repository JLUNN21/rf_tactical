"""RF Tactical Monitor - Configuration Manager

Loads and provides typed access to bands.yaml and settings.yaml.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import yaml


@dataclass
class BandConfig:
    """Configuration for a single RF band."""
    name: str
    center_freq_hz: int
    bandwidth_hz: int
    sample_rate_hz: int
    fft_size: int
    gain_lna: int
    gain_vga: int
    decoder_type: str
    color_hex: str
    description: str


@dataclass
class UISettings:
    """UI display settings."""
    waterfall_history: int
    fft_update_fps: int
    touch_target_min_px: int
    display_width: int
    display_height: int
    fullscreen: bool
    hide_cursor: bool


@dataclass
class ATAKSettings:
    """ATAK/TAK network settings."""
    cot_multicast_group: str
    cot_multicast_port: int
    cot_stale_seconds: int
    cot_type: str
    cot_uid_prefix: str


class ConfigManager:
    """Loads and manages application configuration from YAML files.

    Usage:
        config = ConfigManager("/home/pi/rf_tactical/config")
        adsb_band = config.get_band("adsb")
        fps = config.ui.fft_update_fps
        port = config.atak.cot_multicast_port
    """

    def __init__(self, config_dir: Optional[str] = None):
        if config_dir is None:
            config_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "config"
            )
        self._config_dir = config_dir
        self._bands: Dict[str, BandConfig] = {}
        self._ui: Optional[UISettings] = None
        self._atak: Optional[ATAKSettings] = None
        self._load_bands()
        self._load_settings()

    def _load_yaml(self, filename: str) -> dict:
        """Load a YAML file from the config directory."""
        filepath = os.path.join(self._config_dir, filename)
        with open(filepath, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)

    def _load_bands(self):
        """Parse bands.yaml into BandConfig dataclass instances."""
        data = self._load_yaml("bands.yaml")
        bands_data = data.get("bands", {})
        for key, band_dict in bands_data.items():
            self._bands[key] = BandConfig(
                name=str(band_dict["name"]),
                center_freq_hz=int(band_dict["center_freq_hz"]),
                bandwidth_hz=int(band_dict["bandwidth_hz"]),
                sample_rate_hz=int(band_dict["sample_rate_hz"]),
                fft_size=int(band_dict["fft_size"]),
                gain_lna=int(band_dict["gain_lna"]),
                gain_vga=int(band_dict["gain_vga"]),
                decoder_type=str(band_dict["decoder_type"]),
                color_hex=str(band_dict["color_hex"]),
                description=str(band_dict["description"]),
            )

    def _load_settings(self):
        """Parse settings.yaml into UISettings and ATAKSettings dataclass instances."""
        data = self._load_yaml("settings.yaml")

        ui_data = data.get("ui_settings", {})
        self._ui = UISettings(
            waterfall_history=int(ui_data.get("waterfall_history", 200)),
            fft_update_fps=int(ui_data.get("fft_update_fps", 30)),
            touch_target_min_px=int(ui_data.get("touch_target_min_px", 44)),
            display_width=int(ui_data.get("display_width", 800)),
            display_height=int(ui_data.get("display_height", 480)),
            fullscreen=bool(ui_data.get("fullscreen", True)),
            hide_cursor=bool(ui_data.get("hide_cursor", True)),
        )

        atak_data = data.get("atak_settings", {})
        self._atak = ATAKSettings(
            cot_multicast_group=str(atak_data.get("cot_multicast_group", "239.2.3.1")),
            cot_multicast_port=int(atak_data.get("cot_multicast_port", 6969)),
            cot_stale_seconds=int(atak_data.get("cot_stale_seconds", 300)),
            cot_type=str(atak_data.get("cot_type", "a-f-G-U")),
            cot_uid_prefix=str(atak_data.get("cot_uid_prefix", "rf-tactical")),
        )

    @property
    def ui(self) -> UISettings:
        """Access UI settings."""
        return self._ui

    @property
    def atak(self) -> ATAKSettings:
        """Access ATAK/TAK network settings."""
        return self._atak

    @property
    def bands(self) -> Dict[str, BandConfig]:
        """Access all band configurations as a dictionary."""
        return dict(self._bands)

    def get_band(self, key: str) -> BandConfig:
        """Get a specific band configuration by key.

        Args:
            key: Band identifier (e.g., "adsb", "ism_433", "wifi")

        Returns:
            BandConfig for the requested band.

        Raises:
            KeyError: If the band key does not exist.
        """
        return self._bands[key]

    def band_keys(self) -> List[str]:
        """Return a list of all available band keys."""
        return list(self._bands.keys())

    def get_band_by_decoder(self, decoder_type: str) -> List[BandConfig]:
        """Get all bands that use a specific decoder type.

        Args:
            decoder_type: Decoder identifier (e.g., "adsb", "ism", "wifi")

        Returns:
            List of BandConfig instances matching the decoder type.
        """
        return [b for b in self._bands.values() if b.decoder_type == decoder_type]

    def reload(self):
        """Reload all configuration files from disk."""
        self._bands.clear()
        self._load_bands()
        self._load_settings()
