"""Demodulation helpers for common ISM signal types."""

from __future__ import annotations

from typing import Tuple

import numpy as np
from scipy import signal as scipy_signal


class Demodulator:
    """Demodulates common ISM signal types."""

    @staticmethod
    def demodulate_fsk(
        iq_samples: np.ndarray,
        sample_rate: float,
        deviation_hz: float | None = None,
    ) -> Tuple[np.ndarray, float]:
        """Demodulate FSK signal to bits.

        Args:
            iq_samples: Complex IQ samples.
            sample_rate: Sample rate in Hz.
            deviation_hz: Optional frequency deviation (auto-detect if None).

        Returns:
            bits: Numpy array of binary values (0 or 1).
            symbol_rate: Estimated symbol rate in baud.
        """
        if iq_samples is None or len(iq_samples) < 2 or sample_rate <= 0:
            return np.array([], dtype=int), 0.0

        phase = np.unwrap(np.angle(iq_samples))
        inst_freq = np.diff(phase) / (2 * np.pi) * sample_rate

        window_size = max(3, int(sample_rate / 10000))
        if window_size % 2 == 0:
            window_size += 1
        inst_freq_smooth = scipy_signal.medfilt(inst_freq, window_size)

        center_freq = np.median(inst_freq_smooth)

        if deviation_hz is None:
            deviation_hz = (np.max(inst_freq_smooth) - np.min(inst_freq_smooth)) / 2

        _ = deviation_hz
        bits = (inst_freq_smooth > center_freq).astype(int)

        transitions = np.diff(bits.astype(float))
        transition_indices = np.where(np.abs(transitions) > 0)[0]

        symbol_rate = 0.0
        if len(transition_indices) > 1:
            avg_symbol_len = np.mean(np.diff(transition_indices))
            if avg_symbol_len > 0:
                symbol_rate = sample_rate / avg_symbol_len

        return bits, symbol_rate

    @staticmethod
    def demodulate_ook(
        iq_samples: np.ndarray,
        sample_rate: float,
        threshold_db: float = -50,
    ) -> Tuple[np.ndarray, float]:
        """Demodulate OOK (On-Off Keying) signal to bits.

        Args:
            iq_samples: Complex IQ samples.
            sample_rate: Sample rate in Hz.
            threshold_db: Power threshold in dB.

        Returns:
            bits: Numpy array of binary values.
            symbol_rate: Estimated symbol rate in baud.
        """
        if iq_samples is None or len(iq_samples) == 0 or sample_rate <= 0:
            return np.array([], dtype=int), 0.0

        power = np.abs(iq_samples) ** 2
        power_db = 10 * np.log10(power + 1e-10)

        window_size = max(3, int(sample_rate / 10000))
        if window_size % 2 == 0:
            window_size += 1
        power_smooth = scipy_signal.medfilt(power_db, window_size)

        bits = (power_smooth > threshold_db).astype(int)

        transitions = np.diff(bits.astype(float))
        transition_indices = np.where(np.abs(transitions) > 0)[0]

        symbol_rate = 0.0
        if len(transition_indices) > 1:
            avg_symbol_len = np.mean(np.diff(transition_indices))
            if avg_symbol_len > 0:
                symbol_rate = sample_rate / avg_symbol_len

        return bits, symbol_rate

    @staticmethod
    def decode_manchester(bits: np.ndarray) -> np.ndarray:
        """Decode Manchester encoding.

        Manchester encoding:
        - 0 → 01 (low to high transition)
        - 1 → 10 (high to low transition)

        Args:
            bits: Raw bit stream.

        Returns:
            Decoded binary data.
        """
        if bits is None or len(bits) < 2:
            return np.array([], dtype=int)

        decoded = []
        i = 0

        while i < len(bits) - 1:
            if bits[i] == 0 and bits[i + 1] == 1:
                decoded.append(0)
                i += 2
                continue
            if bits[i] == 1 and bits[i + 1] == 0:
                decoded.append(1)
                i += 2
                continue
            i += 1

        return np.array(decoded, dtype=int)

    @staticmethod
    def decode_differential(bits: np.ndarray) -> np.ndarray:
        """Decode differential encoding.

        Differential encoding:
        - No transition → 0
        - Transition → 1

        Args:
            bits: Raw bit stream.

        Returns:
            Decoded binary data.
        """
        if bits is None or len(bits) < 2:
            return np.array([], dtype=int)

        transitions = np.diff(bits)
        return (transitions != 0).astype(int)

    @staticmethod
    def bits_to_hex(bits: np.ndarray) -> str:
        """Convert bit array to hex string.

        Args:
            bits: Numpy array of 0s and 1s.

        Returns:
            Hex representation.
        """
        if bits is None or len(bits) == 0:
            return ""

        padding = (8 - len(bits) % 8) % 8
        bits_padded = np.concatenate([bits, np.zeros(padding, dtype=int)])

        hex_str = ""
        for i in range(0, len(bits_padded), 8):
            byte = bits_padded[i : i + 8]
            value = int("".join(map(str, byte)), 2)
            hex_str += f"{value:02X} "

        return hex_str.strip()