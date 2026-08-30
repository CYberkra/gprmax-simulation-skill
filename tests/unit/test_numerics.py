import math

import pytest

import scripts.numerics as numerics

C = numerics.SPEED_OF_LIGHT_M_S


def test_phase_velocity():
    assert numerics.phase_velocity_m_s(4.0) == pytest.approx(C / 2.0)


def test_smallest_wavelength():
    lam = numerics.smallest_wavelength_m(4.0, 300e6)
    assert lam == pytest.approx(C / 2.0 / 300e6)


def test_check_mesh_pass_and_fail():
    ok = numerics.check_mesh(0.04, 4.0, 300e6, minimum_cells=10.0)
    assert ok.ok is True
    assert ok.cells_per_wavelength["Nx"] == pytest.approx(C / 2.0 / 300e6 / 0.04)
    assert set(ok.cells_per_wavelength) == {"Nx", "Ny", "Nz"}

    bad = numerics.check_mesh(0.20, 9.0, 600e6, minimum_cells=10.0)
    assert bad.ok is False


def test_check_mesh_per_axis_anisotropic():
    check = numerics.check_mesh((0.04, 0.05, 0.05), 4.0, 300e6)
    lam = C / 2.0 / 300e6
    assert check.cells_per_wavelength["Nx"] == pytest.approx(lam / 0.04)
    assert check.cells_per_wavelength["Ny"] == pytest.approx(lam / 0.05)
    assert check.cells_per_wavelength["Nz"] == pytest.approx(lam / 0.05)


def test_check_mesh_rejects_bad_cells():
    with pytest.raises(ValueError):
        numerics.check_mesh((0.04, -1.0, 0.05), 4.0, 300e6)


def test_cfl_dt_cubic_and_anisotropic():
    cubic = numerics.cfl_dt_s(0.05)
    aniso = numerics.cfl_dt_s(0.04, 0.05, 0.05)
    assert cubic > aniso
    assert cubic == pytest.approx(1.0 / (C * math.sqrt(3 / 0.05**2)))


def test_check_cfl_detects_violation():
    limit = numerics.cfl_dt_s(0.05)
    at_limit = numerics.check_cfl(0.05, None, None, limit)
    assert at_limit.ok is True
    assert at_limit.solver_ok is True
    assert at_limit.project_safety_fraction is None
    good = numerics.check_cfl(0.05, None, None, limit * 0.9)
    assert good.ok is True
    bad = numerics.check_cfl(0.05, None, None, limit * 1.1)
    assert bad.ok is False


def test_check_cfl_distinguishes_declared_project_margin():
    limit = numerics.cfl_dt_s(0.05)
    check = numerics.check_cfl(
        0.05, None, None, limit * 0.98, safety_fraction=0.95
    )
    assert check.solver_ok is True
    assert check.project_ok is False
    assert check.ok is False


def test_two_way_and_window():
    twt = numerics.two_way_travel_s(80.0, 2.8)
    ok = numerics.check_window(80.0, 2.8, window_s=twt * 2, dt_s=1e-9)
    assert ok.ok is True
    short = numerics.check_window(80.0, 2.8, window_s=twt * 0.9, dt_s=1e-9)
    assert short.ok is False


def test_pml_clearance_per_axis():
    pml = numerics.pml_clearance_m(10, (0.04, 0.05, 0.05))
    assert pml == {"x": pytest.approx(0.4), "y": pytest.approx(0.5), "z": pytest.approx(0.5)}
    with pytest.raises(ValueError):
        numerics.pml_clearance_m(0, 0.05)


def test_grid_cells_total():
    total = numerics.grid_cells_total((10, 5, 5), (0.05, 0.05, 0.05))
    assert total == (10 / 0.05) * (5 / 0.05) * (5 / 0.05)


def test_grid_cells_total_rejects_unaligned_extent_instead_of_ceiling():
    with pytest.raises(ValueError, match="integer multiple"):
        numerics.grid_cells_total((10.01, 5, 5), (0.05, 0.05, 0.05))


def test_estimate_resources_interval():
    resource = numerics.estimate_resources(
        (10, 5, 5), (0.05, 0.05, 0.05), window_s=1e-6, dt_s=1e-9
    )
    assert resource.cells_total > 0
    assert resource.vram_gb_fp32 > 0
    assert resource.vram_gb_fp64 > resource.vram_gb_fp32
    assert 0 < resource.runtime_hours_min <= resource.runtime_hours_max
    assert resource.is_estimate is True


def test_estimate_resources_calibrated_throughput():
    resource_slow = numerics.estimate_resources(
        (10, 5, 5), (0.05, 0.05, 0.05), window_s=1e-6, dt_s=1e-9,
        gpu_throughput_cells_per_s=2e8,
    )
    resource_fast = numerics.estimate_resources(
        (10, 5, 5), (0.05, 0.05, 0.05), window_s=1e-6, dt_s=1e-9,
        gpu_throughput_cells_per_s=8e8,
    )
    assert resource_fast.runtime_hours_max < resource_slow.runtime_hours_max


def test_numerics_report_structure():
    report = numerics.numerics_report(
        eps_r=2.8,
        max_frequency_hz=240e6,
        cells_m=(0.05, 0.05, 0.05),
        domain_m=(60, 16, 7),
        target_distance_m=80.0,
        window_s=2.0e-6,
        pml_layers=10,
    )
    assert report["mesh"]["ok"] is True
    assert report["mesh"]["cells_per_wavelength"]["Nz"] > 0
    assert report["window"]["ok"] is True
    assert report["cfl"]["explicit_dt"] is False
    assert report["cfl"]["project_safety_fraction"] is None
    assert report["resources"]["is_estimate"] is True
    assert report["resources"]["runtime_hours_max"] >= report["resources"]["runtime_hours_min"]
    assert report["pml"]["thickness_m"]["x"] == pytest.approx(0.5)


def test_numerics_report_marks_missing_pml_unknown():
    report = numerics.numerics_report(
        eps_r=2.8,
        max_frequency_hz=240e6,
        cells_m=(0.05, 0.05, 0.05),
        domain_m=(60, 16, 7),
        target_distance_m=80.0,
        window_s=2.0e-6,
        pml_layers=None,
    )
    assert report["pml"] == {
        "layers": None,
        "source": "not_provided",
        "status": "UNKNOWN",
        "thickness_m": None,
    }


def test_report_to_text_covers_sections():
    report = numerics.numerics_report(
        eps_r=2.8,
        max_frequency_hz=240e6,
        cells_m=(0.05, 0.05, 0.05),
        domain_m=(60, 16, 7),
        target_distance_m=80.0,
        window_s=2.0e-6,
        pml_layers=10,
    )
    text = numerics.report_to_text(report)
    assert "网格" in text
    assert "时步" in text
    assert "显存" in text
    assert "区间估计" in text
