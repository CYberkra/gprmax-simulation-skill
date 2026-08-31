"""Batch orchestration for the data-factory pipeline.

Turns a sampled case list into an executed batch: per-case validation, GPU
farm sharding, resume on existing outputs, a status dashboard, and a summary
table. This is the execution backbone of the training-data factory — it must
be safe to interrupt and resume at any point (long batches are the norm).

State model (persisted per study):

- ``<study>/cases.json``     — the sampled case list (labels)
- ``<study>/batch/state.json`` — per-case status (pending/running/done/fail)
- ``<study>/outputs/``       — per-case ``.out`` files (raw evidence)
- ``<study>/batch/summary.csv`` — final case → status → output table

The runner itself is gprMax; this module only orchestrates. Actual GPU
commands are delegated to the study's runner script (for example a
``run_case.sh``), keeping the skill hardware-agnostic.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from scripts.sampling import SamplingError, load_case_list

VALID_STATUSES = {"pending", "running", "done", "fail"}

# Legal status transitions (guards against accidental regression).
_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"running", "done", "fail"},
    "running": {"done", "fail", "pending"},
    "done": set(),
    "fail": set(),  # re-run via reset(), not direct transition
}


class BatchError(ValueError):
    """Invalid batch state or orchestration call."""


def model_establishment_gaps(study_root: Path) -> list[str]:
    """Return unmet model-establishment requirements before batch simulation.

    A new project must first establish a single validated model — contract
    confirmed, dimension declared, materials/band resolved, and at least one
    real run output audited — before any batch expansion. Each returned string
    is a human-readable requirement that is not yet met; an empty list means
    the model is established and batch simulation may proceed.

    Checks (all required):
    1. ``simulation_contract.yaml`` exists and parses (YAML mapping);
    2. the contract declares ``model.dimension`` (2d / 2.5d / 3d);
    3. the contract declares medium/target material names (no ``unknown``);
    4. the contract declares a waveform band (``waveform.band_mhz``);
    5. ``outputs/`` holds at least one ``.out`` file (single-model smoke has
       produced auditable raw evidence).
    """
    import yaml

    study_root = Path(study_root)
    gaps: list[str] = []

    contract_path = study_root / "simulation_contract.yaml"
    if not contract_path.is_file():
        gaps.append("simulation_contract.yaml missing — run the guided setup first")
        return gaps
    try:
        contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        gaps.append("simulation_contract.yaml is unreadable — re-dump from the wizard")
        return gaps
    if not isinstance(contract, dict):
        gaps.append("simulation_contract.yaml must be a mapping")
        return gaps

    model = contract.get("model") or {}
    dimension = model.get("dimension") if isinstance(model, Mapping) else None
    if dimension not in {"2d", "2.5d", "3d"}:
        gaps.append(
            "model.dimension not declared (need 2d/2.5d/3d) — confirm it in the wizard"
        )

    medium = contract.get("medium") or {}
    if isinstance(medium, Mapping):
        for field, label in (("medium_material", "围岩介质"), ("target_material", "目标材料")):
            value = medium.get(field)
            if value is None or str(value).strip().lower() in {"", "unknown", "待调研"}:
                gaps.append(f"medium.{field} ({label}) unresolved — research and confirm")
    else:
        gaps.append("medium block missing in contract")

    waveform = contract.get("waveform") or {}
    band = waveform.get("band_mhz") if isinstance(waveform, Mapping) else None
    if band is None:
        gaps.append("waveform.band_mhz not declared — confirm frequency band")

    outputs = outputs_dir(study_root)
    out_files = sorted(outputs.glob("*.out")) if outputs.is_dir() else []
    if not out_files:
        gaps.append(
            "no .out in outputs/ — run and audit at least one single-model case first"
        )

    return gaps


def require_model_established(study_root: Path, *, force: bool = False) -> list[str]:
    """Fail-closed gate for batch entry.

    Raises ``BatchError`` listing every unmet model-establishment requirement
    unless ``force=True`` (explicit user override, matching the skill's
    "user-specified wins" rule). Returns the gap list when empty.
    """
    gaps = model_establishment_gaps(study_root)
    if gaps and not force:
        raise BatchError(
            "model not established; fix before batch simulation:\n- "
            + "\n- ".join(gaps)
        )
    return gaps


def batch_dir(study_root: Path) -> Path:
    return Path(study_root) / "batch"


def outputs_dir(study_root: Path) -> Path:
    """Per-case raw ``.out`` outputs live under ``<study>/outputs/``.

    Single source of truth for the output tree so the CLI, dataset packer
    and any runner script agree on where cases write their evidence.
    """
    return Path(study_root) / "outputs"


def state_path(study_root: Path) -> Path:
    return batch_dir(study_root) / "state.json"


def summary_path(study_root: Path) -> Path:
    return batch_dir(study_root) / "summary.csv"


def load_state(study_root: Path) -> dict[str, dict[str, Any]]:
    """Load per-case status; raise if the batch was initialised but state is lost."""
    path = state_path(study_root)
    if not path.is_file():
        cases_file = Path(study_root) / "cases.json"
        if cases_file.is_file():
            raise BatchError(
                f"state file {path} missing although cases.json exists — "
                "batch state lost; reinitialise or restore the state file"
            )
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BatchError(f"state file {path} is unreadable JSON ({error})") from error
    if isinstance(value, dict):
        return dict(value)
    raise BatchError(f"state file {path} must contain a JSON object")


def save_state(study_root: Path, state: Mapping[str, Mapping[str, Any]]) -> None:
    batch_dir(study_root).mkdir(parents=True, exist_ok=True)
    state_path(study_root).write_text(
        json.dumps(dict(state), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _case_id(case: Mapping[str, Any]) -> str:
    case_id = case.get("case_id")
    if not isinstance(case_id, str) or not case_id:
        raise BatchError("each case must carry a non-empty case_id")
    return case_id


def initialise_batch(
    study_root: Path, cases: Sequence[Mapping[str, Any]], *, force: bool = False
) -> Path:
    """Persist the case list and initialise per-case state.

    Re-initialising a study that already has a case list or state is
    destructive (it overwrites status bookkeeping), so it raises by default;
    pass ``force=True`` to deliberately re-create the batch from scratch.
    """
    study_root = Path(study_root)
    cases_file = study_root / "cases.json"
    state_path_existing = state_path(study_root)
    if not force and (cases_file.is_file() or state_path_existing.is_file()):
        raise BatchError(
            f"{study_root} already has cases.json/state.json — re-initialising "
            "would discard status bookkeeping; pass force=True to re-create"
        )
    cases_file.parent.mkdir(parents=True, exist_ok=True)
    cases_file.write_text(
        json.dumps(list(cases), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    state = {
        _case_id(case): {"status": "pending", "output": None, "error": None}
        for case in cases
    }
    save_state(study_root, state)
    return cases_file


def mark(study_root: Path, case_id: str, status: str, **extra: Any) -> None:
    """Transition one case to a new status (persisted).

    Legal transitions guard against accidental regression (for example a done
    case being silently re-marked). ``fail`` may be re-run explicitly via
    ``reset``, not by direct transition.
    """
    if status not in VALID_STATUSES:
        raise BatchError(f"invalid status: {status}")
    state = load_state(study_root)
    if case_id not in state:
        raise BatchError(f"unknown case_id: {case_id}")
    current = state[case_id].get("status", "pending")
    allowed = _TRANSITIONS.get(current, set())
    if status not in allowed:
        raise BatchError(
            f"illegal state transition {current} -> {status} for {case_id} "
            f"(allowed: {sorted(allowed)})"
        )
    entry = dict(state[case_id])
    entry["status"] = status
    entry.update(extra)
    state[case_id] = entry
    save_state(study_root, state)


def reset(study_root: Path, case_id: str) -> None:
    """Reset a failed case back to pending so it can be re-run."""
    state = load_state(study_root)
    if case_id not in state:
        raise BatchError(f"unknown case_id: {case_id}")
    current = state[case_id].get("status", "pending")
    if current not in ("fail", "running"):
        raise BatchError(f"reset only applies to fail/running, got {current}")
    state[case_id] = {"status": "pending", "output": None, "error": None}
    save_state(study_root, state)


def pending_cases(study_root: Path) -> list[str]:
    """Cases not yet done or failed — the resume set."""
    state = load_state(study_root)
    return [
        case_id
        for case_id, entry in state.items()
        if entry.get("status") in ("pending", "running")
    ]


def status_dashboard(study_root: Path) -> dict[str, Any]:
    """Aggregate the batch into a dashboard mapping."""
    state = load_state(study_root)
    counts = {status: 0 for status in VALID_STATUSES}
    for entry in state.values():
        status = entry.get("status", "pending")
        counts[status] = counts.get(status, 0) + 1
    return {
        "total": len(state),
        "done": counts.get("done", 0),
        "pending": counts.get("pending", 0),
        "running": counts.get("running", 0),
        "failed": counts.get("fail", 0),
        "resume_count": len(pending_cases(study_root)),
    }


def write_summary(
    study_root: Path, cases: Sequence[Mapping[str, Any]]
) -> Path:
    """Write the final case → status → output summary CSV."""
    state = load_state(study_root)
    path = summary_path(study_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["case_id", "status", "output", "error"])
        for case in cases:
            case_id = _case_id(case)
            entry = state.get(case_id, {})
            writer.writerow(
                [
                    case_id,
                    entry.get("status", "pending"),
                    entry.get("output") or "",
                    entry.get("error") or "",
                ]
            )
    return path


def farm_shards(
    study_root: Path, gpu_count: int
) -> list[list[str]]:
    """Split the pending cases into ``gpu_count`` shards (round-robin)."""
    if not isinstance(gpu_count, int) or gpu_count < 1:
        raise BatchError("gpu_count must be a positive integer")
    pending = pending_cases(study_root)
    shards: list[list[str]] = [[] for _ in range(gpu_count)]
    for index, case_id in enumerate(pending):
        shards[index % gpu_count].append(case_id)
    return shards


def is_complete(study_root: Path) -> bool:
    return status_dashboard(study_root)["resume_count"] == 0