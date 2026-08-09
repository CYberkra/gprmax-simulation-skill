from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable, Iterable

from jsonschema import Draft202012Validator

from scripts.core import GateContext, GateResult, GateState, write_json


class GateContractError(ValueError):
    def __init__(self, code: str, path: str, details: str):
        super().__init__(f"{code} at {path}: {details}")
        self.code = code
        self.path = path
        self.details = details


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
            raise GateContractError(
                "BLOCK_GATE_DUPLICATE_ID", "gate_id", f"duplicate gate_id: {gate_id}"
            )
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
        result = _validate_callback_result(gate, gate.fn(context))
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


def _validate_callback_result(gate: GateDefinition, result: object) -> GateResult:
    if not isinstance(result, GateResult):
        raise GateContractError(
            "BLOCK_GATE_RESULT_TYPE",
            gate.gate_id,
            f"expected GateResult, got {type(result).__name__}",
        )
    if result.gate_id != gate.gate_id:
        raise GateContractError(
            "BLOCK_GATE_RESULT_ID",
            f"{gate.gate_id}.gate_id",
            f"expected {gate.gate_id}, got {result.gate_id}",
        )
    if not isinstance(result.state, GateState):
        raise GateContractError(
            "BLOCK_GATE_RESULT_STATE",
            f"{gate.gate_id}.state",
            f"expected GateState, got {type(result.state).__name__}",
        )
    return result


def _gate_status_schema_path() -> Path:
    return Path(__file__).resolve().parents[1] / "schemas" / "gate_status.schema.json"


def write_gate_report(path: Path, results: Iterable[GateResult]) -> None:
    report = {"results": [_serialize_report_result(index, result) for index, result in enumerate(results)]}
    schema = json.loads(_gate_status_schema_path().read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(report), key=lambda error: list(error.path))
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.path) or "<root>"
        raise GateContractError("BLOCK_GATE_REPORT_SCHEMA", location, error.message)
    write_json(path, report)


def _serialize_report_result(index: int, result: object) -> dict[str, object]:
    path = f"results.{index}"
    if not isinstance(result, GateResult):
        raise GateContractError(
            "BLOCK_GATE_REPORT_RESULT_TYPE", path, f"expected GateResult, got {type(result).__name__}"
        )
    if not isinstance(result.state, GateState):
        raise GateContractError(
            "BLOCK_GATE_REPORT_STATE",
            f"{path}.state",
            f"expected GateState, got {type(result.state).__name__}",
        )
    for field in ("evidence", "invalidates"):
        value = getattr(result, field)
        if not isinstance(value, tuple):
            raise GateContractError(
                "BLOCK_GATE_REPORT_FIELD_TYPE",
                f"{path}.{field}",
                f"expected tuple[str, ...], got {type(value).__name__}",
            )
    return result.to_dict()
