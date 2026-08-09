from pathlib import Path
from typing import Any

import pytest

from scripts.audit_geometry import audit_geometry, audit_model_purpose, quantize_length
from scripts.core import GateContext, GateState


def _contract(**overrides: Any) -> dict[str, Any]:
    contract: dict[str, Any] = {
        "task": {"objective": "detection", "claim_scope": "numerical"},
        "model": {"dimension": "2d"},
        "numerics": {"grid": {"spacing_m": [0.05, 0.05, 0.05]}},
        "geometry": {
            "coordinate_system": {"axes": ["x", "z"]},
            "critical_features": [
                {"id": "target", "size_m": 0.83, "axis": "x", "minimum_cells": 2}
            ],
        },
        "model_purpose": {
            "model_id": "symbolic_model_id",
            "purpose": "symbolic_model_purpose",
            "allowed_claims": ["symbolic_allowed_claim"],
            "forbidden_claims": ["symbolic_forbidden_claim"],
        },
    }
    contract.update(overrides)
    return contract


def _validated_geometry() -> dict[str, Any]:
    return {
        "validated": True,
        "coordinate_axes": ["x", "z"],
        "critical_features": {
            "target": {"discretized_cells": 16, "effective_m": 0.8}
        },
    }


def test_quantization_reports_effective_length():
    """Catches truncation or loss of signed representation error in nominal reporting."""
    q = quantize_length(0.83, 0.05)

    assert q.cells == 17
    assert q.effective_m == 0.85
    assert q.error_m == 0.02


@pytest.mark.parametrize(("length_m", "step_m"), [(0.0, 0.05), (-1.0, 0.05), (1.0, 0.0)])
def test_quantization_rejects_nonphysical_inputs(length_m: float, step_m: float):
    """Catches meaningless helper-level quantization of nonphysical dimensions."""
    with pytest.raises(ValueError):
        quantize_length(length_m, step_m)


def test_geometry_blocks_2d_engineering_system_claim(tmp_path: Path):
    """Catches reduced-dimensional propagation being promoted to system certification."""
    contract = {
        "task": {"objective": "system", "claim_scope": "engineering"},
        "model": {"dimension": "2d"},
    }

    result = audit_geometry(GateContext(tmp_path, contract))

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_DIMENSIONALITY_OVERCLAIM"


def test_geometry_blocks_2d_engineering_detection_claim(tmp_path: Path):
    """Catches engineering certification escaping the 2-D barrier via a benign objective."""
    contract = _contract(task={"objective": "detection", "claim_scope": "engineering"})

    result = audit_geometry(GateContext(tmp_path, contract))

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_DIMENSIONALITY_OVERCLAIM"


@pytest.mark.parametrize("claim_scope", ["physcial", "", "   ", None, 7, []])
def test_geometry_blocks_unknown_or_malformed_claim_scope(
    tmp_path: Path, claim_scope: Any
):
    """Catches typoed or malformed scope values falling through as numerical use."""
    contract = _contract(task={"objective": "detection", "claim_scope": claim_scope})

    result = audit_geometry(GateContext(tmp_path, contract))

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_CLAIM_SCOPE"


def test_geometry_allows_validated_2d_numerical_detection(tmp_path: Path):
    """Catches the stricter claim barrier rejecting legitimate reduced-dimensional exploration."""
    result = audit_geometry(
        GateContext(tmp_path, _contract(), artifacts={"geometry": _validated_geometry()})
    )

    assert result.state is GateState.PASS


@pytest.mark.parametrize("objective", ["finite_target", "antenna", "b_scan", "hardware", "system"])
@pytest.mark.parametrize("claim_scope", ["physical", "engineering"])
def test_geometry_blocks_2d_claim_grade_3d_objectives(
    tmp_path: Path, objective: str, claim_scope: str
):
    """Catches any protected 3-D objective escaping the 2-D claim barrier."""
    contract = _contract(
        task={"objective": objective, "claim_scope": claim_scope},
        model={"dimension": "2d"},
    )

    result = audit_geometry(
        GateContext(tmp_path, contract, artifacts={"geometry": _validated_geometry()})
    )

    assert result.code == "BLOCK_DIMENSIONALITY_OVERCLAIM"


def test_geometry_requires_declared_coordinate_axes(tmp_path: Path):
    """Catches geometry accepted without a common coordinate contract."""
    contract = _contract(
        geometry={
            "critical_features": [
                {"id": "target", "size_m": 0.83, "axis": "x", "minimum_cells": 2}
            ]
        }
    )

    result = audit_geometry(GateContext(tmp_path, contract))

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_GEOMETRY_COORDINATES"


def test_geometry_rejects_axes_inconsistent_with_dimension(tmp_path: Path):
    """Catches a nominal 2-D model silently carrying a three-axis geometry contract."""
    contract = _contract()
    contract["geometry"]["coordinate_system"]["axes"] = ["x", "y", "z"]

    result = audit_geometry(GateContext(tmp_path, contract))

    assert result.code == "BLOCK_GEOMETRY_COORDINATES"


def test_geometry_does_not_promote_nominal_rounding_to_discretized_truth(tmp_path: Path):
    """Catches Python rounding being accepted as solver geometry evidence."""
    contract = _contract()
    ctx = GateContext(tmp_path, contract)

    result = audit_geometry(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_GEOMETRY_DISCRETIZATION_EVIDENCE"
    report = ctx.artifacts["derived"]["geometry"]
    assert report["critical_features"][0]["nominal_quantization"] == {
        "nominal_m": 0.83,
        "step_m": 0.05,
        "cells": 17,
        "effective_m": pytest.approx(0.85),
        "error_m": pytest.approx(0.02),
        "classification": "helper_nominal_not_solver_truth",
    }
    assert "validated_effective_geometry" not in report["critical_features"][0]


def test_geometry_uses_validated_effective_truth_and_preserves_input_evidence(tmp_path: Path):
    """Catches replacement of observed geometry evidence by a helper-derived estimate."""
    contract = _contract()
    observed = _validated_geometry()
    artifacts = {"geometry": observed, "derived": {"grid": {"source": "existing"}}}
    ctx = GateContext(tmp_path, contract, artifacts=artifacts)

    result = audit_geometry(ctx)

    assert result.state is GateState.PASS
    assert result.code == "PASS_GEOMETRY"
    assert ctx.artifacts["geometry"] is observed
    assert ctx.artifacts["derived"]["grid"] == {"source": "existing"}
    feature = ctx.artifacts["derived"]["geometry"]["critical_features"][0]
    assert feature["nominal_quantization"]["cells"] == 17
    assert feature["validated_effective_geometry"] == {
        "discretized_cells": 16,
        "effective_m": 0.8,
        "classification": "validated_geometry_evidence",
    }


@pytest.mark.parametrize(
    "records",
    [
        {"target": {"id": "other", "discretized_cells": 16, "effective_m": 0.8}},
        {"target": {"name": "other", "discretized_cells": 16, "effective_m": 0.8}},
        [{"id": "other", "name": "target", "discretized_cells": 16, "effective_m": 0.8}],
        [{"id": "target", "name": "other", "discretized_cells": 16, "effective_m": 0.8}],
    ],
)
def test_geometry_rejects_conflicting_feature_evidence_identity(
    tmp_path: Path, records: Any
):
    """Catches outer-key or loose-intersection matches hiding contradictory identities."""
    observed = _validated_geometry()
    observed["critical_features"] = records

    result = audit_geometry(
        GateContext(tmp_path, _contract(), artifacts={"geometry": observed})
    )

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_GEOMETRY_DISCRETIZATION_EVIDENCE"


def test_geometry_accepts_exact_sequence_feature_identity(tmp_path: Path):
    """Catches strict identity matching accidentally rejecting an exact sequence record."""
    observed = _validated_geometry()
    observed["critical_features"] = [
        {"id": "target", "discretized_cells": 16, "effective_m": 0.8}
    ]

    result = audit_geometry(
        GateContext(tmp_path, _contract(), artifacts={"geometry": observed})
    )

    assert result.state is GateState.PASS


def test_geometry_accepts_consistent_mapping_keyed_by_exact_feature_name(tmp_path: Path):
    """Catches exact name-keyed evidence being lost when a feature also declares an id."""
    contract = _contract()
    contract["geometry"]["critical_features"][0]["name"] = "target display name"
    observed = _validated_geometry()
    observed["critical_features"] = {
        "target display name": {
            "id": "target",
            "name": "target display name",
            "discretized_cells": 16,
            "effective_m": 0.8,
        }
    }

    result = audit_geometry(
        GateContext(tmp_path, contract, artifacts={"geometry": observed})
    )

    assert result.state is GateState.PASS


def test_geometry_blocks_effective_length_inconsistent_with_cells_and_step(tmp_path: Path):
    """Catches contradictory solver-effective length being accepted as validated truth."""
    observed = _validated_geometry()
    observed["critical_features"]["target"]["effective_m"] = 0.81

    result = audit_geometry(
        GateContext(tmp_path, _contract(), artifacts={"geometry": observed})
    )

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_GEOMETRY_DISCRETIZATION_EVIDENCE"


def test_geometry_labels_effective_length_derived_from_validated_cells(tmp_path: Path):
    """Catches a calculated effective length being mislabeled as solver-supplied geometry."""
    observed = _validated_geometry()
    del observed["critical_features"]["target"]["effective_m"]
    ctx = GateContext(tmp_path, _contract(), artifacts={"geometry": observed})

    result = audit_geometry(ctx)

    assert result.state is GateState.PASS
    effective = ctx.artifacts["derived"]["geometry"]["critical_features"][0][
        "validated_effective_geometry"
    ]
    assert effective == {
        "discretized_cells": 16,
        "effective_m": 0.8,
        "classification": "derived_from_validated_cell_count",
    }


@pytest.mark.parametrize(
    "occupancy",
    [
        {"validated": True, "overlaps": ["cell:1,2"], "gaps": []},
        {"validated": True, "overlaps": [], "gaps": ["cell:3,4"]},
        {"validated": False, "overlaps": [], "gaps": []},
    ],
)
def test_geometry_blocks_invalid_material_occupancy_when_manifest_exists(
    tmp_path: Path, occupancy: dict[str, Any]
):
    """Catches overlap, gap, or unvalidated occupancy evidence being ignored."""
    observed = _validated_geometry()
    observed["material_occupancy"] = occupancy

    result = audit_geometry(
        GateContext(tmp_path, _contract(), artifacts={"geometry": observed})
    )

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_GEOMETRY_OCCUPANCY"


def test_geometry_accepts_validated_gap_free_occupancy_manifest(tmp_path: Path):
    """Catches valid occupancy evidence being rejected merely because it is present."""
    observed = _validated_geometry()
    observed["material_occupancy"] = {"validated": True, "overlaps": [], "gaps": []}

    result = audit_geometry(
        GateContext(tmp_path, _contract(), artifacts={"geometry": observed})
    )

    assert result.state is GateState.PASS


@pytest.mark.parametrize(
    "occupancy",
    [
        {"overlaps": [], "gaps": []},
        {"validated": True, "gaps": []},
        {"validated": True, "overlaps": []},
        {"state": "PASS", "overlaps": "none", "gaps": []},
        {"state": "PASS", "overlaps": [], "gaps": -1},
    ],
)
def test_geometry_blocks_incomplete_or_malformed_occupancy_manifest(
    tmp_path: Path, occupancy: dict[str, Any]
):
    """Catches absent or malformed occupancy evidence being defaulted to no defects."""
    observed = _validated_geometry()
    observed["material_occupancy"] = occupancy

    result = audit_geometry(
        GateContext(tmp_path, _contract(), artifacts={"geometry": observed})
    )

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_GEOMETRY_OCCUPANCY"


def test_geometry_accepts_explicit_accepted_occupancy_counts(tmp_path: Path):
    """Catches valid count-form occupancy evidence being rejected as non-list data."""
    observed = _validated_geometry()
    observed["material_occupancy"] = {"state": "ACCEPTED", "overlaps": 0, "gaps": 0}

    result = audit_geometry(
        GateContext(tmp_path, _contract(), artifacts={"geometry": observed})
    )

    assert result.state is GateState.PASS


def test_model_purpose_blocks_empty_allowed_claims(tmp_path: Path):
    """Catches a model entering the registry without a positive claim boundary."""
    contract = _contract()
    contract["model_purpose"]["allowed_claims"] = []

    result = audit_model_purpose(GateContext(tmp_path, contract))

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_MODEL_PURPOSE_UNDECLARED"


@pytest.mark.parametrize(
    "model_purpose",
    [
        {"purpose": "p", "allowed_claims": ["a"], "forbidden_claims": []},
        {"model_id": "m", "allowed_claims": ["a"], "forbidden_claims": []},
        {"model_id": "m", "purpose": ["p"], "allowed_claims": ["a"], "forbidden_claims": []},
        {"model_id": "m", "purpose": "p", "allowed_claims": "a", "forbidden_claims": []},
        {"model_id": "m", "purpose": "p", "allowed_claims": ["a"]},
    ],
)
def test_model_purpose_requires_complete_registry_entry(
    tmp_path: Path, model_purpose: dict[str, Any]
):
    """Catches missing or structurally ambiguous model-purpose boundaries."""
    contract = _contract(model_purpose=model_purpose)

    result = audit_model_purpose(GateContext(tmp_path, contract))

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_MODEL_PURPOSE_UNDECLARED"


def test_model_purpose_publishes_derived_copy_without_overwriting_registry(tmp_path: Path):
    """Catches model-purpose validation mutating input evidence or another derived report."""
    registry = _contract()["model_purpose"]
    ctx = GateContext(
        tmp_path,
        _contract(model_purpose=registry),
        artifacts={"model_purpose": {"source": "input evidence"}, "derived": {"grid": {}}},
    )

    result = audit_model_purpose(ctx)

    assert result.state is GateState.PASS
    assert result.code == "PASS_MODEL_PURPOSE"
    assert ctx.artifacts["model_purpose"] == {"source": "input evidence"}
    assert ctx.artifacts["derived"]["model_purpose"] == registry
    assert ctx.artifacts["derived"]["grid"] == {}
