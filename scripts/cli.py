from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from scripts.contracts import ContractError, load_contract
from scripts.core import GateContext, GateResult, GateState, write_json
from scripts.fidelity import FidelityLevel, PromotionDecision, can_promote
from scripts.gates import GateContractError, GateRegistry, run_stage, write_gate_report


def build_core_registry() -> GateRegistry:
    """Return the registry extended by later audit modules."""
    return GateRegistry()


def _template_path() -> Path:
    return Path(__file__).resolve().parents[1] / "templates" / "simulation_contract.yaml"


def _init(project_root: Path) -> int:
    project_root.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_template_path(), project_root / "simulation_contract.yaml")
    return 0


def _preflight(contract_path: Path, project_root: Path) -> int:
    report_path = project_root / "gates" / "preflight.json"
    try:
        contract = load_contract(contract_path)
    except (ContractError, OSError, yaml.YAMLError) as error:
        result = GateResult(
            "contract",
            GateState.BLOCK,
            getattr(error, "code", "BLOCK_CONTRACT_READ"),
            str(error),
            evidence=(str(contract_path),),
        )
        write_gate_report(report_path, [result])
        return 2

    context = GateContext(project_root=project_root, contract=contract)
    try:
        results = run_stage(build_core_registry(), "preflight", context)
        write_gate_report(report_path, results)
    except GateContractError as error:
        sanitized = [
            GateResult(
                gate_id="gate_engine",
                state=GateState.BLOCK,
                code=error.code,
                summary=error.details,
            )
        ]
        write_gate_report(report_path, sanitized)
        return 2
    return 2 if any(result.state is GateState.BLOCK for result in results) else 0


def _read_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _read_gate_results(path: Path) -> tuple[GateResult, ...]:
    report = _read_json_object(path)
    schema_path = Path(__file__).resolve().parents[1] / "schemas" / "gate_status.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(report),
        key=lambda error: list(error.path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.path) or "<root>"
        raise ValueError(f"{path}: {location}: {error.message}")

    values = report["results"]
    results: list[GateResult] = []
    for value in values:
        results.append(
            GateResult(
                gate_id=value["gate_id"],
                state=GateState(value["state"]),
                code=value["code"],
                summary=value["summary"],
                evidence=tuple(value["evidence"]),
                invalidates=tuple(value["invalidates"]),
            )
        )
    return tuple(results)


def _write_promotion(
    path: Path,
    current: str | None,
    requested: FidelityLevel,
    decision: PromotionDecision,
) -> None:
    write_json(
        path,
        {
            "allowed": decision.allowed,
            "code": decision.code,
            "current": current,
            "requested": requested.name,
            "summary": decision.summary,
        },
    )


def _promote(
    requested: FidelityLevel,
    project_root: Path,
    skip_reason: str | None,
    allow_conditional: bool,
) -> int:
    gates = project_root / "gates"
    fidelity_path = gates / "fidelity.json"
    promotion_path = gates / "promotion.json"
    try:
        fidelity = _read_json_object(fidelity_path)
        current_name = fidelity["current"]
        if not isinstance(current_name, str):
            raise ValueError(f"{fidelity_path}: current must be a string")
        current = FidelityLevel[current_name]
        results = _read_gate_results(gates / "preflight.json")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        decision = PromotionDecision(False, "BLOCK_PROMOTION_STATE", str(error))
        _write_promotion(promotion_path, None, requested, decision)
        return 2

    decision = can_promote(
        current,
        requested,
        results,
        skip_reason,
        allow_conditional=allow_conditional,
    )
    _write_promotion(promotion_path, current.name, requested, decision)
    if not decision.allowed:
        return 2
    write_json(fidelity_path, {"current": requested.name})
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gprmax-skill")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init")
    init.add_argument("project_root", type=Path)

    preflight = commands.add_parser("preflight")
    preflight.add_argument("contract", type=Path)
    preflight.add_argument("--project-root", type=Path, required=True)

    promote = commands.add_parser("promote")
    promote.add_argument("requested", choices=tuple(level.name for level in FidelityLevel))
    promote.add_argument("--project-root", type=Path, required=True)
    promote.add_argument("--skip-reason")
    promote.add_argument("--allow-conditional", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "init":
        return _init(args.project_root)
    if args.command == "preflight":
        return _preflight(args.contract, args.project_root)
    if args.command == "promote":
        return _promote(
            FidelityLevel[args.requested],
            args.project_root,
            args.skip_reason,
            args.allow_conditional,
        )
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
