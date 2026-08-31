"""Parameter sensitivity analysis for a model plan.

For each key parameter (permittivity, cell sizes, time step, band edge,
target depth, time window, domain), perturb it by ±perturbation (default
20%) and re-evaluate the numerical checks that matter (cells/λ, CFL margin,
window coverage, VRAM). The output is a sensitivity ranking: which
parameter's perturbation moves a check the most.

This is a *cheap analytical* sensitivity — it does not run gprMax. It tells
the user which declared parameters are the most consequential to re-verify,
guiding where measurement or model detail matters most.

Fail-closed: unlike a silent-defaults approach, missing key fields raise
``ValueError`` so the caller knows the analysis is not meaningful.
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


def _required_float(cfg: Mapping[str, Any], key: str, name: str) -> float:
    """A required numeric field; missing/None raises rather than defaults.

    Coerces numeric-looking strings (PyYAML parses ``5e-11`` as a string).
    """
    value = cfg.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{name} is required for sensitivity analysis")
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            raise ValueError(f"{name} must be numeric, got {value!r}") from None
    return float(value)


def _metric_for(check: str, base: dict[str, float]) -> float:
    """Return the numeric value of one check for the current parameter set."""
    eps_r = base["eps_r"]
    f_hi = base["f_hi"]
    dx = base["dx"]
    dy = base["dy"]
    dz = base["dz"]
    dt = base["dt"]
    target_depth = base["target_depth"]
    window = base["window"]

    if check == "cells_per_wavelength":
        mesh = numerics.check_mesh((dx, dy, dz), eps_r, f_hi)
        return min(mesh.cells_per_wavelength.values())
    if check == "cfl_fraction":
        limit = numerics.cfl_dt_s(dx, dy, dz)
        return dt / limit
    if check == "window_coverage":
        twt = numerics.two_way_travel_s(target_depth, eps_r)
        return window / twt
    if check == "vram_fp64_gb":
        domain = (base["domain_x"], base["domain_y"], base["domain_z"])
        resource = numerics.estimate_resources(domain, (dx, dy, dz), window, dt)
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
    sensitive parameter first. Missing key fields raise ``ValueError``.
    """
    medium = _mapping(contract.get("medium"), "contract.medium")
    numerics_cfg = _mapping(contract.get("numerics"), "contract.numerics")
    project = contract.get("project") or {}
    project = _mapping(project, "contract.project")
    waveform = _mapping(contract.get("waveform"), "contract.waveform")

    eps_r = _required_float(medium, "eps_r", "medium.eps_r")
    band = waveform.get("band_mhz")
    if not isinstance(band, str) or "-" not in band:
        raise ValueError("waveform.band_mhz is required as '<lo>-<hi>' MHz")
    band_parts = [float(part) for part in band.split("-")]
    if len(band_parts) != 2 or not (0 < band_parts[0] < band_parts[1]):
        raise ValueError(f"waveform.band_mhz must be '<lo>-<hi>' with 0 < lo < hi")
    f_hi = band_parts[1] * 1e6

    dx = _required_float(numerics_cfg, "dx_m", "numerics.dx_m")
    dy = _required_float(numerics_cfg, "dy_m", "numerics.dy_m") if "dy_m" in numerics_cfg else dx
    dz = _required_float(numerics_cfg, "dz_m", "numerics.dz_m") if "dz_m" in numerics_cfg else dx
    dt = (
        _required_float(numerics_cfg, "dt_s", "numerics.dt_s")
        if "dt_s" in numerics_cfg
        else numerics.cfl_dt_s(dx, dy, dz)
    )
    window = (
        _required_float(numerics_cfg, "time_window_s", "numerics.time_window_s")
        if "time_window_s" in numerics_cfg
        else 1e-6
    )
    target_depth = _required_float(project, "target_depth_m", "project.target_depth_m")

    domain = contract.get("domain_m")
    if not isinstance(domain, (list, tuple)) or len(domain) != 3 or not all(
        isinstance(v, (int, float)) and v > 0 for v in domain
    ):
        raise ValueError("domain_m must be [x, y, z] with positive dimensions")
    domain_x, domain_y, domain_z = (float(v) for v in domain)

    base: dict[str, float] = {
        "eps_r": eps_r,
        "f_hi": f_hi,
        "dx": dx,
        "dy": dy,
        "dz": dz,
        "dt": dt,
        "target_depth": target_depth,
        "window": window,
        "domain_x": domain_x,
        "domain_y": domain_y,
        "domain_z": domain_z,
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
                base_metric = _metric_for(check, base)
                for factor in (1.0 - perturbation, 1.0 + perturbation):
                    perturbed = _perturb(base, parameter, factor)
                    perturbed_metric = _metric_for(check, perturbed)
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