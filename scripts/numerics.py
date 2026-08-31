"""Quantitative numerical checks for the guided setup.

Converts a model plan into concrete numbers: cells per wavelength (per axis),
the CFL-limited time step, PML thickness and clearance (per axis),
time-window coverage, and VRAM / runtime estimates.

Discipline:
- every figure derives only from *confirmed inputs*; missing inputs yield
  BLOCK/UNKNOWN, never silent placeholder values;
- VRAM and runtime are interval estimates with documented, replaceable
  calibration parameters — the defaults are explicitly labelled lower/upper
  bounds, not first-principle constants;
- nothing here hard-codes a project-specific band, distance, or permittivity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

SPEED_OF_LIGHT_M_S = 299_792_458.0

# Rough per-cell FDTD memory lower bound in bytes for fp32: six field
# components (Ex,Ey,Ez,Hx,Hy,Hz) × 4 bytes. Auxiliary arrays and padding are
# not included, so this is a stated lower bound, replaceable via parameter.
BYTES_PER_CELL_FP32_DEFAULT = 24.0

# Planning interval for sustained GPU throughput (cell-updates per second).
# Order-of-magnitude; real throughput depends on the GPU and model. Provide a
# calibrated value for a concrete hardware target when available.
GPU_THROUGHPUT_CELLS_PER_S_LOW = 2.0e8
GPU_THROUGHPUT_CELLS_PER_S_HIGH = 1.0e9


def _cell_vector(cells_m: float | Sequence[float]) -> tuple[float, float, float]:
    if isinstance(cells_m, (int, float)):
        value = float(cells_m)
        if value <= 0:
            raise ValueError("cell size must be positive")
        return (value, value, value)
    values = tuple(float(v) for v in cells_m)
    if len(values) != 3 or any(v <= 0 for v in values):
        raise ValueError("cells_m must be a positive scalar or (dx, dy, dz)")
    return values


@dataclass(frozen=True)
class MeshCheck:
    cells_per_wavelength: dict[str, float]
    min_wavelength_m: float
    max_frequency_hz: float
    ok: bool
    note: str


@dataclass(frozen=True)
class CflCheck:
    dt_s: float
    cfl_fraction: float | None
    solver_limit_s: float
    project_safety_fraction: float | None
    solver_ok: bool
    project_ok: bool | None
    ok: bool
    note: str


@dataclass(frozen=True)
class WindowCheck:
    two_way_s: float
    window_s: float
    ok: bool
    note: str


@dataclass(frozen=True)
class ResourceEstimate:
    cells_total: int
    vram_gb_fp32: float
    vram_gb_fp64: float
    runtime_hours_min: float
    runtime_hours_max: float
    is_estimate: bool = True


def effective_permittivity(eps_r: float) -> float:
    """Effective relative permittivity for phase velocity (low-loss approx)."""
    if eps_r <= 0:
        raise ValueError("eps_r must be positive")
    return eps_r


def phase_velocity_m_s(eps_r: float) -> float:
    return SPEED_OF_LIGHT_M_S / math.sqrt(effective_permittivity(eps_r))


def smallest_wavelength_m(eps_r: float, max_frequency_hz: float) -> float:
    """Shortest wavelength in the band for a homogeneous material."""
    if max_frequency_hz <= 0:
        raise ValueError("max_frequency_hz must be positive")
    return phase_velocity_m_s(eps_r) / max_frequency_hz


def check_mesh(
    cells_m: float | Sequence[float],
    eps_r: float,
    max_frequency_hz: float,
    minimum_cells: float = 10.0,
) -> MeshCheck:
    """Cells per wavelength at the band top, per mesh axis (Nx/λ, Ny/λ, Nz/λ)."""
    dx, dy, dz = _cell_vector(cells_m)
    min_wavelength = smallest_wavelength_m(eps_r, max_frequency_hz)
    per_axis = {
        "Nx": min_wavelength / dx,
        "Ny": min_wavelength / dy,
        "Nz": min_wavelength / dz,
    }
    ok = all(value >= minimum_cells for value in per_axis.values())
    parts = " ".join(
        f"{key}/λ={value:.2f}" for key, value in per_axis.items()
    )
    note = (
        f"{parts} at {max_frequency_hz / 1e6:.0f} MHz "
        f"(λ_min={min_wavelength:.3f} m)"
    )
    if not ok:
        note += f" — an axis is below {minimum_cells:.0f} required"
    return MeshCheck(per_axis, min_wavelength, max_frequency_hz, ok, note)


def cfl_dt_s(dx_m: float, dy_m: float | None = None, dz_m: float | None = None) -> float:
    """CFL-limited time step for the realised mesh."""
    dy = dy_m if dy_m is not None else dx_m
    dz = dz_m if dz_m is not None else dx_m
    if min(dx_m, dy, dz) <= 0:
        raise ValueError("cell sizes must be positive")
    inv = 1.0 / dx_m**2 + 1.0 / dy**2 + 1.0 / dz**2
    return 1.0 / (SPEED_OF_LIGHT_M_S * math.sqrt(inv))


def check_cfl(
    dx_m: float,
    dy_m: float | None,
    dz_m: float | None,
    dt_s: float,
    safety_fraction: float | None = None,
) -> CflCheck:
    """Check ``dt`` against solver stability and an optional project margin.

    The Yee-grid CFL value is the solver stability limit.  A project may
    additionally require a stricter fraction of that value, but no such
    margin is silently imposed here: gprMax's own CFL-equal time step must not
    be rejected merely because a planning convention used 0.95 elsewhere.
    """
    limit = cfl_dt_s(dx_m, dy_m, dz_m)
    if not math.isfinite(dt_s) or dt_s <= 0:
        raise ValueError("dt_s must be positive and finite")
    if safety_fraction is not None and not (0 < safety_fraction <= 1):
        raise ValueError("safety_fraction must be in (0, 1]")
    # Allow only floating-point round-off at the analytical stability limit.
    solver_ok = dt_s <= limit or math.isclose(dt_s, limit, rel_tol=1e-12)
    project_limit = None if safety_fraction is None else safety_fraction * limit
    project_ok = (
        None
        if project_limit is None
        else dt_s <= project_limit
        or math.isclose(dt_s, project_limit, rel_tol=1e-12)
    )
    ok = solver_ok and project_ok is not False
    fraction = dt_s / limit
    note = f"dt={dt_s:.3e} s vs solver CFL {limit:.3e} s ({fraction:.3f}×)"
    if not solver_ok:
        note += " — exceeds solver stability limit"
    elif safety_fraction is not None:
        note += f"; project limit={safety_fraction:.3f}× CFL"
        if project_ok is False:
            note += " — exceeds declared project margin"
    else:
        note += "; no additional project safety factor declared"
    return CflCheck(
        dt_s,
        fraction,
        limit,
        safety_fraction,
        solver_ok,
        project_ok,
        ok,
        note,
    )


def two_way_travel_s(distance_m: float, eps_r: float) -> float:
    return 2.0 * distance_m / phase_velocity_m_s(eps_r)


def check_window(
    distance_m: float, eps_r: float, window_s: float, dt_s: float
) -> WindowCheck:
    """Time window must cover two-way travel; sample count must fit it."""
    twt = two_way_travel_s(distance_m, eps_r)
    ok = window_s >= twt
    note = (
        f"two-way {twt:.3e} s vs window {window_s:.3e} s "
        f"({int(window_s / dt_s)} samples)"
    )
    if not ok:
        note += " — window too short"
    return WindowCheck(twt, window_s, ok, note)


def pml_clearance_m(
    pml_layers: int, cells_m: float | Sequence[float]
) -> dict[str, float]:
    """PML thickness in metres per axis for a given layer count."""
    if pml_layers <= 0:
        raise ValueError("pml_layers must be positive")
    dx, dy, dz = _cell_vector(cells_m)
    return {
        "x": pml_layers * dx,
        "y": pml_layers * dy,
        "z": pml_layers * dz,
    }


def grid_cells_total(
    domain_m: tuple[float, float, float],
    cell_m: tuple[float, float, float],
) -> int:
    """Return realised cell count for an exactly grid-aligned domain.

    Silently applying ``ceil`` changes the physical domain.  Reject an
    unaligned extent so the caller must explicitly snap the geometry and
    record that realised value in the contract.
    """
    if len(domain_m) != 3 or len(cell_m) != 3:
        raise ValueError("domain_m and cell_m must each contain x, y, z")
    counts: list[int] = []
    for axis, extent, cell in zip("xyz", domain_m, cell_m):
        if not (math.isfinite(extent) and math.isfinite(cell)) or extent <= 0 or cell <= 0:
            raise ValueError(f"{axis}: domain extent and cell size must be positive and finite")
        ratio = extent / cell
        realised = round(ratio)
        if not math.isclose(ratio, realised, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError(
                f"{axis}: domain extent {extent} m is not an integer multiple "
                f"of cell size {cell} m (ratio={ratio:.12g}); explicitly align it"
            )
        counts.append(int(realised))
    nx, ny, nz = counts
    return nx * ny * nz


def estimate_resources(
    domain_m: tuple[float, float, float],
    cell_m: tuple[float, float, float],
    window_s: float,
    dt_s: float,
    bytes_per_cell_fp32: float = BYTES_PER_CELL_FP32_DEFAULT,
    gpu_throughput_cells_per_s: float | None = None,
) -> ResourceEstimate:
    """Rough planning figures as an *interval* estimate.

    ``bytes_per_cell_fp32`` defaults to a stated lower bound (six field
    components); pass a calibrated value for the real build. Throughput
    defaults to an order-of-magnitude GPU interval; pass a calibrated value
    for a concrete target. No pseudo-precision.
    """
    total = grid_cells_total(domain_m, cell_m)
    steps = max(1, int(math.ceil(window_s / dt_s)))
    update_ops = total * steps
    bytes_fp64 = bytes_per_cell_fp32 * 2.0

    if gpu_throughput_cells_per_s is not None:
        low = high = float(gpu_throughput_cells_per_s)
    else:
        low = GPU_THROUGHPUT_CELLS_PER_S_LOW
        high = GPU_THROUGHPUT_CELLS_PER_S_HIGH

    runtime_hours = update_ops / 3600.0
    return ResourceEstimate(
        cells_total=total,
        vram_gb_fp32=total * bytes_per_cell_fp32 / (1024**3),
        vram_gb_fp64=total * bytes_fp64 / (1024**3),
        runtime_hours_min=runtime_hours / high,
        runtime_hours_max=runtime_hours / low,
    )


def numerics_report(
    *,
    eps_r: float,
    max_frequency_hz: float,
    cells_m: float | Sequence[float],
    dt_s: float | None = None,
    domain_m: tuple[float, float, float],
    target_distance_m: float,
    window_s: float,
    pml_layers: int | None,
    minimum_cells: float = 10.0,
    project_cfl_safety_fraction: float | None = None,
    bytes_per_cell_fp32: float = BYTES_PER_CELL_FP32_DEFAULT,
    gpu_throughput_cells_per_s: float | None = None,
) -> dict[str, Any]:
    """Assemble a full setup-time numerics report as a plain mapping.

    All numbers derive from the supplied inputs; no placeholder values are
    injected. ``dt_s`` defaults to the CFL limit when not supplied (stated).
    """
    dx, dy, dz = _cell_vector(cells_m)
    cfl_limit = cfl_dt_s(dx, dy, dz)
    mesh = check_mesh(cells_m, eps_r, max_frequency_hz, minimum_cells)
    used_dt = dt_s if dt_s is not None else cfl_limit
    cfl = check_cfl(
        dx,
        dy,
        dz,
        used_dt,
        safety_fraction=project_cfl_safety_fraction,
    )
    window = check_window(target_distance_m, eps_r, window_s, used_dt)
    resource = estimate_resources(
        domain_m,
        (dx, dy, dz),
        window_s,
        used_dt,
        bytes_per_cell_fp32=bytes_per_cell_fp32,
        gpu_throughput_cells_per_s=gpu_throughput_cells_per_s,
    )
    pml = (
        pml_clearance_m(pml_layers, (dx, dy, dz))
        if pml_layers is not None
        else None
    )

    return {
        "mesh": {
            "cells_per_wavelength": {
                key: round(value, 2) for key, value in mesh.cells_per_wavelength.items()
            },
            "min_wavelength_m": round(mesh.min_wavelength_m, 4),
            "max_frequency_mhz": round(mesh.max_frequency_hz / 1e6, 2),
            "cells_m": {"dx": dx, "dy": dy, "dz": dz},
            "ok": mesh.ok,
            "note": mesh.note,
        },
        "cfl": {
            "dt_s": used_dt,
            "limit_s": cfl_limit,
            "explicit_dt": dt_s is not None,
            "ok": cfl.ok,
            "solver_ok": cfl.solver_ok,
            "project_safety_fraction": project_cfl_safety_fraction,
            "project_ok": cfl.project_ok,
            "note": cfl.note,
        },
        "window": {
            "two_way_s": window.two_way_s,
            "window_s": window_s,
            "samples": int(window_s / used_dt),
            "ok": window.ok,
            "note": window.note,
        },
        "pml": {
            "layers": pml_layers,
            "source": "user_confirmed" if pml_layers is not None else "not_provided",
            "status": "KNOWN" if pml_layers is not None else "UNKNOWN",
            "thickness_m": (
                {key: round(value, 4) for key, value in pml.items()}
                if pml is not None
                else None
            ),
        },
        "resources": {
            "cells_total": resource.cells_total,
            "vram_gb_fp32": round(resource.vram_gb_fp32, 2),
            "vram_gb_fp64": round(resource.vram_gb_fp64, 2),
            "runtime_hours_min": round(resource.runtime_hours_min, 2),
            "runtime_hours_max": round(resource.runtime_hours_max, 2),
            "is_estimate": True,
            "note": (
                "VRAM is a lower bound (field components only); runtime is an "
                "interval over GPU throughput — pass calibrated values for a "
                "hardware target."
            ),
        },
    }


def report_to_text(report: Mapping[str, Any]) -> str:
    m = report.get("mesh", {})
    c = report.get("cfl", {})
    w = report.get("window", {})
    p = report.get("pml", {})
    r = report.get("resources", {})
    per_axis = m.get("cells_per_wavelength", {})
    mesh_part = " ".join(
        f"{key}/λ={value}" for key, value in per_axis.items()
    )
    lines = [
        "## 数值核算（setup-time numerics）",
        f"- 网格: {mesh_part} @ {m.get('max_frequency_mhz')} MHz  {'✅' if m.get('ok') else '⛔'}",
        f"- 时步: {c.get('note', '')}",
        f"- 时窗: {w.get('note', '')}  {'✅' if w.get('ok') else '⛔'}",
        f"- PML: {p.get('layers')} 层 x/y/z ≈ {p.get('thickness_m')} m",
        f"- 网格总量: {r.get('cells_total', 0):,} cells",
        f"- 显存(fp32/fp64): {r.get('vram_gb_fp32')} / {r.get('vram_gb_fp64')} GB（下限）",
        f"- 单卡耗时(区间估计): {r.get('runtime_hours_min')}–{r.get('runtime_hours_max')} h  [依赖 GPU 吞吐，非承诺]",
    ]
    return "\n".join(lines)
