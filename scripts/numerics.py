"""Quantitative numerical checks for the guided setup.

Converts a model plan into concrete numbers: cells per wavelength, the
CFL-limited time step, PML thickness and clearance, time-window coverage, and
rough VRAM / runtime estimates. All values are derived from first principles or
clearly-labelled engineering estimates; nothing here hard-codes a
project-specific band, distance, or permittivity.

Runtime/VRAM figures are order-of-magnitude estimates for planning only — label
them as such in any report.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

SPEED_OF_LIGHT_M_S = 299_792_458.0

# Rough per-cell FDTD field memory (E + H + aux) in bytes for fp32.
_BYTES_PER_CELL_FP32 = 12.0
# Rough sustained GPU throughput estimate for planning: cells updated per
# second (order of magnitude, depends on hardware and model).
_CELLS_PER_SECOND_GPU = 2.0e8


@dataclass(frozen=True)
class MeshCheck:
    cells_per_wavelength: float
    min_wavelength_m: float
    max_frequency_hz: float
    ok: bool
    note: str


@dataclass(frozen=True)
class CflCheck:
    dt_s: float
    cfl_fraction: float | None
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
    runtime_hours: float
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
    dx_m: float, eps_r: float, max_frequency_hz: float, minimum_cells: float = 10.0
) -> MeshCheck:
    """Cells per wavelength at the band top (the observable-controlling cell)."""
    min_wavelength = smallest_wavelength_m(eps_r, max_frequency_hz)
    cells = min_wavelength / dx_m
    ok = cells >= minimum_cells
    note = (
        f"{cells:.1f} cells/λ at {max_frequency_hz / 1e6:.0f} MHz "
        f"(λ_min={min_wavelength:.3f} m)"
    )
    if not ok:
        note += f" < {minimum_cells:.0f} required"
    return MeshCheck(cells, min_wavelength, max_frequency_hz, ok, note)


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
    safety_fraction: float = 0.95,
) -> CflCheck:
    """Check a chosen dt against the CFL limit (dt must be <= safety limit)."""
    limit = cfl_dt_s(dx_m, dy_m, dz_m)
    safe_limit = safety_fraction * limit
    ok = dt_s <= safe_limit
    fraction = dt_s / limit
    note = f"dt={dt_s:.3e} s vs CFL {limit:.3e} s ({fraction:.2f}×)"
    if not ok:
        note += " exceeds safety limit"
    return CflCheck(dt_s, fraction, ok, note)


def two_way_travel_s(distance_m: float, eps_r: float) -> float:
    return 2.0 * distance_m / phase_velocity_m_s(eps_r)


def check_window(
    distance_m: float, eps_r: float, window_s: float, dt_s: float
) -> WindowCheck:
    """Time window must cover two-way travel; sample count must fit it."""
    twt = two_way_travel_s(distance_m, eps_r)
    ok = window_s > twt
    note = (
        f"two-way {twt:.2e} s vs window {window_s:.2e} s "
        f"({int(window_s / dt_s)} samples)"
    )
    if not ok:
        note += " — window too short"
    return WindowCheck(twt, window_s, ok, note)


def pml_clearance_m(pml_layers: int, cell_size_m: float) -> float:
    """PML thickness in metres for a given layer count (same cell size)."""
    if pml_layers <= 0:
        raise ValueError("pml_layers must be positive")
    return pml_layers * cell_size_m


def grid_cells_total(
    domain_m: tuple[float, float, float],
    cell_m: tuple[float, float, float],
) -> int:
    nx = math.ceil(domain_m[0] / cell_m[0])
    ny = math.ceil(domain_m[1] / cell_m[1])
    nz = math.ceil(domain_m[2] / cell_m[2])
    return nx * ny * nz


def estimate_resources(
    domain_m: tuple[float, float, float],
    cell_m: tuple[float, float, float],
    window_s: float,
    dt_s: float,
) -> ResourceEstimate:
    """Rough planning figures: total cells, VRAM, single-GPU wall time."""
    total = grid_cells_total(domain_m, cell_m)
    steps = max(1, int(math.ceil(window_s / dt_s)))
    update_ops = total * steps
    return ResourceEstimate(
        cells_total=total,
        vram_gb_fp32=total * _BYTES_PER_CELL_FP32 / (1024**3),
        vram_gb_fp64=total * _BYTES_PER_CELL_FP32 * 2 / (1024**3),
        runtime_hours=update_ops / _CELLS_PER_SECOND_GPU / 3600.0,
    )


def numerics_report(
    *,
    eps_r: float,
    max_frequency_hz: float,
    dx_m: float,
    dy_m: float | None = None,
    dz_m: float | None = None,
    dt_s: float | None = None,
    domain_m: tuple[float, float, float],
    target_distance_m: float,
    window_s: float,
    pml_layers: int,
    minimum_cells: float = 10.0,
) -> dict[str, Any]:
    """Assemble a full setup-time numerics report as a plain mapping.

    ``dt_s`` defaults to the CFL limit when not supplied, and the report notes
    that choice.
    """
    mesh = check_mesh(dx_m, eps_r, max_frequency_hz, minimum_cells)
    used_dt = dt_s if dt_s is not None else cfl_dt_s(dx_m, dy_m, dz_m)
    cfl = check_cfl(dx_m, dy_m, dz_m, used_dt) if dt_s is not None else None
    window = check_window(target_distance_m, eps_r, window_s, used_dt)
    resource = estimate_resources(domain_m, (dx_m, dy_m or dx_m, dz_m or dx_m), window_s, used_dt)
    pml = pml_clearance_m(pml_layers, min(dx_m, dy_m or dx_m, dz_m or dx_m))

    return {
        "mesh": {
            "cells_per_wavelength": round(mesh.cells_per_wavelength, 2),
            "min_wavelength_m": round(mesh.min_wavelength_m, 4),
            "max_frequency_mhz": round(mesh.max_frequency_hz / 1e6, 2),
            "ok": mesh.ok,
            "note": mesh.note,
        },
        "cfl": {
            "dt_s": used_dt,
            "limit_s": cfl_dt_s(dx_m, dy_m, dz_m),
            "explicit_dt": dt_s is not None,
            "ok": cfl.ok if cfl else True,
            "note": cfl.note if cfl else "dt taken at CFL limit",
        },
        "window": {
            "two_way_s": round(window.two_way_s, 6),
            "window_s": window_s,
            "samples": int(window_s / used_dt),
            "ok": window.ok,
            "note": window.note,
        },
        "pml": {
            "layers": pml_layers,
            "thickness_m": round(pml, 4),
        },
        "resources": {
            "cells_total": resource.cells_total,
            "vram_gb_fp32": round(resource.vram_gb_fp32, 2),
            "vram_gb_fp64": round(resource.vram_gb_fp64, 2),
            "runtime_hours_estimate": round(resource.runtime_hours, 2),
            "is_estimate": True,
        },
    }


def report_to_text(report: Mapping[str, Any]) -> str:
    m = report.get("mesh", {})
    c = report.get("cfl", {})
    w = report.get("window", {})
    p = report.get("pml", {})
    r = report.get("resources", {})
    lines = [
        "## 数值核算（setup-time numerics）",
        f"- 网格: {m.get('note', '')}  {'✅' if m.get('ok') else '⛔'}",
        f"- 时步: {c.get('note', '')}",
        f"- 时窗: {w.get('note', '')}  {'✅' if w.get('ok') else '⛔'}",
        f"- PML: {p.get('layers')} 层 ≈ {p.get('thickness_m')} m",
        f"- 网格总量: {r.get('cells_total', 0):,} cells",
        f"- 显存(fp32/fp64): {r.get('vram_gb_fp32')} / {r.get('vram_gb_fp64')} GB",
        f"- 单卡耗时(粗估): {r.get('runtime_hours_estimate')} h  [估算值，非承诺]",
    ]
    return "\n".join(lines)