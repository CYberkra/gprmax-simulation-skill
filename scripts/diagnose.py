"""Pre-run failure diagnostics for a model plan.

Before an expensive gprMax run, predict the common failure modes from the
declared model parameters alone (no simulation): insufficient VRAM, time
window too short for the farthest target, mesh resolution below the
cells/λ gate, PML clearance too thin, and tones above Nyquist. This turns
runtime errors into setup-time warnings.

Every check reuses the same physics in ``numerics.py``; nothing here invents
a second set of formulas. The result is a list of diagnostics, each with a
severity (``BLOCK`` / ``WARN`` / ``OK``) and a human-readable message.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from scripts import numerics


@dataclass(frozen=True)
class Diagnosis:
    check: str
    severity: str  # BLOCK | WARN | OK
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"check": self.check, "severity": self.severity, "message": self.message}


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    return value


def _as_float(cfg: Mapping[str, Any], key: str) -> float | None:
    """Coerce a numerics value to float, handling YAML's string-exponent gotcha.

    PyYAML (YAML 1.1) parses ``2e-6`` as a string because its float resolver
    requires a decimal point; only ``2.0e-6`` becomes a float. This helper
    converts such numeric-looking strings defensively.
    """
    value = cfg.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return float(value)


def diagnose_model(
    contract: Mapping[str, Any],
    *,
    gpu_vram_gb: float | None = None,
) -> list[Diagnosis]:
    """Predict failure modes from the model contract.

    ``contract`` carries ``medium`` (eps_r), ``waveform`` (band),
    ``numerics`` (dx/dy/dz, dt, time window, PML, precision), and
    ``project.target_depth_m``. Missing optional inputs yield ``WARN``
    diagnostics rather than a crash.
    """
    findings: list[Diagnosis] = []

    medium = _mapping(contract.get("medium"), "contract.medium")
    numerics_cfg = _mapping(contract.get("numerics"), "contract.numerics")
    project = contract.get("project") or {}
    project = _mapping(project, "contract.project")

    eps_r = medium.get("eps_r")
    if not isinstance(eps_r, (int, float)) or eps_r <= 0:
        findings.append(
            Diagnosis("material", "WARN", "medium.eps_r missing — cannot verify mesh resolution")
        )
        return findings

    band = contract.get("waveform", {}).get("band_mhz")
    f_hi = None
    if isinstance(band, str) and "-" in band:
        try:
            f_hi = float(band.split("-")[1]) * 1e6
        except ValueError:
            f_hi = None
    if f_hi is None:
        findings.append(
            Diagnosis("band", "WARN", "waveform.band_mhz missing — cannot verify Nyquist / mesh")
        )
        return findings

    dx = numerics_cfg.get("dx_m")
    dy = numerics_cfg.get("dy_m")
    dz = numerics_cfg.get("dz_m")
    if not isinstance(dx, (int, float)) or dx <= 0:
        findings.append(Diagnosis("mesh", "WARN", "numerics.dx_m missing — cannot verify mesh"))
        return findings
    dy = dy if isinstance(dy, (int, float)) and dy > 0 else dx
    dz = dz if isinstance(dz, (int, float)) and dz > 0 else dx

    # 1. mesh resolution
    mesh = numerics.check_mesh((dx, dy, dz), eps_r, f_hi)
    findings.append(
        Diagnosis(
            "mesh",
            "BLOCK" if not mesh.ok else "OK",
            mesh.note,
        )
    )

    # 2. CFL / time step
    dt = _as_float(numerics_cfg, "dt_s")
    if dt is not None and dt > 0:
        cfl = numerics.check_cfl(dx, dy, dz, dt)
        findings.append(
            Diagnosis(
                "cfl",
                "BLOCK" if not cfl.ok else "OK",
                cfl.note,
            )
        )
    else:
        findings.append(
            Diagnosis("cfl", "WARN", "numerics.dt_s missing — CFL check skipped")
        )

    # 3. time window vs farthest target
    target_depth = project.get("target_depth_m")
    window = _as_float(numerics_cfg, "time_window_s")
    if isinstance(target_depth, (int, float)) and window is not None:
        window_check = numerics.check_window(target_depth, eps_r, window, dt or numerics.cfl_dt_s(dx, dy, dz))
        findings.append(
            Diagnosis(
                "window",
                "BLOCK" if not window_check.ok else "OK",
                window_check.note,
            )
        )
    else:
        findings.append(
            Diagnosis(
                "window", "WARN",
                "target_depth_m or time_window_s missing — window coverage skipped",
            )
        )

    # 4. PML clearance
    pml = numerics_cfg.get("pml_layers")
    if isinstance(pml, (int, float)) and pml > 0:
        clearance = numerics.pml_clearance_m(int(pml), (dx, dy, dz))
        # Rule of thumb: clearance should be >= a few cells in each axis.
        severity = "OK"
        if min(clearance.values()) < 3 * min(dx, dy, dz):
            severity = "WARN"
        findings.append(
            Diagnosis(
                "pml",
                severity,
                f"PML {int(pml)} layers -> clearance {clearance} m",
            )
        )
    else:
        findings.append(
            Diagnosis("pml", "WARN", "numerics.pml_layers missing — PML check skipped")
        )

    # 5. Nyquist
    dt_for_nyquist = dt if isinstance(dt, (int, float)) and dt > 0 else numerics.cfl_dt_s(dx, dy, dz)
    nyquist = 0.5 / dt_for_nyquist
    if f_hi >= nyquist:
        findings.append(
            Diagnosis(
                "nyquist",
                "BLOCK",
                f"highest tone {f_hi/1e6:.1f} MHz >= Nyquist {nyquist/1e6:.1f} MHz",
            )
        )
    else:
        findings.append(Diagnosis("nyquist", "OK", f"tones below Nyquist ({nyquist/1e6:.1f} MHz)"))

    # 6. VRAM
    domain = contract.get("domain_m")
    if isinstance(domain, (list, tuple)) and len(domain) == 3 and all(
        isinstance(v, (int, float)) and v > 0 for v in domain
    ):
        resource = numerics.estimate_resources(
            tuple(domain), (dx, dy, dz), window or 1e-6, dt_for_nyquist
        )
        if gpu_vram_gb is not None and resource.vram_gb_fp64 > gpu_vram_gb:
            findings.append(
                Diagnosis(
                    "vram",
                    "BLOCK",
                    f"fp64 VRAM estimate {resource.vram_gb_fp64:.1f} GB > GPU {gpu_vram_gb:.1f} GB",
                )
            )
        elif gpu_vram_gb is not None and resource.vram_gb_fp32 > gpu_vram_gb:
            findings.append(
                Diagnosis(
                    "vram",
                    "WARN",
                    f"fp32 VRAM {resource.vram_gb_fp32:.1f} GB near GPU {gpu_vram_gb:.1f} GB",
                )
            )
        else:
            findings.append(
                Diagnosis(
                    "vram",
                    "OK",
                    f"VRAM est. {resource.vram_gb_fp32:.1f} GB (fp32) / {resource.vram_gb_fp64:.1f} GB (fp64)",
                )
            )
    else:
        findings.append(
            Diagnosis("vram", "WARN", "domain_m missing — VRAM check skipped")
        )

    return findings


def render_diagnostics(findings: Sequence[Diagnosis]) -> str:
    lines = ["## 仿真失败预诊断（pre-run diagnostics）"]
    for finding in findings:
        marker = {"BLOCK": "⛔", "WARN": "⚠️", "OK": "✅"}.get(finding.severity, "·")
        lines.append(f"{marker} [{finding.severity}] {finding.check}: {finding.message}")
    return "\n".join(lines)