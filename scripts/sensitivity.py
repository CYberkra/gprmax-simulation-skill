"""Parameter sensitivity analysis for a model plan.

For each key parameter (permittivity, conductivity, cell size, PML layers,
time window), perturb it by ±perturbation (default 20%) and re-evaluate the
numerical checks that matter (cells/λ, CFL margin, window coverage, VRAM).
The output is a sensitivity ranking: which parameter's perturbation moves a
check the most.

This is a *cheap analytical* sensitivity — it does not run gprMax. It tells
the user which declared parameters are the most consequential to re-verify,
guiding where measurement or model detail matters most.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from scripts import numerics


@dataclass(frozen=True)
class Sensitivity:
    parameter: str
    check: str
    base_value: float
    perturbed_value: float
    base_metric: float
    perturbed_metric: float
    relative_change: float  # |Δmetric| / |metric| (fraction)

    def to_dict(self) -> dict[str, float | str]:
        return {
            "parameter": self.parameter,
            "check": self.check,
            "base_value": self.base_value,
            "perturbed_value": self.perturbed_value,
            "base_metric": self.base_metric,
            "perturbed_metric": self.perturbed_metric,
            "relative_change": self.relative_change,
        }


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    return value


def _metric_for(check: str, contract: Mapping[str, Any], base: dict[str, float]) -> float:
    """Return the numeric value of one check for the current parameter set."""
    eps_r = base.get("eps_r", 4.0)
    f_hi = base.get("f_hi", 200e6)
    dx = base.get("dx", 0.05)
    dy = base.get("dy", 0.05)
    dz = base.get("dz", 0.05)
    dt = base.get("dt", numerics.cfl_dt_s(dx, dy, dz))
    target_depth = base.get("target_depth", 60.0)
    window = base.get("window", 1e-6)

    if check == "cells_per_wavelength":
        return numerics.check_mesh((dx, dy, dz), eps_r, f_hi).cells_per_wavelength["Nx"]
    if check == "cfl_fraction":
        limit = numerics.cfl_dt_s(dx, dy, dz)
        return dt / limit
    if check == "window_coverage":
        twt = numerics.two_way_travel_s(target_depth, eps_r)
        return window / twt
    if check == "vram_fp64_gb":
        resource = numerics.estimate_resources(
            (base.get("domain_x", 60.0), 16.0, 7.0), (dx, dy, dz), window, dt
        )
        return resource.vram_gb_fp64
    raise ValueError(f"unknown check: {check}")


def _perturb(base: dict[str, float], key: str, factor: float) -> dict[str, float]:
    out = dict(base)
    if key in out:
        out[key] = out[key] * factor
    return out


def analyse_sensitivity(
    contract: Mapping[str, Any],
    *,
    perturbation: float = 0.2,
    parameters: Sequence[str] | None = None,
    checks: Sequence[str] | None = None,
) -> list[Sensitivity]:
    """Perturb each declared parameter and measure check movement.

    ``parameters`` defaults to the keys present in the plan; ``checks``
    defaults to the four standard checks. Returns a list sorted by the most
    sensitive parameter first.
    """
    medium = _mapping(contract.get("medium"), "contract.medium")
    numerics_cfg = _mapping(contract.get("numerics"), "contract.numerics")
    project = contract.get("project") or {}
    project = _mapping(project, "contract.project")
    waveform = contract.get("waveform") or {}
    waveform = _mapping(waveform, "contract.waveform")

    eps_r = medium.get("eps_r", 4.0)
    band = waveform.get("band_mhz")
    f_hi = 200e6
    if isinstance(band, str) and "-" in band:
        try:
            f_hi = float(band.split("-")[1]) * 1e6
        except ValueError:
            f_hi = 200e6

    dx = numerics_cfg.get("dx_m", 0.05)
    dy = numerics_cfg.get("dy_m", dx)
    dz = numerics_cfg.get("dz_m", dx)
    dt = numerics_cfg.get("dt_s", numerics.cfl_dt_s(dx, dy, dz))
    domain = contract.get("domain_m")
    domain_x = domain[0] if isinstance(domain, (list, tuple)) and len(domain) >= 1 else 60.0

    base: dict[str, float] = {
        "eps_r": float(eps_r),
        "f_hi": float(f_hi),
        "dx": float(dx),
        "dy": float(dy),
        "dz": float(dz),
        "dt": float(dt),
        "target_depth": float(project.get("target_depth_m", 60.0)),
        "window": float(numerics_cfg.get("time_window_s", 1e-6)),
        "domain_x": float(domain_x),
    }

    if parameters is None:
        parameters = tuple(base.keys())
    if checks is None:
        checks = ("cells_per_wavelength", "cfl_fraction", "window_coverage", "vram_fp64_gb")

    results: list[Sensitivity] = []
    for parameter in parameters:
        if parameter not in base:
            continue
        for check in checks:
            try:
                base_metric = _metric_for(check, contract, base)
                for factor in (1.0 - perturbation, 1.0 + perturbation):
                    perturbed = _perturb(base, parameter, factor)
                    perturbed_metric = _metric_for(check, contract, perturbed)
                    if abs(base_metric) < 1e-12:
                        continue
                    relative = abs(perturbed_metric - base_metric) / abs(base_metric)
                    results.append(
                        Sensitivity(
                            parameter=parameter,
                            check=check,
                            base_value=base[parameter],
                            perturbed_value=perturbed[parameter],
                            base_metric=base_metric,
                            perturbed_metric=perturbed_metric,
                            relative_change=relative,
                        )
                    )
            except (ValueError, ZeroDivisionError):
                continue

    results.sort(key=lambda item: item.relative_change, reverse=True)
    return results


def render_sensitivity(results: Sequence[Sensitivity]) -> str:
    if not results:
        return "无敏感性结果（参数或检查不可用）"
    lines = ["## 参数敏感性分析（analytical, ±perturbation）"]
    lines.append("| 参数 | 检查 | 基准指标 | 扰动指标 | 相对变化 |")
    lines.append("|---|---|---|---|---|")
    for item in results[:20]:
        lines.append(
            f"| {item.parameter} | {item.check} | {item.base_metric:.4g} "
            f"| {item.perturbed_metric:.4g} | {item.relative_change:.2%} |"
        )
    return "\n".join(lines)


def rank_most_sensitive(
    results: Sequence[Sensitivity], top: int = 3
) -> list[Sensitivity]:
    """The parameters whose perturbation moves some check the most."""
    best_per_parameter: dict[str, Sensitivity] = {}
    for item in results:
        current = best_per_parameter.get(item.parameter)
        if current is None or item.relative_change > current.relative_change:
            best_per_parameter[item.parameter] = item
    ranked = sorted(
        best_per_parameter.values(), key=lambda item: item.relative_change, reverse=True
    )
    return ranked[:top]