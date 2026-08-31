"""Regression tests against a *real* gprMax 3.1.6 output file.

The fixture ``tests/fixtures/real_out/mini_3d_rx1.out`` was produced by
running the bundled ``mini_3d.in`` with gprMax 3.1.6 (CPU) locally. It is the
ground truth for the P1 fix: gprMax writes ``dt`` as an HDF5 *root* attribute
(``fields_outputs.py``), and the ``rxs/rx1/Ez`` dataset carries no attributes
at all. Synthetic tests that put ``dt`` on the dataset would not catch a
regression of that behaviour.

To regenerate the fixture: ``python -m gprMax tests/fixtures/real_out/mini_3d.in``
(gprMax must be importable from the active interpreter).
"""

from pathlib import Path
import json

import numpy as np
import pytest

from scripts import visualize

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "real_out" / "mini_3d_rx1.out"
FIXTURE_IN = Path(__file__).resolve().parents[1] / "fixtures" / "real_out" / "mini_3d.in"


@pytest.fixture(scope="module")
def real_trace() -> tuple[np.ndarray, float]:
    if not FIXTURE.is_file():
        pytest.skip("real gprMax fixture missing; regenerate with gprMax")
    return visualize.read_ez_from_out(FIXTURE)


def test_fixture_files_present():
    assert FIXTURE.is_file(), f"fixture missing: {FIXTURE}"
    assert FIXTURE_IN.is_file(), f"fixture source missing: {FIXTURE_IN}"


def test_real_out_dt_read_from_root(real_trace):
    """P1 regression: dt must come from the HDF5 root attribute."""
    traces, dt_s = real_trace
    assert dt_s is not None
    # gprMax 3.1.6 mini_3d.in: dx=dy=dz=0.01 m → dt ≈ 1.926e-11 s
    assert dt_s == pytest.approx(1.9258e-11, rel=1e-3)


def test_real_out_shape_and_dtype(real_trace):
    traces, dt_s = real_trace
    assert traces.ndim == 2
    assert traces.shape[0] == 1  # one receiver
    assert traces.shape[1] > 1000  # 30 ns window at ~1.93e-11 dt
    assert np.all(np.isfinite(traces))


def test_real_out_has_signal(real_trace):
    """The fixture must contain an actual reflection (not all zeros)."""
    traces, _ = real_trace
    assert np.max(np.abs(traces)) > 0


def test_real_out_ez_dataset_has_no_attrs(tmp_path):
    """gprMax leaves the Ez dataset without attributes — the fallback path
    must not be required for real outputs."""
    import h5py

    with h5py.File(FIXTURE, "r") as handle:
        dataset_attrs = dict(handle["rxs/rx1/Ez"].attrs)
    assert dataset_attrs == {}  # real gprMax layout


def test_process_and_plot_real_output(tmp_path):
    """End-to-end on the real .out: read → impulse_lti chain → plot → params."""
    artifacts = visualize.process_and_plot(
        FIXTURE,
        mode="impulse_lti",
        frequencies_mhz=[200, 250, 300, 350],
        output_dir=tmp_path,
        impulse_response=visualize.read_ez_from_out(FIXTURE)[0][0],
    )
    assert artifacts["ascan_png"].is_file()
    assert artifacts["ascan_png"].stat().st_size > 5000
    assert artifacts["parameters_json"].is_file()
    params = json.loads(artifacts["parameters_json"].read_text(encoding="utf-8"))
    assert params["mode"] == "impulse_lti"
    assert params["delay_bin_s"] > 0


def test_process_and_plot_reads_dt_from_file(tmp_path):
    """Regression: dt_s=None must not be needed for a real gprMax file."""
    traces, _ = visualize.read_ez_from_out(FIXTURE)
    artifacts = visualize.process_and_plot(
        FIXTURE,
        mode="impulse_lti",
        frequencies_mhz=[200, 250, 300],
        dt_s=None,  # must be recovered from the file root attr
        output_dir=tmp_path,
        impulse_response=traces[0],
    )
    assert artifacts["parameters_json"].is_file()
    params = json.loads(artifacts["parameters_json"].read_text(encoding="utf-8"))
    assert params["delay_bin_s"] > 0
