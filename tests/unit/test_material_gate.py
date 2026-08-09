from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from scripts.audit_materials import audit_materials, complex_permittivity_debye
from scripts.core import GateContext, GateState


def _material(**overrides: Any) -> dict[str, Any]:
    material = {
        "name": "generic dielectric",
        "model": "nondispersive",
        "epsilon_r": 4.0,
        "sigma_s_m": 0.0,
        "provenance": "measured",
    }
    material.update(overrides)
    return material


def _contract(material: dict[str, Any], *, claim_scope: Any = "physical") -> dict[str, Any]:
    return {"task": {"claim_scope": claim_scope}, "materials": [material]}


def _contains_array(value: Any) -> bool:
    if isinstance(value, np.ndarray):
        return True
    if isinstance(value, dict):
        return any(_contains_array(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_array(item) for item in value)
    return False


def test_debye_uses_exp_positive_jwt_passive_loss_sign():
    """Catches a conjugated Debye denominator under the documented phasor convention."""
    frequency = np.array([1.0 / (2.0 * math.pi * 1e-9)])

    epsilon = complex_permittivity_debye(frequency, 3.0, 1.0, 1e-9, 0.0)

    assert epsilon[0].real == pytest.approx(3.5, rel=1e-12)
    assert epsilon[0].imag == pytest.approx(-0.5, rel=1e-12)


def test_debye_conductivity_adds_negative_imaginary_loss():
    """Catches omission or sign reversal of conduction loss in complex permittivity."""
    epsilon = complex_permittivity_debye(np.array([100e6]), 3.0, 0.0, 1e-9, 1e-3)

    assert epsilon[0].real == pytest.approx(3.0, rel=1e-12)
    assert epsilon[0].imag == pytest.approx(-0.1797510357, rel=1e-9)
    assert np.isfinite(epsilon.real).all()
    assert np.isfinite(epsilon.imag).all()


@pytest.mark.parametrize(
    ("frequency", "epsilon_inf", "delta_epsilon", "tau_s", "sigma_s_m"),
    [
        ([0.0], 3.0, 1.0, 1e-9, 0.0),
        ([float("nan")], 3.0, 1.0, 1e-9, 0.0),
        ([1e8], 0.0, 1.0, 1e-9, 0.0),
        ([1e8], 3.0, -1.0, 1e-9, 0.0),
        ([1e8], 3.0, 1.0, 0.0, 0.0),
        ([1e8], 3.0, 1.0, 1e-9, -1e-3),
    ],
)
def test_debye_rejects_nonfinite_or_nonpassive_parameters(
    frequency: list[float],
    epsilon_inf: float,
    delta_epsilon: float,
    tau_s: float,
    sigma_s_m: float,
):
    """Catches acceptance of singular, active, or non-finite one-pole material inputs."""
    with pytest.raises(ValueError):
        complex_permittivity_debye(
            np.asarray(frequency), epsilon_inf, delta_epsilon, tau_s, sigma_s_m
        )


def test_unknown_parameter_provenance_blocks_physical_claim(tmp_path: Path):
    """Catches physical sign-off of otherwise numeric material values with no provenance."""
    contract = {
        "task": {"claim_scope": "physical"},
        "materials": [
            {"name": "m", "model": "nondispersive", "epsilon_r": 4.0, "sigma_s_m": 0.0}
        ],
    }

    result = audit_materials(GateContext(tmp_path, contract))

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_MATERIAL_PROVENANCE"


@pytest.mark.parametrize("provenance", ["", "unknown", "site_measured"])
def test_blank_or_unknown_provenance_class_blocks(tmp_path: Path, provenance: str):
    """Catches provenance labels outside the finite audited vocabulary."""
    result = audit_materials(
        GateContext(tmp_path, _contract(_material(provenance=provenance)))
    )

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_MATERIAL_PROVENANCE"


@pytest.mark.parametrize("provenance", ["assumed", "sensitivity_only"])
@pytest.mark.parametrize("claim_scope", ["physical", "engineering"])
def test_weak_provenance_limits_physical_or_engineering_claims(
    tmp_path: Path, provenance: str, claim_scope: str
):
    """Catches promotion of assumed or sensitivity-only parameters to claim-grade evidence."""
    result = audit_materials(
        GateContext(tmp_path, _contract(_material(provenance=provenance), claim_scope=claim_scope))
    )

    assert result.state is GateState.PASS_WITH_LIMITATION
    assert result.code == "LIMIT_MATERIAL_PROVENANCE"


def test_assumed_material_can_support_only_numerical_scope(tmp_path: Path):
    """Catches an over-broad limitation that rejects explicitly numerical exploration."""
    result = audit_materials(
        GateContext(tmp_path, _contract(_material(provenance="assumed"), claim_scope="numerical"))
    )

    assert result.state is GateState.PASS
    assert result.code == "PASS_MATERIALS"


@pytest.mark.parametrize("claim_scope", ["physcial", "exploratory", "", "   ", None, 7, []])
def test_unknown_or_malformed_claim_scope_blocks_fail_closed(
    tmp_path: Path, claim_scope: Any
):
    """Catches typoed or malformed scopes falling through as if they were numerical."""
    result = audit_materials(
        GateContext(
            tmp_path,
            _contract(_material(provenance="assumed"), claim_scope=claim_scope),
        )
    )

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_CLAIM_SCOPE"


@pytest.mark.parametrize(
    ("claim_scope", "expected_state", "expected_code"),
    [
        ("numerical", GateState.PASS, "PASS_MATERIALS"),
        ("physical", GateState.PASS_WITH_LIMITATION, "LIMIT_MATERIAL_PROVENANCE"),
        ("engineering", GateState.PASS_WITH_LIMITATION, "LIMIT_MATERIAL_PROVENANCE"),
    ],
)
def test_supported_claim_scopes_keep_their_provenance_semantics(
    tmp_path: Path,
    claim_scope: str,
    expected_state: GateState,
    expected_code: str,
):
    """Catches a closed-vocabulary fix that changes established provenance decisions."""
    result = audit_materials(
        GateContext(
            tmp_path,
            _contract(_material(provenance="sensitivity_only"), claim_scope=claim_scope),
        )
    )

    assert result.state is expected_state
    assert result.code == expected_code


@pytest.mark.parametrize("provenance", ["assumed", "sensitivity_only", "literature"])
def test_nonmeasured_material_cannot_be_labeled_site_measured(tmp_path: Path, provenance: str):
    """Catches contradictory promotion of non-measured values to site measurements."""
    result = audit_materials(
        GateContext(
            tmp_path,
            _contract(_material(provenance=provenance, site_measured=True)),
        )
    )

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_MATERIAL_PROVENANCE"


@pytest.mark.parametrize(
    "material",
    [
        _material(epsilon_r=0.0),
        _material(sigma_s_m=-1e-3),
        _material(model="debye", epsilon_inf=3.0, delta_epsilon=1.0, tau_s=0.0),
        _material(model="debye", epsilon_inf=3.0, delta_epsilon=-1.0, tau_s=1e-9),
        _material(model="debye", epsilon_inf=float("inf"), delta_epsilon=1.0, tau_s=1e-9),
    ],
)
def test_invalid_material_parameters_block(tmp_path: Path, material: dict[str, Any]):
    """Catches passive/finite validation gaps in either supported material model."""
    result = audit_materials(GateContext(tmp_path, _contract(material)))

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_MATERIAL_PARAMETERS"


def test_requested_band_must_be_contained_by_material_validity(tmp_path: Path):
    """Catches extrapolation of material parameters outside their stated evidence band."""
    contract = _contract(
        _material(frequency_range_valid_hz=[75e6, 125e6]),
    )
    contract["waveform"] = {"analysis_band": [50e6, 150e6]}

    result = audit_materials(GateContext(tmp_path, contract))

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_MATERIAL_BAND"


@pytest.mark.parametrize(
    "validity",
    [[0.0, 100e6], [200e6, 100e6], [100e6], [100e6, float("nan")]],
)
def test_malformed_material_validity_band_blocks(tmp_path: Path, validity: list[float]):
    """Catches silent acceptance of an unusable declared validity interval."""
    contract = _contract(_material(frequency_range_valid_hz=validity))
    contract["waveform"] = {"analysis_band": [50e6, 75e6]}

    result = audit_materials(GateContext(tmp_path, contract))

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_MATERIAL_BAND"


def test_debye_band_summary_is_compact_and_preserves_evidence(tmp_path: Path):
    """Catches raw array publication, wrong extrema, or overwrite of observed material evidence."""
    tau_s = 1e-9
    f_low = 0.5 / (2.0 * math.pi * tau_s)
    f_high = 2.0 / (2.0 * math.pi * tau_s)
    contract = _contract(
        _material(
            model="debye",
            epsilon_inf=3.0,
            delta_epsilon=1.0,
            tau_s=tau_s,
            sigma_s_m=0.0,
            frequency_range_valid_hz=[f_low / 2.0, f_high * 2.0],
        )
    )
    contract["waveform"] = {"analysis_band": [f_low, f_high]}
    observed = {"source": "solver output", "epsilon_r": [3.25]}
    ctx = GateContext(
        tmp_path,
        contract,
        artifacts={"materials": observed, "derived": {"numerics": {"dt_s": 1e-12}}},
    )

    result = audit_materials(ctx)

    assert result.state is GateState.PASS
    assert ctx.artifacts["materials"] is observed
    assert ctx.artifacts["derived"]["numerics"] == {"dt_s": 1e-12}
    summary = ctx.artifacts["derived"]["materials"]
    assert summary["phasor_convention"] == "exp(+j omega t)"
    assert summary["analysis_band_hz"] == [f_low, f_high]
    material_summary = summary["materials"][0]
    assert material_summary["epsilon_prime_min"] == pytest.approx(3.2, rel=1e-12)
    assert material_summary["epsilon_prime_max"] == pytest.approx(3.8, rel=1e-12)
    assert material_summary["loss_min"] == pytest.approx(0.4, rel=1e-12)
    assert material_summary["loss_max"] == pytest.approx(0.5, rel=1e-12)
    assert material_summary["phase_velocity_m_s_min"] == pytest.approx(
        153_578_305.962126, rel=1e-12
    )
    assert material_summary["phase_velocity_m_s_max"] == pytest.approx(
        167_263_973.5564936, rel=1e-12
    )
    assert not _contains_array(summary)


def test_nested_provenance_and_mapping_band_are_supported(tmp_path: Path):
    """Catches rejection of the structured contract spelling used for auditable metadata."""
    material = _material(
        provenance={"class": "manufacturer", "site_measured": False},
        frequency_range_valid_hz={"min_hz": 40e6, "max_hz": 200e6},
    )
    contract = _contract(material)
    contract["waveform"] = {"analysis_band": {"min_hz": 50e6, "max_hz": 150e6}}

    result = audit_materials(GateContext(tmp_path, contract))

    assert result.state is GateState.PASS
