"""Pre-run failure diagnostics for a model plan.

Before an expensive gprMax run, predict the common failure modes from the
declared model parameters alone (no simulation): insufficient VRAM, time
window too short for the farthest target, mesh resolution below the
cells/λ gate, PML clearance too thin, and tones above Nyquist. This turns
runtime errors into setup-time warnings.

Every check reuses the same physics in ``numerics.py``; nothing here invents
a second set of formulas. Missing optional inputs yield ``WARN``
diagnostics rather than a crash, and each independent check still runs so
one missing field does not hide the others.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from scripts import numerics

# gprMax default PML depth (layers). Below this, absorption is weak.
PML_DEFAULT_LAYERS = 10


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


def _coerce_float(value: Any) -> float | None:
    """Coerce a value to float, handling YAML's string-exponent gotcha.

    PyYAML (YAML 1.1) parses ``2e-6`` as a string because its float resolver
    requires a decimal point; only ``2.0e-6`` becomes a float. This helper
    converts such numeric-looking strings defensively.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return float(value)


def _parse_band_mhz(band: Any) -> tuple[float | None, str | None]:
    """Parse a ``'<lo>-<hi>'`` MHz band; returns (f_hi_hz, warn_message)."""
    if not isinstance(band, str) or "-" not in band:
        return None, "waveform.band_mhz missing or not '<lo>-<hi>' MHz"
    parts = [float(part) for part in band.split("-")]
    if len(parts) != 2:
        return None, "waveform.band_mhz must be '<lo>-<hi>' MHz"
    lo, hi = parts
    if not (0 < lo < hi):
        return None, f"waveform.band_mhz must satisfy 0 < lo < hi, got {band!r}"
    return hi * 1e6, None


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
    try:
        waveform = _mapping(contract.get("waveform"), "contract.waveform")
    except ValueError:
        waveform = {}

    eps_r = _coerce_float(medium.get("eps_r"))
    f_hi, band_warn = _parse_band_mhz(waveform.get("band_mhz"))
    dx = _coerce_float(numerics_cfg.get("dx_m"))
    dy = _coerce_float(numerics_cfg.get("dy_m")) or dx
    dz = _coerce_float(numerics_cfg.get("dz_m")) or dx
    dt = _coerce_float(numerics_cfg.get("dt_s"))
    window = _coerce_float(numerics_cfg.get("time_window_s"))
    pml = _coerce_float(numerics_cfg.get("pml_layers"))
    target_depth = _coerce_float(project.get("target_depth_m"))
    domain = contract.get("domain_m")
    precision = numerics_cfg.get("precision_requirement")

    # Material / band gates (needed by several checks below).
    if band_warn:
        findings.append(Diagnosis("band", "WARN", band_warn))
    if eps_r is None or eps_r <= 0:
        findings.append(
            Diagnosis("material", "WARN", "medium.eps_r missing — mesh/window checks skipped")
        )
    if dx is None or dx <= 0:
        findings.append(
            Diagnosis("mesh", "WARN", "numerics.dx_m missing — mesh/CFL/PML checks skipped")
        )

    # 1. mesh resolution
    if eps_r is not None and eps_r > 0 and f_hi is not None and dx is not None and dx > 0:
        mesh = numerics.check_mesh((dx, dy, dz), eps_r, f_hi)
        findings.append(
            Diagnosis("mesh", "BLOCK" if not mesh.ok else "OK", mesh.note)
        )

    # 2. CFL / time step
    if dx is not None and dx > 0:
        if dt is not None and dt > 0:
            cfl = numerics.check_cfl(dx, dy, dz, dt)
            findings.append(
                Diagnosis("cfl", "BLOCK" if not cfl.ok else "OK", cfl.note)
            )
        else:
            findings.append(
                Diagnosis("cfl", "WARN", "numerics.dt_s missing — CFL check skipped")
            )

    # 3. time window vs farthest target
    if (
        target_depth is not None
        and target_depth > 0
        and window is not None
        and eps_r is not None
        and eps_r > 0
    ):
        dt_for_window = dt if dt is not None and dt > 0 else numerics.cfl_dt_s(dx or 0.05, dy or 0.05, dz or 0.05)
        window_check = numerics.check_window(target_depth, eps_r, window, dt_for_window)
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
                "target_depth_m, time_window_s or eps_r missing — window coverage skipped",
            )
        )

    # 4. PML clearance
    if dx is not None and dx > 0 and pml is not None and pml > 0:
        clearance = numerics.pml_clearance_m(int(pml), (dx, dy, dz))
        # gprMax's default PML depth is 10 cells; below that absorption is weak.
        severity = "OK" if pml >= PML_DEFAULT_LAYERS else "WARN"
        findings.append(
            Diagnosis(
                "pml",
                severity,
                f"PML {int(pml)} layers -> clearance {clearance} m "
                f"(gprMax default is {PML_DEFAULT_LAYERS}; fewer may leak)",
            )
        )
    else:
        findings.append(
            Diagnosis("pml", "WARN", "numerics.pml_layers missing — PML check skipped")
        )

    # 5. Nyquist
    if f_hi is not None and dx is not None and dx > 0:
        dt_for_nyquist = dt if dt is not None and dt > 0 else numerics.cfl_dt_s(dx, dy, dz)
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
            findings.append(
                Diagnosis("nyquist", "OK", f"tones below Nyquist ({nyquist/1e6:.1f} MHz)")
            )

    # 6. VRAM (respect declared precision)
    if (
        isinstance(domain, (list, tuple))
        and len(domain) == 3
        and all(isinstance(v, (int, float)) and v > 0 for v in domain)
        and dx is not None
        and dx > 0
    ):
        window_for_vram = window if window is not None and window > 0 else 1e-6
        dt_for_vram = dt if dt is not None and dt > 0 else numerics.cfl_dt_s(dx, dy, dz)
        resource = numerics.estimate_resources(
            tuple(domain), (dx, dy, dz), window_for_vram, dt_for_vram
        )
        want_fp64 = precision in ("float64", "fp64") or (
            precision == "auto" and resource.vram_gb_fp64 <= (gpu_vram_gb or float("inf"))
        )
        if want_fp64:
            needed = resource.vram_gb_fp64
            label = "fp64"
        else:
            needed = resource.vram_gb_fp32
            label = "fp32"
        if gpu_vram_gb is not None and needed > gpu_vram_gb:
            findings.append(
                Diagnosis(
                    "vram",
                    "BLOCK",
                    f"{label} VRAM estimate {needed:.1f} GB > GPU {gpu_vram_gb:.1f} GB",
                )
            )
        else:
            findings.append(
                Diagnosis(
                    "vram",
                    "OK",
                    f"VRAM est. {resource.vram_gb_fp32:.1f} GB (fp32) / "
                    f"{resource.vram_gb_fp64:.1f} GB (fp64); using {label}",
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