"""SFCW processing chains and waveform synthesis.

Three processing routes are supported and must be *declared* per study — none
is treated as the one universal method:

- ``direct_per_tone``: run each tone separately, extract the complex sample by
  quadrature mixing, and inverse-transform to an A-scan;
- ``impulse_lti`` (the noiseless Liu & Xiao 2021 core route): run a
  single impulse (or user-defined) excitation to obtain the impulse response
  ``h[n]``, convolve it in the time domain with each ramped tone, mix/extract,
  and inverse-transform. One FDTD run substitutes for per-tone runs;
- ``broadband_deconvolution``: run one broadband pulse, sample the complex
  spectrum at exact tones (point-wise DFT, not nearest-bin), Wiener
  deconvolve with the source spectrum, select the band, window, and run a
  zero-padded inverse transform.

Discipline: complex quantities stay complex until the final time-domain
product; every tone grid, band, window, and regularisation is a recorded
parameter.  A complex range-compressed trace uses its magnitude as envelope;
a real trace uses a numpy analytic-signal construction (no SciPy dependency).

All functions are pure numpy and deterministic; no gprMax invocation happens
here.
"""

from __future__ import annotations

import hashlib
from typing import Any, Sequence

import numpy as np

from scripts.sfcw_math import (
    deembed_delay,
    exact_dtft,
    uniform_frequency_step,
    wiener_deconvolve,
)


# --------------------------------------------------------------------------
# Waveform synthesis
# --------------------------------------------------------------------------

def tone_grid(f_lo_hz: float, f_hi_hz: float, df_hz: float) -> np.ndarray:
    """Uniform tone grid: f_n = f_lo + n·df, band B = (N-1)df."""
    if not (0 < f_lo_hz < f_hi_hz and df_hz > 0):
        raise ValueError("require 0 < f_lo < f_hi and df > 0")
    intervals = (f_hi_hz - f_lo_hz) / df_hz
    rounded = int(round(intervals))
    if not np.isclose(intervals, rounded, rtol=1e-12, atol=1e-12):
        raise ValueError("band endpoints must lie exactly on the declared tone step")
    return f_lo_hz + np.arange(rounded + 1, dtype=float) * df_hz


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
    f_hz: float,
    dt_s: float,
    samples: int,
    ramp_k: float = 0.1,
    *,
    ramp_phase: float | None = None,
) -> np.ndarray:
    """Single-tone continuous wave with Liu & Xiao's linear onset ramp.

    Equation (9) is ``k*f*t*sin(2*pi*f*t)`` while ``k*f*t < 1``, followed by
    the unit-amplitude sine.  Therefore the ramp lasts ``1/(k*f)`` and is
    continuous at its endpoint.  ``ramp_phase`` is a deprecated keyword alias
    retained for M3 API compatibility; its value is interpreted as ``k``.
    """
    if ramp_phase is not None:
        if ramp_k != 0.1 and not np.isclose(ramp_k, ramp_phase):
            raise ValueError("specify ramp_k or legacy ramp_phase, not both")
        ramp_k = ramp_phase
    if not (np.isfinite(f_hz) and f_hz > 0 and np.isfinite(dt_s) and dt_s > 0):
        raise ValueError("f_hz and dt_s must be finite and positive")
    if samples <= 0 or not (np.isfinite(ramp_k) and 0 < ramp_k < 1):
        raise ValueError("samples > 0 and 0 < ramp_k < 1 required")
    t = np.arange(samples) * dt_s
    phase = 2 * np.pi * f_hz * t
    tone = np.sin(phase)
    ramp_coordinate = ramp_k * f_hz * t
    ramp = ramp_coordinate < 1.0
    tone[ramp] *= ramp_coordinate[ramp]
    return tone


# --------------------------------------------------------------------------
# Complex sampling
# --------------------------------------------------------------------------

def quad_mix_extract(
    signal: np.ndarray,
    dt_s: float,
    f_hz: float,
    *,
    integration_cycles: float = 4.0,
    settling_samples: int = 0,
) -> complex:
    """Extract a steady-state complex tone by coherent quadrature fitting.

    For ``A*sin(theta-phi)``, fitting the sine and cosine references gives
    ``I=A*cos(phi)`` and ``Q=-A*sin(phi)`` after the documented factor-two
    mixer normalisation.  Thus ``I+jQ=A*exp(-j*phi)`` and positive propagation
    delay reconstructs at positive delay.  The final cycle-count window
    is used after ``settling_samples``; this is a coherent-integration
    equivalent of low-pass filtering followed by steady-state sampling, not an
    average over propagation zeros and ramp transients.
    """
    y = np.asarray(signal, dtype=float)
    if y.ndim != 1 or y.size == 0:
        raise ValueError("signal must be a non-empty one-dimensional array")
    if not (np.isfinite(dt_s) and dt_s > 0 and np.isfinite(f_hz) and f_hz > 0):
        raise ValueError("dt_s and f_hz must be finite and positive")
    if not np.isfinite(integration_cycles) or integration_cycles <= 0:
        raise ValueError("integration_cycles must be finite and positive")
    if settling_samples < 0 or settling_samples >= y.size:
        raise ValueError("settling_samples must lie within the signal")

    requested = int(np.ceil(integration_cycles / (f_hz * dt_s)))
    available = y.size - settling_samples
    if available < requested:
        raise ValueError(
            "not enough steady-state samples for quadrature fitting: "
            f"need {requested} (integration_cycles/f) after settling, "
            f"have {available}; time window too short for a reliable complex sample"
        )
    count = requested
    start = y.size - count
    if start < settling_samples:
        start = settling_samples
    t = np.arange(start, y.size, dtype=float) * dt_s
    design = np.column_stack(
        (np.sin(2.0 * np.pi * f_hz * t), np.cos(2.0 * np.pi * f_hz * t), np.ones_like(t))
    )
    coefficients, _, rank, _ = np.linalg.lstsq(design, y[start:], rcond=None)
    if rank < 3:
        raise ValueError("quadrature fit is rank deficient")
    return complex(coefficients[0] + 1j * coefficients[1])


def dft_at(signal: np.ndarray, dt_s: float, f_hz: float) -> complex:
    """Exact-tone complex evaluation (point-wise DFT). Not nearest-bin."""
    return complex(exact_dtft(signal, dt_s, f_hz))


def synthesize_tone_response(
    impulse_response: np.ndarray,
    dt_s: float,
    f_hz: float,
    ramp_k: float = 0.1,
    *,
    ramp_phase: float | None = None,
) -> np.ndarray:
    """Per-tone receiver response = h[n] convolved with the ramped tone."""
    tone = make_sine_tone(
        f_hz, dt_s, len(impulse_response), ramp_k, ramp_phase=ramp_phase
    )
    full = np.convolve(impulse_response, tone, mode="full")
    return full[: len(impulse_response)]


def complex_samples_impulse_lti(
    impulse_response: np.ndarray,
    dt_s: float,
    frequencies: Sequence[float],
    ramp_k: float = 0.1,
    *,
    ramp_phase: float | None = None,
    integration_cycles: float = 4.0,
    settling_samples: int = 0,
) -> np.ndarray:
    """Liu & Xiao 2021 route: convolve h with each tone, mix/extract."""
    samples = [
        quad_mix_extract(
            synthesize_tone_response(
                impulse_response, dt_s, f, ramp_k, ramp_phase=ramp_phase
            ),
            dt_s,
            f,
            integration_cycles=integration_cycles,
            settling_samples=settling_samples,
        )
        for f in frequencies
    ]
    return np.asarray(samples, dtype=complex)


def complex_samples_direct(
    per_tone_traces: np.ndarray,
    dt_s: float,
    frequencies: Sequence[float],
    *,
    integration_cycles: float = 4.0,
    settling_samples: int = 0,
) -> np.ndarray:
    """direct_per_tone route: per-tone receiver traces already computed."""
    if np.ndim(per_tone_traces) != 2:
        raise ValueError("per_tone_traces must be (n_tones, n_samples)")
    if len(per_tone_traces) != len(frequencies):
        raise ValueError("trace count must match tone count")
    samples = [
        quad_mix_extract(
            per_tone_traces[i],
            dt_s,
            f,
            integration_cycles=integration_cycles,
            settling_samples=settling_samples,
        )
        for i, f in enumerate(frequencies)
    ]
    return np.asarray(samples, dtype=complex)


def complex_samples_broadband(
    receiver_ez: np.ndarray,
    dt_s: float,
    source_waveform: np.ndarray | None = None,
    frequencies: Sequence[float] | None = None,
    dt_source_s: float | None = None,
    regularisation: float = 1e-10,
    f_lo_hz: float | None = None,
    f_hi_hz: float | None = None,
    *,
    source_spectrum: np.ndarray | None = None,
) -> np.ndarray:
    """broadband_deconvolution route: exact-tone sampling + Wiener.

    ``receiver_ez`` is the single broadband run; ``source_waveform`` is the
    time-domain source sampled on the receiver time grid.  The legacy keyword
    ``source_spectrum`` is accepted for compatibility but also denotes that
    time-domain waveform. Frequencies outside the
    selected band are excluded after deconvolution.
    """
    if source_waveform is None:
        source_waveform = source_spectrum
    elif source_spectrum is not None:
        raise ValueError("specify source_waveform or legacy source_spectrum, not both")
    if source_waveform is None or frequencies is None or dt_source_s is None:
        raise ValueError("source waveform, frequencies, and dt_source_s are required")
    s_time = np.asarray(source_waveform, dtype=float)
    r_time = np.asarray(receiver_ez, dtype=float)
    if abs(dt_source_s - dt_s) / dt_s > 1e-6:
        raise ValueError("source and receiver must share the same time grid")
    if len(s_time) != len(r_time):
        raise ValueError("source and receiver sample counts must match")

    selected = np.asarray(
        [
            f
            for f in frequencies
            if (f_lo_hz is None or f >= f_lo_hz)
            and (f_hi_hz is None or f <= f_hi_hz)
        ],
        dtype=float,
    )
    if selected.size == 0:
        raise ValueError("no frequencies remain inside the selected band")
    receiver_values = np.asarray(exact_dtft(r_time, dt_s, selected))
    source_values = np.asarray(exact_dtft(s_time, dt_source_s, selected))
    return wiener_deconvolve(receiver_values, source_values, regularisation)


# --------------------------------------------------------------------------
# Inverse reconstruction
# --------------------------------------------------------------------------

def reconstruct_ascan(
    complex_samples: np.ndarray,
    zero_pad_factor: int = 8,
    window: np.ndarray | None = None,
) -> np.ndarray:
    """Zero-padded complex IFFT of a uniformly spaced stepped-frequency series.

    Sample zero is the measurement at ``f_lo`` and is retained.  This is the
    Liu & Xiao (2021) fusion convention: tone order is the complex baseband
    frequency axis and no artificial Hermitian mirror is added.  Zero padding
    only interpolates delay and the ``Nfft/N`` scale preserves peak amplitude.
    """
    samples = np.asarray(complex_samples, dtype=complex)
    n = len(samples)
    if n < 2:
        raise ValueError("need at least two tones to reconstruct")
    if not isinstance(zero_pad_factor, int) or zero_pad_factor < 1:
        raise ValueError("zero_pad_factor must be a positive integer")
    if window is not None:
        if len(window) != n:
            raise ValueError("window length must match tone count")
        samples = samples * window

    nfft = n * zero_pad_factor
    return np.fft.ifft(samples, n=nfft) * (nfft / n)


def envelope(ascan: np.ndarray) -> np.ndarray:
    """Return magnitude of a complex A-scan or Hilbert envelope of a real one.

    The SFCW complex-IFFT product is already analytic/baseband, so its envelope
    is ``abs(ascan)``.  For a real trace, a numpy-only Hilbert passband mask is
    used.  Both results are nonnegative by construction.
    """
    raw = np.asarray(ascan)
    if np.iscomplexobj(raw):
        return np.abs(raw)
    x = np.asarray(raw, dtype=float)
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
    window_kind: str = "custom",
    zero_pad_factor: int = 8,
    regularisation: float = 1e-10,
    ramp_k: float = 0.1,
    ramp_phase: float | None = None,
    integration_cycles: float = 4.0,
    settling_samples: int = 0,
    source_delay_s: float = 0.0,
) -> dict[str, Any]:
    """Run one declared SFCW chain end-to-end.

    Returns a mapping with ``samples`` (complex), ``ascan`` (complex),
    ``envelope`` (float), and ``mode``. Raises ValueError for a mode whose
    required inputs are missing.
    """
    frequencies = None if frequencies is None else np.asarray(frequencies, dtype=float)

    if frequencies is None:
        raise ValueError("frequencies are required")
    df_hz = uniform_frequency_step(frequencies)
    if ramp_phase is not None:
        if ramp_k != 0.1 and not np.isclose(ramp_k, ramp_phase):
            raise ValueError("specify ramp_k or legacy ramp_phase, not both")
        effective_ramp_k = ramp_phase
    else:
        effective_ramp_k = ramp_k
    used_frequencies = frequencies

    if mode == "direct_per_tone":
        if frequencies is None or per_tone_traces is None:
            raise ValueError("direct_per_tone needs frequencies and per_tone_traces")
        samples = complex_samples_direct(
            per_tone_traces,
            dt_s,
            frequencies,
            integration_cycles=integration_cycles,
            settling_samples=settling_samples,
        )
    elif mode == "impulse_lti":
        if frequencies is None or impulse_response is None:
            raise ValueError("impulse_lti needs frequencies and impulse_response")
        samples = complex_samples_impulse_lti(
            impulse_response,
            dt_s,
            frequencies,
            effective_ramp_k,
            integration_cycles=integration_cycles,
            settling_samples=settling_samples,
        )
    elif mode == "broadband_deconvolution":
        if receiver_ez is None or source_waveform is None:
            raise ValueError(
                "broadband_deconvolution needs receiver_ez and source_waveform"
            )
        lo, hi = band_hz if band_hz is not None else (frequencies[0], frequencies[-1])
        freq_grid = np.asarray(frequencies, dtype=float)
        used_frequencies = freq_grid[(freq_grid >= lo) & (freq_grid <= hi)]
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

    if source_delay_s:
        samples = deembed_delay(samples, used_frequencies, source_delay_s)

    a_scan = reconstruct_ascan(samples, zero_pad_factor=zero_pad_factor, window=window)
    nfft = len(a_scan)
    if window is None:
        window_metadata: dict[str, Any] = {
            "kind": "rectangular",
            "coefficient_count": int(len(samples)),
            "coefficient_sha256": None,
        }
    else:
        coefficients = np.ascontiguousarray(np.asarray(window, dtype=np.float64))
        window_metadata = {
            "kind": window_kind,
            "coefficient_count": int(coefficients.size),
            "coefficient_sha256": hashlib.sha256(coefficients.tobytes()).hexdigest(),
        }
    measurement_mode = {
        "direct_per_tone": "sfcw_direct_per_tone",
        "impulse_lti": "sfcw_equivalent_impulse_lti",
        "broadband_deconvolution": "broadband_to_sfcw_equivalent",
    }[mode]
    return {
        "mode": mode,
        "samples": samples,
        "frequencies_hz": used_frequencies,
        "ascan": a_scan,
        "envelope": envelope(a_scan),
        "fdtd_dt_s": dt_s,
        "delay_bin_s": 1.0 / (nfft * df_hz),
        "unambiguous_delay_s": 1.0 / df_hz,
        "processing_parameters": {
            "measurement_mode": measurement_mode,
            "tone_count": int(len(used_frequencies)),
            "first_tone_hz": float(used_frequencies[0]),
            "last_tone_hz": float(used_frequencies[-1]),
            "delta_f_hz": float(df_hz),
            "window": window_metadata,
            "zero_pad_factor": zero_pad_factor,
            "quantitative_normalization": "none",
            "regularisation": (
                regularisation if mode == "broadband_deconvolution" else None
            ),
            "ramp_k": effective_ramp_k if mode == "impulse_lti" else None,
            "integration_cycles": integration_cycles
            if mode in {"direct_per_tone", "impulse_lti"}
            else None,
            "settling_samples": settling_samples
            if mode in {"direct_per_tone", "impulse_lti"}
            else None,
            "source_delay_s": source_delay_s,
            "noise_model": "none",
            "liu2021_scope": "core_noiseless_lti"
            if mode == "impulse_lti"
            else "not_applicable",
        },
    }
