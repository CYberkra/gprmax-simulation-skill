from __future__ import annotations

import numpy as np

from scripts.audit_source import audit_source, source_peak_time, tail_energy_fraction
from scripts.core import GateContext, GateState


def _contract(samples: list[float]) -> dict:
    return {
        "tones_hz": [50e6, 60e6, 70e6],
        "source": {
            "samples": samples,
            "dt_s": 1e-9,
            "minimum_support_ratio": 0.01,
            "max_dc_ratio": 0.5,
            "max_tail_energy_fraction": 0.1,
        },
    }


def test_source_peak_time_is_sample_accurate():
    assert source_peak_time(np.array([0.0, 1.0, 0.25]), 2e-9) == 2e-9


def test_tail_energy_fraction_excludes_peak_sample():
    assert np.isclose(tail_energy_fraction(np.array([0.0, 2.0, 1.0]), 1), 1.0 / 5.0)


def test_source_audit_passes_flat_exact_tone_support(tmp_path):
    result = audit_source(GateContext(tmp_path, _contract([0.0, 1.0, 0.0])))
    assert result.state is GateState.PASS
    assert result.code == "PASS_SOURCE"


def test_requested_source_spectral_null_blocks(tmp_path):
    contract = _contract([1.0] * 10)
    contract["tones_hz"] = [50e6, 100e6]
    contract["source"]["minimum_support_ratio"] = 0.1
    contract["source"]["max_dc_ratio"] = 1.0
    contract["source"]["max_tail_energy_fraction"] = 1.0
    result = audit_source(GateContext(tmp_path, contract))
    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_SOURCE_SPECTRAL_SUPPORT"


def test_source_dc_above_declared_limit_blocks(tmp_path):
    contract = _contract([1.0, 2.0, 1.0])
    contract["source"]["minimum_support_ratio"] = 0.0
    contract["source"]["max_dc_ratio"] = 0.1
    contract["source"]["max_tail_energy_fraction"] = 1.0
    result = audit_source(GateContext(tmp_path, contract))
    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_SOURCE_DC"


def test_missing_thresholds_are_limited_not_invented(tmp_path):
    contract = _contract([0.0, 1.0, 0.0])
    contract["source"] = {"samples": [0.0, 1.0, 0.0], "dt_s": 1e-9}
    result = audit_source(GateContext(tmp_path, contract))
    assert result.state is GateState.PASS_WITH_LIMITATION
    assert result.code == "LIMIT_SOURCE_THRESHOLDS"
