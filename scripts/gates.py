from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable, Iterable

from jsonschema import Draft202012Validator

from scripts.core import GateContext, GateResult, GateState, write_json


@dataclass(frozen=True)
class GateDefinition:
    stage: str
    gate_id: str
    fn: Callable[[GateContext], GateResult]
    depends_on: tuple[str, ...] = ()


class GateRegistry:
    def __init__(self) -> None:
        self._gates: list[GateDefinition] = []

    def register(
        self,
        stage: str,
        gate_id: str,
        fn: Callable[[GateContext], GateResult],
        depends_on: Iterable[str] = (),
    ) -> None:
        if any(item.gate_id == gate_id for item in self._gates):
            raise ValueError(f"duplicate gate_id: {gate_id}")
        self._gates.append(GateDefinition(stage, gate_id, fn, tuple(depends_on)))

    def for_stage(self, stage: str) -> tuple[GateDefinition, ...]:
        return tuple(item for item in self._gates if item.stage == stage)


def run_stage(registry: GateRegistry, stage: str, context: GateContext) -> list[GateResult]:
    results: list[GateResult] = []
    passed_ids: set[str] = set()
    for gate in registry.for_stage(stage):
        if any(dependency not in passed_ids for dependency in gate.depends_on):
            results.append(
                GateResult(gate.gate_id, GateState.STALE, "STALE_DEPENDENCY", "dependency not satisfied")
            )
            break
        result = gate.fn(context)
        results.append(result)
        if result.state is GateState.BLOCK:
            break
        if result.state in {
            GateState.PASS,
            GateState.PASS_WITH_LIMITATION,
            GateState.NOT_APPLICABLE,
        }:
            passed_ids.add(gate.gate_id)
    return results


def _gate_status_schema_path() -> Path:
    return Path(__file__).resolve().parents[1] / "schemas" / "gate_status.schema.json"


def write_gate_report(path: Path, results: Iterable[GateResult]) -> None:
    report = {"results": [result.to_dict() for result in results]}
    schema = json.loads(_gate_status_schema_path().read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(report)
    write_json(path, report)
