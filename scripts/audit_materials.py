from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from numbers import Real
from typing import Any

import numpy as np

from scripts.core import GateContext, GateResult, GateState


C0 = 299_792_458.0
EPSILON_0_F_M = 8.854_187_812_8e-12
_PROVENANCE_CLASSES = frozenset(
    {"measured", "literature", "manufacturer", "assumed", "sensitivity_only"}
)
_LIMITED_PROVENANCE = frozenset({"assumed", "sensitivity_only"})
_CLAIM_GRADE_SCOPES = frozenset({"physical", "engineering"})
_SUPPORTED_CLAIM_SCOPES = frozenset({"numerical", "physical", "engineering"})


class _MaterialAuditError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def complex_permittivity_debye(
    f_hz: object,
    epsilon_inf: float,
    delta_epsilon: float,
    tau_s: float,
    sigma_s_m: float,
) -> np.ndarray:
    """Return single-pole Debye complex relative permittivity.

    The phasor convention is ``exp(+j omega t)``. Consequently a passive
    dielectric has ``Im(epsilon_r*) <= 0`` and this function evaluates

    ``epsilon_inf + delta_epsilon / (1 + j omega tau)
    - j sigma / (omega epsilon_0)``.

    ``epsilon_inf`` and ``tau_s`` must be positive; ``delta_epsilon`` and
    ``sigma_s_m`` must be non-negative. Frequencies must be finite and
    strictly positive because the conductivity term is singular at DC.
    """
    try:
        frequency = np.asarray(f_hz, dtype=float)
    except (TypeError, ValueError) as error:
        raise ValueError("f_hz must contain finite positive frequencies") from error
    if frequency.size == 0 or not np.isfinite(frequency).all() or np.any(frequency <= 0.0):
        raise ValueError("f_hz must contain finite positive frequencies")

    epsilon_high = _positive_finite(epsilon_inf, "epsilon_inf")
    relaxation_strength = _nonnegative_finite(delta_epsilon, "delta_epsilon")
    relaxation_time = _positive_finite(tau_s, "tau_s")
    conductivity = _nonnegative_finite(sigma_s_m, "sigma_s_m")

    omega = 2.0 * np.pi * frequency
    result = (
        epsilon_high
        + relaxation_strength / (1.0 + 1j * omega * relaxation_time)
        - 1j * conductivity / (omega * EPSILON_0_F_M)
    )
    if not np.isfinite(result.real).all() or not np.isfinite(result.imag).all():
        raise ValueError("Debye permittivity must be finite over the requested frequencies")
    return np.asarray(result, dtype=np.complex128)


def audit_materials(ctx: GateContext) -> GateResult:
    """Validate material parameters, provenance, and requested-band validity."""
    try:
        materials = _materials(ctx.contract)
        claim_scope = _claim_scope(ctx.contract)
        analysis_band = _analysis_band(ctx.contract)
        summaries: list[dict[str, Any]] = []
        limited_names: list[str] = []

        for index, material in enumerate(materials):
            name = _material_name(material, index)
            model = _model_type(material, index)
            provenance, site_measured = _provenance(material, index)
            parameters = _validated_parameters(material, model, index)
            validity_band = _optional_band(
                material.get("frequency_range_valid_hz"),
                f"materials[{index}].frequency_range_valid_hz",
            )
            if analysis_band is not None and validity_band is not None:
                if analysis_band[0] < validity_band[0] or analysis_band[1] > validity_band[1]:
                    raise _MaterialAuditError(
                        "BLOCK_MATERIAL_BAND",
                        f"{name} validity band does not contain the requested analysis band",
                    )

            if site_measured and provenance != "measured":
                raise _MaterialAuditError(
                    "BLOCK_MATERIAL_PROVENANCE",
                    f"{name} is labeled site-measured but its provenance is {provenance}",
                )
            if claim_scope in _CLAIM_GRADE_SCOPES and provenance in _LIMITED_PROVENANCE:
                limited_names.append(name)

            item_summary: dict[str, Any] = {
                "name": name,
                "model": model,
                "provenance_class": provenance,
            }
            if validity_band is not None:
                item_summary["frequency_range_valid_hz"] = list(validity_band)
            if analysis_band is not None:
                item_summary.update(_frequency_summary(model, parameters, analysis_band))
            summaries.append(item_summary)

        report: dict[str, Any] = {
            "phasor_convention": "exp(+j omega t)",
            "passive_loss_definition": "loss = -Im(epsilon_r*)",
            "materials": summaries,
        }
        if analysis_band is not None:
            report["analysis_band_hz"] = list(analysis_band)
        _publish_derived(ctx, report)
    except _MaterialAuditError as error:
        return _blocked(error.code, str(error))
    except (KeyError, TypeError, ValueError) as error:
        return _blocked("BLOCK_MATERIAL_PARAMETERS", str(error))

    if limited_names:
        return GateResult(
            "materials",
            GateState.PASS_WITH_LIMITATION,
            "LIMIT_MATERIAL_PROVENANCE",
            "claim-grade scope uses assumed or sensitivity-only material parameters: "
            + ", ".join(limited_names),
            invalidates=("geometry", "simulation", "claims"),
        )
    return GateResult(
        "materials",
        GateState.PASS,
        "PASS_MATERIALS",
        "material parameters, provenance, and requested-band validity pass",
        invalidates=("geometry", "simulation", "claims"),
    )


def _materials(contract: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    value = contract.get("materials")
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise _MaterialAuditError(
            "BLOCK_MATERIAL_PARAMETERS", "materials must be a non-empty sequence"
        )
    normalized: list[Mapping[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise _MaterialAuditError(
                "BLOCK_MATERIAL_PARAMETERS", f"materials[{index}] must be a mapping"
            )
        normalized.append(item)
    return tuple(normalized)


def _claim_scope(contract: Mapping[str, Any]) -> str:
    task = contract.get("task")
    if not isinstance(task, Mapping):
        raise _MaterialAuditError("BLOCK_CLAIM_SCOPE", "task must be a mapping")
    value = task.get("claim_scope")
    if not isinstance(value, str) or not value.strip():
        raise _MaterialAuditError(
            "BLOCK_CLAIM_SCOPE", "task.claim_scope must be a supported non-empty string"
        )
    scope = value.strip().lower()
    if scope not in _SUPPORTED_CLAIM_SCOPES:
        raise _MaterialAuditError(
            "BLOCK_CLAIM_SCOPE", f"task.claim_scope {scope!r} is not supported"
        )
    return scope


def _material_name(material: Mapping[str, Any], index: int) -> str:
    value = material.get("name", f"material_{index}")
    if not isinstance(value, str) or not value.strip():
        raise _MaterialAuditError(
            "BLOCK_MATERIAL_PARAMETERS", f"materials[{index}].name must be non-empty"
        )
    return value.strip()


def _model_type(material: Mapping[str, Any], index: int) -> str:
    value = material.get("model", material.get("model_type"))
    if not isinstance(value, str) or not value.strip():
        raise _MaterialAuditError(
            "BLOCK_MATERIAL_PARAMETERS", f"materials[{index}].model must be non-empty"
        )
    model = value.strip().lower()
    if model not in {"nondispersive", "debye"}:
        raise _MaterialAuditError(
            "BLOCK_MATERIAL_PARAMETERS", f"materials[{index}] has unsupported model {model}"
        )
    return model


def _provenance(material: Mapping[str, Any], index: int) -> tuple[str, bool]:
    raw = material.get("provenance", material.get("provenance_class"))
    nested_site_measured: object | None = None
    if isinstance(raw, Mapping):
        nested_site_measured = raw.get("site_measured")
        raw = raw.get("class", raw.get("provenance_class"))
    if not isinstance(raw, str) or not raw.strip():
        raise _MaterialAuditError(
            "BLOCK_MATERIAL_PROVENANCE",
            f"materials[{index}] must declare a non-empty provenance class",
        )
    provenance = raw.strip().lower()
    if provenance not in _PROVENANCE_CLASSES:
        raise _MaterialAuditError(
            "BLOCK_MATERIAL_PROVENANCE",
            f"materials[{index}] provenance class {provenance!r} is not recognized",
        )

    top_site_measured = material.get("site_measured")
    if top_site_measured is not None and nested_site_measured is not None:
        if top_site_measured != nested_site_measured:
            raise _MaterialAuditError(
                "BLOCK_MATERIAL_PROVENANCE",
                f"materials[{index}] has conflicting site-measured labels",
            )
    site_label = top_site_measured if top_site_measured is not None else nested_site_measured
    if site_label is not None and not isinstance(site_label, bool):
        raise _MaterialAuditError(
            "BLOCK_MATERIAL_PROVENANCE",
            f"materials[{index}].site_measured must be boolean when supplied",
        )
    return provenance, bool(site_label)


def _validated_parameters(
    material: Mapping[str, Any], model: str, index: int
) -> dict[str, float]:
    nested = material.get("parameters", {})
    if not isinstance(nested, Mapping):
        raise _MaterialAuditError(
            "BLOCK_MATERIAL_PARAMETERS", f"materials[{index}].parameters must be a mapping"
        )

    def parameter(key: str) -> Any:
        if key in material:
            return material[key]
        if key in nested:
            return nested[key]
        raise _MaterialAuditError(
            "BLOCK_MATERIAL_PARAMETERS", f"materials[{index}].{key} is required"
        )

    if model == "nondispersive":
        return {
            "epsilon_r": _positive_finite(parameter("epsilon_r"), f"materials[{index}].epsilon_r"),
            "sigma_s_m": _nonnegative_finite(
                parameter("sigma_s_m"), f"materials[{index}].sigma_s_m"
            ),
        }
    return {
        "epsilon_inf": _positive_finite(
            parameter("epsilon_inf"), f"materials[{index}].epsilon_inf"
        ),
        "delta_epsilon": _nonnegative_finite(
            parameter("delta_epsilon"), f"materials[{index}].delta_epsilon"
        ),
        "tau_s": _positive_finite(parameter("tau_s"), f"materials[{index}].tau_s"),
        "sigma_s_m": _nonnegative_finite(
            parameter("sigma_s_m"), f"materials[{index}].sigma_s_m"
        ),
    }


def _analysis_band(contract: Mapping[str, Any]) -> tuple[float, float] | None:
    waveform = contract.get("waveform")
    if waveform is None:
        return None
    if not isinstance(waveform, Mapping):
        raise _MaterialAuditError("BLOCK_MATERIAL_BAND", "waveform must be a mapping")
    raw = waveform.get("analysis_band", waveform.get("analysis_band_hz"))
    return _optional_band(raw, "waveform.analysis_band")


def _optional_band(value: object, path: str) -> tuple[float, float] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        if "min_hz" not in value or "max_hz" not in value:
            raise _MaterialAuditError(
                "BLOCK_MATERIAL_BAND", f"{path} must contain min_hz and max_hz"
            )
        raw = (value["min_hz"], value["max_hz"])
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) == 2:
        raw = (value[0], value[1])
    else:
        raise _MaterialAuditError(
            "BLOCK_MATERIAL_BAND", f"{path} must contain exactly two frequencies"
        )
    try:
        low = _positive_finite(raw[0], f"{path}[0]")
        high = _positive_finite(raw[1], f"{path}[1]")
    except ValueError as error:
        raise _MaterialAuditError("BLOCK_MATERIAL_BAND", str(error)) from error
    if high < low:
        raise _MaterialAuditError(
            "BLOCK_MATERIAL_BAND", f"{path} maximum must not be below its minimum"
        )
    return low, high


def _frequency_summary(
    model: str, parameters: Mapping[str, float], band: tuple[float, float]
) -> dict[str, float]:
    frequency = np.geomspace(band[0], band[1], 129)
    if model == "debye":
        epsilon = complex_permittivity_debye(
            frequency,
            parameters["epsilon_inf"],
            parameters["delta_epsilon"],
            parameters["tau_s"],
            parameters["sigma_s_m"],
        )
    else:
        omega = 2.0 * np.pi * frequency
        epsilon = parameters["epsilon_r"] - 1j * parameters["sigma_s_m"] / (
            omega * EPSILON_0_F_M
        )
    epsilon_prime = epsilon.real
    loss = -epsilon.imag
    refractive_phase_index = np.sqrt((np.abs(epsilon) + epsilon_prime) / 2.0)
    phase_velocity = C0 / refractive_phase_index
    if (
        not np.isfinite(epsilon_prime).all()
        or not np.isfinite(loss).all()
        or not np.isfinite(phase_velocity).all()
        or np.any(epsilon_prime <= 0.0)
        or np.any(loss < 0.0)
        or np.any(phase_velocity <= 0.0)
    ):
        raise _MaterialAuditError(
            "BLOCK_MATERIAL_PARAMETERS", "material response is not finite and passive over the band"
        )
    return {
        "epsilon_prime_min": float(np.min(epsilon_prime)),
        "epsilon_prime_max": float(np.max(epsilon_prime)),
        "loss_min": float(np.min(loss)),
        "loss_max": float(np.max(loss)),
        "phase_velocity_m_s_min": float(np.min(phase_velocity)),
        "phase_velocity_m_s_max": float(np.max(phase_velocity)),
    }


def _publish_derived(ctx: GateContext, report: Mapping[str, Any]) -> None:
    derived = ctx.artifacts.get("derived")
    if derived is not None and not isinstance(derived, dict):
        raise _MaterialAuditError(
            "BLOCK_MATERIAL_PARAMETERS", "artifacts.derived must be a mutable mapping"
        )
    namespace = ctx.artifacts.setdefault("derived", {})
    namespace["materials"] = dict(report)


def _positive_finite(value: object, name: str) -> float:
    number = _finite_number(value, name)
    if number <= 0.0:
        raise ValueError(f"{name} must be positive")
    return number


def _nonnegative_finite(value: object, name: str) -> float:
    number = _finite_number(value, name)
    if number < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return number


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def _blocked(code: str, summary: str) -> GateResult:
    return GateResult(
        "materials",
        GateState.BLOCK,
        code,
        summary,
        invalidates=("geometry", "simulation", "claims"),
    )
