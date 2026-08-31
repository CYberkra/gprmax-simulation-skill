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


def batch_dir(study_root: Path) -> Path:
    return Path(study_root) / "batch"


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
    study_root: Path, cases: Sequence[Mapping[str, Any]]
) -> Path:
    """Persist the case list and initialise per-case state."""
    study_root = Path(study_root)
    (study_root / "cases.json").parent.mkdir(parents=True, exist_ok=True)
    (study_root / "cases.json").write_text(
        json.dumps(list(cases), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    state = {
        _case_id(case): {"status": "pending", "output": None, "error": None}
        for case in cases
    }
    save_state(study_root, state)
    return study_root / "cases.json"


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