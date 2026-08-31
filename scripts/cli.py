from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
from typing import Any

import yaml
from jsonschema import Draft202012Validator
import numpy as np

from scripts.audit_sfcw import audit_sfcw
from scripts.audit_source import audit_source
from scripts.contracts import ContractError, load_contract
from scripts.core import GateContext, GateResult, GateState, write_json
from scripts.fidelity import FidelityLevel, PromotionDecision, can_promote
from scripts.gates import GateContractError, GateRegistry, run_stage, write_gate_report
import scripts.audit_environment as audit_env
import scripts.audit_geometry as audit_geo
import scripts.audit_materials as audit_mat
import scripts.audit_numerics as audit_num
import scripts.audit_precision as audit_prec
import scripts.materials as materials
import scripts.probe_environment as probe
import scripts.wizard as wizard
from scripts.scaffold import (
    ScaffoldError,
    audit_layout,
    create_study_skeleton,
    describe_layout,
    output_hashes,
    record_output_hashes,
)
import scripts.research as research
import scripts.templates_lib as templates_lib
import scripts.visualize as visualize
import scripts.sampling as sampling
import scripts.report as report
import scripts.sketch as sketch
import scripts.batch as batch
import scripts.dataset as dataset
import scripts.diagnose as diagnose
import scripts.sensitivity as sensitivity


def build_core_registry() -> GateRegistry:
    """Register the model-validation gates into the preflight stage.

    Order follows the evidence-dependency chain:
    environment → numerics (grid/cfl/time_window/pml) → geometry/materials →
    precision → sfcw policy. A BLOCK anywhere stops the preflight.
    """
    registry = GateRegistry()
    registry.register("preflight", "environment", audit_env.audit_environment)
    registry.register(
        "preflight", "grid", audit_num.audit_grid, depends_on=("environment",)
    )
    registry.register(
        "preflight", "cfl", audit_num.audit_cfl, depends_on=("grid",)
    )
    registry.register(
        "preflight", "time_window", audit_num.audit_time_window, depends_on=("cfl",)
    )
    registry.register(
        "preflight", "pml", audit_num.audit_pml, depends_on=("time_window",)
    )
    registry.register(
        "preflight", "geometry", audit_geo.audit_geometry, depends_on=("pml",)
    )
    registry.register(
        "preflight", "model_purpose", audit_geo.audit_model_purpose,
        depends_on=("geometry",),
    )
    registry.register(
        "preflight", "materials", audit_mat.audit_materials, depends_on=("geometry",)
    )
    registry.register(
        "preflight", "precision", audit_prec.audit_precision,
        depends_on=("materials",),
    )
    registry.register(
        "preflight", "sfcw_policy", audit_sfcw, depends_on=("precision",)
    )
    registry.register(
        "preflight", "source", audit_source, depends_on=("sfcw_policy",)
    )
    return registry


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


def _material_suggest(query: str, materials_dir: Path, top_k: int) -> int:
    try:
        if "=" in query:
            # Inline query: name=eps_r=sigma=model (e.g. wet=5.17=0.05=debye)
            parts = query.split("=")
            if len(parts) not in (2, 3, 4):
                raise materials.MaterialError(
                    "inline query must be 'name=eps_r[=sigma[=model]]'"
                )
            name, eps = parts[0], parts[1]
            sigma = parts[2] if len(parts) > 2 else "0"
            model = parts[3] if len(parts) > 3 else "none"
            props: dict[str, Any] = {"model": model, "eps_r": float(eps), "sigma_s_m": float(sigma)}
            results = materials.suggest_similar(
                {"name": name, "properties": props},
                materials_dir,
                override_dir=material_override_dir(materials_dir),
                top_k=top_k,
            )
        else:
            results = materials.suggest_similar(
                query,
                materials_dir,
                override_dir=material_override_dir(materials_dir),
                top_k=top_k,
            )
    except (materials.MaterialError, ValueError) as error:
        print(f"BLOCK {error}", file=sys.stderr)
        return 2

    print(f"与 {query!r} 相近的材料（按距离升序）:")
    for item in results:
        print(
            f"- {item['name']} [{item['category']}]  eps={item['eps']} "
            f"sigma={item['sigma_s_m']:g}  model={item['model']}  "
            f"距离={item['distance']}  src={item['source'][:40]}"
        )
    return 0


def _material_index(materials_dir: Path, index_path: Path) -> int:
    index = materials.build_index(materials_dir)
    materials.write_index(index, index_path)
    invalid = index.get("_invalid")
    if invalid:
        # Index was still written (invalid entries skipped); report but do
        # not treat as a failure per the 0/2 exit convention.
        print(f"wrote index with invalid entries: {invalid}", file=sys.stderr)
        return 0
    print(f"indexed {len(index)} entries -> {index_path}")
    return 0


def material_override_dir(materials_dir: Path) -> Path:
    """The override directory sits next to the library root."""
    library = Path(materials_dir).resolve()
    return library.parent / "materials_override"


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


def _source_registry() -> GateRegistry:
    registry = GateRegistry()
    registry.register("validate-source", "source", audit_source)
    registry.register("validate-source", "sfcw", audit_sfcw, depends_on=("source",))
    return registry


def _load_source_array(path: Path, key: str | None) -> np.ndarray:
    loaded = np.load(path, allow_pickle=False)
    if isinstance(loaded, np.lib.npyio.NpzFile):
        try:
            names = loaded.files
            selected = key
            if selected is None:
                if len(names) != 1:
                    raise ValueError("--source-key is required when an NPZ has multiple arrays")
                selected = names[0]
            if selected not in names:
                raise ValueError(f"source key {selected!r} is absent from {path}")
            return np.asarray(loaded[selected])
        finally:
            loaded.close()
    if key is not None:
        raise ValueError("--source-key is only valid for NPZ input")
    return np.asarray(loaded)


def _validate_source(
    config_path: Path,
    project_root: Path,
    source_array: Path | None,
    source_key: str | None,
) -> int:
    report_path = project_root / "gates" / "validate-source.json"
    details_path = project_root / "gates" / "validate-source-details.json"
    try:
        config = _read_json_object(config_path)
        artifacts: dict[str, Any] = {
            "config_path": str(config_path),
            "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        }
        if source_array is not None:
            artifacts["source_signal"] = _load_source_array(source_array, source_key)
            artifacts["source_array_path"] = str(source_array)
        elif source_key is not None:
            raise ValueError("--source-key requires --source-array")
        context = GateContext(project_root=project_root, contract=config, artifacts=artifacts)
        results = run_stage(_source_registry(), "validate-source", context)
        write_gate_report(report_path, results)
        serializable = {
            key: value
            for key, value in context.artifacts.items()
            if key != "source_signal"
        }
        write_json(details_path, serializable)
    except (OSError, ValueError, json.JSONDecodeError, GateContractError) as error:
        result = GateResult(
            "source_config",
            GateState.BLOCK,
            getattr(error, "code", "BLOCK_SOURCE_CONFIG"),
            str(error),
            evidence=(str(config_path),),
            invalidates=("processing", "metrics", "claims"),
        )
        write_gate_report(report_path, [result])
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
    material_suggest = material_sub.add_parser("suggest")
    material_suggest.add_argument("query", help="material name, or 'name=eps_r=sigma=model' inline")
    material_suggest.add_argument("--materials-dir", type=Path)
    material_suggest.add_argument("--top-k", type=int, default=5)

    preflight = commands.add_parser("preflight")
    preflight.add_argument("contract", type=Path)
    preflight.add_argument("--project-root", type=Path, required=True)

    validate_source = commands.add_parser("validate-source")
    validate_source.add_argument("config", type=Path)
    validate_source.add_argument("--project-root", type=Path, required=True)
    validate_source.add_argument("--source-array", type=Path)
    validate_source.add_argument("--source-key")

    promote = commands.add_parser("promote")
    promote.add_argument("requested", choices=tuple(level.name for level in FidelityLevel))
    promote.add_argument("--project-root", type=Path, required=True)
    promote.add_argument("--skip-reason")
    promote.add_argument("--allow-conditional", action="store_true")

    wcmd = commands.add_parser("wizard")
    wsub = wcmd.add_subparsers(dest="wizard_command", required=True)
    winit = wsub.add_parser("init")
    winit.add_argument("session", type=Path)
    winit.add_argument("--force", action="store_true")
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
    wdump.add_argument(
        "--sketch",
        type=Path,
        default=None,
        help="also render a geometry cross-section sketch to this PNG after dump",
    )
    wdump.add_argument(
        "--report",
        type=Path,
        default=None,
        help="also write a model-card report (Markdown) to this path after dump",
    )

    tcmd = commands.add_parser("template")
    tsub = tcmd.add_subparsers(dest="template_command", required=True)
    tsub.add_parser("list").add_argument("--scenarios-dir", type=Path, default=DEFAULT_SCENARIOS)
    tshow = tsub.add_parser("show")
    tshow.add_argument("name")
    tshow.add_argument("--scenarios-dir", type=Path, default=DEFAULT_SCENARIOS)
    tmatch = tsub.add_parser("match")
    tmatch.add_argument("contract", type=Path)
    tmatch.add_argument("--scenarios-dir", type=Path, default=DEFAULT_SCENARIOS)
    tpropose = tsub.add_parser("propose")
    tpropose.add_argument("entry", type=Path)
    tpropose.add_argument("--scenarios-dir", type=Path, default=DEFAULT_SCENARIOS)
    tverify = tsub.add_parser("verify")
    tverify.add_argument("name")
    tverify.add_argument("--verified-by", nargs="+", required=True)
    tverify.add_argument("--scenarios-dir", type=Path, default=DEFAULT_SCENARIOS)
    textract = tsub.add_parser("extract")
    textract.add_argument("study", type=Path, help="completed study directory")
    textract.add_argument("--scenarios-dir", type=Path, default=DEFAULT_SCENARIOS)
    textract.add_argument(
        "--no-draft",
        action="store_true",
        help="keep status from manifest (verified_by recorded) instead of forcing draft",
    )

    rcmd = commands.add_parser("research")
    rcmd.add_argument("contract", type=Path)
    rcmd.add_argument("--materials-dir", type=Path, default=Path("materials"))
    rcmd.add_argument("--scenarios-dir", type=Path, default=DEFAULT_SCENARIOS)

    scmd = commands.add_parser("sfcw")
    ssub = scmd.add_subparsers(dest="sfcw_command", required=True)
    sprocess = ssub.add_parser("process")
    sprocess.add_argument("out_file", type=Path)
    sprocess.add_argument("--mode", choices=("impulse_lti", "broadband_deconvolution"), default="impulse_lti")
    sprocess.add_argument("--band", required=True, help="tone band as <lo>-<hi> in MHz, e.g. 30-240")
    sprocess.add_argument("--df-mhz", type=float, default=1.0)
    sprocess.add_argument("--dt-s", type=float, default=None)
    sprocess.add_argument("--impulse-response", type=Path, default=None, help="h[n] time series (.npy or text) for impulse_lti")
    sprocess.add_argument("--source-waveform", type=Path, default=None, help="source time series for broadband_deconvolution")
    sprocess.add_argument("--output-dir", type=Path, default=Path("results"))
    sprocess.add_argument("--zero-pad", type=int, default=8)
    sprocess.add_argument("--regularisation", type=float, default=1e-10)
    sprocess.add_argument(
        "--chain",
        choices=("auto", "raw_visual", "standard", "advanced", "imaging", "display_enhancement"),
        default="auto",
        help="processing chain; auto picks from contract (user --mode still wins)",
    )

    dcmd = commands.add_parser("dataset")
    dsub = dcmd.add_subparsers(dest="dataset_command", required=True)
    dsample = dsub.add_parser("sample")
    dsample.add_argument("space", type=Path, help="sampling space YAML")
    dsample.add_argument("--study", type=Path, default=Path("study"))
    dsample.add_argument("--count", type=int, default=None, help="override count")
    dsample.add_argument("--strategy", choices=("random", "grid"), default=None)
    dsample.add_argument("--seed", type=int, default=None)
    dsample.add_argument(
        "--force",
        action="store_true",
        help="skip the model-establishment gate (single-model not yet verified)",
    )
    dcheck = dsub.add_parser("check-model")
    dcheck.add_argument("--study", type=Path, default=Path("study"))
    dstatus = dsub.add_parser("status")
    dstatus.add_argument("--study", type=Path, default=Path("study"))
    dsummary = dsub.add_parser("summary")
    dsummary.add_argument("--study", type=Path, default=Path("study"))
    dpack = dsub.add_parser("pack")
    dpack.add_argument("--study", type=Path, default=Path("study"))
    dpack.add_argument("--out", type=Path, default=Path("dataset.h5"))
    dpack.add_argument("--backend", choices=("h5", "npz"), default="h5")
    dpack.add_argument("--band", required=True, help="tone band <lo>-<hi> MHz, e.g. 30-240")
    dpack.add_argument("--df-mhz", type=float, default=1.0)
    dpack.add_argument("--mode", choices=("impulse_lti", "broadband_deconvolution"), default="impulse_lti")

    diag_cmd = commands.add_parser("diagnose")
    diag_cmd.add_argument("contract", type=Path)
    diag_cmd.add_argument("--gpu-vram-gb", type=float, default=None)

    sens_cmd = commands.add_parser("sensitivity")
    sens_cmd.add_argument("contract", type=Path)
    sens_cmd.add_argument("--perturbation", type=float, default=0.2)

    lcmd = commands.add_parser("layout")
    lsub = lcmd.add_subparsers(dest="layout_command", required=True)
    laudit = lsub.add_parser("audit")
    laudit.add_argument("study_dir", type=Path, help="study directory to audit")
    lhash = lsub.add_parser("hash")
    lhash.add_argument("study_dir", type=Path, help="record SHA-256 of outputs/ into manifest.json")

    rcmd = commands.add_parser("report")
    rsub = rcmd.add_subparsers(dest="report_command", required=True)
    mcard = rsub.add_parser("model-card")
    mcard.add_argument("contract", type=Path, help="simulation_contract.yaml")
    mcard.add_argument("--out", type=Path, default=Path("model_card.md"))
    mcard.add_argument("--diagnostics", type=Path, default=None, help="diagnose JSON/artifact")
    mcard.add_argument("--sensitivity", type=Path, default=None, help="sensitivity JSON/artifact")
    mcard.add_argument("--chain", type=str, default=None, help="processing chain name")
    mcard.add_argument("--probe", type=Path, default=None, help="environment probe JSON")

    skcmd = commands.add_parser("sketch")
    sksub = skcmd.add_subparsers(dest="sketch_command", required=True)
    gsketch = sksub.add_parser("geometry")
    gsketch.add_argument("contract", type=Path, help="simulation_contract.yaml")
    gsketch.add_argument("--out", type=Path, default=Path("geometry_sketch.png"))
    return parser


DEFAULT_SCENARIOS = Path("templates") / "scenarios"


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


def _wizard_dump(
    session_path: Path,
    out: Path | None,
    sketch_path: Path | None,
    report_path: Path | None,
) -> int:
    session = wizard.load_session(session_path)
    try:
        payload = wizard.dump(session)
    except wizard.WizardError as error:
        print(f"BLOCK {error}", file=sys.stderr)
        return 2
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            __import__("yaml").safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        print(f"dump written -> {out}")
    else:
        print(__import__("yaml").safe_dump(payload, sort_keys=False, allow_unicode=True), end="")
    contract = payload.get("contract_draft", {})
    if sketch_path is not None:
        try:
            sketch.plot_geometry_sketch(contract, sketch_path)
            print(f"sketch written -> {sketch_path}")
        except (sketch.SketchError, ValueError) as error:
            print(f"WARN sketch not rendered: {error}", file=sys.stderr)
    if report_path is not None:
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            text = report.render_model_card(contract)
            report_path.write_text(text, encoding="utf-8")
            print(f"model card written -> {report_path}")
        except (ValueError, OSError) as error:
            print(f"WARN model card not rendered: {error}", file=sys.stderr)
    return 0


def _resolve_materials_dir(args: argparse.Namespace) -> Path:
    explicit = getattr(args, "materials_dir", None)
    if explicit is not None:
        return explicit
    return Path("materials")


def _template_list(scenarios_dir: Path) -> int:
    for item in templates_lib.list_templates(scenarios_dir):
        print(f"{item['name']}\t[{item['status']}]\t{item['scenario']}")
    return 0


def _template_show(name: str, scenarios_dir: Path) -> int:
    index = templates_lib.build_index(scenarios_dir)
    if name not in index:
        print(f"template {name!r} not found", file=sys.stderr)
        return 2
    try:
        entry = templates_lib.load_template(scenarios_dir / index[name]["path"])
    except templates_lib.TemplateError as error:
        print(f"BLOCK {error}", file=sys.stderr)
        return 2
    print(
        yaml.safe_dump(entry, sort_keys=False, allow_unicode=True),
        end="",
    )
    return 0


def _template_match(contract_path: Path, scenarios_dir: Path) -> int:
    try:
        contract = load_contract(contract_path)
        signature = templates_lib.signature_from_contract(contract)
        matched = templates_lib.match_scenario(signature, scenarios_dir)
    except (templates_lib.TemplateError, ContractError, OSError, yaml.YAMLError) as error:
        print(f"BLOCK {error}", file=sys.stderr)
        return 2
    if matched is None:
        print("no verified template strictly matches this contract")
        return 0
    print(f"matched: {matched['name']} (verified by {matched['verified_by']})")
    return 0


def _template_propose(entry_path: Path, scenarios_dir: Path) -> int:
    try:
        entry = templates_lib.load_template(entry_path)
        target = templates_lib.propose_template(entry, scenarios_dir)
    except templates_lib.TemplateError as error:
        print(f"BLOCK {error}", file=sys.stderr)
        return 2
    print(f"proposed draft -> {target}")
    return 0


def _template_verify(name: str, scenarios_dir: Path, verified_by: list[str]) -> int:
    try:
        target = templates_lib.verify_template(name, scenarios_dir, verified_by)
    except templates_lib.TemplateError as error:
        print(f"BLOCK {error}", file=sys.stderr)
        return 2
    print(f"verified -> {target}")
    return 0


def _template_extract(study: Path, scenarios_dir: Path, no_draft: bool) -> int:
    try:
        target = templates_lib.extract_study_auto(
            study, scenarios_dir, force_draft=not no_draft
        )
    except templates_lib.TemplateError as error:
        print(f"BLOCK {error}", file=sys.stderr)
        return 2
    print(f"extracted -> {target}")
    return 0


def _research_needs(contract_path: Path, materials_dir: Path, scenarios_dir: Path) -> int:
    try:
        contract = load_contract(contract_path)
        needs = research.identify_research_needs(
            contract,
            materials_dir=materials_dir,
            scenarios_dir=scenarios_dir,
        )
    except (research.ValueError, ContractError, OSError, yaml.YAMLError) as error:
        print(f"BLOCK {error}", file=sys.stderr)
        return 2
    print(research.render_needs(needs))
    return 0


def _load_array(path: Path) -> np.ndarray:
    """Load a 1-D float array from .npy or whitespace text."""
    if path.suffix.lower() == ".npy":
        arr = np.load(path)
    else:
        arr = np.loadtxt(path)
    arr = np.asarray(arr, dtype=float)
    if arr.ndim != 1:
        raise ValueError(f"{path}: expected a one-dimensional array, got {arr.ndim}D")
    return arr


def _sfcw_process(args: argparse.Namespace) -> int:
    try:
        lo_str, hi_str = str(args.band).split("-")
        f_lo, f_hi = float(lo_str), float(hi_str)
        if not (0 < f_lo < f_hi):
            raise ValueError("band must satisfy 0 < lo < hi")
        if args.df_mhz <= 0:
            raise ValueError("--df-mhz must be positive")
        n_tones = int(round((f_hi - f_lo) / args.df_mhz)) + 1
        frequencies_mhz = [f_lo + i * args.df_mhz for i in range(n_tones)]
        band = (f_lo, f_hi)

        impulse_response = (
            _load_array(args.impulse_response)
            if args.impulse_response is not None
            else None
        )
        source_waveform = (
            _load_array(args.source_waveform)
            if args.source_waveform is not None
            else None
        )

        artifacts = visualize.process_and_plot(
            args.out_file,
            mode=args.mode,
            frequencies_mhz=frequencies_mhz,
            dt_s=args.dt_s,
            output_dir=args.output_dir,
            impulse_response=impulse_response,
            source_waveform=source_waveform,
            band_mhz=band,
            zero_pad_factor=args.zero_pad,
            regularisation=args.regularisation,
        )
        if args.chain != "auto":
            chain = visualize.recommend_chain({"chain": args.chain}, {})
            print(
                f"chain        -> {chain['chain']} (mode={chain['mode']}, "
                f"display_only={chain['display_only']}) — {chain['rationale']}"
            )
    except (visualize.ProcessingError, ValueError, OSError) as error:
        print(f"BLOCK {error}", file=sys.stderr)
        return 2
    print(f"ascan        -> {artifacts['ascan_png']}")
    print(f"parameters   -> {artifacts['parameters_json']}")
    return 0


def _dataset_sample(args: argparse.Namespace) -> int:
    from dataclasses import replace

    try:
        batch.require_model_established(args.study, force=args.force)
        space = sampling.load_space(args.space)
        if args.count is not None:
            space = replace(space, count=args.count)
        if args.strategy:
            space = replace(space, strategy=args.strategy)
        if args.seed is not None:
            space = replace(space, seed=args.seed)
        cases = sampling.sample_cases(space)
        cases_path = batch.initialise_batch(args.study, cases)
    except (sampling.SamplingError, batch.BatchError) as error:
        print(f"BLOCK {error}", file=sys.stderr)
        return 2
    print(sampling.render_space(space))
    print(f"sampled {len(cases)} cases -> {cases_path}")
    return 0


def _dataset_check_model(args: argparse.Namespace) -> int:
    gaps = batch.model_establishment_gaps(args.study)
    if not gaps:
        print("model established — batch simulation may proceed")
        return 0
    print("model NOT established; fix before batch simulation:")
    for gap in gaps:
        print(f"- {gap}")
    return 2


def _dataset_status(args: argparse.Namespace) -> int:
    try:
        dashboard = batch.status_dashboard(args.study)
    except (batch.BatchError, OSError) as error:
        print(f"BLOCK {error}", file=sys.stderr)
        return 2
    import json as _json

    print(_json.dumps(dashboard, indent=2, ensure_ascii=False))
    return 0


def _dataset_summary(args: argparse.Namespace) -> int:
    try:
        cases = sampling.load_case_list(args.study / "cases.json")
        path = batch.write_summary(args.study, cases)
    except (sampling.SamplingError, batch.BatchError, OSError) as error:
        print(f"BLOCK {error}", file=sys.stderr)
        return 2
    print(f"summary -> {path}")
    return 0


def _dataset_pack(args: argparse.Namespace) -> int:
    try:
        cases = sampling.load_case_list(args.study / "cases.json")
        state = batch.load_state(args.study)
        done_ids = [
            case["case_id"]
            for case in cases
            if state.get(case["case_id"], {}).get("status") == "done"
        ]
        if not done_ids:
            raise batch.BatchError("no completed cases to pack")

        band_parts = [float(part) for part in str(args.band).split("-")]
        if len(band_parts) != 2:
            raise ValueError("--band must be '<lo>-<hi>' MHz")
        f_lo, f_hi = band_parts
        if not (0 < f_lo < f_hi):
            raise ValueError("--band must satisfy 0 < lo < hi")
        if args.df_mhz <= 0:
            raise ValueError("--df-mhz must be positive")
        frequencies_mhz = [
            f_lo + i * args.df_mhz
            for i in range(int(round((f_hi - f_lo) / args.df_mhz)) + 1)
        ]
        done_cases = [case for case in cases if case["case_id"] in done_ids]
        ascan_arrays: list[np.ndarray] = []
        for case in done_cases:
            output_path = batch.outputs_dir(args.study) / case["case_id"]
            out_files = sorted(output_path.glob("*.out"))
            if not out_files:
                raise batch.BatchError(
                    f"case {case['case_id']} has no .out under {output_path}"
                )
            trace, trace_dt = visualize.read_ez_from_out(out_files[0])
            # In the data-factory LTI pipeline each case's .out is the
            # impulse response h[n]; impulse_lti synthesizes the SFCW
            # response from it. broadband_deconvolution would instead need
            # the source waveform as a separate input.
            result = visualize.process_trace(
                args.mode,
                trace[0],
                dt_s=trace_dt,
                frequencies_mhz=frequencies_mhz,
                impulse_response=trace[0] if args.mode == "impulse_lti" else None,
            )
            ascan_arrays.append(np.asarray(result["envelope"], dtype=np.float64))

        path = dataset.pack_dataset(
            args.out,
            cases=done_cases,
            arrays={"ascan": ascan_arrays},
            backend=args.backend,
        )
    except (
        sampling.SamplingError,
        batch.BatchError,
        dataset.DatasetError,
        visualize.ProcessingError,
        ValueError,
        OSError,
    ) as error:
        print(f"BLOCK {error}", file=sys.stderr)
        return 2
    print(f"packed {len(done_ids)} cases -> {path}")
    print(f"info: {dataset.dataset_info(path)}")
    return 0


def _diagnose(args: argparse.Namespace) -> int:
    try:
        contract = load_contract(args.contract)
        findings = diagnose.diagnose_model(contract, gpu_vram_gb=args.gpu_vram_gb)
    except (ValueError, ContractError, OSError, yaml.YAMLError) as error:
        print(f"BLOCK {error}", file=sys.stderr)
        return 2
    print(diagnose.render_diagnostics(findings))
    blocking = any(f.severity == "BLOCK" for f in findings)
    return 2 if blocking else 0


def _layout_audit(study_dir: Path) -> int:
    try:
        findings = audit_layout(study_dir)
    except (OSError, ValueError) as error:
        print(f"BLOCK {error}", file=sys.stderr)
        return 2
    for finding in findings:
        print(f"[{finding['severity']}] {finding['check']}: {finding['message']}")
    blocking = any(f["severity"] == "BLOCK" for f in findings)
    return 2 if blocking else 0


def _layout_hash(study_dir: Path) -> int:
    try:
        path = record_output_hashes(study_dir)
        hashes = output_hashes(study_dir)
    except (ScaffoldError, ValueError, OSError) as error:
        print(f"BLOCK {error}", file=sys.stderr)
        return 2
    print(f"recorded {len(hashes)} SHA-256 hash(es) -> {path}")
    return 0


def _load_optional_json(path: Path | None) -> list | dict | None:
    if path is None:
        return None
    import json as _json

    try:
        value = _json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, _json.JSONDecodeError) as error:
        print(f"BLOCK {path} is unreadable JSON ({error})", file=sys.stderr)
        raise
    return value


def _report_model_card(args: argparse.Namespace) -> int:
    try:
        contract = load_contract(args.contract)
        diagnostics = _load_optional_json(args.diagnostics)
        sensitivity = _load_optional_json(args.sensitivity)
        probe = _load_optional_json(args.probe)
        chain = None
        if args.chain:
            chain = visualize.recommend_chain({"chain": args.chain}, contract)
        text = report.render_model_card(
            contract,
            diagnostics=diagnostics if isinstance(diagnostics, list) else None,
            sensitivity=sensitivity if isinstance(sensitivity, list) else None,
            chain=chain,
            probe=probe if isinstance(probe, dict) else None,
        )
    except (
        ContractError,
        report.SketchError,
        visualize.ProcessingError,
        ValueError,
        OSError,
        yaml.YAMLError,
    ) as error:
        print(f"BLOCK {error}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"model card -> {args.out}")
    return 0


def _sketch_geometry(args: argparse.Namespace) -> int:
    try:
        contract = load_contract(args.contract)
        path = sketch.plot_geometry_sketch(contract, args.out)
    except (
        ContractError,
        sketch.SketchError,
        ValueError,
        OSError,
        yaml.YAMLError,
    ) as error:
        print(f"BLOCK {error}", file=sys.stderr)
        return 2
    print(f"geometry sketch -> {path}")
    return 0


def _sensitivity(args: argparse.Namespace) -> int:
    try:
        contract = load_contract(args.contract)
        results = sensitivity.analyse_sensitivity(
            contract, perturbation=args.perturbation
        )
    except (ValueError, ContractError, OSError, yaml.YAMLError) as error:
        print(f"BLOCK {error}", file=sys.stderr)
        return 2
    print(sensitivity.render_sensitivity(results))
    print("\n最敏感参数: " + ", ".join(
        f"{item.parameter}" for item in sensitivity.rank_most_sensitive(results)
    ))
    return 0


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
        if args.material_command == "suggest":
            return _material_suggest(args.query, materials_dir, args.top_k)
        raise AssertionError(f"unhandled material command: {args.material_command}")
    if args.command == "preflight":
        return _preflight(args.contract, args.project_root)
    if args.command == "validate-source":
        return _validate_source(
            args.config,
            args.project_root,
            args.source_array,
            args.source_key,
        )
    if args.command == "promote":
        return _promote(
            FidelityLevel[args.requested],
            args.project_root,
            args.skip_reason,
            args.allow_conditional,
        )
    if args.command == "wizard":
        if args.wizard_command == "init":
            try:
                wizard.create_session(args.session, force=args.force)
            except wizard.WizardError as error:
                print(f"BLOCK {error}", file=sys.stderr)
                return 2
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
            return _wizard_dump(args.session, args.out, args.sketch, args.report)
        raise AssertionError(f"unhandled wizard command: {args.wizard_command}")
    if args.command == "template":
        if args.template_command == "list":
            return _template_list(args.scenarios_dir)
        if args.template_command == "show":
            return _template_show(args.name, args.scenarios_dir)
        if args.template_command == "match":
            return _template_match(args.contract, args.scenarios_dir)
        if args.template_command == "propose":
            return _template_propose(args.entry, args.scenarios_dir)
        if args.template_command == "verify":
            return _template_verify(args.name, args.scenarios_dir, args.verified_by)
        if args.template_command == "extract":
            return _template_extract(args.study, args.scenarios_dir, args.no_draft)
        raise AssertionError(f"unhandled template command: {args.template_command}")
    if args.command == "research":
        return _research_needs(args.contract, args.materials_dir, args.scenarios_dir)
    if args.command == "sfcw":
        if args.sfcw_command == "process":
            return _sfcw_process(args)
        raise AssertionError(f"unhandled sfcw command: {args.sfcw_command}")
    if args.command == "dataset":
        if args.dataset_command == "sample":
            return _dataset_sample(args)
        if args.dataset_command == "check-model":
            return _dataset_check_model(args)
        if args.dataset_command == "status":
            return _dataset_status(args)
        if args.dataset_command == "summary":
            return _dataset_summary(args)
        if args.dataset_command == "pack":
            return _dataset_pack(args)
        raise AssertionError(f"unhandled dataset command: {args.dataset_command}")
    if args.command == "diagnose":
        return _diagnose(args)
    if args.command == "sensitivity":
        return _sensitivity(args)
    if args.command == "layout":
        if args.layout_command == "audit":
            return _layout_audit(args.study_dir)
        if args.layout_command == "hash":
            return _layout_hash(args.study_dir)
        raise AssertionError(f"unhandled layout command: {args.layout_command}")
    if args.command == "report":
        if args.report_command == "model-card":
            return _report_model_card(args)
        raise AssertionError(f"unhandled report command: {args.report_command}")
    if args.command == "sketch":
        if args.sketch_command == "geometry":
            return _sketch_geometry(args)
        raise AssertionError(f"unhandled sketch command: {args.sketch_command}")
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
