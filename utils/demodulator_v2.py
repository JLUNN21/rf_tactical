"""RF Tactical Monitor - Demodulator V2

Extended demodulation capabilities inspired by HackRfDiags AM/FM/WBFM/SSB
transceiver. Adds real-time audio demodulation for common analog modes.

Inspired by:
- HackRfDiags: AM/FM/WBFM/SSB demodulator implementations
- GNU Radio analog blocks: FM demod, AM demod concepts
- pyhackrf: Simple read_samples + demod pattern

All demodulation is done in pure NumPy/SciPy (no GNU Radio dependency).
"""

import numpy as np
from typing import Tuple, Optional
from enum import Enum

try:
    from scipy import signal as scipy_signal
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False


class DemodMode(Enum):
    """Demodulation modes."""
    FM_NARROW = "nbfm"      # Narrowband FM (5 kHz deviation)
    FM_WIDE = "wbfm"        # Wideband FM (75 kHz deviation)
    AM = "am"               # Amplitude modulation
    AM_SYNC = "am_sync"     # Synchronous AM (better quality)
    USB = "usb"             # Upper sideband
    LSB = "lsb"             # Lower sideband
    CW = "cw"               # Continuous wave (morse)
    RAW_IQ = "raw_iq"       # Raw IQ passthrough


class DemodulatorV2:
    """Real-time audio demodulator for common analog modes.

    Processes IQ samples and outputs audio samples suitable for
    playback or further analysis.

    From HackRfDiags pattern:
    - IQ input at SDR sample rate
    - Demodulation to baseband audio
    - Decimation to audio rate (typically 48 kHz)
    - Optional squelch gating

    Args:
        sample_rate: Input IQ sample rate in Hz.
        audio_rate: Output audio sample rate in Hz.
        mode: Demodulation mode.
    """

    def __init__(
        self,
        sample_rate: float = 2e6,
        audio_rate: float = 48000,
        mode: DemodMode = DemodMode.FM_NARROW,
    ):
        self._sample_rate = sample_rate
        self._audio_rate = audio_rate
        self._mode = mode

        # Decimation factor
        self._decimation = max(1, int(sample_rate / audio_rate))
        self._actual_audio_rate = sample_rate / self._decimation

        # FM demod state
        self._prev_sample = np.complex64(0)

        # Squelch
        self._squelch_enabled = False
        self._squelch_threshold_db = -40.0
        self._squelch_open = False

        # DC removal filter state
        self._dc_alpha = 0.995
        self._dc_prev = 0.0

        # AGC state
        self._agc_gain = 1.0
        self._agc_target = 0.5
        self._agc_attack = 0.01
        self._agc_decay = 0.001

    def set_mode(self, mode: DemodMode) -> None:
        """Change demodulation mode."""
        self._mode = mode
        self._prev_sample = np.complex64(0)

    def set_sample_rate(self, sample_rate: float) -> None:
        """Update input sample rate."""
        self._sample_rate = sample_rate
        self._decimation = max(1, int(sample_rate / self._audio_rate))
        self._actual_audio_rate = sample_rate / self._decimation

    def set_squelch(self, enabled: bool, threshold_db: float = -40.0) -> None:
        """Configure squelch."""
        self._squelch_enabled = enabled
        self._squelch_threshold_db = threshold_db

    def demodulate(self, iq_samples: np.ndarray) -> np.ndarray:
        """Demodulate IQ samples to audio.

        Args:
            iq_samples: Complex IQ samples at SDR sample rate.

        Returns:
            Float32 audio samples at audio_rate.
        """
        if len(iq_samples) == 0:
            return np.array([], dtype=np.float32)

        # Check squelch
        if self._squelch_enabled:
            power_db = 10.0 * np.log10(np.mean(np.abs(iq_samples) ** 2) + 1e-20)
            if power_db < self._squelch_threshold_db:
                self._squelch_open = False
                n_out = len(iq_samples) // self._decimation
                return np.zeros(max(1, n_out), dtype=np.float32)
            self._squelch_open = True

        # Dispatch to mode-specific demodulator
        demod_funcs = {
            DemodMode.FM_NARROW: self._demod_fm,
            DemodMode.FM_WIDE: self._demod_fm,
            DemodMode.AM: self._demod_am,
            DemodMode.AM_SYNC: self._demod_am_sync,
            DemodMode.USB: self._demod_ssb_upper,
            DemodMode.LSB: self._demod_ssb_lower,
            DemodMode.CW: self._demod_cw,
            DemodMode.RAW_IQ: self._demod_raw,
        }

        func = demod_funcs.get(self._mode, self._demod_fm)
        audio = func(iq_samples)

        # DC removal
        audio = self._remove_dc(audio)

        # AGC
        audio = self._apply_agc(audio)

        return audio.astype(np.float32)

    # ── FM Demodulation (HackRfDiags FmDemodulator) ─────────────

    def _demod_fm(self, iq: np.ndarray) -> np.ndarray:
        """FM demodulation using quadrature discriminator.

        From HackRfDiags FmDemodulator: computes instantaneous frequency
        from phase difference between consecutive samples.

        For NBFM: deviation ~5 kHz, audio BW ~3 kHz
        For WBFM: deviation ~75 kHz, audio BW ~15 kHz
        """
        # Prepend previous sample for continuity
        iq_ext = np.concatenate(([self._prev_sample], iq))
        self._prev_sample = iq[-1]

        # Quadrature discriminator: angle of product with conjugate of previous
        product = iq_ext[1:] * np.conj(iq_ext[:-1])
        phase_diff = np.angle(product)

        # Normalize by max deviation
        if self._mode == DemodMode.FM_WIDE:
            # WBFM: wider deviation, need de-emphasis
            max_dev = 2 * np.pi * 75e3 / self._sample_rate
            audio = phase_diff / max_dev

            # De-emphasis filter (75 us time constant for NA, 50 us for EU)
            if SCIPY_AVAILABLE:
                tau = 75e-6  # 75 microseconds
                dt = 1.0 / self._sample_rate
                alpha = dt / (tau + dt)
                audio = scipy_signal.lfilter([alpha], [1, -(1 - alpha)], audio)
        else:
            # NBFM: narrower deviation
            max_dev = 2 * np.pi * 5e3 / self._sample_rate
            audio = phase_diff / max_dev

        # Decimate to audio rate
        audio = audio[::self._decimation]

        # Low-pass filter for audio bandwidth
        if SCIPY_AVAILABLE and len(audio) > 20:
            cutoff = 3000 if self._mode == DemodMode.FM_NARROW else 15000
            nyq = self._actual_audio_rate / 2
            if cutoff < nyq:
                b, a = scipy_signal.butter(4, cutoff / nyq, btype='low')
                audio = scipy_signal.lfilter(b, a, audio)

        return audio

    # ── AM Demodulation (HackRfDiags AmDemodulator) ─────────────

    def _demod_am(self, iq: np.ndarray) -> np.ndarray:
        """AM envelope demodulation.

        From HackRfDiags AmDemodulator: simple magnitude extraction.
        AM signal: s(t) = [1 + m*audio(t)] * carrier(t)
        Envelope = |s(t)| = 1 + m*audio(t)
        """
        # Envelope detection (magnitude)
        envelope = np.abs(iq)

        # Remove DC (carrier component)
        envelope = envelope - np.mean(envelope)

        # Decimate
        audio = envelope[::self._decimation]

        # Low-pass filter
        if SCIPY_AVAILABLE and len(audio) > 20:
            nyq = self._actual_audio_rate / 2
            cutoff = min(5000, nyq * 0.9)
            b, a = scipy_signal.butter(4, cutoff / nyq, btype='low')
            audio = scipy_signal.lfilter(b, a, audio)

        return audio

    def _demod_am_sync(self, iq: np.ndarray) -> np.ndarray:
        """Synchronous AM demodulation.

        Better quality than envelope detection - uses a PLL to
        track the carrier and coherently demodulate.
        Simplified version: uses Hilbert transform approach.
        """
        # Use real part after frequency correction
        # Simple approach: multiply by estimated carrier, take real part
        phase = np.unwrap(np.angle(iq))
        carrier_est = np.exp(-1j * phase)
        baseband = iq * carrier_est

        audio = np.real(baseband)
        audio = audio - np.mean(audio)

        # Decimate
        audio = audio[::self._decimation]

        if SCIPY_AVAILABLE and len(audio) > 20:
            nyq = self._actual_audio_rate / 2
            cutoff = min(5000, nyq * 0.9)
            b, a = scipy_signal.butter(4, cutoff / nyq, btype='low')
            audio = scipy_signal.lfilter(b, a, audio)

        return audio

    # ── SSB Demodulation (HackRfDiags SsbDemodulator) ───────────

    def _demod_ssb_upper(self, iq: np.ndarray) -> np.ndarray:
        """Upper Sideband (USB) demodulation.

        From HackRfDiags SsbDemodulator concept:
        USB = Real(IQ) * cos(wt) + Imag(IQ) * sin(wt)
        Simplified: just take real part (baseband is already at 0 Hz).
        """
        # For USB: shift spectrum down, take real part
        # The IQ signal is already at baseband, so USB is the positive frequencies
        audio = np.real(iq) + np.imag(iq)

        # Decimate
        audio = audio[::self._decimation]

        # Bandpass for voice (300-3000 Hz)
        if SCIPY_AVAILABLE and len(audio) > 20:
            nyq = self._actual_audio_rate / 2
            low = 300 / nyq
            high = min(3000 / nyq, 0.99)
            if low < high:
                b, a = scipy_signal.butter(4, [low, high], btype='band')
                audio = scipy_signal.lfilter(b, a, audio)

        return audio

    def _demod_ssb_lower(self, iq: np.ndarray) -> np.ndarray:
        """Lower Sideband (LSB) demodulation.

        LSB is the mirror of USB.
        """
        # For LSB: conjugate the signal to flip spectrum, then demod as USB
        audio = np.real(iq) - np.imag(iq)

        # Decimate
        audio = audio[::self._decimation]

        # Bandpass for voice
        if SCIPY_AVAILABLE and len(audio) > 20:
            nyq = self._actual_audio_rate / 2
            low = 300 / nyq
            high = min(3000 / nyq, 0.99)
            if low < high:
                b, a = scipy_signal.butter(4, [low, high], btype='band')
                audio = scipy_signal.lfilter(b, a, audio)

        return audio

    # ── CW Demodulation ─────────────────────────────────────────

    def _demod_cw(self, iq: np.ndarray) -> np.ndarray:
        """CW (Morse) demodulation with BFO.

        Mixes with a Beat Frequency Oscillator at ~700 Hz offset
        to produce an audible tone.
        """
        n = len(iq)
        t = np.arange(n) / self._sample_rate
        bfo_freq = 700.0  # Hz

        # Mix with BFO
        bfo = np.exp(2j * np.pi * bfo_freq * t)
        mixed = iq * bfo

        # Take real part
        audio = np.real(mixed)

        # Decimate
        audio = audio[::self._decimation]

        # Narrow bandpass around BFO frequency
        if SCIPY_AVAILABLE and len(audio) > 20:
            nyq = self._actual_audio_rate / 2
            low = 500 / nyq
            high = min(900 / nyq, 0.99)
            if low < high:
                b, a = scipy_signal.butter(4, [low, high], btype='band')
                audio = scipy_signal.lfilter(b, a, audio)

        return audio

    # ── Raw IQ ──────────────────────────────────────────────────

    def _demod_raw(self, iq: np.ndarray) -> np.ndarray:
        """Raw IQ passthrough (magnitude)."""
        audio = np.abs(iq)
        return audio[::self._decimation]

    # ── Utility Methods ─────────────────────────────────────────

    def _remove_dc(self, audio: np.ndarray) -> np.ndarray:
        """Remove DC offset with single-pole high-pass filter."""
        output = np.empty_like(audio)
        prev = self._dc_prev
        alpha = self._dc_alpha
        for i in range(len(audio)):
            output[i] = audio[i] - prev + alpha * (output[i - 1] if i > 0 else 0)
            prev = audio[i]
        self._dc_prev = prev
        return output

    def _apply_agc(self, audio: np.ndarray) -> np.ndarray:
        """Simple AGC to normalize audio level."""
        if len(audio) == 0:
            return audio

        peak = np.max(np.abs(audio))
        if peak > 0:
            target_gain = self._agc_target / peak
            if target_gain > self._agc_gain:
                # Attack (fast)
                self._agc_gain += self._agc_attack * (target_gain - self._agc_gain)
            else:
                # Decay (slow)
                self._agc_gain += self._agc_decay * (target_gain - self._agc_gain)

            # Clamp gain
            self._agc_gain = np.clip(self._agc_gain, 0.01, 100.0)

        return audio * self._agc_gain

    @property
    def squelch_open(self) -> bool:
        """Whether squelch is currently open."""
        return self._squelch_open

    @property
    def mode(self) -> DemodMode:
        return self._mode

    @property
    def audio_rate(self) -> float:
        return self._actual_audio_rate

    def reset(self) -> None:
        """Reset demodulator state."""
        self._prev_sample = np.complex64(0)
        self._dc_prev = 0.0
        self._agc_gain = 1.0
        self._squelch_open = False
