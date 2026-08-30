from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.audit_sfcw import audit_sfcw, delay_bin, unambiguous_delay
from scripts.core import GateContext, GateState


def _config() -> dict:
    return {
        "tones_hz": [50e6, 60e6, 70e6],
        "requested_max_delay_s": 50e-9,
        "processing": {
            "processing_id": "sfcw-audit-test",
            "mode": "impulse_lti",
            "frequency_extraction": "quadrature_mixing",
            "tone_source": "declared_list",
            "nfft": 24,
            "window": {"kind": "rectangular"},
            "zero_padding": {
                "factor": 8,
                "claims_physical_resolution_gain": False,
            },
            "quantitative_normalization": "none",
            "source_delay": {
                "artificial_delay_s": 0.0,
                "correction_count": 0,
                "residual_group_delay_abs_s": 0.0,
                "tolerance_s": 0.0,
            },
            "reference": {
                "class": "none",
                "requested_use": "none",
                "field_available": False,
            },
        },
        "acquisition": {
            "motion_during_sweep": False,
            "positions_change_per_tone": False,
            "tones_completed_per_position": True,
        },
    }


def _audit(tmp_path, config):
    return audit_sfcw(
        GateContext(
            tmp_path,
            config,
            artifacts={
                "source_audit": {
                    "notch_fraction": 0.0,
                    "normalized_power_ratios": [1.0, 1.0, 1.0],
                }
            },
        )
    )


def test_delay_contract_formulas():
    assert unambiguous_delay(10e6) == pytest.approx(100e-9)
    assert delay_bin(10e6, 20) == pytest.approx(5e-9)


def test_valid_sfcw_policy_passes_and_publishes_provenance(tmp_path):
    context = GateContext(
        tmp_path,
        _config(),
        artifacts={
            "source_audit": {
                "notch_fraction": 0.0,
                "normalized_power_ratios": [1.0, 1.0, 1.0],
            }
        },
    )
    result = audit_sfcw(context)
    assert result.state is GateState.PASS
    assert context.artifacts["sfcw_audit"]["delay_bin_s"] == pytest.approx(1 / 240e6)
    assert context.artifacts["sfcw_audit"]["processing_id"] == "sfcw-audit-test"


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda c: c.update(tones_hz=[50e6, 61e6, 70e6]), "BLOCK_SFCW_NONUNIFORM_TONES"),
        (
            lambda c: c["processing"].update(quantitative_normalization="per_tone"),
            "BLOCK_QUANTITATIVE_NORMALIZATION",
        ),
        (
            lambda c: c["processing"]["zero_padding"].update(
                claims_physical_resolution_gain=True
            ),
            "BLOCK_FALSE_RESOLUTION_CLAIM",
        ),
        (
            lambda c: c["processing"]["source_delay"].update(
                artificial_delay_s=10e-9, correction_count=0
            ),
            "BLOCK_SOURCE_DELAY_CORRECTION_COUNT",
        ),
        (
            lambda c: c["processing"]["source_delay"].update(
                residual_group_delay_abs_s=2e-9, tolerance_s=1e-9
            ),
            "BLOCK_SOURCE_DELAY_NOT_DEEMBEDDED",
        ),
        (
            lambda c: c["processing"]["reference"].update(
                **{
                    "class": "solver_truth",
                    "requested_use": "engineering_input",
                    "field_available": False,
                }
            ),
            "BLOCK_TRUTH_REFERENCE_ENGINEERING_INPUT",
        ),
        (
            lambda c: c["acquisition"].update(
                positions_change_per_tone=True, tones_completed_per_position=False
            ),
            "BLOCK_SFCW_POSITION_SEMANTICS",
        ),
        (
            lambda c: c.update(requested_max_delay_s=100e-9),
            "BLOCK_SFCW_AMBIGUOUS_DELAY",
        ),
        (
            lambda c: c["processing"].update(frequency_extraction="exact_dtft"),
            "BLOCK_SFCW_EXTRACTION_MODE",
        ),
    ],
)
def test_policy_defects_fail_closed(tmp_path, mutate, code):
    config = deepcopy(_config())
    mutate(config)
    result = _audit(tmp_path, config)
    assert result.state is GateState.BLOCK
    assert result.code == code


def test_broadband_deconvolution_requires_audited_regularization(tmp_path):
    config = _config()
    config["processing"]["mode"] = "broadband_deconvolution"
    config["processing"]["frequency_extraction"] = "exact_dtft"
    result = _audit(tmp_path, config)
    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_SFCW_CONTRACT"


def test_broadband_deconvolution_blocks_excess_notch_fraction(tmp_path):
    config = _config()
    config["processing"]["mode"] = "broadband_deconvolution"
    config["processing"]["frequency_extraction"] = "exact_dtft"
    config["processing"]["regularization"] = {
        "value": 1e-6,
        "selection": "predeclared synthetic test",
        "max_condition_fraction": 0.1,
    }
    context = GateContext(
        tmp_path,
        config,
        artifacts={
            "source_audit": {
                "notch_fraction": 0.25,
                "normalized_power_ratios": [1.0, 1e-8, 1e-9, 1.0],
            }
        },
    )
    result = audit_sfcw(context)
    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_DECONVOLUTION_CONDITION"
