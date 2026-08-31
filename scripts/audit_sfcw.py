from __future__ import annotations

from typing import Any, Mapping

import numpy as np

from scripts.core import GateContext, GateResult, GateState


_MODES = {"direct_per_tone", "impulse_lti", "broadband_deconvolution"}
_EXTRACTION_METHODS = {"quadrature_mixing", "exact_dtft"}
_WINDOWS = {"rectangular", "hann", "kaiser"}
_FORBIDDEN_NORMALIZATIONS = {"per_tone", "per_trace", "per_distance"}
_REFERENCE_CLASSES = {
    "none",
    "solver_truth",
    "calibration_reference",
    "engineering_background",
}


def unambiguous_delay(delta_f_hz: float) -> float:
    delta = _positive(delta_f_hz, "delta_f_hz")
    return 1.0 / delta


def delay_bin(delta_f_hz: float, nfft: int) -> float:
    delta = _positive(delta_f_hz, "delta_f_hz")
    if isinstance(nfft, bool) or not isinstance(nfft, (int, np.integer)) or nfft < 2:
        raise ValueError("nfft must be an integer of at least 2")
    return 1.0 / (float(nfft) * delta)


def unambiguous_range(velocity_mps: float, delta_f_hz: float) -> float:
    return _positive(velocity_mps, "velocity_mps") / (2.0 * _positive(delta_f_hz, "delta_f_hz"))


def bandwidth_resolution_scale(velocity_mps: float, bandwidth_hz: float) -> float:
    return _positive(velocity_mps, "velocity_mps") / (2.0 * _positive(bandwidth_hz, "bandwidth_hz"))


def audit_sfcw(ctx: GateContext) -> GateResult:
    """Fail-closed audit of SFCW sampling, processing, and acquisition policy."""
    try:
        contract = ctx.contract
        tones = _tone_grid(contract.get("tones_hz"))
        spacing = np.diff(tones)
        delta_f_hz = float(spacing[0])
        if not np.allclose(spacing, delta_f_hz, rtol=1e-10, atol=max(1e-9, abs(delta_f_hz) * 1e-12)):
            return _blocked("BLOCK_SFCW_NONUNIFORM_TONES", "tones_hz must be uniformly spaced")

        processing = _mapping(contract.get("processing"), "processing")
        mode = _choice(processing.get("mode"), _MODES, "processing.mode")
        extraction = _choice(
            processing.get("frequency_extraction"),
            _EXTRACTION_METHODS,
            "processing.frequency_extraction",
        )
        expected_extraction = (
            "exact_dtft" if mode == "broadband_deconvolution" else "quadrature_mixing"
        )
        if extraction != expected_extraction:
            return _blocked(
                "BLOCK_SFCW_EXTRACTION_MODE",
                f"{mode} requires frequency_extraction={expected_extraction}",
            )
        processing_id = _nonempty(processing.get("processing_id"), "processing.processing_id")
        tone_source = _nonempty(processing.get("tone_source"), "processing.tone_source")
        nfft = _integer(processing.get("nfft"), "processing.nfft", minimum=len(tones))

        window = _mapping(processing.get("window"), "processing.window")
        window_kind = _choice(window.get("kind"), _WINDOWS, "processing.window.kind")
        if window_kind == "kaiser":
            _finite(window.get("beta"), "processing.window.beta")

        zero_padding = _mapping(processing.get("zero_padding"), "processing.zero_padding")
        zero_pad_factor = _integer(
            zero_padding.get("factor"), "processing.zero_padding.factor", minimum=1
        )
        if nfft != len(tones) * zero_pad_factor:
            return _blocked(
                "BLOCK_SFCW_NFFT_CONTRACT",
                "processing.nfft must equal tone_count * zero_padding.factor",
            )
        if zero_padding.get("claims_physical_resolution_gain") is not False:
            return _blocked(
                "BLOCK_FALSE_RESOLUTION_CLAIM",
                "zero padding may refine sampling but cannot claim physical resolution gain",
            )

        normalization = _nonempty(
            processing.get("quantitative_normalization"),
            "processing.quantitative_normalization",
        )
        if normalization in _FORBIDDEN_NORMALIZATIONS:
            return _blocked(
                "BLOCK_QUANTITATIVE_NORMALIZATION",
                f"{normalization} normalization is forbidden in the quantitative chain",
            )

        source_delay = _mapping(processing.get("source_delay"), "processing.source_delay")
        artificial_delay_s = _nonnegative(
            source_delay.get("artificial_delay_s"),
            "processing.source_delay.artificial_delay_s",
        )
        corrections = _integer(
            source_delay.get("correction_count"),
            "processing.source_delay.correction_count",
            minimum=0,
        )
        expected_corrections = 1 if artificial_delay_s > 0 else 0
        if corrections != expected_corrections:
            return _blocked(
                "BLOCK_SOURCE_DELAY_CORRECTION_COUNT",
                f"source delay requires exactly {expected_corrections} correction(s), got {corrections}",
            )
        residual_delay_s = _nonnegative(
            source_delay.get("residual_group_delay_abs_s"),
            "processing.source_delay.residual_group_delay_abs_s",
        )
        delay_tolerance_s = _nonnegative(
            source_delay.get("tolerance_s"), "processing.source_delay.tolerance_s"
        )
        if residual_delay_s > delay_tolerance_s:
            return _blocked(
                "BLOCK_SOURCE_DELAY_NOT_DEEMBEDDED",
                f"residual group delay {residual_delay_s:.12g} s exceeds {delay_tolerance_s:.12g} s",
            )

        regularization = _regularization(processing, mode, ctx.artifacts.get("source_audit"))
        reference = _reference(processing)
        acquisition = _acquisition(contract)

        max_delay_s = contract.get("requested_max_delay_s")
        ambiguity_s = unambiguous_delay(delta_f_hz)
        if max_delay_s is not None and _nonnegative(max_delay_s, "requested_max_delay_s") >= ambiguity_s:
            return _blocked(
                "BLOCK_SFCW_AMBIGUOUS_DELAY",
                "requested_max_delay_s must be smaller than the unambiguous delay 1/df",
            )

        # Nyquist check: the highest tone must be below the Nyquist rate
        # (only when a solver time step is declared).
        numerics = contract.get("numerics")
        dt_s = None
        if isinstance(numerics, Mapping):
            dt_s = numerics.get("dt_s")
        if dt_s is not None and tones[-1] >= 0.5 / _positive(dt_s, "numerics.dt_s"):
            return _blocked(
                "BLOCK_SFCW_TONES_ABOVE_NYQUIST",
                f"highest tone {tones[-1]/1e6:.1f} MHz >= Nyquist {0.5/dt_s/1e6:.1f} MHz "
                f"(dt_s={dt_s:.2e})",
            )

        # Steady-state feasibility: the trace window must be long enough for
        # the ramp, settling, and the requested integration cycles (only when
        # ramp_k and a time window are declared).
        ramp_k = processing.get("ramp_k")
        window_s = numerics.get("time_window_s") if isinstance(numerics, Mapping) else None
        if ramp_k is not None and window_s is not None:
            ramp_k = _fraction(ramp_k, "processing.ramp_k")
            f_lo = tones[0]
            ramp_s = 1.0 / (ramp_k * f_lo) if ramp_k > 0 else 0.0
            int_cycles = processing.get("integration_cycles", 4.0)
            settling_s = processing.get("settling_samples", 0) * dt_s if dt_s else 0.0
            int_s = int_cycles / f_lo if f_lo > 0 else 0.0
            needed_s = ramp_s + settling_s + int_s
            if window_s < needed_s:
                return _blocked(
                    "BLOCK_SFCW_STEADY_STATE_WINDOW",
                    f"time window {window_s:.2e} s too short for steady-state "
                    f"extraction: need {needed_s:.2e} s "
                    f"(ramp {ramp_s:.2e} + settling {settling_s:.2e} + "
                    f"integration {int_s:.2e})",
                )

        report = {
            "processing_id": processing_id,
            "mode": mode,
            "frequency_extraction": extraction,
            "tone_source": tone_source,
            "tone_count": int(tones.size),
            "first_tone_hz": float(tones[0]),
            "last_tone_hz": float(tones[-1]),
            "delta_f_hz": delta_f_hz,
            "bandwidth_hz": float(tones[-1] - tones[0]),
            "nfft": nfft,
            "delay_bin_s": delay_bin(delta_f_hz, nfft),
            "unambiguous_delay_s": ambiguity_s,
            "window": dict(window),
            "zero_padding": dict(zero_padding),
            "quantitative_normalization": normalization,
            "source_delay": dict(source_delay),
            "regularization": regularization,
            "reference": reference,
            "acquisition": acquisition,
            "zero_pad_factor": zero_pad_factor,
        }
        ctx.artifacts["sfcw_audit"] = report
        if max_delay_s is None:
            return GateResult(
                "sfcw",
                GateState.PASS_WITH_LIMITATION,
                "PASS_SFCW_WITHOUT_DELAY_LIMIT",
                "SFCW checks pass but requested_max_delay_s is not declared; "
                "unambiguous-delay coverage is unverified",
                evidence=(
                    f"processing_id={processing_id}",
                    f"delta_f_hz={delta_f_hz}",
                    f"unambiguous_delay_s={ambiguity_s}",
                ),
                invalidates=("processing", "metrics", "claims"),
            )
        return GateResult(
            "sfcw",
            GateState.PASS,
            "PASS_SFCW",
            "SFCW tone, delay, processing, reference, and acquisition checks pass",
            evidence=(
                f"processing_id={processing_id}",
                f"delta_f_hz={delta_f_hz}",
                f"delay_bin_s={report['delay_bin_s']}",
                f"unambiguous_delay_s={ambiguity_s}",
            ),
            invalidates=("processing", "metrics", "claims"),
        )
    except _PolicyBlock as error:
        return _blocked(error.code, error.summary)
    except (TypeError, ValueError) as error:
        return _blocked("BLOCK_SFCW_CONTRACT", str(error))


def _regularization(
    processing: Mapping[str, Any], mode: str, source_report: object
) -> dict[str, Any] | None:
    raw = processing.get("regularization")
    if mode != "broadband_deconvolution":
        if raw is not None:
            raise ValueError("processing.regularization is only valid for broadband_deconvolution")
        return None
    value = _mapping(raw, "processing.regularization")
    strength = _nonnegative(value.get("value"), "processing.regularization.value")
    selection = _nonempty(value.get("selection"), "processing.regularization.selection")
    max_condition_fraction = _fraction(
        value.get("max_condition_fraction"),
        "processing.regularization.max_condition_fraction",
    )
    if not isinstance(source_report, Mapping):
        raise ValueError("source audit evidence is required for broadband deconvolution")
    power_ratios = np.asarray(source_report.get("normalized_power_ratios"), dtype=float)
    if power_ratios.ndim != 1 or power_ratios.size == 0 or not np.isfinite(power_ratios).all():
        raise ValueError("source normalized power evidence is required for deconvolution conditioning")
    observed_fraction = float(np.mean(power_ratios <= strength))
    if observed_fraction > max_condition_fraction:
        raise _PolicyBlock(
            "BLOCK_DECONVOLUTION_CONDITION",
            f"source notch fraction {observed_fraction:.6g} exceeds {max_condition_fraction:.6g}",
        )
    return {
        "value": strength,
        "selection": selection,
        "condition_fraction": observed_fraction,
        "max_condition_fraction": max_condition_fraction,
    }


def _reference(processing: Mapping[str, Any]) -> dict[str, Any]:
    reference = _mapping(processing.get("reference"), "processing.reference")
    classification = _choice(
        reference.get("class"), _REFERENCE_CLASSES, "processing.reference.class"
    )
    requested_use = _nonempty(
        reference.get("requested_use"), "processing.reference.requested_use"
    )
    field_available = reference.get("field_available")
    if not isinstance(field_available, bool):
        raise ValueError("processing.reference.field_available must be boolean")
    if classification == "solver_truth" and requested_use == "engineering_input" and not field_available:
        raise _PolicyBlock(
            "BLOCK_TRUTH_REFERENCE_ENGINEERING_INPUT",
            "solver-truth subtraction cannot be promoted to an unavailable engineering reference",
        )
    return dict(reference)


def _acquisition(contract: Mapping[str, Any]) -> dict[str, Any]:
    acquisition = _mapping(contract.get("acquisition"), "acquisition")
    motion = acquisition.get("motion_during_sweep")
    positions_change = acquisition.get("positions_change_per_tone")
    complete = acquisition.get("tones_completed_per_position")
    if not all(isinstance(value, bool) for value in (motion, positions_change, complete)):
        raise ValueError("acquisition motion/position fields must be boolean")
    if not motion and (positions_change or not complete):
        raise _PolicyBlock(
            "BLOCK_SFCW_POSITION_SEMANTICS",
            "a stationary sweep must complete every tone before changing antenna position",
        )
    return dict(acquisition)


def _tone_grid(value: object) -> np.ndarray:
    tones = np.asarray(value, dtype=float) if value is not None else np.asarray([])
    if tones.ndim != 1 or tones.size < 2 or not np.isfinite(tones).all():
        raise ValueError("tones_hz must contain at least two finite values")
    if np.any(tones <= 0) or np.any(np.diff(tones) <= 0):
        raise ValueError("tones_hz must be positive and strictly increasing")
    return tones


class _PolicyBlock(ValueError):
    def __init__(self, code: str, summary: str):
        super().__init__(summary)
        self.code = code
        self.summary = summary


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _choice(value: object, choices: set[str], name: str) -> str:
    text = _nonempty(value, name)
    if text not in choices:
        raise ValueError(f"{name} must be one of {', '.join(sorted(choices))}")
    return text


def _nonempty(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite")
    number = float(value)
    if not np.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _positive(value: object, name: str) -> float:
    number = _finite(value, name)
    if number <= 0:
        raise ValueError(f"{name} must be positive")
    return number


def _nonnegative(value: object, name: str) -> float:
    number = _finite(value, name)
    if number < 0:
        raise ValueError(f"{name} must be non-negative")
    return number


def _fraction(value: object, name: str) -> float:
    number = _finite(value, name)
    if not 0 <= number <= 1:
        raise ValueError(f"{name} must be between 0 and 1")
    return number


def _integer(value: object, name: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return int(value)


def _blocked(code: str, summary: str) -> GateResult:
    return GateResult(
        "sfcw",
        GateState.BLOCK,
        code,
        summary,
        invalidates=("processing", "metrics", "claims"),
    )
