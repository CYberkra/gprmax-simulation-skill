"""Tests for ``scripts.sketch`` — geometry cross-section sketch."""

import pytest

from scripts import sketch


def _contract(**overrides):
    contract = {
        "project": {"target_depth_m": 80.0, "target_size_m": 4.0},
        "domain_m": [120.0, 20.0, 100.0],
        "task": {"objective": "tunnel", "claim_scope": "numerical"},
        "medium": {
            "target_material": "WET",
            "medium_material": "coal",
            "model_type": "debye",
            "parameter_source": "literature",
        },
        "waveform": {
            "excitation_mode": "unit_impulse",
            "measurement_mode": "sfcw_equivalent",
            "processing_route": "impulse_lti",
            "band_mhz": "30-240",
        },
        "numerics": {"precision_requirement": "fp32", "pml_layers": 20},
        "geometry": {"target_level": "L3", "antenna": "ideal_hertzian", "noise": "none"},
        "acceptance": {"negative_controls": [], "sensitivity_tests": []},
        "evidence": {"required_outputs": ["rxs/rx1/Ez"], "provenance_level": "strict"},
    }
    contract.update(overrides)
    return contract


def test_plot_geometry_sketch_saves_file(tmp_path):
    out = sketch.plot_geometry_sketch(_contract(), tmp_path / "sketch.png")
    assert out.exists()
    assert out.stat().st_size > 5000


def test_plot_geometry_sketch_requires_depth(tmp_path):
    with pytest.raises(sketch.SketchError):
        sketch.plot_geometry_sketch({}, tmp_path / "sketch.png")


def test_plot_geometry_sketch_domain_too_small(tmp_path):
    contract = _contract(domain_m=[120.0, 20.0, 10.0])  # z < target_depth 80
    with pytest.raises(sketch.SketchError):
        sketch.plot_geometry_sketch(contract, tmp_path / "sketch.png")


def test_plot_geometry_sketch_without_domain(tmp_path):
    contract = _contract()
    del contract["domain_m"]
    out = sketch.plot_geometry_sketch(contract, tmp_path / "sketch.png")
    assert out.exists()
    assert out.stat().st_size > 5000


def test_plot_geometry_sketch_rejects_nonpositive_depth(tmp_path):
    with pytest.raises(sketch.SketchError):
        sketch.plot_geometry_sketch(
            {"project": {"target_depth_m": -5}}, tmp_path / "sketch.png"
        )
