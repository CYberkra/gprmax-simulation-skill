"""Tests for ``scripts.visualize`` — processing and plotting.

Uses synthetic data only; no real gprMax ``.out`` files are needed.
"""

from pathlib import Path

import numpy as np
import pytest

from scripts import sfcw, visualize


def test_process_trace_impulse_lti_returns_envelope(tmp_path: Path):
    dt = 0.1e-9
    n = 4096
    h = np.zeros(n)
    h[300] = 0.1
    h[600] = 0.05
    freqs = [60, 160]
    result = visualize.process_trace(
        "impulse_lti", h, dt_s=dt, frequencies_mhz=freqs, impulse_response=h
    )
    assert "envelope" in result
    assert result["envelope"].ndim == 1
    assert np.all(result["envelope"] >= 0)


def test_process_trace_rejects_missing_impulse_response(tmp_path: Path):
    with pytest.raises(visualize.ProcessingError):
        visualize.process_trace("impulse_lti", np.zeros(100), dt_s=0.1e-9, frequencies_mhz=[60])


def test_process_trace_rejects_direct_per_tone(tmp_path: Path):
    with pytest.raises(visualize.ProcessingError):
        visualize.process_trace("direct_per_tone", np.zeros(100), dt_s=0.1e-9, frequencies_mhz=[60])


def test_plot_ascan_saves_file(tmp_path: Path):
    dt = 0.1e-9
    n = 4096
    h = np.zeros(n)
    h[300] = 0.1
    freqs = np.arange(60e6, 161e6, 1e6)
    samples = sfcw.complex_samples_impulse_lti(h, dt, freqs)
    asc = sfcw.reconstruct_ascan(samples, zero_pad_factor=8)
    result = {
        "mode": "impulse_lti",
        "ascan": asc,
        "envelope": sfcw.envelope(asc.real),
        "delay_bin_s": 1.0 / (len(asc) * 1e6),
    }
    out = visualize.plot_ascan(result, tmp_path / "ascan.png")
    assert out.exists()
    assert out.stat().st_size > 5000  # reasonable PNG size


def test_process_and_plot_with_synthetic_out(tmp_path: Path):
    """End-to-end: write a synthetic .out (h5py), process, plot, save params."""
    import h5py

    dt = 0.1e-9
    n = 4096
    # synthetic receiver: impulse-like response convolved with nothing → direct echo
    ez = np.zeros(n)
    ez[0] = 1.0
    ez[300] = 0.1  # weak reflection at 30 ns

    out_file = tmp_path / "synth.out"
    with h5py.File(out_file, "w") as handle:
        dset = handle.create_dataset("rxs/rx1/Ez", data=ez.reshape(1, 1, n))
        dset.attrs["dt"] = dt

    # impulse-response route: pass h = ez (the receiver itself) as h[n] is not
    # available from a .out; here we treat the synthetic trace as h for the
    # impulse_lti chain so the pipeline runs end-to-end.
    out_dir = tmp_path / "results"
    artifacts = visualize.process_and_plot(
        out_file,
        mode="impulse_lti",
        frequencies_mhz=[60, 160],
        dt_s=dt,
        output_dir=out_dir,
        impulse_response=ez,
    )
    assert artifacts["ascan_png"].exists()
    assert artifacts["ascan_png"].stat().st_size > 5000
    assert artifacts["parameters_json"].exists()
    import json

    params = json.loads(artifacts["parameters_json"].read_text(encoding="utf-8"))
    assert params["mode"] == "impulse_lti"
    assert params["delay_bin_s"] > 0


def test_save_processing_parameters(tmp_path: Path):
    result = {
        "mode": "impulse_lti",
        "delay_bin_s": 1.23e-9,
        "unambiguous_delay_s": 1.0e-6,
        "processing_parameters": {"tone_count": 101, "window": {"kind": "rectangular"}},
    }
    path = visualize.save_processing_parameters(result, tmp_path / "params.json")
    import json
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["mode"] == "impulse_lti"
    assert data["tone_count"] == 101


def test_plot_bscan_saves_file(tmp_path: Path):
    traces = [np.sin(np.linspace(0, 4 * np.pi, 200)) for _ in range(5)]
    out = visualize.plot_bscan(
        traces, tmp_path / "bscan.png", delay_bin_s=1.0e-9
    )
    assert out.exists()
    assert out.stat().st_size > 5000


# --------------------------------------------------------------------------
# processing chain recommendation
# --------------------------------------------------------------------------

def test_recommend_chain_user_specified_wins():
    rec = visualize.recommend_chain(
        {"chain": "advanced"}, {"waveform": {"measurement_mode": "time_domain"}}
    )
    assert rec["chain"] == "advanced"
    assert rec["display_only"] is False
    assert "user-specified" in rec["rationale"]


def test_recommend_chain_rejects_unknown():
    with pytest.raises(visualize.ProcessingError):
        visualize.recommend_chain({"chain": "bogus"}, {})


def test_recommend_chain_sfcw_contract_gets_standard():
    rec = visualize.recommend_chain(
        None, {"waveform": {"measurement_mode": "sfcw_equivalent"}}
    )
    assert rec["chain"] == "standard"
    assert rec["display_only"] is False


def test_recommend_chain_sfcw_high_quality_advanced():
    rec = visualize.recommend_chain(
        {"quality": "high"}, {"waveform": {"measurement_mode": "sfcw_equivalent"}}
    )
    assert rec["chain"] == "advanced"


def test_recommend_chain_time_domain_raw():
    rec = visualize.recommend_chain(None, {"waveform": {"measurement_mode": "time_domain"}})
    assert rec["chain"] == "raw_visual"
    assert rec["display_only"] is True


def test_recommend_chain_imaging_optional():
    rec = visualize.recommend_chain(
        {"need_imaging": True}, {"waveform": {"measurement_mode": "sfcw_equivalent"}}
    )
    assert rec["chain"] == "imaging"
    assert "imaging" in rec["rationale"]


def test_plot_bscan_pair_saves_file(tmp_path: Path):
    before = [np.sin(np.linspace(0, 4 * np.pi, 200)) for _ in range(5)]
    after = [np.sin(np.linspace(0, 4 * np.pi, 200)) * 0.5 for _ in range(5)]
    out = visualize.plot_bscan_pair(
        before, after, tmp_path / "pair.png", delay_bin_s=1.0e-9
    )
    assert out.exists()
    assert out.stat().st_size > 5000


def test_plot_bscan_pair_rejects_shape_mismatch(tmp_path: Path):
    before = [np.sin(np.linspace(0, 4 * np.pi, 200)) for _ in range(5)]
    after = [np.sin(np.linspace(0, 4 * np.pi, 100)) for _ in range(5)]
    with pytest.raises(visualize.ProcessingError):
        visualize.plot_bscan_pair(before, after, tmp_path / "pair.png", delay_bin_s=1e-9)