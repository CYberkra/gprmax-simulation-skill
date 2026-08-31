from pathlib import Path

import pytest
import yaml

import scripts.diagnose as diagnose
import scripts.numerics as numerics
import scripts.sensitivity as sensitivity


def _contract(**overrides) -> dict:
    contract = {
        "project": {"target_depth_m": 80.0},
        "medium": {"eps_r": 2.8},
        "waveform": {"band_mhz": "30-240"},
        "domain_m": [60.0, 16.0, 7.0],
        "numerics": {
            "dx_m": 0.05,
            "dy_m": 0.05,
            "dz_m": 0.05,
            "dt_s": 5.0e-11,
            "time_window_s": 2.0e-6,
            "pml_layers": 20,
        },
    }
    contract.update(overrides)
    return contract


# --------------------------------------------------------------------------
# calibrate_throughput
# --------------------------------------------------------------------------

def test_calibrate_throughput_backs_out_measured_time():
    # A model with known op count; measured time yields the throughput.
    domain = (10.0, 5.0, 5.0)
    cell = (0.05, 0.05, 0.05)
    window = 1e-6
    dt = 1e-9
    total = numerics.grid_cells_total(domain, cell)
    steps = max(1, int(__import__("math").ceil(window / dt)))
    ops = total * steps
    throughput = numerics.calibrate_throughput(domain, cell, window, dt, measured_seconds=10.0)
    assert throughput == pytest.approx(ops / 10.0)


def test_calibrate_throughput_rejects_bad_time():
    with pytest.raises(ValueError):
        numerics.calibrate_throughput((10, 5, 5), (0.05,) * 3, 1e-6, 1e-9, measured_seconds=0)


def test_calibrate_throughput_rejects_bad_window_or_dt():
    # Regression: window_s / dt_s were not validated; NaN or zero could
    # silently produce a bogus throughput figure.
    for bad_window in (0.0, -1e-6, float("nan")):
        with pytest.raises(ValueError):
            numerics.calibrate_throughput(
                (10, 5, 5), (0.05,) * 3, bad_window, 1e-9, measured_seconds=10.0
            )
    for bad_dt in (0.0, -1e-9, float("nan")):
        with pytest.raises(ValueError):
            numerics.calibrate_throughput(
                (10, 5, 5), (0.05,) * 3, 1e-6, bad_dt, measured_seconds=10.0
            )


# --------------------------------------------------------------------------
# diagnose
# --------------------------------------------------------------------------

def test_diagnose_ok_contract():
    findings = diagnose.diagnose_model(_contract())
    assert findings
    assert all(f.severity != "BLOCK" for f in findings)
    checks = {f.check for f in findings}
    assert {"mesh", "cfl", "window", "pml", "nyquist", "vram"} <= checks


def test_diagnose_blocks_short_window():
    contract = _contract()
    contract["numerics"]["time_window_s"] = 1.0e-9  # far too short
    findings = diagnose.diagnose_model(contract)
    window = next(f for f in findings if f.check == "window")
    assert window.severity == "BLOCK"


def test_diagnose_blocks_vram_when_gpu_too_small():
    contract = _contract()
    findings = diagnose.diagnose_model(contract, gpu_vram_gb=0.001)
    vram = next(f for f in findings if f.check == "vram")
    assert vram.severity == "BLOCK"


def test_diagnose_warns_on_missing_material():
    findings = diagnose.diagnose_model(_contract(medium={}))
    assert findings[0].check == "material"
    assert findings[0].severity == "WARN"


def test_render_diagnostics_contains_markers():
    text = diagnose.render_diagnostics(
        [diagnose.Diagnosis("mesh", "OK", "fine"), diagnose.Diagnosis("cfl", "BLOCK", "bad")]
    )
    assert "✅" in text
    assert "⛔" in text


# --------------------------------------------------------------------------
# sensitivity
# --------------------------------------------------------------------------

def test_sensitivity_returns_ranked_results():
    results = sensitivity.analyse_sensitivity(_contract())
    assert results
    # sorted by relative_change descending
    changes = [r.relative_change for r in results]
    assert changes == sorted(changes, reverse=True)


def test_sensitivity_most_sensitive_is_eps_or_cell():
    results = sensitivity.analyse_sensitivity(_contract())
    top = sensitivity.rank_most_sensitive(results, top=3)
    assert top
    names = {item.parameter for item in top}
    # eps_r moves every propagation-related check (wavelength, window
    # coverage); dx moves cells-per-wavelength and grid total directly.
    # The top-3 must contain at least one of them — not merely any of the
    # five axes.
    assert "eps_r" in names or "dx" in names
    assert names.issubset(
        {"eps_r", "f_hi", "dx", "dy", "dz", "dt", "target_depth", "window"}
    )


def test_sensitivity_render_table():
    results = sensitivity.analyse_sensitivity(_contract())
    text = sensitivity.render_sensitivity(results)
    assert "参数" in text
    assert "相对变化" in text


def test_sensitivity_custom_checks():
    results = sensitivity.analyse_sensitivity(
        _contract(), checks=("cells_per_wavelength",)
    )
    assert all(r.check == "cells_per_wavelength" for r in results)


# --------------------------------------------------------------------------
# negative paths (fail-closed regressions)
# --------------------------------------------------------------------------

def test_diagnose_handles_string_exponents(tmp_path: Path):
    """Regression: PyYAML parses 2e-6 as str; must still be diagnosed as OK."""
    contract = _contract()
    contract["numerics"]["time_window_s"] = "2e-6"
    contract["numerics"]["dt_s"] = "5e-11"
    findings = diagnose.diagnose_model(contract)
    assert findings
    assert all(f.severity != "BLOCK" for f in findings)


def test_diagnose_pml_below_default_warns():
    contract = _contract()
    contract["numerics"]["pml_layers"] = 3
    findings = diagnose.diagnose_model(contract)
    pml = next(f for f in findings if f.check == "pml")
    assert pml.severity == "WARN"


def test_diagnose_vram_respects_precision():
    # fp32 declared: fp64 estimate may exceed GPU, but fp32 must not BLOCK.
    contract = _contract()
    contract["numerics"]["precision_requirement"] = "fp32"
    findings = diagnose.diagnose_model(contract, gpu_vram_gb=1.5)
    vram = next(f for f in findings if f.check == "vram")
    assert vram.severity != "BLOCK"


def test_diagnose_vram_blocks_on_fp64():
    contract = _contract()
    contract["numerics"]["precision_requirement"] = "float64"
    findings = diagnose.diagnose_model(contract, gpu_vram_gb=1.5)
    vram = next(f for f in findings if f.check == "vram")
    assert vram.severity == "BLOCK"


def test_diagnose_waveform_not_mapping_does_not_crash():
    findings = diagnose.diagnose_model(_contract(waveform=None))
    assert findings  # returns warnings, no crash


def test_sensitivity_requires_fields():
    with pytest.raises(ValueError):
        sensitivity.analyse_sensitivity(_contract(medium={}))
    with pytest.raises(ValueError):
        sensitivity.analyse_sensitivity(_contract(waveform={"band_mhz": "bad"}))
    with pytest.raises(ValueError):
        sensitivity.analyse_sensitivity(_contract(domain_m=None))


def test_sensitivity_uses_contract_domain():
    contract = _contract(domain_m=[100.0, 20.0, 8.0])
    results = sensitivity.analyse_sensitivity(contract, checks=("vram_fp64_gb",))
    # VRAM should scale with the larger domain; no hard-coded (60,16,7).
    big = sensitivity.analyse_sensitivity(_contract(domain_m=[100.0, 20.0, 8.0]))
    small = sensitivity.analyse_sensitivity(_contract(domain_m=[30.0, 8.0, 4.0]))
    big_vram = next(r for r in big if r.check == "vram_fp64_gb")
    small_vram = next(r for r in small if r.check == "vram_fp64_gb")
    assert big_vram.base_metric > small_vram.base_metric