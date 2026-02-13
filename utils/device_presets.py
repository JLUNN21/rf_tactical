"""Device Preset Manager for RF Tactical Monitor

Loads and manages device frequency presets from device_presets.yaml
"""

import os
from dataclasses import dataclass
from typing import List, Dict, Optional
import yaml


@dataclass
class DevicePreset:
    """A single device preset with frequency and metadata."""
    name: str
    category: str
    frequency_mhz: float
    bandwidth_mhz: float
    modulation: str
    description: str
    notes: str
    
    @property
    def frequency_hz(self) -> int:
        """Get frequency in Hz."""
        return int(self.frequency_mhz * 1e6)
    
    @property
    def bandwidth_hz(self) -> int:
        """Get bandwidth in Hz."""
        return int(self.bandwidth_mhz * 1e6)
    
    def __str__(self) -> str:
        """String representation for dropdown display."""
        return f"{self.name} ({self.frequency_mhz} MHz)"


class DevicePresetManager:
    """Manages device frequency presets."""
    
    def __init__(self, config_dir: Optional[str] = None):
        """Initialize preset manager.
        
        Args:
            config_dir: Path to config directory. If None, uses default.
        """
        if config_dir is None:
            config_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "config"
            )
        self._config_dir = config_dir
        self._presets: List[DevicePreset] = []
        self._presets_by_category: Dict[str, List[DevicePreset]] = {}
        self._load_presets()
    
    def _load_presets(self):
        """Load presets from device_presets.yaml."""
        filepath = os.path.join(self._config_dir, "device_presets.yaml")
        
        if not os.path.exists(filepath):
            # No presets file, return empty
            return
        
        try:
            with open(filepath, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            
            presets_data = data.get("presets", [])
            
            for preset_dict in presets_data:
                preset = DevicePreset(
                    name=str(preset_dict["name"]),
                    category=str(preset_dict["category"]),
                    frequency_mhz=float(preset_dict["frequency_mhz"]),
                    bandwidth_mhz=float(preset_dict["bandwidth_mhz"]),
                    modulation=str(preset_dict["modulation"]),
                    description=str(preset_dict["description"]),
                    notes=str(preset_dict["notes"]),
                )
                self._presets.append(preset)
                
                # Group by category
                if preset.category not in self._presets_by_category:
                    self._presets_by_category[preset.category] = []
                self._presets_by_category[preset.category].append(preset)
        
        except Exception as e:
            print(f"Error loading device presets: {e}")
    
    def get_all_presets(self) -> List[DevicePreset]:
        """Get all presets."""
        return list(self._presets)
    
    def get_presets_by_category(self, category: str) -> List[DevicePreset]:
        """Get presets for a specific category.
        
        Args:
            category: Category name (e.g., "Garage Door", "Automotive")
        
        Returns:
            List of presets in that category.
        """
        return self._presets_by_category.get(category, [])
    
    def get_categories(self) -> List[str]:
        """Get list of all categories."""
        return sorted(self._presets_by_category.keys())
    
    def get_preset_by_name(self, name: str) -> Optional[DevicePreset]:
        """Get a preset by its name.
        
        Args:
            name: Preset name
        
        Returns:
            DevicePreset if found, None otherwise.
        """
        for preset in self._presets:
            if preset.name == name:
                return preset
        return None
    
    def search_presets(self, query: str) -> List[DevicePreset]:
        """Search presets by name, description, or notes.
        
        Args:
            query: Search string (case-insensitive)
        
        Returns:
            List of matching presets.
        """
        query_lower = query.lower()
        results = []
        
        for preset in self._presets:
            if (query_lower in preset.name.lower() or
                query_lower in preset.description.lower() or
                query_lower in preset.notes.lower() or
                query_lower in preset.category.lower()):
                results.append(preset)
        
        return results
    
    def get_presets_in_range(self, min_freq_mhz: float, max_freq_mhz: float) -> List[DevicePreset]:
        """Get presets within a frequency range.
        
        Args:
            min_freq_mhz: Minimum frequency in MHz
            max_freq_mhz: Maximum frequency in MHz
        
        Returns:
            List of presets in range, sorted by frequency.
        """
        results = [
            p for p in self._presets
            if min_freq_mhz <= p.frequency_mhz <= max_freq_mhz
        ]
        return sorted(results, key=lambda p: p.frequency_mhz)
