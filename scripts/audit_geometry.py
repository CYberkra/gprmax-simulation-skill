from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal
import math
from numbers import Real
from typing import Any

from scripts.core import GateContext, GateResult, GateState


_AXES = frozenset({"x", "y", "z"})
_EFFECTIVE_LENGTH_REL_TOL = 1e-9
_EFFECTIVE_LENGTH_ABS_TOL_M = 1e-12
_THREE_DIMENSIONAL_OBJECTIVES = frozenset(
    {"finite_target", "antenna", "b_scan", "bscan", "hardware", "system"}
)
_SUPPORTED_CLAIM_SCOPES = frozenset({"numerical", "physical", "engineering"})


@dataclass(frozen=True)
class GeometryQuantization:
    nominal_m: float
    step_m: float
    cells: int
    effective_m: float
    error_m: float


class _GeometryAuditError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def quantize_length(length_m: float, step_m: float) -> GeometryQuantization:
    """Report helper-level nearest-cell quantization of a nominal length.

    This arithmetic is not gprMax discretized geometry evidence. Consumers
    must use validated occupancy or geometry artifacts for acceptance.
    """
    nominal = _positive_finite(length_m, "length_m")
    step = _positive_finite(step_m, "step_m")
    cells = max(1, int(round(nominal / step)))
    effective_decimal = Decimal(cells) * Decimal(str(step))
    error_decimal = effective_decimal - Decimal(str(nominal))
    return GeometryQuantization(
        nominal,
        step,
        cells,
        float(effective_decimal),
        float(error_decimal),
    )


def audit_geometry(ctx: GateContext) -> GateResult:
    """Audit coordinate, dimensionality, and validated discretized geometry truth."""
    report: dict[str, Any] = {
        "critical_features": [],
        "effective_length_consistency_tolerance": {
            "relative": _EFFECTIVE_LENGTH_REL_TOL,
            "absolute_m": _EFFECTIVE_LENGTH_ABS_TOL_M,
        },
    }
    try:
        dimension = _dimension(ctx.contract)
        task = _mapping(ctx.contract.get("task"), "task")
        objective = _required_text(task, "objective", "task").lower().replace("-", "_")
        claim_scope = _claim_scope(task)
        report["dimension"] = dimension
        if (
            dimension == "2d"
            and (
                claim_scope == "engineering"
                or (
                    claim_scope == "physical"
                    and objective in _THREE_DIMENSIONAL_OBJECTIVES
                )
            )
        ):
            _publish_derived(ctx, "geometry", report)
            return _geometry_result(
                GateState.BLOCK,
                "BLOCK_DIMENSIONALITY_OVERCLAIM",
                f"2-D geometry cannot certify {claim_scope} {objective} claims",
            )

        axes = _coordinate_axes(ctx.contract, dimension)
        report["coordinate_axes"] = list(axes)
        _check_observed_axes(ctx.artifacts, axes)
        spacing = _grid_spacing(ctx.contract)
        observed_geometry = _validated_geometry(ctx.artifacts)
        features = _critical_features(ctx.contract)
        for index, feature in enumerate(features):
            item = _feature_report(feature, index, axes, spacing, observed_geometry)
            report["critical_features"].append(item)
            if "validated_effective_geometry" not in item:
                _publish_derived(ctx, "geometry", report)
                name = item["id"]
                return _geometry_result(
                    GateState.BLOCK,
                    "BLOCK_GEOMETRY_DISCRETIZATION_EVIDENCE",
                    f"critical feature {name} lacks validated discretized geometry evidence",
                )
            observed_cells = item["validated_effective_geometry"]["discretized_cells"]
            if observed_cells < item["minimum_cells"]:
                _publish_derived(ctx, "geometry", report)
                return _geometry_result(
                    GateState.BLOCK,
                    "BLOCK_GEOMETRY_UNDERSAMPLED",
                    f"critical feature {item['id']} has {observed_cells} validated cells; "
                    f"minimum is {item['minimum_cells']}",
                )

        occupancy = _occupancy_report(ctx.artifacts)
        if occupancy is not None:
            report["material_occupancy"] = occupancy
            if not occupancy["validated"] or occupancy["overlap_count"] or occupancy["gap_count"]:
                _publish_derived(ctx, "geometry", report)
                return _geometry_result(
                    GateState.BLOCK,
                    "BLOCK_GEOMETRY_OCCUPANCY",
                    "material occupancy evidence is unvalidated or contains overlaps/gaps",
                )
        _publish_derived(ctx, "geometry", report)
    except _GeometryAuditError as error:
        return _geometry_result(GateState.BLOCK, error.code, str(error))
    except (TypeError, ValueError) as error:
        return _geometry_result(GateState.BLOCK, "BLOCK_GEOMETRY_INVALID", str(error))

    return _geometry_result(
        GateState.PASS,
        "PASS_GEOMETRY",
        "coordinate, dimensionality, and validated geometry checks pass",
    )


def audit_model_purpose(ctx: GateContext) -> GateResult:
    """Require an explicit, bounded model-purpose registry entry."""
    try:
        entry = _mapping(ctx.contract.get("model_purpose"), "model_purpose")
        normalized = {
            "model_id": _required_text(entry, "model_id", "model_purpose"),
            "purpose": _required_text(entry, "purpose", "model_purpose"),
            "allowed_claims": _text_list(entry.get("allowed_claims"), "allowed_claims", nonempty=True),
            "forbidden_claims": _text_list(
                entry.get("forbidden_claims"), "forbidden_claims", nonempty=False
            ),
        }
        _publish_derived(ctx, "model_purpose", normalized)
    except (KeyError, TypeError, ValueError, _GeometryAuditError) as error:
        return GateResult(
            "model_purpose",
            GateState.BLOCK,
            "BLOCK_MODEL_PURPOSE_UNDECLARED",
            str(error),
            invalidates=("simulation", "claims"),
        )
    return GateResult(
        "model_purpose",
        GateState.PASS,
        "PASS_MODEL_PURPOSE",
        "model purpose and claim boundaries are declared",
        invalidates=("simulation", "claims"),
    )


def _dimension(contract: Mapping[str, Any]) -> str:
    model = _mapping(contract.get("model"), "model")
    dimension = _required_text(model, "dimension", "model").lower()
    if dimension not in {"2d", "3d"}:
        raise _GeometryAuditError(
            "BLOCK_GEOMETRY_DIMENSION", "model.dimension must be '2d' or '3d'"
        )
    return dimension


def _claim_scope(task: Mapping[str, Any]) -> str:
    raw = task.get("claim_scope")
    if not isinstance(raw, str) or not raw.strip():
        raise _GeometryAuditError(
            "BLOCK_CLAIM_SCOPE", "task.claim_scope must be a supported non-empty string"
        )
    scope = raw.strip().lower()
    if scope not in _SUPPORTED_CLAIM_SCOPES:
        raise _GeometryAuditError(
            "BLOCK_CLAIM_SCOPE", f"task.claim_scope {scope!r} is not supported"
        )
    return scope


def _coordinate_axes(contract: Mapping[str, Any], dimension: str) -> tuple[str, ...]:
    geometry = _mapping(contract.get("geometry"), "geometry")
    coordinate = geometry.get("coordinate_system")
    if isinstance(coordinate, Mapping):
        raw = coordinate.get("axes")
    else:
        raw = geometry.get("coordinate_axes")
    if not _is_sequence(raw):
        raise _GeometryAuditError(
            "BLOCK_GEOMETRY_COORDINATES", "geometry must declare coordinate axes"
        )
    axes = tuple(str(axis).strip().lower() for axis in raw)
    expected_count = 2 if dimension == "2d" else 3
    if (
        len(axes) != expected_count
        or len(set(axes)) != len(axes)
        or any(axis not in _AXES for axis in axes)
    ):
        raise _GeometryAuditError(
            "BLOCK_GEOMETRY_COORDINATES",
            f"{dimension} geometry must declare {expected_count} distinct x/y/z axes",
        )
    return axes


def _check_observed_axes(artifacts: Mapping[str, Any], declared: tuple[str, ...]) -> None:
    geometry = artifacts.get("geometry")
    if not isinstance(geometry, Mapping) or "coordinate_axes" not in geometry:
        return
    raw = geometry["coordinate_axes"]
    if not _is_sequence(raw):
        raise _GeometryAuditError(
            "BLOCK_GEOMETRY_COORDINATES", "artifacts.geometry.coordinate_axes is malformed"
        )
    observed = tuple(str(axis).strip().lower() for axis in raw)
    if observed != declared:
        raise _GeometryAuditError(
            "BLOCK_GEOMETRY_COORDINATES",
            "validated geometry axes do not match the declared coordinate axes",
        )


def _grid_spacing(contract: Mapping[str, Any]) -> dict[str, float]:
    numerics = _mapping(contract.get("numerics"), "numerics")
    grid = _mapping(numerics.get("grid"), "numerics.grid")
    raw = grid.get("spacing_m")
    if isinstance(raw, Mapping):
        if any(axis not in raw for axis in _AXES):
            raise _GeometryAuditError(
                "BLOCK_GEOMETRY_INVALID", "numerics.grid.spacing_m must contain x, y, and z"
            )
        return {axis: _positive_finite(raw[axis], f"spacing_m.{axis}") for axis in _AXES}
    if _is_sequence(raw) and len(raw) == 3:
        return {
            axis: _positive_finite(value, f"spacing_m.{axis}")
            for axis, value in zip(("x", "y", "z"), raw, strict=True)
        }
    if all(key in grid for key in ("dx_m", "dy_m", "dz_m")):
        return {
            axis: _positive_finite(grid[f"d{axis}_m"], f"d{axis}_m") for axis in _AXES
        }
    raise _GeometryAuditError(
        "BLOCK_GEOMETRY_INVALID", "numerics.grid must declare three-axis spacing"
    )


def _critical_features(contract: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    geometry = _mapping(contract.get("geometry"), "geometry")
    raw = geometry.get("critical_features")
    if not _is_sequence(raw) or not raw:
        raise _GeometryAuditError(
            "BLOCK_GEOMETRY_DISCRETIZATION_EVIDENCE",
            "geometry.critical_features must be a non-empty sequence",
        )
    if any(not isinstance(item, Mapping) for item in raw):
        raise _GeometryAuditError(
            "BLOCK_GEOMETRY_INVALID", "each critical feature must be a mapping"
        )
    return tuple(raw)  # type: ignore[return-value]


def _feature_report(
    feature: Mapping[str, Any],
    index: int,
    axes: tuple[str, ...],
    spacing: Mapping[str, float],
    observed_geometry: Mapping[str, Any] | None,
) -> dict[str, Any]:
    identity_value = feature.get("id", feature.get("name"))
    if not isinstance(identity_value, str) or not identity_value.strip():
        raise _GeometryAuditError(
            "BLOCK_GEOMETRY_INVALID", f"critical_features[{index}] requires id or name"
        )
    identity = identity_value.strip()
    axis = _required_text(feature, "axis", f"critical_features[{index}]").lower()
    if axis not in axes:
        raise _GeometryAuditError(
            "BLOCK_GEOMETRY_COORDINATES",
            f"critical feature {identity} axis {axis!r} is not a declared coordinate axis",
        )
    nominal_m = _positive_finite(feature.get("size_m"), f"critical_features[{index}].size_m")
    minimum_cells = _positive_integer(
        feature.get("minimum_cells", feature.get("minimum_cell_count")),
        f"critical_features[{index}].minimum_cells",
    )
    quantization = asdict(quantize_length(nominal_m, spacing[axis]))
    quantization["classification"] = "helper_nominal_not_solver_truth"
    report: dict[str, Any] = {
        "id": identity,
        "axis": axis,
        "minimum_cells": minimum_cells,
        "nominal_quantization": quantization,
    }
    record = _observed_feature(observed_geometry, feature)
    if record is not None:
        cells = _positive_integer(record.get("discretized_cells"), "discretized_cells")
        expected_effective = _cell_length(cells, spacing[axis])
        if "effective_m" in record:
            effective = _positive_finite(record["effective_m"], "effective_m")
            if not math.isclose(
                effective,
                expected_effective,
                rel_tol=_EFFECTIVE_LENGTH_REL_TOL,
                abs_tol=_EFFECTIVE_LENGTH_ABS_TOL_M,
            ):
                raise _GeometryAuditError(
                    "BLOCK_GEOMETRY_DISCRETIZATION_EVIDENCE",
                    f"critical feature {identity} effective_m is inconsistent with "
                    "discretized_cells * step_m",
                )
            classification = "validated_geometry_evidence"
        else:
            effective = expected_effective
            classification = "derived_from_validated_cell_count"
        report["validated_effective_geometry"] = {
            "discretized_cells": cells,
            "effective_m": effective,
            "classification": classification,
        }
    return report


def _validated_geometry(artifacts: Mapping[str, Any]) -> Mapping[str, Any] | None:
    geometry = artifacts.get("geometry")
    if not isinstance(geometry, Mapping):
        return None
    validated = geometry.get("validated") is True or str(geometry.get("state", "")).upper() == "PASS"
    return geometry if validated else None


def _observed_feature(
    geometry: Mapping[str, Any] | None, feature: Mapping[str, Any]
) -> Mapping[str, Any] | None:
    if geometry is None:
        return None
    records = geometry.get("critical_features")
    expected = _feature_identities(feature)
    primary_key = "id" if "id" in expected else "name"
    primary_value = expected[primary_key]
    if isinstance(records, Mapping):
        for key in ("id", "name"):
            if key not in expected:
                continue
            record = records.get(expected[key])
            if not isinstance(record, Mapping):
                continue
            if _record_identity_is_consistent(record, expected):
                return record
            return None
    elif _is_sequence(records):
        for record in records:
            if not isinstance(record, Mapping):
                continue
            raw_primary = record.get(primary_key)
            if not isinstance(raw_primary, str) or raw_primary.strip() != primary_value:
                continue
            if _record_identity_is_consistent(record, expected):
                return record
            return None
    return None


def _feature_identities(feature: Mapping[str, Any]) -> dict[str, str]:
    return {
        key: str(feature[key]).strip()
        for key in ("id", "name")
        if key in feature and isinstance(feature[key], str) and str(feature[key]).strip()
    }


def _record_identity_is_consistent(
    record: Mapping[str, Any], expected: Mapping[str, str]
) -> bool:
    for key in ("id", "name"):
        if key not in record:
            continue
        value = record[key]
        if (
            not isinstance(value, str)
            or key not in expected
            or value.strip() != expected[key]
        ):
            return False
    return True


def _occupancy_report(artifacts: Mapping[str, Any]) -> dict[str, Any] | None:
    geometry = artifacts.get("geometry")
    if not isinstance(geometry, Mapping) or "material_occupancy" not in geometry:
        return None
    occupancy = geometry["material_occupancy"]
    if not isinstance(occupancy, Mapping):
        raise _GeometryAuditError(
            "BLOCK_GEOMETRY_OCCUPANCY", "material occupancy manifest must be a mapping"
        )
    validation_states: list[bool] = []
    if "validated" in occupancy:
        if not isinstance(occupancy["validated"], bool):
            raise _GeometryAuditError(
                "BLOCK_GEOMETRY_OCCUPANCY", "occupancy validated must be boolean"
            )
        validation_states.append(occupancy["validated"])
    for key in ("state", "status"):
        if key in occupancy:
            value = occupancy[key]
            if not isinstance(value, str) or not value.strip():
                raise _GeometryAuditError(
                    "BLOCK_GEOMETRY_OCCUPANCY", f"occupancy {key} must be non-empty text"
                )
            validation_states.append(value.strip().upper() in {"PASS", "ACCEPTED"})
    if not validation_states:
        raise _GeometryAuditError(
            "BLOCK_GEOMETRY_OCCUPANCY",
            "occupancy manifest must explicitly declare validated or an accepted state",
        )
    if "overlaps" not in occupancy or "gaps" not in occupancy:
        raise _GeometryAuditError(
            "BLOCK_GEOMETRY_OCCUPANCY",
            "occupancy manifest must explicitly declare overlaps and gaps",
        )
    return {
        "validated": all(validation_states),
        "overlap_count": _occupancy_count(occupancy["overlaps"], "overlaps"),
        "gap_count": _occupancy_count(occupancy["gaps"], "gaps"),
        "classification": "validated_material_occupancy_evidence",
    }


def _occupancy_count(value: object, name: str) -> int:
    if _is_sequence(value):
        return len(value)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    raise _GeometryAuditError(
        "BLOCK_GEOMETRY_OCCUPANCY",
        f"occupancy {name} must be a list or non-negative integer count",
    )


def _text_list(value: object, name: str, *, nonempty: bool) -> list[str]:
    if not _is_sequence(value) or (nonempty and not value):
        qualifier = "non-empty " if nonempty else ""
        raise ValueError(f"model_purpose.{name} must be an explicit {qualifier}list")
    normalized: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"model_purpose.{name}[{index}] must be non-empty text")
        normalized.append(item.strip())
    return normalized


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    return value


def _required_text(value: Mapping[str, Any], key: str, prefix: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{prefix}.{key} must be non-empty text")
    return raw.strip()


def _positive_integer(value: object, name: str) -> int:
    number = _positive_finite(value, name)
    if not number.is_integer():
        raise ValueError(f"{name} must be a positive integer")
    return int(number)


def _cell_length(cells: int, step_m: float) -> float:
    return float(Decimal(cells) * Decimal(str(step_m)))


def _positive_finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite positive number")
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(f"{name} must be a finite positive number")
    return number


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def _publish_derived(ctx: GateContext, key: str, value: Mapping[str, Any]) -> None:
    derived = ctx.artifacts.get("derived")
    if derived is not None and not isinstance(derived, dict):
        raise ValueError("artifacts.derived must be a mutable mapping")
    namespace = ctx.artifacts.setdefault("derived", {})
    namespace[key] = dict(value)


def _geometry_result(state: GateState, code: str, summary: str) -> GateResult:
    return GateResult(
        "geometry",
        state,
        code,
        summary,
        invalidates=("model_purpose", "simulation", "claims"),
    )
