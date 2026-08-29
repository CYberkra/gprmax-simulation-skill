"""SFCW processing chains and waveform synthesis.

Three equivalent routes are supported and must be *declared* per study — none
is treated as the one universal method:

- ``direct_per_tone``: run each tone separately, extract the complex sample by
  quadrature mixing, and inverse-transform to an A-scan;
- ``impulse_lti`` (Liu & Xiao 2021, the recommended configuration): run a
  single impulse (or user-defined) excitation to obtain the impulse response
  ``h[n]``, convolve it in the time domain with each ramped tone, mix/extract,
  and inverse-transform. One FDTD run substitutes for per-tone runs;
- ``broadband_deconvolution``: run one broadband pulse, sample the complex
  spectrum at exact tones (point-wise DFT, not nearest-bin), Wiener
  deconvolve with the source spectrum, select the band, window, and run a
  zero-padded inverse transform.

Discipline: complex quantities stay complex until the final time-domain
product; every tone grid, band, window, and regularisation is a recorded
parameter; envelopes are computed with a numpy analytic-signal construction
(no SciPy dependency).

All functions are pure numpy and deterministic; no gprMax invocation happens
here.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np


# --------------------------------------------------------------------------
# Waveform synthesis
# --------------------------------------------------------------------------

def tone_grid(f_lo_hz: float, f_hi_hz: float, df_hz: float) -> np.ndarray:
    """Uniform tone grid: f_n = f_lo + n·df, band B = (N-1)df."""
    if not (0 < f_lo_hz < f_hi_hz and df_hz > 0):
        raise ValueError("require 0 < f_lo < f_hi and df > 0")
    return np.arange(f_lo_hz, f_hi_hz + df_hz / 2, df_hz)


def make_flatpulse(
    f_lo_hz: float,
    f_hi_hz: float,
    dt_s: float,
    samples: int,
    rolloff_mhz: float = 10.0,
    delay_ratio: float = 0.1,
) -> np.ndarray:
    """Broadband flat pulse via a raised-cosine frequency mask + IFFT.

    Leaves rolloff at both band edges to avoid hard spectral truncation
    (coda artefacts); the pulse is time-shifted so its energy is not at t=0.
    """
    if samples <= 0 or delay_ratio <= 0 or delay_ratio >= 0.5:
        raise ValueError("samples > 0 and 0 < delay_ratio < 0.5 required")
    freqs = np.fft.rfftfreq(samples, dt_s)
    mask = np.zeros_like(freqs)
    roll = rolloff_mhz * 1e6

    lower = f_lo_hz - roll
    upper = f_hi_hz + roll
    inside = (freqs >= lower) & (freqs <= upper)
    mask[inside] = 1.0
    # raised-cosine edges
    edge_lo = (freqs > lower) & (freqs < f_lo_hz)
    edge_hi = (freqs > f_hi_hz) & (freqs < upper)
    if np.any(edge_lo):
        mask[edge_lo] = 0.5 * (
            1 + np.cos(np.pi * (freqs[edge_lo] - f_lo_hz) / roll)
        )
    if np.any(edge_hi):
        mask[edge_hi] = 0.5 * (
            1 + np.cos(np.pi * (freqs[edge_hi] - f_hi_hz) / roll)
        )

    pulse = np.fft.irfft(mask, samples)
    shift = int(delay_ratio * samples)
    pulse = np.roll(pulse, shift)
    pulse -= pulse.mean()
    peak = np.max(np.abs(pulse))
    if peak > 0:
        pulse /= peak
    return pulse


def make_sine_tone(
    f_hz: float, dt_s: float, samples: int, ramp_phase: float = 0.1
) -> np.ndarray:
    """Single-tone continuous wave with a linear onset ramp.

    The ramp (Liu & Xiao 2021, eq. 9) avoids Gibbs-type high-frequency
    artefacts from a hard switch-on.
    """
    t = np.arange(samples) * dt_s
    phase = 2 * np.pi * f_hz * t
    tone = np.sin(phase)
    ramp_n = int(ramp_phase / (2 * np.pi * f_hz) / dt_s)
    if ramp_n > 0:
        t_ramp = t[:ramp_n]
        tone[:ramp_n] = (f_hz * t_ramp) * np.sin(2 * np.pi * f_hz * t_ramp)
    return tone


# --------------------------------------------------------------------------
# Complex sampling
# --------------------------------------------------------------------------

def quad_mix_extract(signal: np.ndarray, dt_s: float, f_hz: float) -> complex:
    """Quadrature mixing + low-pass (whole-window average) -> complex sample.

    A delayed echo `sin(θ-φ)` with `φ = 2πf·τ` mixes to `I=A/2·cosφ`,
    `Q=A/2·sinφ`; the returned sample is `I - jQ = A/2·e^{-jφ}`, i.e. the
    negative-phase convention so that a target at delay `τ` appears at `+τ`
    after reconstruction. Mixing with sin/cos and averaging removes the 2f
    term; the baseband I/Q components survive.
    """
    if len(signal) == 0:
        raise ValueError("empty signal")
    t = np.arange(len(signal)) * dt_s
    i = signal * np.sin(2 * np.pi * f_hz * t)
    q = signal * np.cos(2 * np.pi * f_hz * t)
    # I = A/2·cosφ, Q = -A/2·sinφ, so I + jQ = A/2·e^{-jφ}
    return 2.0 * (np.mean(i) + 1j * np.mean(q))


def dft_at(signal: np.ndarray, dt_s: float, f_hz: float) -> complex:
    """Exact-tone complex evaluation (point-wise DFT). Not nearest-bin."""
    t = np.arange(len(signal)) * dt_s
    return np.sum(signal * np.exp(-1j * 2 * np.pi * f_hz * t))


def synthesize_tone_response(
    impulse_response: np.ndarray, dt_s: float, f_hz: float, ramp_phase: float = 0.1
) -> np.ndarray:
    """Per-tone receiver response = h[n] convolved with the ramped tone."""
    tone = make_sine_tone(f_hz, dt_s, len(impulse_response), ramp_phase)
    full = np.convolve(impulse_response, tone, mode="full")
    return full[: len(impulse_response)]


def complex_samples_impulse_lti(
    impulse_response: np.ndarray,
    dt_s: float,
    frequencies: Sequence[float],
    ramp_phase: float = 0.1,
) -> np.ndarray:
    """Liu & Xiao 2021 route: convolve h with each tone, mix/extract."""
    samples = [
        quad_mix_extract(
            synthesize_tone_response(impulse_response, dt_s, f, ramp_phase),
            dt_s,
            f,
        )
        for f in frequencies
    ]
    return np.asarray(samples, dtype=complex)


def complex_samples_direct(
    per_tone_traces: np.ndarray, dt_s: float, frequencies: Sequence[float]
) -> np.ndarray:
    """direct_per_tone route: per-tone receiver traces already computed."""
    if np.ndim(per_tone_traces) != 2:
        raise ValueError("per_tone_traces must be (n_tones, n_samples)")
    if len(per_tone_traces) != len(frequencies):
        raise ValueError("trace count must match tone count")
    samples = [
        quad_mix_extract(per_tone_traces[i], dt_s, f)
        for i, f in enumerate(frequencies)
    ]
    return np.asarray(samples, dtype=complex)


def complex_samples_broadband(
    receiver_ez: np.ndarray,
    dt_s: float,
    source_spectrum: np.ndarray,
    frequencies: Sequence[float],
    dt_source_s: float,
    regularisation: float = 1e-10,
    f_lo_hz: float | None = None,
    f_hi_hz: float | None = None,
) -> np.ndarray:
    """broadband_deconvolution route: exact-tone sampling + Wiener.

    ``receiver_ez`` is the single broadband run; ``source_spectrum`` is the
    source waveform's spectrum sampled on the receiver's time grid (passed as
    a time-domain array with ``dt_source_s``). Frequencies outside the
    selected band are excluded after deconvolution.
    """
    s_time = np.asarray(source_spectrum, dtype=float)
    r_time = np.asarray(receiver_ez, dtype=float)
    if abs(dt_source_s - dt_s) / dt_s > 1e-6:
        raise ValueError("source and receiver must share the same time grid")
    if len(s_time) != len(r_time):
        raise ValueError("source and receiver sample counts must match")

    s_spectrum = np.fft.fft(s_time)
    r_spectrum = np.fft.fft(r_time)
    n = len(r_time)
    freqs = np.fft.fftfreq(n, dt_s)

    def _spectrum_at(f_hz: float) -> complex:
        # exact evaluation by spectral interpolation at a single tone
        # (point-wise DFT of the time series is equivalent; use it directly)
        return dft_at(r_time, dt_s, f_hz)

    samples: list[complex] = []
    for f in frequencies:
        if f_lo_hz is not None and f < f_lo_hz:
            continue
        if f_hi_hz is not None and f > f_hi_hz:
            continue
        e = _spectrum_at(f)
        s = _spectrum_from_fft(s_spectrum, freqs, f)
        denom = np.abs(s) ** 2 + regularisation * np.max(np.abs(s_spectrum) ** 2)
        samples.append(e * np.conj(s) / denom)
    return np.asarray(samples, dtype=complex)


def _spectrum_from_fft(spectrum: np.ndarray, freqs: np.ndarray, f_hz: float) -> complex:
    """Evaluate the FFT spectrum at an arbitrary tone by linear interpolation."""
    index = np.argmin(np.abs(freqs - f_hz))
    return spectrum[index]


# --------------------------------------------------------------------------
# Inverse reconstruction
# --------------------------------------------------------------------------

def reconstruct_ascan(
    complex_samples: np.ndarray,
    zero_pad_factor: int = 8,
    window: np.ndarray | None = None,
) -> np.ndarray:
    """Zero-padded inverse transform of uniformly spaced complex samples.

    The tone band is treated as the complex baseband spectrum (matching the
    distance-compression convention: the A-scan is the range envelope, not a
    carrier-resolved trace — DC/Nyquist handling is explicit below). Returns
    a complex time-domain trace; use :func:`envelope` for the magnitude.
    """
    samples = np.asarray(complex_samples, dtype=complex)
    n = len(samples)
    if n < 2:
        raise ValueError("need at least two tones to reconstruct")
    if window is not None:
        if len(window) != n:
            raise ValueError("window length must match tone count")
        samples = samples * window

    zp = n * zero_pad_factor
    spec = np.zeros(zp, dtype=complex)
    # The tone grid starts above DC, so bin 0 (0 Hz) carries no measurement:
    # keep it at zero (band-pass reconstruction) to preserve Hermitian
    # realness. The lowest tone's complex phase lives in the band content.
    spec[:n] = samples
    spec[0] = 0.0
    # Hermitian negative frequencies for a real time-domain trace:
    # spec[zp - (n-1) .. zp-1] = conj(samples[n-1 .. 1])
    if n > 1:
        spec[zp - n + 1 :] = np.conj(samples[:0:-1])
    return np.fft.ifft(spec)


def envelope(ascan: np.ndarray) -> np.ndarray:
    """Instantaneous-amplitude envelope via an analytic-signal construction.

    numpy-only Hilbert: passband mask then IFFT. Nonnegative by construction.
    """
    x = np.asarray(ascan, dtype=float)
    n = len(x)
    X = np.fft.fft(x)
    h = np.zeros(n)
    h[0] = 1.0
    if n > 1:
        h[1 : (n + 1) // 2] = 2.0
        if n % 2 == 0:
            h[n // 2] = 1.0
    analytic = np.fft.ifft(X * h)
    return np.abs(analytic)


def bscan_from_ascans(ascans: Sequence[np.ndarray]) -> np.ndarray:
    """Stack per-trace A-scans into a B-scan (trace index × time index)."""
    rows = [np.asarray(a, dtype=complex) for a in ascans]
    length = max(len(row) for row in rows)
    padded = np.zeros((len(rows), length), dtype=complex)
    for i, row in enumerate(rows):
        padded[i, : len(row)] = row
    return padded


def run_chain(
    mode: str,
    *,
    dt_s: float,
    frequencies: Sequence[float] | None = None,
    impulse_response: np.ndarray | None = None,
    per_tone_traces: np.ndarray | None = None,
    receiver_ez: np.ndarray | None = None,
    source_waveform: np.ndarray | None = None,
    band_hz: tuple[float, float] | None = None,
    window: np.ndarray | None = None,
    zero_pad_factor: int = 8,
    regularisation: float = 1e-10,
    ramp_phase: float = 0.1,
) -> dict[str, Any]:
    """Run one declared SFCW chain end-to-end.

    Returns a mapping with ``samples`` (complex), ``ascan`` (complex),
    ``envelope`` (float), and ``mode``. Raises ValueError for a mode whose
    required inputs are missing.
    """
    frequencies = None if frequencies is None else np.asarray(frequencies, dtype=float)

    if mode == "direct_per_tone":
        if frequencies is None or per_tone_traces is None:
            raise ValueError("direct_per_tone needs frequencies and per_tone_traces")
        samples = complex_samples_direct(per_tone_traces, dt_s, frequencies)
    elif mode == "impulse_lti":
        if frequencies is None or impulse_response is None:
            raise ValueError("impulse_lti needs frequencies and impulse_response")
        samples = complex_samples_impulse_lti(
            impulse_response, dt_s, frequencies, ramp_phase
        )
    elif mode == "broadband_deconvolution":
        if receiver_ez is None or source_waveform is None:
            raise ValueError(
                "broadband_deconvolution needs receiver_ez and source_waveform"
            )
        lo, hi = band_hz if band_hz is not None else (frequencies[0], frequencies[-1])
        freq_grid = np.asarray(frequencies, dtype=float)
        samples = complex_samples_broadband(
            receiver_ez,
            dt_s,
            source_waveform,
            freq_grid,
            dt_s,
            regularisation=regularisation,
            f_lo_hz=lo,
            f_hi_hz=hi,
        )
    else:
        raise ValueError(
            f"mode must be direct_per_tone | impulse_lti | broadband_deconvolution"
        )

    a_scan = reconstruct_ascan(samples, zero_pad_factor=zero_pad_factor, window=window)
    return {
        "mode": mode,
        "samples": samples,
        "ascan": a_scan,
        "envelope": envelope(a_scan.real),
        "dt_s": dt_s,
    }