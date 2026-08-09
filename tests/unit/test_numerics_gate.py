import json
import math
from pathlib import Path

import pytest

from scripts.audit_numerics import (
    audit_cfl,
    audit_grid,
    audit_pml,
    audit_time_window,
    build_analytic_sanity,
    courant_limit,
    estimate_cell_count,
    minimum_wavelength,
    required_round_trip_time,
)
from scripts.core import GateContext, GateState


def test_minimum_wavelength_uses_highest_permittivity():
    """Catches omission of the square-root permittivity velocity reduction."""
    lam = minimum_wavelength(200e6, 4.0)

    assert math.isclose(lam, 0.749481145, rel_tol=1e-12)


def test_courant_limit_for_cubic_grid():
    """Catches a 1-D CFL expression being used for a 3-D cubic grid."""
    dt = courant_limit(0.01, 0.01, 0.01)

    assert math.isclose(dt, 1.9258332015464708e-11, rel_tol=1e-12)


def test_round_trip_time_includes_both_path_legs():
    """Catches reporting one-way propagation as round-trip coverage."""
    assert required_round_trip_time(3.0, 150_000_000.0) == 4.0e-8


def test_cell_count_ceil_covers_each_domain_axis():
    """Catches truncating partially covered cells at a domain boundary."""
    assert estimate_cell_count((1.01, 0.5, 0.02), (0.1, 0.1, 0.01)) == 110


@pytest.mark.parametrize(
    ("fn", "args"),
    [
        (minimum_wavelength, (0.0, 4.0)),
        (minimum_wavelength, (200e6, -1.0)),
        (courant_limit, (0.01, float("nan"), 0.01)),
        (required_round_trip_time, (-1.0, 150_000_000.0)),
        (required_round_trip_time, (1.0, 0.0)),
        (estimate_cell_count, ((1.0, 1.0), (0.1, 0.1, 0.1))),
    ],
)
def test_formula_inputs_fail_deterministically(fn, args):
    """Catches nonphysical inputs leaking into inf, NaN, or meaningless estimates."""
    with pytest.raises(ValueError):
        fn(*args)


def test_grid_blocks_undersampled_precision_feature(tmp_path: Path):
    """Catches acceptance of a one-cell feature that requires two-cell localization."""
    contract = {
        "task": {"objective": "localization"},
        "numerics": {
            "f_max_hz": 200e6,
            "epsilon_r_max": 4.0,
            "grid": {
                "spacing_m": [0.02, 0.02, 0.02],
                "cells_per_wavelength_required": 8.0,
            },
        },
        "geometry": {
            "critical_features": [
                {
                    "name": "target back interface",
                    "size_m": 0.02,
                    "discretized_cells": 1,
                    "minimum_cells": 2,
                    "purpose": "precision_localization",
                }
            ]
        },
    }

    result = audit_grid(GateContext(tmp_path, contract))

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_GEOMETRY_UNDERSAMPLED"


def test_grid_blocks_when_critical_feature_lacks_discretized_truth(tmp_path: Path):
    """Catches inferred Python rounding being accepted as validated geometry truth."""
    contract = {
        "numerics": {
            "f_max_hz": 200e6,
            "epsilon_r_max": 4.0,
            "grid": {
                "spacing_m": [0.02, 0.02, 0.02],
                "cells_per_wavelength_required": 8.0,
            },
        },
        "geometry": {
            "critical_features": [
                {"id": "thin_target", "name": "thin target", "size_m": 0.1, "minimum_cells": 2}
            ]
        },
    }

    result = audit_grid(GateContext(tmp_path, contract))

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_GEOMETRY_DISCRETIZATION_EVIDENCE"


def test_grid_accepts_cells_from_validated_geometry_artifact(tmp_path: Path):
    """Catches rejection of exact discretization evidence published by geometry validation."""
    contract = {
        "numerics": {
            "f_max_hz": 200e6,
            "epsilon_r_max": 4.0,
            "grid": {
                "spacing_m": [0.02, 0.02, 0.02],
                "cells_per_wavelength_required": 8.0,
            },
        },
        "geometry": {
            "critical_features": [
                {"id": "thin_target", "name": "thin target", "minimum_cells": 2}
            ]
        },
    }
    artifacts = {
        "geometry": {
            "validated": True,
            "critical_features": {"thin_target": {"discretized_cells": 5}},
        }
    }

    result = audit_grid(GateContext(tmp_path, contract, artifacts=artifacts))

    assert result.state is GateState.PASS
    assert result.code == "PASS_GRID_RESOLVED"


def test_grid_does_not_invent_a_universal_wavelength_requirement(tmp_path: Path):
    """Catches silently hard-coding lambda/10 when the contract declares no threshold."""
    contract = {
        "numerics": {
            "f_max_hz": 200e6,
            "epsilon_r_max": 4.0,
            "grid": {"spacing_m": [0.02, 0.02, 0.02]},
        }
    }

    result = audit_grid(GateContext(tmp_path, contract))

    assert result.state is GateState.PASS_WITH_LIMITATION
    assert result.code == "LIMIT_GRID_REQUIREMENT_UNDECLARED"


def test_cfl_uses_observed_dt_when_available(tmp_path: Path):
    """Catches a safe declared step masking an unsafe observed solver step."""
    contract = {
        "numerics": {
            "grid": {"spacing_m": [0.01, 0.01, 0.01]},
            "dt_s": 1.0e-11,
        }
    }
    ctx = GateContext(tmp_path, contract, artifacts={"numerics": {"observed_dt_s": 2.0e-11}})

    result = audit_cfl(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_CFL_VIOLATION"


def test_time_window_blocks_target_back_interface_truncation(tmp_path: Path):
    """Catches a window that omits source support and the deepest two-way path."""
    contract = {
        "waveform": {"source_delay_s": 5e-9, "source_tail_s": 10e-9},
        "numerics": {
            "time": {
                "longest_path_m": 3.0,
                "velocity_mps": 150_000_000.0,
                "response_duration_s": 10e-9,
                "guard_s": 5e-9,
                "simulation_time_s": 69e-9,
            }
        },
    }

    ctx = GateContext(tmp_path, contract)

    result = audit_time_window(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_TIME_WINDOW_TRUNCATION_RISK"
    assert ctx.artifacts["derived"]["time_window"]["required_time_window_s"] == 70e-9


def test_pml_sensitivity_is_not_required_without_acceptance_declaration(tmp_path: Path):
    """Catches an invented mandatory PML sensitivity study."""
    contract = {
        "numerics": {"pml": {"clearance_m": 0.3, "minimum_clearance_m": 0.2}},
        "acceptance": {"sensitivity_tests": []},
    }

    result = audit_pml(GateContext(tmp_path, contract))

    assert result.state is GateState.PASS
    assert result.code == "PASS_PML_CLEARANCE"


def test_pml_sensitivity_blocks_only_when_explicitly_required(tmp_path: Path):
    """Catches skipping a PML sensitivity study named by acceptance."""
    contract = {
        "numerics": {"pml": {"clearance_m": 0.3, "minimum_clearance_m": 0.2}},
        "acceptance": {"sensitivity_tests": ["pml"]},
    }

    result = audit_pml(GateContext(tmp_path, contract))

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_PML_SENSITIVITY_REQUIRED"


def test_domain_sensitivity_name_explicitly_requires_pml_evidence(tmp_path: Path):
    """Catches overlooking an explicitly named domain-boundary sensitivity test."""
    contract = {
        "numerics": {"pml": {"clearance_m": 0.3, "minimum_clearance_m": 0.2}},
        "acceptance": {"sensitivity_tests": [{"name": "domain boundary"}]},
    }

    result = audit_pml(GateContext(tmp_path, contract))

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_PML_SENSITIVITY_REQUIRED"


@pytest.mark.parametrize("identifier", ["frequency_domain_response", "subdomain_decomposition"])
def test_unrelated_sensitivity_near_match_does_not_require_pml_evidence(
    tmp_path: Path, identifier: str
):
    """Catches substring matching that turns unrelated sensitivity IDs into PML requirements."""
    contract = {
        "numerics": {"pml": {"clearance_m": 0.3, "minimum_clearance_m": 0.2}},
        "acceptance": {"sensitivity_tests": [identifier]},
    }

    result = audit_pml(GateContext(tmp_path, contract))

    assert result.state is GateState.PASS
    assert result.code == "PASS_PML_CLEARANCE"


@pytest.mark.parametrize(
    "requirement",
    ["pml", "PML sensitivity", {"gate_id": "pml", "required": True}],
)
def test_exact_normalized_pml_identifiers_require_evidence(tmp_path: Path, requirement):
    """Catches loss of explicit PML requirements while avoiding fuzzy substring matching."""
    contract = {
        "numerics": {"pml": {"clearance_m": 0.3, "minimum_clearance_m": 0.2}},
        "acceptance": {"sensitivity_tests": [requirement]},
    }

    result = audit_pml(GateContext(tmp_path, contract))

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_PML_SENSITIVITY_REQUIRED"


def test_analytic_sanity_uses_only_declared_assumptions_and_writes_f0(tmp_path: Path):
    """Catches hidden solver constants in the F0 memory and compute estimate."""
    contract = {
        "waveform": {"source_delay_s": 2e-9, "source_tail_s": 3e-9},
        "numerics": {
            "f_max_hz": 100e6,
            "epsilon_r_max": 4.0,
            "domain_m": [1.0, 0.5, 0.02],
            "grid": {"spacing_m": [0.1, 0.1, 0.01]},
            "dt_s": 1e-11,
            "time": {
                "longest_path_m": 3.0,
                "velocity_mps": 150_000_000.0,
                "response_duration_s": 4e-9,
                "guard_s": 5e-9,
            },
            "compute_assumptions": {
                "bytes_per_cell": 64,
                "operations_per_cell_update": 30,
            },
        },
    }
    ctx = GateContext(tmp_path, contract)

    report = build_analytic_sanity(ctx)

    assert report == {
        "fidelity_level": "F0",
        "minimum_wavelength_m": 1.49896229,
        "courant_limit_s": 3.302776692856877e-11,
        "maximum_round_trip_time_s": 4e-8,
        "required_time_window_s": 5.4e-8,
        "estimated_cell_count": 100,
        "time_step_s": 1e-11,
        "estimated_time_steps": 5400,
        "memory_estimate": {
            "estimated_bytes": 6400,
            "assumed_bytes_per_cell": 64,
            "classification": "contract_assumption_not_solver_truth",
        },
        "compute_estimate": {
            "estimated_operations": 16_200_000,
            "assumed_operations_per_cell_update": 30,
            "classification": "contract_assumption_not_solver_truth",
        },
    }
    assert ctx.artifacts["derived"]["analytic_sanity"] == report
    assert json.loads((tmp_path / "artifacts" / "analytic_sanity.json").read_text(encoding="utf-8")) == report


def test_analytic_sanity_rejects_missing_compute_assumptions_without_writing(tmp_path: Path):
    """Catches a report that quietly substitutes an undeclared memory coefficient."""
    contract = {
        "waveform": {"source_delay_s": 0.0, "source_tail_s": 0.0},
        "numerics": {
            "f_max_hz": 100e6,
            "epsilon_r_max": 4.0,
            "domain_m": [1.0, 1.0, 0.01],
            "grid": {"spacing_m": [0.1, 0.1, 0.01]},
            "dt_s": 1e-11,
            "time": {
                "longest_path_m": 1.0,
                "velocity_mps": 150_000_000.0,
                "response_duration_s": 0.0,
                "guard_s": 0.0,
            },
        },
    }
    ctx = GateContext(tmp_path, contract)

    with pytest.raises(ValueError, match="compute_assumptions"):
        build_analytic_sanity(ctx)

    assert "analytic_sanity" not in ctx.artifacts
    assert not (tmp_path / "artifacts" / "analytic_sanity.json").exists()


def test_analytic_sanity_uses_observed_dt_for_compute_estimate(tmp_path: Path):
    """Catches an observed solver step being ignored in favor of a stale declaration."""
    contract = {
        "waveform": {"source_delay_s": 0.0, "source_tail_s": 0.0},
        "numerics": {
            "f_max_hz": 100e6,
            "epsilon_r_max": 4.0,
            "domain_m": [1.0, 1.0, 0.01],
            "grid": {"spacing_m": [0.1, 0.1, 0.01]},
            "dt_s": 1e-11,
            "time": {
                "longest_path_m": 1.5,
                "velocity_mps": 150_000_000.0,
                "response_duration_s": 0.0,
                "guard_s": 0.0,
            },
            "compute_assumptions": {
                "bytes_per_cell": 8,
                "operations_per_cell_update": 2,
            },
        },
    }
    ctx = GateContext(tmp_path, contract, artifacts={"numerics": {"observed_dt_s": 2e-11}})

    report = build_analytic_sanity(ctx)

    assert report["time_step_s"] == 2e-11
    assert report["estimated_time_steps"] == 1000
    assert report["compute_estimate"]["estimated_operations"] == 200_000


def test_analytic_sanity_publishes_derived_state_only_after_persisting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Catches in-memory publication of an F0 report before durable persistence succeeds."""
    from scripts.core import write_json as real_write_json

    contract = {
        "waveform": {"source_delay_s": 0.0, "source_tail_s": 0.0},
        "numerics": {
            "f_max_hz": 100e6,
            "epsilon_r_max": 4.0,
            "domain_m": [1.0, 1.0, 0.01],
            "grid": {"spacing_m": [0.1, 0.1, 0.01]},
            "dt_s": 1e-11,
            "time": {
                "longest_path_m": 1.5,
                "velocity_mps": 150_000_000.0,
                "response_duration_s": 0.0,
                "guard_s": 0.0,
            },
            "compute_assumptions": {
                "bytes_per_cell": 8,
                "operations_per_cell_update": 2,
            },
        },
    }
    ctx = GateContext(tmp_path, contract, artifacts={"analytic_sanity": {"solver": "evidence"}})
    published_during_write = []

    def observe_write(path, value):
        published_during_write.append("derived" in ctx.artifacts)
        real_write_json(path, value)

    monkeypatch.setattr("scripts.audit_numerics.write_json", observe_write)

    report = build_analytic_sanity(ctx)

    assert published_during_write == [False]
    assert ctx.artifacts["analytic_sanity"] == {"solver": "evidence"}
    assert ctx.artifacts["derived"]["analytic_sanity"] == report


def test_analytic_sanity_does_not_publish_when_persistence_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Catches failed artifact writes leaving a derived report available in memory."""
    contract = {
        "waveform": {"source_delay_s": 0.0, "source_tail_s": 0.0},
        "numerics": {
            "f_max_hz": 100e6,
            "epsilon_r_max": 4.0,
            "domain_m": [1.0, 1.0, 0.01],
            "grid": {"spacing_m": [0.1, 0.1, 0.01]},
            "dt_s": 1e-11,
            "time": {
                "longest_path_m": 1.5,
                "velocity_mps": 150_000_000.0,
                "response_duration_s": 0.0,
                "guard_s": 0.0,
            },
            "compute_assumptions": {
                "bytes_per_cell": 8,
                "operations_per_cell_update": 2,
            },
        },
    }
    ctx = GateContext(tmp_path, contract, artifacts={"keep": "input evidence"})

    def fail_write(_path, _value):
        raise OSError("disk full")

    monkeypatch.setattr("scripts.audit_numerics.write_json", fail_write)

    with pytest.raises(OSError, match="disk full"):
        build_analytic_sanity(ctx)

    assert ctx.artifacts == {"keep": "input evidence"}


@pytest.mark.parametrize("gate", [audit_grid, audit_cfl, audit_time_window, audit_pml])
def test_gate_derived_outputs_preserve_preexisting_input_artifacts(tmp_path: Path, gate):
    """Catches numerical gates overwriting top-level solver or validation evidence."""
    contract = {
        "waveform": {"source_delay_s": 0.0, "source_tail_s": 0.0},
        "numerics": {
            "f_max_hz": 100e6,
            "epsilon_r_max": 4.0,
            "grid": {
                "spacing_m": [0.1, 0.1, 0.01],
                "cells_per_wavelength_required": 2.0,
            },
            "dt_s": 1e-11,
            "time": {
                "longest_path_m": 1.5,
                "velocity_mps": 150_000_000.0,
                "response_duration_s": 0.0,
                "guard_s": 0.0,
                "simulation_time_s": 30e-9,
            },
            "pml": {"clearance_m": 0.3, "minimum_clearance_m": 0.2},
        },
        "acceptance": {"sensitivity_tests": []},
    }
    sentinels = {
        "grid": {"solver": "grid evidence"},
        "cfl": {"solver": "cfl evidence"},
        "time_window": {"solver": "time evidence"},
        "pml": {"solver": "pml evidence"},
    }
    ctx = GateContext(tmp_path, contract, artifacts=dict(sentinels))

    gate(ctx)

    for key, expected in sentinels.items():
        assert ctx.artifacts[key] == expected
    assert gate.__name__.removeprefix("audit_") in ctx.artifacts["derived"]
