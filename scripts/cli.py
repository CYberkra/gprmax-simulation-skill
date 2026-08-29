from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from scripts.contracts import ContractError, load_contract
from scripts.core import GateContext, GateResult, GateState, write_json
from scripts.fidelity import FidelityLevel, PromotionDecision, can_promote
from scripts.gates import GateContractError, GateRegistry, run_stage, write_gate_report
import scripts.materials as materials
import scripts.probe_environment as probe
import scripts.wizard as wizard
from scripts.scaffold import describe_layout, create_study_skeleton


def build_core_registry() -> GateRegistry:
    """Return the registry extended by later audit modules."""
    return GateRegistry()


def _template_path() -> Path:
    return Path(__file__).resolve().parents[1] / "templates" / "simulation_contract.yaml"


def _init(project_root: Path, name: str | None) -> int:
    create_study_skeleton(project_root, name=name)
    return 0


def _probe(output_dir: Path, as_json: bool) -> int:
    report = probe.collect_probe(output_volume=output_dir)
    if as_json:
        print(probe.probe_to_json(report), end="")
    else:
        print(probe.format_report(report))
    return 0


def _material_add(path: Path, materials_dir: Path, override: bool) -> int:
    try:
        entry = materials.load_material(path)
    except materials.MaterialError as error:
        print(f"BLOCK {error}", file=sys.stderr)
        return 2
    if override:
        target_dir = materials_dir.parent / "materials_override"
        target_dir.mkdir(parents=True, exist_ok=True)
    else:
        target_dir = materials_dir / entry["category"]
        target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{Path(path).stem}.yaml"
    target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"added {entry['name']} -> {target.relative_to(materials_dir.parent)}")
    return 0


def _material_list(materials_dir: Path, override_dir: Path | None) -> int:
    overrides = material_override_dir(materials_dir) if override_dir is None else override_dir
    for name in materials.list_entries(materials_dir, override_dir=overrides):
        print(name)
    return 0


def _material_show(name: str, materials_dir: Path, override_dir: Path | None) -> int:
    overrides = material_override_dir(materials_dir) if override_dir is None else override_dir
    path = materials.resolve_entry(name, materials_dir, override_dir=overrides)
    if path is None:
        print(f"material {name!r} not found", file=sys.stderr)
        return 2
    try:
        print(yaml.safe_dump(materials.load_material(path), sort_keys=False, allow_unicode=True), end="")
    except materials.MaterialError as error:
        print(f"BLOCK {error}", file=sys.stderr)
        return 2
    return 0


def _material_index(materials_dir: Path, index_path: Path) -> int:
    index = materials.build_index(materials_dir)
    materials.write_index(index, index_path)
    invalid = index.get("_invalid")
    if invalid:
        print(f"wrote index with invalid entries: {invalid}", file=sys.stderr)
        return 1
    print(f"indexed {len(index)} entries -> {index_path}")
    return 0


def material_override_dir(materials_dir: Path) -> Path:
    """The override directory sits next to the library root."""
    library = Path(materials_dir).resolve()
    if library.name == "materials":
        candidate = library.parent / "materials_override"
    else:
        candidate = library.parent / "materials_override"
    return candidate


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
    parser.add_argument(
        "--materials-dir",
        type=Path,
        default=Path("materials"),
        help="Material library root (default ./materials)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init")
    init.add_argument("project_root", type=Path)
    init.add_argument("--name", help="study_id following <nn>_<yyyymmdd>_<TOPIC>")

    probe_cmd = commands.add_parser("probe")
    probe_cmd.add_argument("--output-dir", type=Path, default=Path.cwd())
    probe_cmd.add_argument("--json", action="store_true", dest="as_json")

    material = commands.add_parser("material")
    material_sub = material.add_subparsers(dest="material_command", required=True)
    material_add = material_sub.add_parser("add")
    material_add.add_argument("path", type=Path)
    material_add.add_argument("--override", action="store_true")
    material_add.add_argument("--materials-dir", type=Path)
    material_list = material_sub.add_parser("list")
    material_list.add_argument("--materials-dir", type=Path)
    material_show = material_sub.add_parser("show")
    material_show.add_argument("name")
    material_show.add_argument("--materials-dir", type=Path)
    material_index = material_sub.add_parser("index")
    material_index.add_argument("--materials-dir", type=Path)
    material_index.add_argument("--index-path", type=Path, default=Path("materials_index.json"))

    preflight = commands.add_parser("preflight")
    preflight.add_argument("contract", type=Path)
    preflight.add_argument("--project-root", type=Path, required=True)

    promote = commands.add_parser("promote")
    promote.add_argument("requested", choices=tuple(level.name for level in FidelityLevel))
    promote.add_argument("--project-root", type=Path, required=True)
    promote.add_argument("--skip-reason")
    promote.add_argument("--allow-conditional", action="store_true")

    wcmd = commands.add_parser("wizard")
    wsub = wcmd.add_subparsers(dest="wizard_command", required=True)
    wsub.add_parser("init").add_argument("session", type=Path)
    wanswer = wsub.add_parser("answer")
    wanswer.add_argument("session", type=Path)
    wanswer.add_argument("field", type=str)
    wanswer.add_argument("value", type=str)
    wback = wsub.add_parser("back")
    wback.add_argument("session", type=Path)
    wback.add_argument("--steps", type=int, default=1)
    wsub.add_parser("status").add_argument("session", type=Path)
    wdump = wsub.add_parser("dump")
    wdump.add_argument("session", type=Path)
    wdump.add_argument("--out", type=Path)
    return parser


def _wizard_answer(session_path: Path, field: str, value: str) -> int:
    session = wizard.load_session(session_path)
    try:
        validated = wizard.answer(session, field, value)
    except wizard.WizardError as error:
        print(f"BLOCK {error}", file=sys.stderr)
        return 2
    print(f"{field} = {validated!r}")
    return 0


def _wizard_status(session_path: Path) -> int:
    session = wizard.load_session(session_path)
    import json as _json

    print(_json.dumps(wizard.status(session), indent=2, ensure_ascii=False))
    return 0


def _wizard_dump(session_path: Path, out: Path | None) -> int:
    session = wizard.load_session(session_path)
    payload = wizard.dump(session)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            __import__("yaml").safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        print(f"dump written -> {out}")
    else:
        print(__import__("yaml").safe_dump(payload, sort_keys=False, allow_unicode=True), end="")
    return 0


def _resolve_materials_dir(args: argparse.Namespace) -> Path:
    explicit = getattr(args, "materials_dir", None)
    if explicit is not None:
        return explicit
    return args.materials_dir if hasattr(args, "materials_dir") else Path("materials")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "init":
        return _init(args.project_root, args.name)
    if args.command == "probe":
        return _probe(args.output_dir, args.as_json)
    if args.command == "material":
        materials_dir = _resolve_materials_dir(args)
        if args.material_command == "add":
            return _material_add(args.path, materials_dir, args.override)
        if args.material_command == "list":
            return _material_list(materials_dir, None)
        if args.material_command == "show":
            return _material_show(args.name, materials_dir, None)
        if args.material_command == "index":
            return _material_index(materials_dir, args.index_path)
        raise AssertionError(f"unhandled material command: {args.material_command}")
    if args.command == "preflight":
        return _preflight(args.contract, args.project_root)
    if args.command == "promote":
        return _promote(
            FidelityLevel[args.requested],
            args.project_root,
            args.skip_reason,
            args.allow_conditional,
        )
    if args.command == "wizard":
        if args.wizard_command == "init":
            wizard.create_session(args.session)
            print(f"wizard session created -> {args.session}")
            return 0
        if args.wizard_command == "answer":
            return _wizard_answer(args.session, args.field, args.value)
        if args.wizard_command == "back":
            session = wizard.load_session(args.session)
            try:
                removed = wizard.back(session, args.steps)
            except wizard.WizardError as error:
                print(f"BLOCK {error}", file=sys.stderr)
                return 2
            print(f"removed: {removed}")
            return 0
        if args.wizard_command == "status":
            return _wizard_status(args.session)
        if args.wizard_command == "dump":
            return _wizard_dump(args.session, args.out)
        raise AssertionError(f"unhandled wizard command: {args.wizard_command}")
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
