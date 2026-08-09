# gprMax Core Contract and Gate Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the stable core interfaces that every later gprMax module uses: validated simulation contracts, gate states/results, F0–F5 promotion, dependency invalidation, and a stage-oriented CLI.

**Architecture:** Keep the core free of domain-specific physics. `scripts/core.py` owns state types, `scripts/contracts.py` owns schema-backed loading, `scripts/gates.py` owns execution/dependency behavior, `scripts/fidelity.py` owns claim-to-fidelity constraints, and `scripts/cli.py` is a thin command router.

**Tech Stack:** Python 3.11+, PyYAML, jsonschema, pytest, standard-library `argparse`, `dataclasses`, `enum`, `pathlib`, `hashlib`, `json`.

## Global Constraints

- Generic core contains no tunnel-face project-specific numerical defaults.
- Any `BLOCK` gate stops stage promotion.
- `PASS_WITH_LIMITATION` may continue only when the requested next stage explicitly allows conditional evidence; it never silently becomes `VERIFIED`.
- Upstream changes can invalidate downstream gates and claims to `STALE`.
- All contract validation errors are deterministic and machine-readable.
- Raw evidence paths are referenced but never modified by the core.

---

## File map

- Create: `pyproject.toml` — Python requirements, pytest configuration, `gprmax-skill` console entry point.
- Create: `scripts/__init__.py` — package marker.
- Create: `scripts/core.py` — `GateState`, `ClaimState`, `GateResult`, `GateContext`, serialization helpers.
- Create: `scripts/contracts.py` — YAML loading and JSON Schema validation.
- Create: `scripts/gates.py` — gate registry, ordered execution, fail-closed stop, dependency invalidation.
- Create: `scripts/fidelity.py` — F0–F5 enum, claim minimums, promotion decision.
- Create: `scripts/cli.py` — `init`, `preflight`, `promote` commands initially; later plans extend it.
- Create: `schemas/simulation_contract.schema.json` — canonical task contract schema.
- Create: `schemas/gate_status.schema.json` — serialized gate report schema.
- Create: `templates/simulation_contract.yaml` — generic example with null/auto values only.
- Create: `templates/gate_status.yaml` — generic gate-status shape.
- Test: `tests/unit/test_core.py`
- Test: `tests/unit/test_contracts.py`
- Test: `tests/unit/test_gates.py`
- Test: `tests/unit/test_fidelity.py`
- Test: `tests/unit/test_cli_core.py`

### Task 1: Core state model and package scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `scripts/__init__.py`
- Create: `scripts/core.py`
- Test: `tests/unit/test_core.py`

**Interfaces:**
- Produces: `GateState`, `ClaimState`, `GateResult`, `GateContext`, `write_json(path, value)`.
- Later plans must import these exact names; they must not redefine status enums.

- [ ] **Step 1: Write the failing state-model tests**

```python
# tests/unit/test_core.py
from pathlib import Path
from scripts.core import ClaimState, GateContext, GateResult, GateState


def test_gate_result_serializes_stably():
    result = GateResult(
        gate_id="environment",
        state=GateState.BLOCK,
        code="BLOCK_ENVIRONMENT_UNRESOLVED",
        summary="runtime banner is missing",
        evidence=("logs/run.log",),
        invalidates=("source", "claims"),
    )
    assert result.to_dict() == {
        "gate_id": "environment",
        "state": "BLOCK",
        "code": "BLOCK_ENVIRONMENT_UNRESOLVED",
        "summary": "runtime banner is missing",
        "evidence": ["logs/run.log"],
        "invalidates": ["source", "claims"],
    }


def test_gate_context_has_mutable_derived_artifacts_only(tmp_path: Path):
    ctx = GateContext(project_root=tmp_path, contract={"task": {"objective": "detection"}})
    ctx.artifacts["computed"] = 3
    assert ctx.artifacts == {"computed": 3}
    assert ClaimState.STALE.value == "STALE"
```

- [ ] **Step 2: Run the tests and verify the import failure**

Run:

```bash
pytest tests/unit/test_core.py -v
```

Expected: FAIL because `scripts.core` does not exist.

- [ ] **Step 3: Implement the minimal stable core types**

```python
# scripts/core.py
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import json
from pathlib import Path
from typing import Any, Mapping


class GateState(StrEnum):
    PASS = "PASS"
    PASS_WITH_LIMITATION = "PASS_WITH_LIMITATION"
    BLOCK = "BLOCK"
    STALE = "STALE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ClaimState(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    CONDITIONAL = "CONDITIONAL"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    STALE = "STALE"


@dataclass(frozen=True)
class GateResult:
    gate_id: str
    state: GateState
    code: str
    summary: str
    evidence: tuple[str, ...] = ()
    invalidates: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["state"] = self.state.value
        value["evidence"] = list(self.evidence)
        value["invalidates"] = list(self.invalidates)
        return value


@dataclass
class GateContext:
    project_root: Path
    contract: Mapping[str, Any]
    artifacts: dict[str, Any] = field(default_factory=dict)


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
```

Create `scripts/__init__.py` as an empty file and configure `pyproject.toml`:

```toml
[project]
name = "gprmax-simulation-skill"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["PyYAML>=6", "jsonschema>=4.20", "numpy>=1.26", "h5py>=3.10"]

[project.scripts]
gprmax-skill = "scripts.cli:main"

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 4: Run the state-model tests**

Run: `pytest tests/unit/test_core.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the core types**

```bash
git add pyproject.toml scripts/__init__.py scripts/core.py tests/unit/test_core.py
git commit -m "feat: add gprmax skill core state model"
```

### Task 2: Simulation contract schema and loader

**Files:**
- Create: `schemas/simulation_contract.schema.json`
- Create: `templates/simulation_contract.yaml`
- Create: `scripts/contracts.py`
- Test: `tests/unit/test_contracts.py`

**Interfaces:**
- Consumes: `GateContext` only indirectly.
- Produces: `load_contract(path: Path) -> dict[str, Any]`, `validate_contract(value: Mapping[str, Any]) -> None`.
- Raises: `ContractError(code: str, message: str)` with deterministic codes.

- [ ] **Step 1: Write contract tests covering valid, missing, and project-specific-free templates**

```python
# tests/unit/test_contracts.py
from pathlib import Path
import pytest
from scripts.contracts import ContractError, load_contract


def test_minimal_contract_loads(tmp_path: Path):
    path = tmp_path / "contract.yaml"
    path.write_text(
        "task:\n  objective: detection\n  claim_scope: numerical\n"
        "medium:\n  model_type: nondispersive\n  parameter_source: assumed\n"
        "waveform:\n  excitation_mode: pulse_broadband\n  measurement_mode: time_domain\n"
        "numerics:\n  precision_requirement: auto\n"
        "acceptance:\n  negative_controls: []\n  sensitivity_tests: []\n"
        "evidence:\n  required_outputs: []\n  provenance_level: strict\n",
        encoding="utf-8",
    )
    value = load_contract(path)
    assert value["task"]["objective"] == "detection"


def test_missing_claim_scope_is_blocking_schema_error(tmp_path: Path):
    path = tmp_path / "bad.yaml"
    path.write_text("task:\n  objective: detection\n", encoding="utf-8")
    with pytest.raises(ContractError) as exc:
        load_contract(path)
    assert exc.value.code == "BLOCK_CONTRACT_SCHEMA"


def test_generic_template_has_no_tunnel_face_defaults():
    text = Path("templates/simulation_contract.yaml").read_text(encoding="utf-8")
    for forbidden in ("80-200", "40-200", "100 m", "3.5", "5e-4", "37 dBm", "60 dB"):
        assert forbidden not in text
```

- [ ] **Step 2: Run the contract tests and verify failure**

Run: `pytest tests/unit/test_contracts.py -v`

Expected: FAIL because schema/loader/template are absent.

- [ ] **Step 3: Implement schema-backed loading**

Implement `ContractError`, load YAML with `yaml.safe_load`, validate with `jsonschema.Draft202012Validator`, sort validation errors by JSON path, and raise the first deterministic message.

```python
# scripts/contracts.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping
import yaml
from jsonschema import Draft202012Validator


class ContractError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _schema_path() -> Path:
    return Path(__file__).resolve().parents[1] / "schemas" / "simulation_contract.schema.json"


def validate_contract(value: Mapping[str, Any]) -> None:
    schema = json.loads(_schema_path().read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda e: list(e.path))
    if errors:
        err = errors[0]
        location = ".".join(str(part) for part in err.path) or "<root>"
        raise ContractError("BLOCK_CONTRACT_SCHEMA", f"{location}: {err.message}")


def load_contract(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError("BLOCK_CONTRACT_SCHEMA", "<root>: contract must be a mapping")
    validate_contract(value)
    return value
```

The schema must require `task.objective`, `task.claim_scope`, `medium.model_type`, `medium.parameter_source`, `waveform.excitation_mode`, `waveform.measurement_mode`, `numerics.precision_requirement`, `acceptance.negative_controls`, `acceptance.sensitivity_tests`, `evidence.required_outputs`, and `evidence.provenance_level`; allow optional nested project data without supplying numeric defaults.

The template must use `auto`, `null`, empty lists/maps, and descriptive enum values only.

- [ ] **Step 4: Run the contract tests**

Run: `pytest tests/unit/test_contracts.py -v`

Expected: PASS.

- [ ] **Step 5: Commit contract validation**

```bash
git add schemas/simulation_contract.schema.json templates/simulation_contract.yaml scripts/contracts.py tests/unit/test_contracts.py
git commit -m "feat: validate simulation contracts"
```

### Task 3: Gate report schema and fail-closed engine

**Files:**
- Create: `schemas/gate_status.schema.json`
- Create: `templates/gate_status.yaml`
- Create: `scripts/gates.py`
- Test: `tests/unit/test_gates.py`

**Interfaces:**
- Consumes: `GateContext`, `GateResult`, `GateState`.
- Produces: `GateRegistry.register(stage, gate_id, fn, depends_on=())`, `run_stage(registry, stage, context) -> list[GateResult]`, `write_gate_report(path, results)`.

- [ ] **Step 1: Write tests proving a blocking gate stops later gates**

```python
# tests/unit/test_gates.py
from pathlib import Path
from scripts.core import GateContext, GateResult, GateState
from scripts.gates import GateRegistry, run_stage


def test_block_stops_remaining_gates(tmp_path: Path):
    calls = []
    registry = GateRegistry()

    def first(ctx):
        calls.append("first")
        return GateResult("first", GateState.BLOCK, "BLOCK_TEST", "stop")

    def second(ctx):
        calls.append("second")
        return GateResult("second", GateState.PASS, "PASS", "should not run")

    registry.register("preflight", "first", first)
    registry.register("preflight", "second", second, depends_on=("first",))
    results = run_stage(registry, "preflight", GateContext(tmp_path, {}))
    assert calls == ["first"]
    assert [r.state for r in results] == [GateState.BLOCK]


def test_pass_with_limitation_does_not_become_pass(tmp_path: Path):
    registry = GateRegistry()
    registry.register(
        "preflight",
        "conditional",
        lambda ctx: GateResult("conditional", GateState.PASS_WITH_LIMITATION, "LIMITED", "conditional"),
    )
    result = run_stage(registry, "preflight", GateContext(tmp_path, {}))[0]
    assert result.state is GateState.PASS_WITH_LIMITATION
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/unit/test_gates.py -v`

Expected: FAIL because `scripts.gates` does not exist.

- [ ] **Step 3: Implement the registry and ordered fail-closed stage runner**

Use a small immutable gate definition and reject duplicate IDs.

```python
@dataclass(frozen=True)
class GateDefinition:
    stage: str
    gate_id: str
    fn: Callable[[GateContext], GateResult]
    depends_on: tuple[str, ...] = ()


class GateRegistry:
    def __init__(self) -> None:
        self._gates: list[GateDefinition] = []

    def register(self, stage: str, gate_id: str, fn, depends_on=()) -> None:
        if any(item.gate_id == gate_id for item in self._gates):
            raise ValueError(f"duplicate gate_id: {gate_id}")
        self._gates.append(GateDefinition(stage, gate_id, fn, tuple(depends_on)))

    def for_stage(self, stage: str) -> tuple[GateDefinition, ...]:
        return tuple(item for item in self._gates if item.stage == stage)


def run_stage(registry: GateRegistry, stage: str, context: GateContext) -> list[GateResult]:
    results: list[GateResult] = []
    passed_ids: set[str] = set()
    for gate in registry.for_stage(stage):
        if any(dep not in passed_ids for dep in gate.depends_on):
            results.append(GateResult(gate.gate_id, GateState.STALE, "STALE_DEPENDENCY", "dependency not satisfied"))
            break
        result = gate.fn(context)
        results.append(result)
        if result.state is GateState.BLOCK:
            break
        if result.state in {GateState.PASS, GateState.PASS_WITH_LIMITATION, GateState.NOT_APPLICABLE}:
            passed_ids.add(gate.gate_id)
    return results
```

`write_gate_report` serializes `{"results": [result.to_dict(), ...]}` and validates it against `schemas/gate_status.schema.json` before writing.

- [ ] **Step 4: Run gate tests**

Run: `pytest tests/unit/test_gates.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the gate engine**

```bash
git add schemas/gate_status.schema.json templates/gate_status.yaml scripts/gates.py tests/unit/test_gates.py
git commit -m "feat: add fail closed gate engine"
```

### Task 4: Fidelity model and claim-to-minimum-fidelity barrier

**Files:**
- Create: `scripts/fidelity.py`
- Test: `tests/unit/test_fidelity.py`

**Interfaces:**
- Produces: `FidelityLevel`, `minimum_fidelity(objective, claim_scope)`, `can_promote(current, requested, results, skip_reason=None) -> PromotionDecision`.

- [ ] **Step 1: Write tests for claim barriers and blocked promotion**

```python
# tests/unit/test_fidelity.py
from scripts.core import GateResult, GateState
from scripts.fidelity import FidelityLevel, can_promote, minimum_fidelity


def test_system_claim_requires_f5():
    assert minimum_fidelity("system", "engineering") is FidelityLevel.F5


def test_physical_resolution_requires_at_least_f4():
    assert minimum_fidelity("resolution", "physical") is FidelityLevel.F4


def test_blocked_gate_prevents_promotion():
    decision = can_promote(
        FidelityLevel.F1,
        FidelityLevel.F2,
        [GateResult("grid", GateState.BLOCK, "BLOCK_GRID", "bad grid")],
    )
    assert decision.allowed is False
    assert decision.code == "BLOCK_PROMOTION_GATE"


def test_skip_requires_reason():
    decision = can_promote(FidelityLevel.F1, FidelityLevel.F3, [], skip_reason=None)
    assert decision.allowed is False
    assert decision.code == "BLOCK_FIDELITY_SKIP_UNJUSTIFIED"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/unit/test_fidelity.py -v`

Expected: FAIL because fidelity types are missing.

- [ ] **Step 3: Implement explicit F0–F5 semantics**

```python
class FidelityLevel(IntEnum):
    F0 = 0
    F1 = 1
    F2 = 2
    F3 = 3
    F4 = 4
    F5 = 5


@dataclass(frozen=True)
class PromotionDecision:
    allowed: bool
    code: str
    summary: str


_MINIMUM = {
    ("antenna", "engineering"): FidelityLevel.F4,
    ("system", "engineering"): FidelityLevel.F5,
    ("detection", "engineering"): FidelityLevel.F5,
    ("resolution", "physical"): FidelityLevel.F4,
    ("thickness", "physical"): FidelityLevel.F4,
}


def minimum_fidelity(objective: str, claim_scope: str) -> FidelityLevel:
    return _MINIMUM.get((objective, claim_scope), FidelityLevel.F1)
```

`can_promote` must reject any `BLOCK`/`STALE` result; accept same-level or +1 promotion after clean gates; require a non-empty skip reason for jumps larger than one; never allow requested fidelity below the minimum needed for the declared final claim when sign-off is requested.

- [ ] **Step 4: Run fidelity tests**

Run: `pytest tests/unit/test_fidelity.py -v`

Expected: PASS.

- [ ] **Step 5: Commit fidelity promotion logic**

```bash
git add scripts/fidelity.py tests/unit/test_fidelity.py
git commit -m "feat: enforce fidelity promotion barriers"
```

### Task 5: Dependency invalidation and stale-state propagation

**Files:**
- Modify: `scripts/gates.py`
- Test: `tests/unit/test_gates.py`

**Interfaces:**
- Produces: `DependencyGraph.add(upstream, downstream)`, `DependencyGraph.invalidate(changed) -> set[str]`, `mark_stale(report, affected)`.

- [ ] **Step 1: Add failing tests for transitive invalidation**

```python
def test_source_change_invalidates_all_downstream():
    from scripts.gates import DependencyGraph
    graph = DependencyGraph()
    graph.add("source", "processing")
    graph.add("processing", "metrics")
    graph.add("metrics", "claims")
    assert graph.invalidate({"source"}) == {"processing", "metrics", "claims"}
```

- [ ] **Step 2: Run the targeted test**

Run: `pytest tests/unit/test_gates.py::test_source_change_invalidates_all_downstream -v`

Expected: FAIL because `DependencyGraph` is undefined.

- [ ] **Step 3: Implement deterministic breadth-first invalidation**

```python
class DependencyGraph:
    def __init__(self) -> None:
        self._edges: dict[str, set[str]] = {}

    def add(self, upstream: str, downstream: str) -> None:
        self._edges.setdefault(upstream, set()).add(downstream)

    def invalidate(self, changed: set[str]) -> set[str]:
        affected: set[str] = set()
        queue = list(sorted(changed))
        while queue:
            current = queue.pop(0)
            for downstream in sorted(self._edges.get(current, ())):
                if downstream not in affected and downstream not in changed:
                    affected.add(downstream)
                    queue.append(downstream)
        return affected
```

Add the canonical chain `environment → numerics → source → geometry_materials → antenna_system → simulation → processing → metrics → claims` in one constructor helper named `default_dependency_graph()`.

- [ ] **Step 4: Run all gate tests**

Run: `pytest tests/unit/test_gates.py -v`

Expected: PASS.

- [ ] **Step 5: Commit invalidation support**

```bash
git add scripts/gates.py tests/unit/test_gates.py
git commit -m "feat: invalidate stale downstream evidence"
```

### Task 6: Core CLI commands and non-zero blocking exit codes

**Files:**
- Create: `scripts/cli.py`
- Test: `tests/unit/test_cli_core.py`

**Interfaces:**
- Produces CLI: `gprmax-skill init`, `preflight`, `promote`.
- `main(argv: list[str] | None = None) -> int` returns `0` for clean/conditional non-blocking stages and `2` for blocking contract/gate failures.

- [ ] **Step 1: Write CLI tests**

```python
# tests/unit/test_cli_core.py
from pathlib import Path
from scripts.cli import main


def test_init_copies_generic_contract_template(tmp_path: Path):
    rc = main(["init", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "simulation_contract.yaml").exists()


def test_invalid_contract_returns_blocking_exit(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("task:\n  objective: detection\n", encoding="utf-8")
    rc = main(["preflight", str(bad), "--project-root", str(tmp_path)])
    assert rc == 2
```

- [ ] **Step 2: Run CLI tests and verify failure**

Run: `pytest tests/unit/test_cli_core.py -v`

Expected: FAIL because CLI does not exist.

- [ ] **Step 3: Implement thin argparse routing**

`init` copies the template without inserting numeric defaults. `preflight` loads the contract, creates `GateContext`, invokes the registry returned by `build_core_registry()`, writes `gates/preflight.json`, and returns `2` if any result is `BLOCK`. `promote` reads the current fidelity from `gates/fidelity.json`, evaluates `can_promote`, writes the promotion decision, and returns `2` on refusal.

Expose `main()` and add:

```python
if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run core unit suite**

Run:

```bash
pytest tests/unit/test_core.py tests/unit/test_contracts.py tests/unit/test_gates.py tests/unit/test_fidelity.py tests/unit/test_cli_core.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit the core CLI**

```bash
git add scripts/cli.py tests/unit/test_cli_core.py
git commit -m "feat: add staged gprmax skill cli"
```

### Task 7: Core plan acceptance fixture

**Files:**
- Create: `tests/fixtures/contracts/minimal_valid.yaml`
- Create: `tests/fixtures/projects/minimal/.gitkeep`
- Test: `tests/unit/test_cli_core.py`

**Interfaces:**
- Produces one reusable minimal valid contract used by later plans.

- [ ] **Step 1: Add a fixture-level acceptance test**

```python
def test_minimal_fixture_preflight_succeeds():
    rc = main([
        "preflight",
        "tests/fixtures/contracts/minimal_valid.yaml",
        "--project-root",
        "tests/fixtures/projects/minimal",
    ])
    assert rc == 0
    assert Path("tests/fixtures/projects/minimal/gates/preflight.json").exists()
```

- [ ] **Step 2: Run the acceptance test and observe failure until fixture exists**

Run: `pytest tests/unit/test_cli_core.py::test_minimal_fixture_preflight_succeeds -v`

Expected: FAIL with missing fixture.

- [ ] **Step 3: Create the minimal fixture with only generic values**

Use a nondispersive, numerical-scope, time-domain contract with `auto` precision/grid/time/PML and empty acceptance thresholds. Do not insert any tunnel-face case values.

- [ ] **Step 4: Run the complete Plan 1 suite**

Run: `pytest tests/unit/test_core.py tests/unit/test_contracts.py tests/unit/test_gates.py tests/unit/test_fidelity.py tests/unit/test_cli_core.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the acceptance fixture**

```bash
git add tests/fixtures/contracts/minimal_valid.yaml tests/fixtures/projects/minimal tests/unit/test_cli_core.py
git commit -m "test: add minimal core acceptance fixture"
```

## Plan 1 completion gate

Run:

```bash
pytest tests/unit/test_core.py tests/unit/test_contracts.py tests/unit/test_gates.py tests/unit/test_fidelity.py tests/unit/test_cli_core.py -q
python -m scripts.cli preflight tests/fixtures/contracts/minimal_valid.yaml --project-root tests/fixtures/projects/minimal
```

Expected: all tests PASS and CLI exit code `0`. No later plan begins until these stable interfaces are reviewed and accepted.
