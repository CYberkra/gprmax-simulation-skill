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


def test_plot_geometry_sketch_surface_on_top(tmp_path):
    """Physical convention: Tx/Rx at z=0 sit at the TOP, target depth below.

    Regression: the first version plotted z=0 at the bottom, making the
    radar look like it fires upward from underground.
    """
    import numpy as np
    from PIL import Image

    out = sketch.plot_geometry_sketch(
        _contract(target_size_m=8.0), tmp_path / "sketch.png"
    )
    image = np.asarray(Image.open(out).convert("RGB"))
    height = image.shape[0]

    # Tx marker: red accent (#dc2626) — find its rows.
    red = (image[:, :, 0] > 180) & (image[:, :, 1] < 120) & (image[:, :, 2] < 120)
    tx_rows = np.where(red.any(axis=1))[0]
    # Target fill: accent blue (#0ea5e9) — find its rows.
    blue = (image[:, :, 0] < 80) & (image[:, :, 1] > 120) & (image[:, :, 2] > 160)
    target_rows = np.where(blue.any(axis=1))[0]

    assert len(tx_rows) > 0, "Tx marker not found in sketch"
    assert len(target_rows) > 0, "target box not found in sketch"
    # Surface must be above the target (smaller pixel row = closer to top).
    assert tx_rows.mean() < target_rows.mean(), (
        "Tx must sit above the target (surface on top, depth downward)"
    )
    assert target_rows.max() < height * 0.9, "target should stay inside the plot"
