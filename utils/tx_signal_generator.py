"""RF Tactical Monitor - TX Signal Generator

Comprehensive signal generation for HackRF transmission. Provides multiple
modulation types, jamming patterns, and test signal generation.

Inspired by:
- RFwatch tx_thread: Gaussian noise + tone jamming via GNU Radio
- HackRF-data: FM transmitter, morse code encoder, OFDM TX
- multichannel-hackrf-transmitter: Multi-channel FM with polyphase filter
- HackRfDiags: AM/FM/WBFM/SSB modulator concepts
- hacktv: Complex modulation pipeline patterns

All signal generation is done in pure NumPy (no GNU Radio dependency)
so it works on any platform. Signals are generated as complex64 IQ
samples ready for direct transmission via SoapySDR.

Safety features:
- Maximum duration limits
- Amplitude clamping
- Ramp up/down to prevent spectral splatter
"""

import numpy as np
import logging
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from enum import Enum


class TxMode(Enum):
    """Transmission signal types."""
    CW = "cw"                    # Continuous wave (carrier only)
    TONE = "tone"                # Single tone at offset frequency
    MULTI_TONE = "multi_tone"    # Multiple tones
    FM = "fm"                    # Frequency modulation
    AM = "am"                    # Amplitude modulation
    OOK = "ook"                  # On-Off Keying
    NOISE = "noise"              # Gaussian noise (broadband)
    NOISE_BAND = "noise_band"    # Band-limited noise
    CHIRP = "chirp"              # Linear frequency sweep
    PULSE = "pulse"              # Pulsed carrier
    MORSE = "morse"              # Morse code
    BARRAGE_JAM = "barrage_jam"  # Broadband noise jamming
    SPOT_JAM = "spot_jam"        # Narrowband noise + tone jamming
    SWEEP_JAM = "sweep_jam"      # Sweeping jammer


@dataclass
class TxSignalParams:
    """Parameters for signal generation."""
    mode: TxMode = TxMode.CW
    sample_rate: float = 2e6
    duration_sec: float = 1.0
    amplitude: float = 0.7          # 0.0 to 1.0
    freq_offset_hz: float = 0.0     # Offset from center frequency

    # FM parameters
    fm_deviation_hz: float = 75e3   # FM deviation (75kHz for WBFM, 5kHz for NBFM)
    fm_audio_freq_hz: float = 1000  # Audio tone frequency for FM test

    # AM parameters
    am_depth: float = 0.8           # Modulation depth 0.0-1.0
    am_audio_freq_hz: float = 1000  # Audio tone frequency for AM

    # Multi-tone parameters
    tone_freqs_hz: Optional[List[float]] = None  # List of tone offsets
    tone_amplitudes: Optional[List[float]] = None  # Per-tone amplitudes

    # Chirp parameters
    chirp_start_hz: float = -500e3  # Chirp start frequency
    chirp_end_hz: float = 500e3     # Chirp end frequency

    # Pulse parameters
    pulse_on_sec: float = 0.001     # Pulse on time
    pulse_off_sec: float = 0.001    # Pulse off time

    # Morse parameters
    morse_text: str = "CQ CQ CQ"
    morse_wpm: int = 18

    # Noise parameters
    noise_bandwidth_hz: float = 0.0  # 0 = full bandwidth

    # Jamming parameters
    jam_num_tones: int = 5           # Number of jamming tones
    jam_sweep_rate_hz: float = 1e6   # Sweep rate for sweep jammer

    # Safety
    max_duration_sec: float = 30.0   # Hard limit
    ramp_percent: float = 0.02       # Ramp up/down percentage


class TxSignalGenerator:
    """Generates IQ samples for various TX signal types.

    All methods return np.ndarray of complex64 samples ready for
    direct transmission via SoapySDR writeStream.

    Usage:
        gen = TxSignalGenerator()
        params = TxSignalParams(mode=TxMode.FM, duration_sec=2.0)
        iq = gen.generate(params)
        # iq is ready for sdr_worker.transmit_signal()
    """

    def __init__(self):
        self._logger = logging.getLogger(__name__)

    def generate(self, params: TxSignalParams) -> np.ndarray:
        """Generate IQ samples based on parameters.

        Args:
            params: TxSignalParams with signal configuration.

        Returns:
            Complex64 numpy array of IQ samples.
        """
        # Safety: enforce duration limit
        duration = min(params.duration_sec, params.max_duration_sec)
        if duration != params.duration_sec:
            self._logger.warning(
                "Duration capped from %.1fs to %.1fs", params.duration_sec, duration
            )
        params.duration_sec = duration

        generators = {
            TxMode.CW: self._gen_cw,
            TxMode.TONE: self._gen_tone,
            TxMode.MULTI_TONE: self._gen_multi_tone,
            TxMode.FM: self._gen_fm,
            TxMode.AM: self._gen_am,
            TxMode.OOK: self._gen_ook,
            TxMode.NOISE: self._gen_noise,
            TxMode.NOISE_BAND: self._gen_noise_band,
            TxMode.CHIRP: self._gen_chirp,
            TxMode.PULSE: self._gen_pulse,
            TxMode.MORSE: self._gen_morse,
            TxMode.BARRAGE_JAM: self._gen_barrage_jam,
            TxMode.SPOT_JAM: self._gen_spot_jam,
            TxMode.SWEEP_JAM: self._gen_sweep_jam,
        }

        gen_func = generators.get(params.mode, self._gen_cw)
        iq = gen_func(params)

        # Apply amplitude scaling and clamping
        iq = self._apply_amplitude(iq, params.amplitude)

        # Apply ramp up/down to prevent spectral splatter
        iq = self._apply_ramp(iq, params.ramp_percent)

        self._logger.info(
            "Generated %s signal: %d samples (%.3fs) at %.1f MSPS, amp=%.2f",
            params.mode.value, len(iq), params.duration_sec,
            params.sample_rate / 1e6, params.amplitude,
        )

        return iq.astype(np.complex64)

    # ── Basic Signal Types ──────────────────────────────────────

    def _gen_cw(self, p: TxSignalParams) -> np.ndarray:
        """Continuous wave carrier at offset frequency."""
        n = int(p.duration_sec * p.sample_rate)
        t = np.arange(n) / p.sample_rate
        return np.exp(2j * np.pi * p.freq_offset_hz * t)

    def _gen_tone(self, p: TxSignalParams) -> np.ndarray:
        """Single tone at specified offset frequency."""
        n = int(p.duration_sec * p.sample_rate)
        t = np.arange(n) / p.sample_rate
        return np.exp(2j * np.pi * p.freq_offset_hz * t)

    def _gen_multi_tone(self, p: TxSignalParams) -> np.ndarray:
        """Multiple tones at specified frequencies.

        From multichannel-hackrf-transmitter concept: generate multiple
        simultaneous signals within the SDR bandwidth.
        """
        n = int(p.duration_sec * p.sample_rate)
        t = np.arange(n) / p.sample_rate
        iq = np.zeros(n, dtype=np.complex128)

        freqs = p.tone_freqs_hz or [0, 50e3, -50e3, 100e3, -100e3]
        amps = p.tone_amplitudes or [1.0 / len(freqs)] * len(freqs)

        for freq, amp in zip(freqs, amps):
            iq += amp * np.exp(2j * np.pi * freq * t)

        return iq

    # ── FM Modulation (from HackRF-data FM transmitter) ─────────

    def _gen_fm(self, p: TxSignalParams) -> np.ndarray:
        """FM modulated signal with audio tone.

        Implements FM modulation in pure NumPy:
        1. Generate audio tone (baseband message)
        2. Integrate to get phase
        3. Apply frequency deviation
        4. Generate complex exponential

        From HackRF-data fm_transmitter and multichannel-tx:
        FM modulation index = deviation / audio_freq
        """
        n = int(p.duration_sec * p.sample_rate)
        t = np.arange(n) / p.sample_rate

        # Generate audio tone (message signal)
        audio = np.sin(2 * np.pi * p.fm_audio_freq_hz * t)

        # FM modulation: phase is integral of message signal
        # deviation_hz controls how far the frequency swings
        sensitivity = 2 * np.pi * p.fm_deviation_hz / p.sample_rate
        phase = np.cumsum(audio) * sensitivity

        # Add carrier offset
        carrier_phase = 2 * np.pi * p.freq_offset_hz * t

        return np.exp(1j * (carrier_phase + phase))

    def generate_fm_from_audio(
        self,
        audio_samples: np.ndarray,
        audio_rate: float = 48000,
        sample_rate: float = 2e6,
        deviation_hz: float = 75e3,
        amplitude: float = 0.7,
    ) -> np.ndarray:
        """Generate FM signal from audio samples.

        From HackRF-data FM transmitter pattern: takes audio input,
        resamples to SDR rate, applies FM modulation.

        Args:
            audio_samples: Float audio samples (-1.0 to 1.0).
            audio_rate: Audio sample rate in Hz.
            sample_rate: Output IQ sample rate in Hz.
            deviation_hz: FM deviation in Hz.
            amplitude: Output amplitude.

        Returns:
            Complex64 IQ samples.
        """
        # Resample audio to SDR sample rate
        ratio = sample_rate / audio_rate
        n_out = int(len(audio_samples) * ratio)
        indices = np.arange(n_out) / ratio
        indices_int = indices.astype(int)
        indices_int = np.clip(indices_int, 0, len(audio_samples) - 1)
        audio_resampled = audio_samples[indices_int]

        # FM modulation
        sensitivity = 2 * np.pi * deviation_hz / sample_rate
        phase = np.cumsum(audio_resampled) * sensitivity
        iq = np.exp(1j * phase).astype(np.complex64)

        # Apply amplitude and ramp
        iq = self._apply_amplitude(iq, amplitude)
        iq = self._apply_ramp(iq, 0.01)

        return iq

    # ── AM Modulation (from HackRfDiags AM modulator concept) ───

    def _gen_am(self, p: TxSignalParams) -> np.ndarray:
        """AM modulated signal.

        AM: s(t) = [1 + m*audio(t)] * carrier(t)
        where m is modulation depth (0-1).

        From HackRfDiags AmModulator concept.
        """
        n = int(p.duration_sec * p.sample_rate)
        t = np.arange(n) / p.sample_rate

        # Audio tone
        audio = np.sin(2 * np.pi * p.am_audio_freq_hz * t)

        # AM envelope: 1 + m*audio
        envelope = 1.0 + p.am_depth * audio

        # Carrier
        carrier = np.exp(2j * np.pi * p.freq_offset_hz * t)

        return envelope * carrier

    # ── OOK (On-Off Keying) ─────────────────────────────────────

    def _gen_ook(self, p: TxSignalParams) -> np.ndarray:
        """On-Off Keying signal (carrier burst)."""
        n = int(p.duration_sec * p.sample_rate)
        t = np.arange(n) / p.sample_rate
        return np.exp(2j * np.pi * p.freq_offset_hz * t)

    # ── Noise Generation (from RFwatch tx_thread) ───────────────

    def _gen_noise(self, p: TxSignalParams) -> np.ndarray:
        """Gaussian white noise (broadband).

        From RFwatch tx_thread: analog.noise_source_c(GR_GAUSSIAN, amp, 0)
        """
        n = int(p.duration_sec * p.sample_rate)
        noise_i = np.random.randn(n).astype(np.float64)
        noise_q = np.random.randn(n).astype(np.float64)
        return noise_i + 1j * noise_q

    def _gen_noise_band(self, p: TxSignalParams) -> np.ndarray:
        """Band-limited noise centered at offset frequency.

        Generates broadband noise then applies a bandpass filter
        to limit bandwidth.
        """
        n = int(p.duration_sec * p.sample_rate)
        bw = p.noise_bandwidth_hz if p.noise_bandwidth_hz > 0 else p.sample_rate * 0.8

        # Generate broadband noise
        noise = np.random.randn(n) + 1j * np.random.randn(n)

        # Apply frequency-domain bandpass filter
        spectrum = np.fft.fft(noise)
        freqs = np.fft.fftfreq(n, d=1.0 / p.sample_rate)

        # Create bandpass mask centered at freq_offset
        mask = np.abs(freqs - p.freq_offset_hz) < (bw / 2)
        spectrum *= mask

        return np.fft.ifft(spectrum)

    # ── Chirp / Sweep Signal ────────────────────────────────────

    def _gen_chirp(self, p: TxSignalParams) -> np.ndarray:
        """Linear frequency chirp (sweep).

        Sweeps from chirp_start_hz to chirp_end_hz over duration.
        Common in radar and test applications.
        """
        n = int(p.duration_sec * p.sample_rate)
        t = np.arange(n) / p.sample_rate

        # Linear chirp: frequency increases linearly
        f0 = p.chirp_start_hz
        f1 = p.chirp_end_hz
        phase = 2 * np.pi * (f0 * t + (f1 - f0) / (2 * p.duration_sec) * t ** 2)

        return np.exp(1j * phase)

    # ── Pulse Signal ────────────────────────────────────────────

    def _gen_pulse(self, p: TxSignalParams) -> np.ndarray:
        """Pulsed carrier (on/off pattern).

        Generates repeating pulses of carrier with configurable
        on and off times.
        """
        n = int(p.duration_sec * p.sample_rate)
        t = np.arange(n) / p.sample_rate

        # Carrier
        carrier = np.exp(2j * np.pi * p.freq_offset_hz * t)

        # Pulse envelope
        period = p.pulse_on_sec + p.pulse_off_sec
        if period <= 0:
            return carrier

        phase_in_period = (t % period)
        envelope = (phase_in_period < p.pulse_on_sec).astype(np.float64)

        return carrier * envelope

    # ── Morse Code (from HackRF-data morse encoder) ─────────────

    def _gen_morse(self, p: TxSignalParams) -> np.ndarray:
        """Morse code signal.

        From HackRF-data epy_block_0.py morse encoder:
        - Dot = 1 time unit
        - Dash = 3 time units
        - Inter-element gap = 1 time unit
        - Inter-character gap = 3 time units
        - Inter-word gap = 7 time units
        - Time unit = 1.2 / WPM seconds
        """
        MORSE_CODE = {
            'A': '.-',     'B': '-...',   'C': '-.-.',
            'D': '-..',    'E': '.',      'F': '..-.',
            'G': '--.',    'H': '....',   'I': '..',
            'J': '.---',   'K': '-.-',    'L': '.-..',
            'M': '--',     'N': '-.',     'O': '---',
            'P': '.--.',   'Q': '--.-',   'R': '.-.',
            'S': '...',    'T': '-',      'U': '..-',
            'V': '...-',   'W': '.--',    'X': '-..-',
            'Y': '-.--',   'Z': '--..',
            '0': '-----',  '1': '.----',  '2': '..---',
            '3': '...--',  '4': '....-',  '5': '.....',
            '6': '-....',  '7': '--...',  '8': '---..',
            '9': '----.',
            '.': '.-.-.-', ',': '--..--', '?': '..--..',
            '!': '-.-.--', '/': '-..-.',  ':': '---...',
            '=': '-...-',  '-': '-....-',
        }

        # Time unit in seconds (from HackRF-data: 1.2 / WPM)
        tu = 1.2 / p.morse_wpm
        samples_per_tu = int(tu * p.sample_rate)

        # Build binary pattern
        bits = []
        text = p.morse_text.upper()
        for wi, word in enumerate(text.split()):
            if wi > 0:
                bits.extend([0] * 7)  # Inter-word gap
            for ci, char in enumerate(word):
                if ci > 0:
                    bits.extend([0] * 3)  # Inter-character gap
                code = MORSE_CODE.get(char, '')
                for ei, element in enumerate(code):
                    if ei > 0:
                        bits.extend([0] * 1)  # Inter-element gap
                    if element == '.':
                        bits.extend([1] * 1)  # Dot
                    elif element == '-':
                        bits.extend([1] * 3)  # Dash

        if not bits:
            bits = [0]

        # Expand bits to samples
        n_total = len(bits) * samples_per_tu
        t = np.arange(n_total) / p.sample_rate

        # Create envelope from bits
        envelope = np.zeros(n_total, dtype=np.float64)
        for i, bit in enumerate(bits):
            start = i * samples_per_tu
            end = start + samples_per_tu
            if end <= n_total:
                envelope[start:end] = bit

        # Carrier
        carrier = np.exp(2j * np.pi * p.freq_offset_hz * t)

        return carrier * envelope

    # ── Jamming Patterns ────────────────────────────────────────

    def _gen_barrage_jam(self, p: TxSignalParams) -> np.ndarray:
        """Barrage jamming: broadband noise across full bandwidth.

        From RFwatch tx_thread pattern: Gaussian noise source.
        Fills the entire SDR bandwidth with noise to deny
        communications across a wide frequency range.
        """
        n = int(p.duration_sec * p.sample_rate)
        # High-power Gaussian noise
        noise_i = np.random.randn(n)
        noise_q = np.random.randn(n)
        return noise_i + 1j * noise_q

    def _gen_spot_jam(self, p: TxSignalParams) -> np.ndarray:
        """Spot jamming: narrowband noise + tone at target frequency.

        From RFwatch tx_thread: noise_source + sig_source combined.
        Concentrates energy at a specific frequency to jam a
        particular channel or signal.
        """
        n = int(p.duration_sec * p.sample_rate)
        t = np.arange(n) / p.sample_rate

        # Strong tone at target frequency
        tone = 0.7 * np.exp(2j * np.pi * p.freq_offset_hz * t)

        # Narrowband noise around target
        noise = np.random.randn(n) + 1j * np.random.randn(n)
        # Bandpass filter noise
        spectrum = np.fft.fft(noise)
        freqs = np.fft.fftfreq(n, d=1.0 / p.sample_rate)
        bw = p.noise_bandwidth_hz if p.noise_bandwidth_hz > 0 else 50e3
        mask = np.abs(freqs - p.freq_offset_hz) < (bw / 2)
        spectrum *= mask
        filtered_noise = np.fft.ifft(spectrum) * 0.3

        # Additional jamming tones spread around target
        jam_tones = np.zeros(n, dtype=np.complex128)
        if p.jam_num_tones > 1:
            spacing = bw / p.jam_num_tones
            for i in range(p.jam_num_tones):
                f = p.freq_offset_hz + (i - p.jam_num_tones // 2) * spacing
                jam_tones += (0.2 / p.jam_num_tones) * np.exp(2j * np.pi * f * t)

        return tone + filtered_noise + jam_tones

    def _gen_sweep_jam(self, p: TxSignalParams) -> np.ndarray:
        """Sweep jamming: rapidly sweeping tone across bandwidth.

        Sweeps a tone back and forth across the target bandwidth,
        creating a comb-like jamming pattern that's harder to filter.
        """
        n = int(p.duration_sec * p.sample_rate)
        t = np.arange(n) / p.sample_rate

        # Triangular sweep (back and forth)
        sweep_period = p.sample_rate / p.jam_sweep_rate_hz if p.jam_sweep_rate_hz > 0 else 0.001
        sweep_phase = t / sweep_period
        # Triangle wave: goes 0->1->0->1...
        triangle = 2 * np.abs(sweep_phase - np.floor(sweep_phase + 0.5))

        # Map triangle to frequency range
        f_low = p.chirp_start_hz
        f_high = p.chirp_end_hz
        inst_freq = f_low + (f_high - f_low) * triangle

        # Integrate frequency to get phase
        phase = 2 * np.pi * np.cumsum(inst_freq) / p.sample_rate

        # Add some noise for wider spectral coverage
        noise = 0.2 * (np.random.randn(n) + 1j * np.random.randn(n))

        return np.exp(1j * phase) + noise

    # ── Utility Methods ─────────────────────────────────────────

    def _apply_amplitude(self, iq: np.ndarray, amplitude: float) -> np.ndarray:
        """Scale and clamp amplitude."""
        amplitude = np.clip(amplitude, 0.0, 1.0)
        # Normalize to peak = 1.0, then scale
        peak = np.max(np.abs(iq))
        if peak > 0:
            iq = iq / peak * amplitude
        return iq

    def _apply_ramp(self, iq: np.ndarray, ramp_percent: float) -> np.ndarray:
        """Apply ramp up/down to prevent spectral splatter."""
        n = len(iq)
        ramp_samples = int(n * ramp_percent)
        if ramp_samples < 2:
            return iq

        # Raised cosine ramp (smoother than linear)
        ramp_up = 0.5 * (1 - np.cos(np.pi * np.arange(ramp_samples) / ramp_samples))
        ramp_down = 0.5 * (1 + np.cos(np.pi * np.arange(ramp_samples) / ramp_samples))

        iq[:ramp_samples] *= ramp_up
        iq[-ramp_samples:] *= ramp_down

        return iq

    @staticmethod
    def get_available_modes() -> List[Dict[str, str]]:
        """Get list of available TX modes with descriptions."""
        return [
            {"mode": "cw", "name": "CW", "desc": "Continuous wave carrier"},
            {"mode": "tone", "name": "Tone", "desc": "Single tone at offset frequency"},
            {"mode": "multi_tone", "name": "Multi-Tone", "desc": "Multiple simultaneous tones"},
            {"mode": "fm", "name": "FM", "desc": "Frequency modulation (NBFM/WBFM)"},
            {"mode": "am", "name": "AM", "desc": "Amplitude modulation"},
            {"mode": "ook", "name": "OOK", "desc": "On-Off Keying carrier burst"},
            {"mode": "noise", "name": "Noise", "desc": "Broadband Gaussian noise"},
            {"mode": "noise_band", "name": "Band Noise", "desc": "Band-limited noise"},
            {"mode": "chirp", "name": "Chirp", "desc": "Linear frequency sweep"},
            {"mode": "pulse", "name": "Pulse", "desc": "Pulsed carrier (on/off)"},
            {"mode": "morse", "name": "Morse", "desc": "Morse code transmission"},
            {"mode": "barrage_jam", "name": "Barrage Jam", "desc": "Broadband noise jamming"},
            {"mode": "spot_jam", "name": "Spot Jam", "desc": "Narrowband noise + tone jamming"},
            {"mode": "sweep_jam", "name": "Sweep Jam", "desc": "Sweeping tone jammer"},
        ]

    @staticmethod
    def validate_params(params: TxSignalParams) -> tuple:
        """Validate TX parameters before generation.

        Returns:
            (is_valid, error_message)
        """
        if params.duration_sec <= 0:
            return False, "Duration must be positive"
        if params.duration_sec > params.max_duration_sec:
            return False, f"Duration exceeds {params.max_duration_sec}s limit"
        if params.amplitude < 0 or params.amplitude > 1.0:
            return False, "Amplitude must be 0.0-1.0"
        if params.sample_rate < 1e6:
            return False, "Sample rate must be >= 1 MHz"
        if abs(params.freq_offset_hz) > params.sample_rate / 2:
            return False, "Frequency offset exceeds Nyquist limit"
        return True, ""
