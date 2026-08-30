from __future__ import annotations

import hashlib
from typing import Any, Mapping

import numpy as np

from scripts.core import GateContext, GateResult, GateState


def source_spectrum(
    signal: np.ndarray, dt_s: float, frequencies_hz: np.ndarray
) -> np.ndarray:
    """Evaluate the source spectrum at the exact requested frequencies."""
    values = np.asarray(signal, dtype=np.complex128)
    tones = np.asarray(frequencies_hz, dtype=np.float64)
    if values.ndim != 1 or values.size == 0:
        raise ValueError("source signal must be a non-empty one-dimensional array")
    if not np.isfinite(values).all():
        raise ValueError("source signal must contain only finite samples")
    if not np.isfinite(dt_s) or dt_s <= 0:
        raise ValueError("source.dt_s must be positive and finite")
    if tones.ndim != 1 or tones.size == 0 or not np.isfinite(tones).all():
        raise ValueError("tones_hz must be a non-empty finite one-dimensional array")
    time_s = np.arange(values.size, dtype=np.float64) * dt_s
    return np.exp(-2j * np.pi * np.outer(tones, time_s)) @ values


def source_peak_time(signal: np.ndarray, dt_s: float) -> float:
    values = np.asarray(signal)
    if values.ndim != 1 or values.size == 0:
        raise ValueError("source signal must be a non-empty one-dimensional array")
    if not np.isfinite(dt_s) or dt_s <= 0:
        raise ValueError("source.dt_s must be positive and finite")
    return float(np.argmax(np.abs(values)) * dt_s)


def tail_energy_fraction(signal: np.ndarray, peak_index: int) -> float:
    values = np.asarray(signal, dtype=np.complex128)
    if values.ndim != 1 or values.size == 0:
        raise ValueError("source signal must be a non-empty one-dimensional array")
    if not 0 <= peak_index < values.size:
        raise ValueError("peak_index is outside the source signal")
    power = np.abs(values) ** 2
    total = float(power.sum())
    if total == 0:
        raise ValueError("source signal has zero energy")
    return float(power[peak_index + 1 :].sum() / total)


def audit_source(ctx: GateContext) -> GateResult:
    """Audit exact-tone support, DC, peak time, and post-peak tail energy."""
    try:
        source = _mapping(ctx.contract.get("source"), "source")
        tones = _tones(ctx.contract)
        signal = _source_signal(ctx, source)
        dt_s = _positive(source.get("dt_s"), "source.dt_s")
        spectrum = source_spectrum(signal, dt_s, tones)
        magnitudes = np.abs(spectrum)
        strongest = float(magnitudes.max())
        if strongest == 0:
            return _blocked("BLOCK_SOURCE_ZERO", "source has zero support at every requested tone")

        minimum_support = _optional_fraction(
            source.get("minimum_support_ratio"), "source.minimum_support_ratio"
        )
        support_ratios = magnitudes / strongest
        notch_fraction = (
            None
            if minimum_support is None
            else float(np.mean(support_ratios < minimum_support))
        )
        peak_index = int(np.argmax(np.abs(signal)))
        peak_time_s = source_peak_time(signal, dt_s)
        tail_fraction = tail_energy_fraction(signal, peak_index)
        peak_amplitude = float(np.max(np.abs(signal)))
        dc_ratio = float(abs(np.mean(signal)) / peak_amplitude) if peak_amplitude else float("inf")

        report = {
            "sample_count": int(signal.size),
            "sample_dtype": signal.dtype.name,
            "sample_sha256": hashlib.sha256(
                np.ascontiguousarray(signal).view(np.uint8).tobytes()
            ).hexdigest(),
            "dt_s": dt_s,
            "peak_index": peak_index,
            "peak_time_s": peak_time_s,
            "tail_energy_fraction": tail_fraction,
            "dc_ratio": dc_ratio,
            "minimum_support_ratio": minimum_support,
            "minimum_observed_support_ratio": float(support_ratios.min()),
            "normalized_power_ratios": [float(value) for value in support_ratios**2],
            "notch_fraction": notch_fraction,
        }
        ctx.artifacts["source_audit"] = report

        if minimum_support is not None and notch_fraction and notch_fraction > 0:
            return _blocked(
                "BLOCK_SOURCE_SPECTRAL_SUPPORT",
                f"{notch_fraction:.6g} of requested tones fall below the declared source support",
                report,
            )
        max_dc_ratio = _optional_fraction(source.get("max_dc_ratio"), "source.max_dc_ratio")
        if max_dc_ratio is not None and dc_ratio > max_dc_ratio:
            return _blocked(
                "BLOCK_SOURCE_DC",
                f"source DC ratio {dc_ratio:.6g} exceeds {max_dc_ratio:.6g}",
                report,
            )
        max_tail_fraction = _optional_fraction(
            source.get("max_tail_energy_fraction"), "source.max_tail_energy_fraction"
        )
        if max_tail_fraction is not None and tail_fraction > max_tail_fraction:
            return _blocked(
                "BLOCK_SOURCE_TAIL",
                f"source tail-energy fraction {tail_fraction:.6g} exceeds {max_tail_fraction:.6g}",
                report,
            )

        missing = [
            name
            for name, value in (
                ("minimum_support_ratio", minimum_support),
                ("max_dc_ratio", max_dc_ratio),
                ("max_tail_energy_fraction", max_tail_fraction),
            )
            if value is None
        ]
        if missing:
            return GateResult(
                "source",
                GateState.PASS_WITH_LIMITATION,
                "LIMIT_SOURCE_THRESHOLDS",
                "source math passed but explicit thresholds are missing: " + ", ".join(missing),
                evidence=_evidence(report),
                invalidates=("processing", "metrics", "claims"),
            )
        return GateResult(
            "source",
            GateState.PASS,
            "PASS_SOURCE",
            "source support, DC, timing, and tail checks pass",
            evidence=_evidence(report),
            invalidates=("processing", "metrics", "claims"),
        )
    except (TypeError, ValueError) as error:
        return _blocked("BLOCK_SOURCE_CONTRACT", str(error))


def _source_signal(ctx: GateContext, source: Mapping[str, Any]) -> np.ndarray:
    value = ctx.artifacts.get("source_signal", source.get("samples"))
    if value is None:
        raise ValueError("source samples are required through --source-array or source.samples")
    signal = np.asarray(value)
    if signal.ndim != 1 or signal.size == 0 or not np.isfinite(signal).all():
        raise ValueError("source samples must be a non-empty finite one-dimensional array")
    return signal


def _tones(contract: Mapping[str, Any]) -> np.ndarray:
    raw = contract.get("tones_hz")
    tones = np.asarray(raw, dtype=float) if raw is not None else np.asarray([])
    if tones.ndim != 1 or tones.size < 2 or not np.isfinite(tones).all():
        raise ValueError("tones_hz must contain at least two finite values")
    return tones


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _positive(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be positive and finite")
    number = float(value)
    if not np.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be positive and finite")
    return number


def _optional_fraction(value: object, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{name} must be between 0 and 1")
    number = float(value)
    if not np.isfinite(number) or not 0 <= number <= 1:
        raise ValueError(f"{name} must be between 0 and 1")
    return number


def _evidence(report: Mapping[str, Any]) -> tuple[str, ...]:
    keys = (
        "sample_count",
        "sample_dtype",
        "sample_sha256",
        "peak_time_s",
        "tail_energy_fraction",
        "dc_ratio",
        "minimum_observed_support_ratio",
        "notch_fraction",
    )
    return tuple(f"{key}={report[key]}" for key in keys)


def _blocked(
    code: str, summary: str, report: Mapping[str, Any] | None = None
) -> GateResult:
    return GateResult(
        "source",
        GateState.BLOCK,
        code,
        summary,
        evidence=() if report is None else _evidence(report),
        invalidates=("processing", "metrics", "claims"),
    )
