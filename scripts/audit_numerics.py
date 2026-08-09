from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from scripts.core import GateContext, GateResult, GateState, write_json


C0 = 299_792_458.0
_ANALYTIC_ARTIFACT = "artifacts/analytic_sanity.json"


def minimum_wavelength(f_max_hz: float, epsilon_r_max: float) -> float:
    """Return the shortest nondispersive wavelength declared for the analysis."""
    frequency = _positive_finite(f_max_hz, "f_max_hz")
    permittivity = _positive_finite(epsilon_r_max, "epsilon_r_max")
    return C0 / frequency / math.sqrt(permittivity)


def courant_limit(dx: float, dy: float, dz: float) -> float:
    """Return the three-dimensional Yee-grid Courant time-step limit."""
    spacing = tuple(
        _positive_finite(value, name)
        for value, name in zip((dx, dy, dz), ("dx", "dy", "dz"), strict=True)
    )
    return 1.0 / (C0 * math.sqrt(sum(value**-2 for value in spacing)))


def required_round_trip_time(path_m: float, velocity_mps: float) -> float:
    """Return two-way propagation time for a declared one-way path length."""
    path = _nonnegative_finite(path_m, "path_m")
    velocity = _positive_finite(velocity_mps, "velocity_mps")
    return 2.0 * path / velocity


def estimate_cell_count(domain_m: object, grid_m: object) -> int:
    """Estimate allocated cells by covering every declared domain dimension."""
    domain = _three_axes(domain_m, "domain_m")
    grid = _three_axes(grid_m, "grid_m")
    return math.prod(_covering_count(length, spacing) for length, spacing in zip(domain, grid, strict=True))


def build_analytic_sanity(ctx: GateContext) -> dict[str, Any]:
    """Build and persist the contract-only F0 numerical sanity artifact.

    Memory and compute values are estimates whose coefficients must be supplied
    by the contract. They are deliberately labelled as assumptions rather than
    solver facts.
    """
    numerics = _required_mapping(ctx.contract, "numerics")
    waveform = _required_mapping(ctx.contract, "waveform")
    grid_spec = _required_mapping(numerics, "grid", prefix="numerics")
    time_spec = _required_mapping(numerics, "time", prefix="numerics")
    assumptions = _required_mapping(numerics, "compute_assumptions", prefix="numerics")

    spacing = _grid_spacing(grid_spec)
    domain = _three_axes(_required_value(numerics, "domain_m", "numerics"), "numerics.domain_m")
    f_max_hz = _positive_finite(_required_value(numerics, "f_max_hz", "numerics"), "numerics.f_max_hz")
    epsilon_r_max = _positive_finite(
        _required_value(numerics, "epsilon_r_max", "numerics"), "numerics.epsilon_r_max"
    )
    dt_s, _ = _time_step(ctx, numerics)
    source_delay_s = _nonnegative_finite(
        _required_value(waveform, "source_delay_s", "waveform"), "waveform.source_delay_s"
    )
    source_tail_s = _nonnegative_finite(
        _required_value(waveform, "source_tail_s", "waveform"), "waveform.source_tail_s"
    )
    round_trip_s, required_window_s = _time_requirements(time_spec, source_delay_s, source_tail_s)
    bytes_per_cell = _positive_integer(
        _required_value(assumptions, "bytes_per_cell", "numerics.compute_assumptions"),
        "numerics.compute_assumptions.bytes_per_cell",
    )
    operations_per_update = _positive_integer(
        _required_value(
            assumptions,
            "operations_per_cell_update",
            "numerics.compute_assumptions",
        ),
        "numerics.compute_assumptions.operations_per_cell_update",
    )

    cells = estimate_cell_count(domain, spacing)
    steps = _covering_count(required_window_s, dt_s)
    report: dict[str, Any] = {
        "fidelity_level": "F0",
        "minimum_wavelength_m": minimum_wavelength(f_max_hz, epsilon_r_max),
        "courant_limit_s": courant_limit(*spacing),
        "maximum_round_trip_time_s": round_trip_s,
        "required_time_window_s": required_window_s,
        "estimated_cell_count": cells,
        "time_step_s": dt_s,
        "estimated_time_steps": steps,
        "memory_estimate": {
            "estimated_bytes": cells * bytes_per_cell,
            "assumed_bytes_per_cell": bytes_per_cell,
            "classification": "contract_assumption_not_solver_truth",
        },
        "compute_estimate": {
            "estimated_operations": cells * steps * operations_per_update,
            "assumed_operations_per_cell_update": operations_per_update,
            "classification": "contract_assumption_not_solver_truth",
        },
    }
    requirement = grid_spec.get("cells_per_wavelength_required")
    if requirement is not None:
        report["cells_per_wavelength_required"] = _positive_finite(
            requirement, "numerics.grid.cells_per_wavelength_required"
        )

    ctx.artifacts["analytic_sanity"] = report
    write_json(ctx.project_root / _ANALYTIC_ARTIFACT, report)
    return report


def audit_grid(ctx: GateContext) -> GateResult:
    """Audit declared wavelength resolution and exact critical-feature cell counts."""
    try:
        numerics = _required_mapping(ctx.contract, "numerics")
        grid_spec = _required_mapping(numerics, "grid", prefix="numerics")
        spacing = _grid_spacing(grid_spec)
        wavelength = minimum_wavelength(
            _required_value(numerics, "f_max_hz", "numerics"),
            _required_value(numerics, "epsilon_r_max", "numerics"),
        )
        feature_failure = _undersampled_feature(ctx.contract, spacing)
        requirement = _wavelength_requirement(grid_spec, ctx.artifacts)
    except (KeyError, TypeError, ValueError) as error:
        return _invalid_gate("grid", error)

    ctx.artifacts["grid"] = {
        "minimum_wavelength_m": wavelength,
        "spacing_m": list(spacing),
        "cells_per_wavelength": wavelength / max(spacing),
    }
    if feature_failure is not None:
        return GateResult(
            "grid",
            GateState.BLOCK,
            "BLOCK_GEOMETRY_UNDERSAMPLED",
            feature_failure,
            invalidates=("cfl", "time_window", "pml", "geometry"),
        )
    if requirement is None:
        return GateResult(
            "grid",
            GateState.PASS_WITH_LIMITATION,
            "LIMIT_GRID_REQUIREMENT_UNDECLARED",
            "no cells-per-wavelength requirement is declared",
            invalidates=("cfl", "geometry"),
        )

    actual = wavelength / max(spacing)
    ctx.artifacts["grid"]["cells_per_wavelength_required"] = requirement
    if actual < requirement:
        return GateResult(
            "grid",
            GateState.BLOCK,
            "BLOCK_GRID_WAVELENGTH_UNDERSAMPLED",
            f"{actual:.12g} cells per wavelength is below declared requirement {requirement:.12g}",
            invalidates=("cfl", "time_window", "pml", "geometry"),
        )
    return GateResult(
        "grid",
        GateState.PASS,
        "PASS_GRID_RESOLVED",
        f"{actual:.12g} cells per wavelength meets declared requirement {requirement:.12g}",
        invalidates=("cfl", "geometry"),
    )


def audit_cfl(ctx: GateContext) -> GateResult:
    """Compare the observed time step, or declared step when absent, to CFL."""
    try:
        numerics = _required_mapping(ctx.contract, "numerics")
        grid_spec = _required_mapping(numerics, "grid", prefix="numerics")
        limit = courant_limit(*_grid_spacing(grid_spec))
        dt_s, source = _time_step(ctx, numerics)
    except (KeyError, TypeError, ValueError) as error:
        return _invalid_gate("cfl", error)

    ctx.artifacts["cfl"] = {"courant_limit_s": limit, "dt_s": dt_s, "dt_source": source}
    if dt_s > limit:
        return GateResult(
            "cfl",
            GateState.BLOCK,
            "BLOCK_CFL_VIOLATION",
            f"{source} dt {dt_s:.12g} s exceeds CFL limit {limit:.12g} s",
            invalidates=("time_window", "simulation"),
        )
    return GateResult(
        "cfl",
        GateState.PASS,
        "PASS_CFL",
        f"{source} dt is within the CFL limit",
        invalidates=("time_window", "simulation"),
    )


def audit_time_window(ctx: GateContext) -> GateResult:
    """Require source support, deepest two-way path, response, and guard coverage."""
    try:
        waveform = _required_mapping(ctx.contract, "waveform")
        numerics = _required_mapping(ctx.contract, "numerics")
        time_spec = _required_mapping(numerics, "time", prefix="numerics")
        source_delay_s = _nonnegative_finite(
            _required_value(waveform, "source_delay_s", "waveform"), "waveform.source_delay_s"
        )
        source_tail_s = _nonnegative_finite(
            _required_value(waveform, "source_tail_s", "waveform"), "waveform.source_tail_s"
        )
        round_trip_s, required_s = _time_requirements(time_spec, source_delay_s, source_tail_s)
        simulation_s = _positive_finite(
            _required_value(time_spec, "simulation_time_s", "numerics.time"),
            "numerics.time.simulation_time_s",
        )
    except (KeyError, TypeError, ValueError) as error:
        return _invalid_gate("time_window", error)

    ctx.artifacts["time_window"] = {
        "source_delay_s": source_delay_s,
        "source_tail_s": source_tail_s,
        "maximum_round_trip_time_s": round_trip_s,
        "response_duration_s": _nonnegative_finite(time_spec["response_duration_s"], "response_duration_s"),
        "guard_s": _nonnegative_finite(time_spec["guard_s"], "guard_s"),
        "required_time_window_s": required_s,
        "simulation_time_s": simulation_s,
    }
    if simulation_s < required_s:
        return GateResult(
            "time_window",
            GateState.BLOCK,
            "BLOCK_TIME_WINDOW_TRUNCATION_RISK",
            f"simulation window {simulation_s:.12g} s is shorter than required {required_s:.12g} s",
            invalidates=("pml", "simulation", "claims"),
        )
    return GateResult(
        "time_window",
        GateState.PASS,
        "PASS_TIME_WINDOW",
        "simulation window covers declared source, path, response, and guard",
        invalidates=("pml", "simulation", "claims"),
    )


def audit_pml(ctx: GateContext) -> GateResult:
    """Audit declared PML clearance and only explicitly required sensitivity evidence."""
    try:
        numerics = _required_mapping(ctx.contract, "numerics")
        pml = _required_mapping(numerics, "pml", prefix="numerics")
        clearance = _minimum_declared_clearance(pml.get("clearance_m"))
        minimum = _positive_finite(
            _required_value(pml, "minimum_clearance_m", "numerics.pml"),
            "numerics.pml.minimum_clearance_m",
        )
        acceptance = ctx.contract.get("acceptance", {})
        if not isinstance(acceptance, Mapping):
            raise ValueError("acceptance must be a mapping")
        tests = acceptance.get("sensitivity_tests", [])
        if not isinstance(tests, Sequence) or isinstance(tests, (str, bytes)):
            raise ValueError("acceptance.sensitivity_tests must be a sequence")
    except (KeyError, TypeError, ValueError) as error:
        return _invalid_gate("pml", error)

    ctx.artifacts["pml"] = {
        "minimum_observed_clearance_m": clearance,
        "minimum_clearance_required_m": minimum,
    }
    if clearance < minimum:
        return GateResult(
            "pml",
            GateState.BLOCK,
            "BLOCK_PML_CLEARANCE",
            f"minimum PML clearance {clearance:.12g} m is below declared requirement {minimum:.12g} m",
            invalidates=("simulation", "claims"),
        )

    sensitivity_required = any(_is_pml_sensitivity(item) for item in tests)
    evidence = pml.get("domain_sensitivity_evidence", pml.get("sensitivity_evidence"))
    if evidence is None:
        evidence = ctx.artifacts.get("pml_sensitivity")
    evidence_passes = _evidence_passes(evidence)
    ctx.artifacts["pml"]["sensitivity_required"] = sensitivity_required
    ctx.artifacts["pml"]["sensitivity_evidence_passes"] = evidence_passes
    if sensitivity_required and not evidence_passes:
        return GateResult(
            "pml",
            GateState.BLOCK,
            "BLOCK_PML_SENSITIVITY_REQUIRED",
            "acceptance requires PML/domain sensitivity evidence, but no passing evidence is declared",
            invalidates=("simulation", "claims"),
        )

    evidence_refs = (evidence,) if isinstance(evidence, str) and evidence.strip() else ()
    return GateResult(
        "pml",
        GateState.PASS,
        "PASS_PML_CLEARANCE",
        "PML clearance meets its declared requirement",
        evidence=evidence_refs,
        invalidates=("simulation", "claims"),
    )


def _positive_finite(value: object, name: str) -> float:
    number = _finite_number(value, name)
    if number <= 0:
        raise ValueError(f"{name} must be positive")
    return number


def _nonnegative_finite(value: object, name: str) -> float:
    number = _finite_number(value, name)
    if number < 0:
        raise ValueError(f"{name} must be non-negative")
    return number


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def _positive_integer(value: object, name: str) -> int:
    number = _positive_finite(value, name)
    if not number.is_integer():
        raise ValueError(f"{name} must be a positive integer")
    return int(number)


def _three_axes(value: object, name: str) -> tuple[float, float, float]:
    if isinstance(value, Mapping):
        try:
            raw = (value["x"], value["y"], value["z"])
        except KeyError as error:
            raise ValueError(f"{name} mapping must contain x, y, and z") from error
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) == 3:
        raw = tuple(value)
    else:
        raise ValueError(f"{name} must contain exactly three axes")
    return tuple(_positive_finite(axis, f"{name}[{index}]") for index, axis in enumerate(raw))  # type: ignore[return-value]


def _grid_spacing(grid_spec: Mapping[str, Any]) -> tuple[float, float, float]:
    if "spacing_m" in grid_spec:
        return _three_axes(grid_spec["spacing_m"], "numerics.grid.spacing_m")
    try:
        return tuple(
            _positive_finite(grid_spec[key], f"numerics.grid.{key}")
            for key in ("dx_m", "dy_m", "dz_m")
        )  # type: ignore[return-value]
    except KeyError as error:
        raise ValueError("numerics.grid must declare spacing_m or dx_m/dy_m/dz_m") from error


def _required_mapping(
    value: Mapping[str, Any], key: str, *, prefix: str | None = None
) -> Mapping[str, Any]:
    path = f"{prefix}.{key}" if prefix else key
    item = _required_value(value, key, prefix)
    if not isinstance(item, Mapping):
        raise ValueError(f"{path} must be a mapping")
    return item


def _required_value(value: Mapping[str, Any], key: str, prefix: str | None = None) -> Any:
    if key not in value:
        path = f"{prefix}.{key}" if prefix else key
        raise ValueError(f"{path} is required")
    return value[key]


def _time_requirements(
    time_spec: Mapping[str, Any], source_delay_s: float, source_tail_s: float
) -> tuple[float, float]:
    path = _nonnegative_finite(
        _required_value(time_spec, "longest_path_m", "numerics.time"),
        "numerics.time.longest_path_m",
    )
    velocity = _positive_finite(
        _required_value(time_spec, "velocity_mps", "numerics.time"),
        "numerics.time.velocity_mps",
    )
    response = _nonnegative_finite(
        _required_value(time_spec, "response_duration_s", "numerics.time"),
        "numerics.time.response_duration_s",
    )
    guard = _nonnegative_finite(
        _required_value(time_spec, "guard_s", "numerics.time"), "numerics.time.guard_s"
    )
    round_trip = required_round_trip_time(path, velocity)
    return round_trip, source_delay_s + source_tail_s + round_trip + response + guard


def _time_step(ctx: GateContext, numerics: Mapping[str, Any]) -> tuple[float, str]:
    artifact_numerics = ctx.artifacts.get("numerics")
    if isinstance(artifact_numerics, Mapping):
        for key in ("observed_dt_s", "actual_dt_s", "dt_s"):
            if key in artifact_numerics:
                return _positive_finite(artifact_numerics[key], f"artifacts.numerics.{key}"), "observed"
    for key in ("observed_dt_s", "actual_dt_s"):
        if key in ctx.artifacts:
            return _positive_finite(ctx.artifacts[key], f"artifacts.{key}"), "observed"
    return _positive_finite(_required_value(numerics, "dt_s", "numerics"), "numerics.dt_s"), "declared"


def _wavelength_requirement(
    grid_spec: Mapping[str, Any], artifacts: Mapping[str, Any]
) -> float | None:
    requirement = grid_spec.get("cells_per_wavelength_required")
    if requirement is None:
        analytic = artifacts.get("analytic_sanity")
        if isinstance(analytic, Mapping):
            requirement = analytic.get("cells_per_wavelength_required")
            if requirement is None and isinstance(analytic.get("grid"), Mapping):
                requirement = analytic["grid"].get("cells_per_wavelength_required")
    if requirement is None:
        return None
    return _positive_finite(requirement, "cells_per_wavelength_required")


def _undersampled_feature(
    contract: Mapping[str, Any], spacing: tuple[float, float, float]
) -> str | None:
    geometry = contract.get("geometry", {})
    if not isinstance(geometry, Mapping):
        raise ValueError("geometry must be a mapping")
    features = geometry.get("critical_features", [])
    if not isinstance(features, Sequence) or isinstance(features, (str, bytes)):
        raise ValueError("geometry.critical_features must be a sequence")
    for index, feature in enumerate(features):
        if not isinstance(feature, Mapping):
            raise ValueError(f"geometry.critical_features[{index}] must be a mapping")
        required = feature.get("minimum_cells", feature.get("minimum_cell_count"))
        if required is None:
            raise ValueError(f"geometry.critical_features[{index}].minimum_cells is required")
        required_cells = _positive_integer(required, f"critical_features[{index}].minimum_cells")
        observed = feature.get("discretized_cells", feature.get("actual_cells"))
        if observed is None:
            size = _positive_finite(
                _required_value(feature, "size_m", f"geometry.critical_features[{index}]"),
                f"critical_features[{index}].size_m",
            )
            axis = feature.get("axis")
            if axis in ("x", "y", "z"):
                step = spacing[("x", "y", "z").index(axis)]
            elif axis is None:
                step = max(spacing)
            else:
                raise ValueError(f"critical_features[{index}].axis must be x, y, or z")
            observed_cells = max(1, int(round(size / step)))
        else:
            observed_cells = _positive_integer(observed, f"critical_features[{index}].discretized_cells")
        if observed_cells < required_cells:
            name = str(feature.get("name", f"critical feature {index}"))
            return f"{name} uses {observed_cells} cells; declared minimum is {required_cells}"
    return None


def _minimum_declared_clearance(value: object) -> float:
    if isinstance(value, Mapping):
        if not value:
            raise ValueError("numerics.pml.clearance_m must not be empty")
        return min(_nonnegative_finite(item, f"clearance_m.{key}") for key, item in value.items())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if not value:
            raise ValueError("numerics.pml.clearance_m must not be empty")
        return min(_nonnegative_finite(item, "clearance_m") for item in value)
    return _nonnegative_finite(value, "numerics.pml.clearance_m")


def _is_pml_sensitivity(value: object) -> bool:
    if isinstance(value, str):
        return _names_domain_or_pml_sensitivity(value)
    if isinstance(value, Mapping):
        if value.get("required") is False:
            return False
        return any(
            _names_domain_or_pml_sensitivity(str(value.get(key, "")))
            for key in ("id", "name", "kind", "gate", "type")
        )
    return False


def _evidence_passes(value: object) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        if value.get("passed") is True:
            return True
        return str(value.get("state", value.get("status", ""))).upper() == "PASS"
    return False


def _names_domain_or_pml_sensitivity(value: str) -> bool:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return any(term in normalized for term in ("pml", "domain", "boundary"))


def _covering_count(total: float, step: float) -> int:
    ratio = total / step
    nearest = round(ratio)
    if math.isclose(ratio, nearest, rel_tol=1e-12, abs_tol=1e-12):
        return int(nearest)
    return math.ceil(ratio)


def _invalid_gate(gate_id: str, error: Exception) -> GateResult:
    return GateResult(
        gate_id,
        GateState.BLOCK,
        "BLOCK_NUMERICS_INVALID",
        str(error),
        invalidates=("simulation", "claims"),
    )
