"""IQ Recorder for RF Tactical Monitor.

Records IQ samples to disk with metadata and SHA-256 hashing.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


class IQRecorder:
    """Records IQ samples to disk with metadata."""

    def __init__(self, base_dir="recordings") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.recording = False
        self.iq_file = None
        self.metadata = {}
        self.samples_written = 0
        self.start_time = None
        self.current_filename = None

    def start_recording(self, center_freq, sample_rate, gain_lna, gain_vga):
        """Start recording IQ samples."""
        if self.recording:
            raise RuntimeError("Already recording")

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        freq_mhz = center_freq / 1e6
        self.current_filename = f"iq_{timestamp}_{freq_mhz:.2f}MHz"

        iq_path = self.base_dir / f"{self.current_filename}.iq"
        self.iq_file = open(iq_path, "wb")

        self.metadata = {
            "filename": self.current_filename,
            "start_time": datetime.now(timezone.utc).isoformat(),
            "center_freq_hz": int(center_freq),
            "sample_rate_hz": int(sample_rate),
            "gain_lna": int(gain_lna),
            "gain_vga": int(gain_vga),
            "sample_format": "complex64",
            "samples_written": 0,
            "duration_seconds": 0.0,
            "file_size_bytes": 0,
            "sha256": None,
            "signal_events": [],
        }

        self.recording = True
        self.samples_written = 0
        self.start_time = datetime.now(timezone.utc)

    def write_samples(self, iq_samples):
        """Write IQ samples to file."""
        if not self.recording or self.iq_file is None:
            return

        self.iq_file.write(iq_samples.astype(np.complex64).tobytes())
        self.samples_written += len(iq_samples)

    def mark_signal_event(self, freq_hz, power_dbm, duration_sec):
        """Mark a detected signal during recording."""
        if not self.recording or self.start_time is None:
            return

        elapsed = (datetime.now(timezone.utc) - self.start_time).total_seconds()

        event = {
            "timestamp_sec": round(elapsed, 3),
            "frequency_hz": int(freq_hz),
            "power_dbm": round(power_dbm, 1),
            "duration_sec": round(duration_sec, 3),
        }

        self.metadata["signal_events"].append(event)

    def stop_recording(self):
        """Stop recording and save metadata."""
        if not self.recording:
            return None, None

        self.recording = False

        if self.iq_file is not None:
            self.iq_file.close()
            self.iq_file = None

        iq_path = self.base_dir / f"{self.current_filename}.iq"

        sha256 = hashlib.sha256()
        with open(iq_path, "rb") as file_handle:
            while True:
                chunk = file_handle.read(8192)
                if not chunk:
                    break
                sha256.update(chunk)

        duration = 0.0
        if self.start_time is not None:
            duration = (datetime.now(timezone.utc) - self.start_time).total_seconds()

        self.metadata["duration_seconds"] = round(duration, 3)
        self.metadata["samples_written"] = self.samples_written
        self.metadata["file_size_bytes"] = iq_path.stat().st_size
        self.metadata["sha256"] = sha256.hexdigest()

        meta_path = self.base_dir / f"{self.current_filename}.json"
        with open(meta_path, "w", encoding="utf-8") as file_handle:
            json.dump(self.metadata, file_handle, indent=2)

        return str(iq_path), str(meta_path)

    def get_recording_status(self):
        """Get current recording status."""
        if not self.recording or self.start_time is None:
            return {"recording": False}

        elapsed = (datetime.now(timezone.utc) - self.start_time).total_seconds()
        file_size = self.samples_written * 8

        return {
            "recording": True,
            "duration_sec": round(elapsed, 1),
            "samples": self.samples_written,
            "file_size_mb": round(file_size / 1024 / 1024, 2),
            "events": len(self.metadata.get("signal_events", [])),
        }