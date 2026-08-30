"""Small, convention-explicit numerical primitives for SFCW processing."""

from __future__ import annotations

from typing import Sequence

import numpy as np


def exact_dtft(
    signal: np.ndarray, dt_s: float, frequencies_hz: float | Sequence[float]
) -> complex | np.ndarray:
    """Evaluate a sampled time signal at arbitrary frequencies by direct DTFT.

    No nearest-FFT-bin approximation is made.  The ``exp(-j 2 pi f t)``
    convention is used throughout the SFCW chain.
    """
    x = np.asarray(signal)
    if x.ndim != 1 or x.size == 0:
        raise ValueError("signal must be a non-empty one-dimensional array")
    if not np.isfinite(dt_s) or dt_s <= 0:
        raise ValueError("dt_s must be finite and positive")
    f = np.atleast_1d(np.asarray(frequencies_hz, dtype=float))
    if not np.all(np.isfinite(f)):
        raise ValueError("frequencies must be finite")
    t = np.arange(x.size, dtype=float) * dt_s
    values = np.asarray(
        [np.sum(x * np.exp(-1j * 2.0 * np.pi * fi * t)) for fi in f],
        dtype=complex,
    )
    if np.ndim(frequencies_hz) == 0:
        return complex(values[0])
    return values


def uniform_frequency_step(frequencies_hz: Sequence[float]) -> float:
    """Return the positive uniform step or reject a nonuniform tone grid."""
    f = np.asarray(frequencies_hz, dtype=float)
    if f.ndim != 1 or f.size < 2 or not np.all(np.isfinite(f)):
        raise ValueError("at least two finite frequencies are required")
    steps = np.diff(f)
    if np.any(steps <= 0):
        raise ValueError("frequencies must be strictly increasing")
    df = float(steps[0])
    if not np.allclose(steps, df, rtol=1e-10, atol=max(1e-9, abs(df) * 1e-12)):
        raise ValueError("IFFT reconstruction requires a uniform tone grid")
    return df


def wiener_deconvolve(
    receiver_spectrum: np.ndarray,
    source_spectrum: np.ndarray,
    regularisation: float = 1e-10,
) -> np.ndarray:
    """Regularised complex division ``R/S`` with relative Wiener loading."""
    r = np.asarray(receiver_spectrum, dtype=complex)
    s = np.asarray(source_spectrum, dtype=complex)
    if r.shape != s.shape:
        raise ValueError("receiver and source spectra must have the same shape")
    if not np.isfinite(regularisation) or regularisation < 0:
        raise ValueError("regularisation must be finite and nonnegative")
    reference_power = float(np.max(np.abs(s) ** 2)) if s.size else 0.0
    if reference_power == 0.0:
        raise ValueError("source spectrum is zero at all requested tones")
    return r * np.conj(s) / (np.abs(s) ** 2 + regularisation * reference_power)


def deembed_delay(
    spectrum: np.ndarray, frequencies_hz: Sequence[float], delay_s: float
) -> np.ndarray:
    """Remove a known linear delay from an ``exp(-j 2 pi f tau)`` spectrum."""
    h = np.asarray(spectrum, dtype=complex)
    f = np.asarray(frequencies_hz, dtype=float)
    if h.shape != f.shape:
        raise ValueError("spectrum and frequencies must have the same shape")
    if not np.isfinite(delay_s):
        raise ValueError("delay_s must be finite")
    return h * np.exp(1j * 2.0 * np.pi * f * delay_s)


def two_interface_response(
    frequencies_hz: Sequence[float],
    delays_s: Sequence[float],
    amplitudes: Sequence[complex],
) -> np.ndarray:
    """Independent analytic complex response used by synthetic validation."""
    f = np.asarray(frequencies_hz, dtype=float)
    tau = np.asarray(delays_s, dtype=float)
    amp = np.asarray(amplitudes, dtype=complex)
    if tau.ndim != 1 or amp.ndim != 1 or tau.size != amp.size:
        raise ValueError("delays and amplitudes must be one-dimensional and matched")
    return np.sum(
        amp[:, None] * np.exp(-1j * 2.0 * np.pi * tau[:, None] * f[None, :]),
        axis=0,
    )
