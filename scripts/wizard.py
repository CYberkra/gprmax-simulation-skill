"""Guided-setup session state machine.

The agent drives the conversation; this module keeps the session state:
step progress, validated answers, back support, and a final dump that produces
the answers record, the per-axis recommendations, dependency markers, a
numerics report, and a simulation_contract.yaml draft.

Discipline:
- no placeholder values: numerics are computed only from confirmed inputs,
  otherwise the report is absent/UNKNOWN and the caller is told why;
- scan factors are declared explicitly by the user, never inferred from
  ordinary model parameters;
- `dump` validates band format, axis options, numeric ranges, and session
  completeness before producing anything;
- `init` never overwrites an existing session without `--force`.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from scripts import axes
from scripts import numerics

SESSION_FILE = "session.json"
STEPS: tuple[str, ...] = (
    "scenario",
    "target_medium",
    "band_mode",
    "fidelity",
    "environment",
)

_BAND_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*$")

# Stated margin applied when deriving the time window from the two-way travel
# to the farthest target (window = 2·distance/v · WINDOW_MARGIN).
WINDOW_MARGIN = 1.5

# Fields that must be answered before a dump is allowed.
REQUIRED_FIELDS = (
    "scenario_type",
    "target_depth_m",
    "target_material",
    "medium_material",
    "needs_sfcw",
    "band_mhz",
    "fidelity",
    "dimension",
    "run_env",
)
# Optional fields that refine numerics but never block a dump.
OPTIONAL_FIELDS = {
    "domain_m",
    "pml_layers",
    "medium_eps_r",
    "custom_cells_m",
    "scan_factors",
}

STEP_FIELDS: dict[str, dict[str, Any]] = {
    "scenario": {
        "question": "场景类型与目标深度？",
        "fields": {
            "scenario_type": {
                "label": "场景类型",
                "choices": axes.SCENARIOS,
            },
            "target_depth_m": {"label": "目标埋深/距离 (m)", "type": "number"},
            "domain_m": {
                "label": "域尺寸 x,y,z (m，可选)",
                "type": "triple",
                "optional": True,
            },
            "pml_layers": {
                "label": "PML 层数（可选）",
                "type": "int",
                "optional": True,
            },
        },
    },
    "target_medium": {
        "question": "目标与围岩介质？（未知填 unknown）",
        "fields": {
            "target_material": {"label": "目标材料", "type": "str"},
            "medium_material": {"label": "围岩介质", "type": "str"},
            "medium_eps_r": {
                "label": "围岩 ε_r（可选，供数值核算）",
                "type": "number",
                "optional": True,
            },
            "scan_factors": {
                "label": "扫描因素（逗号分隔，空=单变量；可选）",
                "type": "factors",
                "optional": True,
            },
        },
    },
    "band_mode": {
        "question": "频段与体制？",
        "fields": {
            "needs_sfcw": {"label": "需要 SFCW 体制结论", "type": "bool"},
            "band_mhz": {"label": "频率范围 (如 20-300)", "type": "band"},
        },
    },
    "fidelity": {
        "question": "拟真度取向？",
        "fields": {
            "fidelity": {"label": "拟真度", "choices": axes.FIDELITY_INTENTS},
            "dimension": {
                "label": "模型维度",
                "choices": tuple(item.id for item in axes.axis_by_id("dimension").options),
            },
            "custom_cells_m": {
                "label": "自定义网格 dx,dy,dz (m，可选)",
                "type": "triple",
                "optional": True,
            },
        },
    },
    "environment": {
        "question": "运行环境？",
        "fields": {
            "run_env": {"label": "本机/服务器", "choices": ("local", "server")},
        },
    },
}


class WizardError(ValueError):
    """Invalid session state or answer."""


@dataclass
class Session:
    path: Path
    answers: dict[str, Any] = field(default_factory=dict)

    @property
    def state_path(self) -> Path:
        return self.path / SESSION_FILE

    def field_index(self, field: str) -> int:
        for index, step in enumerate(STEPS):
            if field in STEP_FIELDS[step]["fields"]:
                return index
        raise WizardError(f"unknown field: {field!r}")

    def remaining_fields(self, required_only: bool = False) -> list[str]:
        done = set(self.answers)
        return [
            field
            for step in STEPS
            for field, spec in STEP_FIELDS[step]["fields"].items()
            if field not in done and (not required_only or not spec.get("optional"))
        ]

    def incomplete_steps(self) -> list[str]:
        return [
            step
            for step in STEPS
            if any(
                field not in self.answers and not spec.get("optional")
                for field, spec in STEP_FIELDS[step]["fields"].items()
            )
        ]


def create_session(path: Path, force: bool = False) -> Session:
    session = Session(Path(path))
    if session.state_path.exists() and not force:
        raise WizardError(
            f"session already exists at {session.state_path} (use force=True to reset)"
        )
    session.path.mkdir(parents=True, exist_ok=True)
    save_session(session)
    return session


def load_session(path: Path) -> Session:
    state = Path(path) / SESSION_FILE
    if not state.is_file():
        raise WizardError(f"no session at {path}")
    value = json.loads(state.read_text(encoding="utf-8"))
    return Session(Path(path), answers=dict(value.get("answers", {})))


def save_session(session: Session) -> None:
    session.state_path.write_text(
        json.dumps(
            {"answers": session.answers}, indent=2, ensure_ascii=False, sort_keys=True
        )
        + "\n",
        encoding="utf-8",
    )


def _parse_band(value: str) -> tuple[float, float]:
    match = _BAND_PATTERN.match(value)
    if not match:
        raise WizardError(
            f"band_mhz must be '<low>-<high>' with positive numbers, got {value!r}"
        )
    low, high = float(match.group(1)), float(match.group(2))
    if not (0 < low < high):
        raise WizardError(f"band_mhz must satisfy 0 < low < high, got {value!r}")
    return low, high


def _parse_triple(value: Any) -> tuple[float, float, float]:
    try:
        if isinstance(value, (tuple, list)) and len(value) == 3:
            parts = tuple(float(item) for item in value)
        else:
            parts = tuple(
                float(part) for part in str(value).replace(" ", "").split(",")
            )
    except (TypeError, ValueError) as error:
        raise WizardError(f"expected three positive numbers 'x,y,z', got {value!r}") from error
    if len(parts) != 3 or not all(math.isfinite(v) and v > 0 for v in parts):
        raise WizardError(
            f"expected three positive numbers 'x,y,z', got {value!r}"
        )
    return parts


def _validate_answer(field: str, value: Any, spec: Mapping[str, Any]) -> Any:
    kind = spec.get("type")
    if kind == "number":
        try:
            number = float(value)
        except (TypeError, ValueError) as error:
            raise WizardError(f"{field}: expected a number, got {value!r}") from error
        if not math.isfinite(number) or number < 0:
            raise WizardError(f"{field}: must be a non-negative finite number")
        return number
    if kind == "int":
        if isinstance(value, float) and not value.is_integer():
            raise WizardError(f"{field}: expected an integer, got {value!r}")
        try:
            integer = int(value)
        except (TypeError, ValueError) as error:
            raise WizardError(f"{field}: expected an integer, got {value!r}") from error
        if integer <= 0:
            raise WizardError(f"{field}: must be a positive integer")
        return integer
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("true", "yes", "1", "y"):
                return True
            if lowered in ("false", "no", "0", "n"):
                return False
        raise WizardError(f"{field}: expected a boolean")
    if kind == "band":
        low, high = _parse_band(str(value))
        return f"{low:g}-{high:g}"
    if kind == "triple":
        return _parse_triple(value)
    if kind == "factors":
        if isinstance(value, (list, tuple)):
            factors = [str(item).strip() for item in value]
        else:
            factors = [item.strip() for item in str(value).split(",") if item.strip()]
        return factors
    choices = spec.get("choices")
    if choices is not None:
        if value not in choices:
            raise WizardError(f"{field}: must be one of {choices}, got {value!r}")
        return value
    if not isinstance(value, str) or not value.strip():
        raise WizardError(f"{field}: expected non-empty text")
    return value.strip()


def answer(session: Session, field: str, value: Any) -> Any:
    step_index = session.field_index(field)
    spec = STEP_FIELDS[STEPS[step_index]]["fields"][field]
    validated = _validate_answer(field, value, spec)
    session.answers[field] = validated
    save_session(session)
    return validated


def back(session: Session, steps: int = 1) -> list[str]:
    """Remove the most recent *steps* answers (in insertion order), supporting corrections."""
    ordered = list(session.answers)
    if not ordered:
        raise WizardError("nothing to step back from")
    removed: list[str] = []
    for field in list(reversed(ordered))[:steps]:
        session.answers.pop(field, None)
        removed.append(field)
    save_session(session)
    return list(reversed(removed))


def status(session: Session) -> dict[str, Any]:
    remaining = session.remaining_fields(required_only=True)
    return {
        "complete": not remaining,
        "remaining_required_fields": remaining,
        "incomplete_steps": session.incomplete_steps(),
        "answered": sorted(session.answers),
    }


def validate_for_dump(session: Session) -> list[str]:
    """Re-validate every stored answer and session completeness.

    Returns a list of problems; empty means the session is dump-ready. This
    re-checks fields even if session.json was hand-edited.
    """
    problems: list[str] = []
    for field in REQUIRED_FIELDS:
        step_index = session.field_index(field)
        spec = STEP_FIELDS[STEPS[step_index]]["fields"][field]
        if field not in session.answers:
            problems.append(f"missing required field: {field}")
            continue
        try:
            _validate_answer(field, session.answers[field], spec)
        except WizardError as error:
            problems.append(str(error))
    for field in OPTIONAL_FIELDS:
        if field not in session.answers:
            continue
        step_index = session.field_index(field)
        spec = STEP_FIELDS[STEPS[step_index]]["fields"][field]
        try:
            validated = _validate_answer(field, session.answers[field], spec)
            session.answers[field] = validated
        except WizardError as error:
            problems.append(str(error))
    if not problems:
        save_session(session)
    return problems


def _recommendations(session: Session) -> dict[str, dict[str, str]]:
    scenario = session.answers.get("scenario_type", "other")
    fidelity = session.answers.get("fidelity", "standard")
    needs_sfcw = session.answers.get("needs_sfcw")
    return axes.recommend(scenario, fidelity, needs_sfcw=needs_sfcw)


def _numerics_from_answers(session: Session) -> dict[str, Any] | None:
    """Compute numerics only from *confirmed* inputs.

    Returns None (with a reason attached to the caller) if any required
    numeric input is missing. ``window`` is derived from the two-way travel
    with a stated 1.5× margin — a declared rule, not a placeholder material
    value; PML remains explicitly UNKNOWN unless ``pml_layers`` was given.
    """
    missing: list[str] = []
    medium_eps_r = session.answers.get("medium_eps_r")
    if medium_eps_r is None:
        missing.append("medium_eps_r")
    cells_m = session.answers.get("custom_cells_m")
    if cells_m is None:
        missing.append("custom_cells_m")
    domain_m = session.answers.get("domain_m")
    if domain_m is None:
        missing.append("domain_m")
    if missing:
        return None

    try:
        eps_r = float(medium_eps_r)  # type: ignore[arg-type]
        band = str(session.answers.get("band_mhz", ""))
        low_hz, high_hz = (float(part) * 1e6 for part in band.split("-"))
        target_distance_m = float(session.answers["target_depth_m"])
    except (TypeError, ValueError, KeyError):
        return None

    two_way = numerics.two_way_travel_s(target_distance_m, eps_r)
    window_s = two_way * WINDOW_MARGIN
    pml_layers = session.answers.get("pml_layers")
    try:
        report = numerics.numerics_report(
            eps_r=eps_r,
            max_frequency_hz=high_hz,
            cells_m=cells_m,  # type: ignore[arg-type]
            domain_m=tuple(domain_m),  # type: ignore[arg-type]
            target_distance_m=target_distance_m,
            window_s=window_s,
            pml_layers=pml_layers,
        )
    except ValueError as error:
        raise WizardError(f"numeric setup invalid: {error}") from error
    report["window"]["derived_from"] = "two-way travel × 1.5 (stated margin rule)"
    return report


def dump(session: Session) -> dict[str, Any]:
    """Validate, then produce the full setup dump."""
    problems = validate_for_dump(session)
    if problems:
        raise WizardError("; ".join(problems))

    recommendations = _recommendations(session)
    chosen = {axis: rec["option"] for axis, rec in recommendations.items()}
    markers = axes.markers_for(chosen)
    report = _numerics_from_answers(session)
    return {
        "answers": dict(session.answers),
        "recommendations": recommendations,
        "dependency_markers": markers,
        "numerics": report,
        "numerics_unknown_reason": (
            None
            if report is not None
            else "numeric inputs incomplete (need medium_eps_r, custom_cells_m, domain_m)"
        ),
        "contract_draft": _contract_draft(session, recommendations),
    }


def _contract_draft(
    session: Session, recommendations: Mapping[str, Mapping[str, str]]
) -> dict[str, Any]:
    factors = list(session.answers.get("scan_factors", []))
    # Keep the public contract vocabulary aligned with SKILL.md:
    # single_variable | multi_factor.  The subtype preserves the important
    # distinction between a single case and an actual one-factor sweep.
    design_type = "multi_factor" if len(factors) > 1 else "single_variable"
    design_subtype = "single_case" if not factors else (
        "one_factor" if len(factors) == 1 else "factorial"
    )
    sfcw_enabled = chosen_sfcw(recommendations)
    dimension = session.answers.get("dimension")
    project = {
        "design_type": design_type,
        "design_subtype": design_subtype,
        "factors": factors,
        "invariants": [],
        "note": "factors declared by the user; other parameters are fixed controls",
    }
    if "target_depth_m" in session.answers:
        project["target_depth_m"] = float(session.answers["target_depth_m"])
    return {
        "project": project,
        "model": {
            "dimension": dimension if dimension in {"2d", "2.5d", "3d"} else "unknown",
        },
        "task": {
            "objective": session.answers.get("scenario_type", "other"),
            "claim_scope": "numerical",
        },
        "medium": {
            "target_material": session.answers.get("target_material", "unknown"),
            "medium_material": session.answers.get("medium_material", "unknown"),
            "model_type": recommendations.get("dispersion", {}).get("option", "none"),
            "parameter_source": "assumed",
        },
        "waveform": {
            # ``excitation_mode`` is retained for the current schema and old
            # consumers.  The three explicit fields prevent a processing
            # route from being mistaken for a solver excitation.
            "excitation_mode": "unit_impulse" if sfcw_enabled else "pulse_broadband",
            "solver_excitation": "unit_impulse" if sfcw_enabled else "pulse_broadband",
            "measurement_mode": "sfcw_equivalent" if sfcw_enabled else "time_domain",
            "processing_route": "impulse_lti" if sfcw_enabled else "direct_time_domain",
            "band_mhz": session.answers.get("band_mhz"),
        },
        "numerics": {
            "precision_requirement": recommendations.get("precision", {}).get(
                "option", "fp32"
            ),
            "pml_layers": session.answers.get("pml_layers", "unknown"),
            "note": "cells/λ, CFL, window coverage: see numerics report (UNKNOWN until inputs confirmed)",
        },
        "geometry": {
            "target_level": recommendations.get("geometry", {}).get("option", "L1"),
            "antenna": recommendations.get("antenna", {}).get(
                "option", "ideal_hertzian"
            ),
            "noise": recommendations.get("noise", {}).get("option", "none"),
        },
        "acceptance": {"negative_controls": [], "sensitivity_tests": []},
        "evidence": {"required_outputs": ["rxs/rx1/Ez"], "provenance_level": "strict"},
    }


def chosen_sfcw(recommendations: Mapping[str, Mapping[str, str]]) -> bool:
    return recommendations.get("sfcw", {}).get("option") == "on"


def dump_to_yaml(session: Session) -> str:
    import yaml

    return yaml.safe_dump(dump(session), sort_keys=False, allow_unicode=True)
