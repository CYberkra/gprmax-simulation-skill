"""Guided-setup session state machine.

The agent drives the conversation; this module keeps the session state:
step progress, validated answers, back support, and a final dump that produces
the answers record, the per-axis recommendations, dependency markers, a
numerics report, and a simulation_contract.yaml draft.

Sessions are plain directories holding a `session.json` state file, so a
session can be saved and resumed later (intermediate state is preserved).
"""

from __future__ import annotations

import json
import math
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

STEP_FIELDS: dict[str, dict[str, Any]] = {
    "scenario": {
        "question": "场景类型与目标深度？",
        "fields": {
            "scenario_type": {
                "label": "场景类型",
                "choices": axes.SCENARIOS,
            },
            "target_depth_m": {"label": "目标埋深/距离 (m)", "type": "number"},
        },
    },
    "target_medium": {
        "question": "目标与围岩介质？（未知填 unknown）",
        "fields": {
            "target_material": {"label": "目标材料", "type": "str"},
            "medium_material": {"label": "围岩介质", "type": "str"},
        },
    },
    "band_mode": {
        "question": "频段与体制？",
        "fields": {
            "needs_sfcw": {"label": "需要 SFCW 体制结论", "type": "bool"},
            "band_mhz": {"label": "频率范围 (如 20-300)", "type": "str"},
        },
    },
    "fidelity": {
        "question": "拟真度取向？",
        "fields": {
            "fidelity": {"label": "拟真度", "choices": axes.FIDELITY_INTENTS},
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

    def answered(self, field: str) -> bool:
        return field in self.answers

    def remaining_fields(self) -> list[str]:
        done = set(self.answers)
        return [
            field
            for step in STEPS
            for field in STEP_FIELDS[step]["fields"]
            if field not in done
        ]

    def incomplete_steps(self) -> list[str]:
        return [
            step
            for step in STEPS
            if any(
                field not in self.answers
                for field in STEP_FIELDS[step]["fields"]
            )
        ]


def create_session(path: Path) -> Session:
    session = Session(Path(path))
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


def _validate_answer(field: str, value: Any, spec: Mapping[str, Any]) -> Any:
    kind = spec.get("type")
    if kind == "number":
        number = float(value)  # raises ValueError -> WizardError below
        if not math.isfinite(number) or number < 0:
            raise WizardError(f"{field}: must be a non-negative finite number")
        return number
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
    """Remove the last *steps* answers (by step order), supporting corrections."""
    ordered = [
        field
        for step in STEPS
        for field in STEP_FIELDS[step]["fields"]
        if field in session.answers
    ]
    if not ordered:
        raise WizardError("nothing to step back from")
    removed: list[str] = []
    for field in list(reversed(ordered))[:steps]:
        session.answers.pop(field, None)
        removed.append(field)
    save_session(session)
    return list(reversed(removed))


def status(session: Session) -> dict[str, Any]:
    remaining = session.remaining_fields()
    return {
        "complete": not remaining,
        "remaining_fields": remaining,
        "incomplete_steps": session.incomplete_steps(),
        "answered": sorted(session.answers),
    }


def _recommendations(session: Session) -> dict[str, dict[str, str]]:
    scenario = session.answers.get("scenario_type", "other")
    fidelity = session.answers.get("fidelity", "standard")
    needs_sfcw = session.answers.get("needs_sfcw")
    return axes.recommend(scenario, fidelity, needs_sfcw=needs_sfcw)


def _numerics_from_answers(session: Session) -> dict[str, Any] | None:
    """Build a numerics report if the numeric inputs are present."""

    try:
        target_depth_m = float(session.answers["target_depth_m"])
    except (KeyError, TypeError, ValueError):
        return None
    band = str(session.answers.get("band_mhz", "") or "")
    if not band or "-" not in band:
        return None
    try:
        low, high = (float(part) for part in band.replace(" ", "").split("-", 1))
    except ValueError:
        return None
    eps_r = 4.0  # placeholder until material research resolves the medium
    dx_m = 0.05  # placeholder until mesh strategy is chosen
    domain_m = (60.0, 16.0, 7.0)  # placeholder domain
    window_s = 2 * target_depth_m / numerics.phase_velocity_m_s(eps_r) * 1.5
    return numerics.numerics_report(
        eps_r=eps_r,
        max_frequency_hz=high * 1e6,
        dx_m=dx_m,
        domain_m=domain_m,
        target_distance_m=target_depth_m,
        window_s=window_s,
        pml_layers=10,
    )


def dump(session: Session) -> dict[str, Any]:
    """Produce the full setup dump: answers, recommendations, markers,
    numerics report, and a contract draft."""
    recommendations = _recommendations(session)
    chosen = {axis: rec["option"] for axis, rec in recommendations.items()}
    markers = axes.markers_for(chosen)
    report = _numerics_from_answers(session)
    return {
        "answers": dict(session.answers),
        "recommendations": recommendations,
        "dependency_markers": markers,
        "numerics": report,
        "contract_draft": _contract_draft(session, recommendations),
    }


def _contract_draft(
    session: Session, recommendations: Mapping[str, Mapping[str, str]]
) -> dict[str, Any]:
    return {
        "project": {
            "design_type": (
                "multi_factor"
                if len(_factor_like_answers(session)) > 1
                else "single_variable"
            ),
            "factors": _factor_like_answers(session),
            "invariants": [],
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
            "excitation_mode": (
                "impulse_lti" if chosen_sfcw(recommendations) else "pulse_broadband"
            ),
            "measurement_mode": "time_domain",
            "band_mhz": session.answers.get("band_mhz"),
        },
        "numerics": {
            "precision_requirement": recommendations.get("precision", {}).get(
                "option", "fp32"
            ),
            "pml_layers": 10,
            "note": "cells/λ, CFL, window coverage: see numerics report",
        },
        "geometry": {
            "target_level": recommendations.get("geometry", {}).get("option", "L1"),
            "antenna": recommendations.get("antenna", {}).get(
                "option", "ideal_herzian"
            ),
            "noise": recommendations.get("noise", {}).get("option", "none"),
        },
        "acceptance": {"negative_controls": [], "sensitivity_tests": []},
        "evidence": {"required_outputs": ["rxs/rx1/Ez"], "provenance_level": "strict"},
    }


def chosen_sfcw(recommendations: Mapping[str, Mapping[str, str]]) -> bool:
    return recommendations.get("sfcw", {}).get("option") == "on"


def _factor_like_answers(session: Session) -> list[str]:
    return [
        field
        for field in (
            "target_depth_m",
            "band_mhz",
            "target_material",
            "medium_material",
        )
        if field in session.answers
    ]


def dump_to_yaml(session: Session) -> str:
    import yaml

    return yaml.safe_dump(
        dump(session), sort_keys=False, allow_unicode=True
    )