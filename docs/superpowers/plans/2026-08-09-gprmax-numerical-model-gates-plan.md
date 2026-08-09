# gprMax Numerical and Physical Model Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement fail-closed preflight gates for runtime identity, grid/CFL/time/PML, material realization, geometry representation, FP32/FP64 precision, model purpose, and paired-run invariants.

**Architecture:** Each technical concern is a pure or file-reading gate that returns one `GateResult`. `scripts/preflight.py` composes them into the `preflight` and `validate-model` stages without hiding individual evidence.

**Tech Stack:** Python 3.11+, NumPy, h5py, PyYAML, pytest; optional gprMax runtime metadata/logs supplied through fixture files.

## Global Constraints

- Grid requirements are derived from wavelength, geometry, dispersion, and claim accuracy; no universal `lambda/10` hard-code.
- Post-processing must use the actual solver `dt` from output metadata when present.
- Materials keep provenance and frequency validity separate from numeric parameter values.
- Weak-differential/high-dynamic-range work is blocked when observed residuals are near floating-point ULP floor.
- Target/reference and other pairs may differ only in explicitly permitted fields.
- F2 reduced-dimensional results cannot sign 3D finite-target/antenna/system claims.

---

## File map

- Create: `scripts/audit_environment.py`
- Create: `scripts/audit_numerics.py`
- Create: `scripts/audit_materials.py`
- Create: `scripts/audit_geometry.py`
- Create: `scripts/audit_precision.py`
- Create: `scripts/audit_pair_contract.py`
- Create: `scripts/preflight.py`
- Create: `scripts/run_manifest.py`
- Create: `scripts/smoke.py`
- Create: `scripts/run_simulation.py`
- Create: `schemas/run_manifest.schema.json`
- Create: `templates/model_purpose.yaml`
- Test: `tests/unit/test_environment_gate.py`
- Test: `tests/unit/test_numerics_gate.py`
- Test: `tests/unit/test_material_gate.py`
- Test: `tests/unit/test_geometry_gate.py`
- Test: `tests/unit/test_precision_gate.py`
- Test: `tests/unit/test_pair_contract.py`
- Test: `tests/unit/test_preflight_registry.py`
- Test: `tests/unit/test_smoke_run.py`

### Task 1: Runtime/environment identity gate

**Files:**
- Create: `scripts/audit_environment.py`
- Create: `schemas/run_manifest.schema.json`
- Test: `tests/unit/test_environment_gate.py`

**Interfaces:**
- Consumes `GateContext.contract["runtime"]` when supplied and files under `logs/`.
- Produces `audit_environment(ctx: GateContext) -> GateResult` and `collect_environment(ctx) -> dict[str, Any]`.

- [ ] **Step 1: Write failing tests for resolved and unresolved runtime identity**

```python
from pathlib import Path
from scripts.core import GateContext, GateState
from scripts.audit_environment import audit_environment


def test_missing_runtime_identity_blocks(tmp_path: Path):
    ctx = GateContext(tmp_path, {"runtime": {}})
    result = audit_environment(ctx)
    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_ENVIRONMENT_UNRESOLVED"


def test_banner_import_path_and_precision_are_recorded(tmp_path: Path):
    log = tmp_path / "logs" / "runtime.json"
    log.parent.mkdir()
    log.write_text(
        '{"gprmax_version":"3.1.7","banner":"gprMax 3.1.7","import_path":"/opt/gprMax/gprMax/__init__.py",'
        '"backend":"gpu","real_dtype":"float64","complex_dtype":"complex128"}',
        encoding="utf-8",
    )
    ctx = GateContext(tmp_path, {"runtime": {"manifest": "logs/runtime.json"}})
    result = audit_environment(ctx)
    assert result.state is GateState.PASS
    assert ctx.artifacts["environment"]["real_dtype"] == "float64"
```

- [ ] **Step 2: Run the tests**

Run: `pytest tests/unit/test_environment_gate.py -v`

Expected: FAIL because the environment gate does not exist.

- [ ] **Step 3: Implement deterministic runtime manifest parsing**

`collect_environment` reads the declared JSON manifest, requires non-empty `gprmax_version`, `banner`, `import_path`, `backend`, `real_dtype`, and `complex_dtype`, optionally records Python/CUDA/GPU/driver values, and places the normalized dictionary in `ctx.artifacts["environment"]`.

`audit_environment` returns `BLOCK_ENVIRONMENT_UNRESOLVED` on missing/malformed required fields and `PASS_ENVIRONMENT_LOCKED` on success. Do not infer version from directory names.

- [ ] **Step 4: Run environment tests**

Run: `pytest tests/unit/test_environment_gate.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/audit_environment.py schemas/run_manifest.schema.json tests/unit/test_environment_gate.py
git commit -m "feat: audit actual gprmax runtime identity"
```

### Task 2: Analytical grid, CFL, time-window, and PML gates

**Files:**
- Create: `scripts/audit_numerics.py`
- Test: `tests/unit/test_numerics_gate.py`

**Interfaces:**
- Produces: `minimum_wavelength(f_max_hz, epsilon_r_max)`, `courant_limit(dx, dy, dz)`, `required_round_trip_time(path_m, velocity_mps)`, `estimate_cell_count(domain_m, grid_m)`, `build_analytic_sanity(ctx) -> dict[str, Any]`, and four gate functions `audit_grid`, `audit_cfl`, `audit_time_window`, `audit_pml`.

- [ ] **Step 1: Write formula and blocking tests**

```python
import math
from scripts.audit_numerics import courant_limit, minimum_wavelength


def test_minimum_wavelength_uses_highest_permittivity():
    lam = minimum_wavelength(200e6, 4.0)
    assert math.isclose(lam, 299792458.0 / 200e6 / 2.0, rel_tol=1e-12)


def test_courant_limit_for_cubic_grid():
    dt = courant_limit(0.01, 0.01, 0.01)
    expected = 1.0 / (299792458.0 * ((3.0 / 0.01**2) ** 0.5))
    assert math.isclose(dt, expected, rel_tol=1e-12)
```

Add fixture tests where a contract declares a critical feature of `0.02 m` but discretized geometry uses only one cell and expects precision localization; `audit_grid` must return `BLOCK_GEOMETRY_UNDERSAMPLED`. Add a time-window fixture where target back-interface arrival exceeds declared simulation time; expect `BLOCK_TIME_WINDOW_TRUNCATION_RISK`. Add a `build_analytic_sanity` test that verifies it returns wavelength, CFL limit, round-trip time, estimated cell count, and a compute/memory estimate only from contract-declared domain/grid/precision assumptions.

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/unit/test_numerics_gate.py -v`

Expected: FAIL because the module is missing.

- [ ] **Step 3: Implement formulas and contract-driven thresholds**

```python
C0 = 299_792_458.0


def minimum_wavelength(f_max_hz: float, epsilon_r_max: float) -> float:
    if f_max_hz <= 0 or epsilon_r_max <= 0:
        raise ValueError("frequency and permittivity must be positive")
    return C0 / f_max_hz / math.sqrt(epsilon_r_max)


def courant_limit(dx: float, dy: float, dz: float) -> float:
    return 1.0 / (C0 * math.sqrt(dx**-2 + dy**-2 + dz**-2))


def required_round_trip_time(path_m: float, velocity_mps: float) -> float:
    return 2.0 * path_m / velocity_mps
```

`build_analytic_sanity` writes the F0 artifact `artifacts/analytic_sanity.json` and derives wavelength, CFL limit, maximum round-trip time, cell count, and a memory/compute estimate from contract inputs. The memory estimate must expose its assumed bytes-per-cell/update coefficient rather than presenting it as solver truth. `audit_grid` reads explicit `numerics.grid.cells_per_wavelength_required` or a derived requirement stored by the analytic report; if neither is supplied, return `PASS_WITH_LIMITATION` with code `LIMIT_GRID_REQUIREMENT_UNDECLARED`, not a fabricated universal threshold. Critical geometry features with a declared minimum cell count must be checked exactly.

`audit_cfl` compares declared/observed `dt` to `courant_limit`. `audit_time_window` sums declared source delay/tail, longest relevant path, response duration, and guard. `audit_pml` checks declared clearance and optional domain-sensitivity evidence; missing sensitivity is only blocking when `acceptance.sensitivity_tests` requires it.

- [ ] **Step 4: Run numerics tests**

Run: `pytest tests/unit/test_numerics_gate.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/audit_numerics.py tests/unit/test_numerics_gate.py
git commit -m "feat: add numerical validity gates"
```

### Task 3: Material provenance and dispersion gate

**Files:**
- Create: `scripts/audit_materials.py`
- Test: `tests/unit/test_material_gate.py`

**Interfaces:**
- Produces: `complex_permittivity_debye(f_hz, epsilon_inf, delta_epsilon, tau_s, sigma_s_m)`, `audit_materials(ctx) -> GateResult`.

- [ ] **Step 1: Write tests for provenance and Debye physics**

```python
import numpy as np
from pathlib import Path
from scripts.core import GateContext, GateState
from scripts.audit_materials import audit_materials, complex_permittivity_debye


def test_debye_returns_finite_passive_loss():
    eps = complex_permittivity_debye(np.array([1e8]), 3.0, 1.0, 1e-9, 1e-3)
    assert np.isfinite(eps.real).all()
    assert np.isfinite(eps.imag).all()
    assert eps.real[0] > 0


def test_unknown_parameter_provenance_blocks_physical_claim(tmp_path: Path):
    contract = {
        "task": {"claim_scope": "physical"},
        "materials": [{"name": "m", "model": "nondispersive", "epsilon_r": 4.0, "sigma_s_m": 0.0}],
    }
    result = audit_materials(GateContext(tmp_path, contract))
    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_MATERIAL_PROVENANCE"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/unit/test_material_gate.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement material validation**

Use the `exp(+j omega t)`/`exp(-j omega t)` convention explicitly in the docstring and keep the returned sign convention consistent throughout tests. Validate positive permittivity, non-negative conductivity for passive nondispersive materials, positive Debye time constants, non-empty provenance class in `{measured, literature, manufacturer, assumed, sensitivity_only}`, and optional `frequency_range_valid_hz` containment of the requested analysis band.

For engineering/physical claims, `assumed` or `sensitivity_only` returns `PASS_WITH_LIMITATION` unless the contract incorrectly labels it as site-measured; missing provenance is blocking.

Store derived frequency-dependent arrays only as summaries (`min/max epsilon'`, `min/max loss`, `min/max phase velocity`) in `ctx.artifacts`, not enormous binary arrays.

- [ ] **Step 4: Run material tests**

Run: `pytest tests/unit/test_material_gate.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/audit_materials.py tests/unit/test_material_gate.py
git commit -m "feat: validate material provenance and dispersion"
```

### Task 4: Geometry quantization, dimensionality, and model-purpose gate

**Files:**
- Create: `scripts/audit_geometry.py`
- Create: `templates/model_purpose.yaml`
- Test: `tests/unit/test_geometry_gate.py`

**Interfaces:**
- Produces: `quantize_length(length_m, step_m) -> GeometryQuantization`, `audit_geometry(ctx)`, `audit_model_purpose(ctx)`.

- [ ] **Step 1: Write quantization and claim-barrier tests**

```python
from scripts.audit_geometry import quantize_length


def test_quantization_reports_effective_length():
    q = quantize_length(0.83, 0.05)
    assert q.cells == 17
    assert q.effective_m == 0.85
    assert q.error_m == 0.02
```

Add a contract fixture with `model.dimension="2d"`, `task.objective="system"`, `task.claim_scope="engineering"`; `audit_geometry` must return `BLOCK_DIMENSIONALITY_OVERCLAIM`. Add a model-purpose fixture with an empty `allowed_claims`; expect `BLOCK_MODEL_PURPOSE_UNDECLARED`.

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/unit/test_geometry_gate.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement geometry truth levels**

```python
@dataclass(frozen=True)
class GeometryQuantization:
    nominal_m: float
    step_m: float
    cells: int
    effective_m: float
    error_m: float


def quantize_length(length_m: float, step_m: float) -> GeometryQuantization:
    cells = max(1, int(round(length_m / step_m)))
    effective = cells * step_m
    return GeometryQuantization(length_m, step_m, cells, effective, effective - length_m)
```

`audit_geometry` checks declared coordinate axes, critical features, discretized truth, overlaps/gaps when a material occupancy manifest exists, and 2D→3D claim barriers. `audit_model_purpose` requires `model_id`, one `purpose`, non-empty `allowed_claims`, and explicit `forbidden_claims` list. The generic template contains symbolic example strings only.

- [ ] **Step 4: Run geometry tests**

Run: `pytest tests/unit/test_geometry_gate.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/audit_geometry.py templates/model_purpose.yaml tests/unit/test_geometry_gate.py
git commit -m "feat: audit geometry truth and model purpose"
```

### Task 5: Precision/dtype and ULP-floor gate

**Files:**
- Create: `scripts/audit_precision.py`
- Test: `tests/unit/test_precision_gate.py`

**Interfaces:**
- Produces: `local_ulp(values: np.ndarray) -> np.ndarray`, `precision_floor_ratio(total, differential) -> float`, `audit_precision(ctx) -> GateResult`.

- [ ] **Step 1: Write synthetic ULP-floor and HDF5 dtype tests**

```python
import h5py
import numpy as np
from pathlib import Path
from scripts.audit_precision import precision_floor_ratio, audit_precision
from scripts.core import GateContext, GateState


def test_float32_ulp_floor_is_detectable():
    total = np.array([1.0], dtype=np.float32)
    diff = np.array([np.spacing(np.float32(1.0))], dtype=np.float32)
    assert precision_floor_ratio(total, diff) <= 1.1


def test_required_fp64_blocks_float32_output(tmp_path: Path):
    out = tmp_path / "run.h5"
    with h5py.File(out, "w") as f:
        rx = f.create_group("rxs").create_group("rx1")
        rx.create_dataset("Ez", data=np.array([1.0, 2.0], dtype=np.float32))
    ctx = GateContext(tmp_path, {
        "numerics": {"precision_requirement": "float64"},
        "outputs": {"hdf5": "run.h5", "receiver_dataset": "/rxs/rx1/Ez"},
    })
    result = audit_precision(ctx)
    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_OUTPUT_DTYPE"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/unit/test_precision_gate.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement precision budget checks**

```python
def local_ulp(values: np.ndarray) -> np.ndarray:
    arr = np.asarray(values)
    return np.abs(np.spacing(arr))


def precision_floor_ratio(total: np.ndarray, differential: np.ndarray) -> float:
    ulp = local_ulp(total.astype(total.dtype, copy=False))
    mask = ulp > 0
    ratios = np.abs(differential[mask]) / ulp[mask]
    return float(np.nanmedian(ratios)) if ratios.size else float("inf")
```

`audit_precision` checks runtime real/complex dtype from `ctx.artifacts["environment"]`, actual HDF5 receiver dtype, finiteness, and optional `precision_audit` pair arrays. If contract risk flags include `weak_differential`, `long_distance`, `coherent_phase`, `high_dynamic_range`, or `fine_delay_fit`, require float64 unless `numerics.fp32_adequacy_evidence` is explicitly supplied and independently passes a comparison fixture.

For a provided total/differential diagnostic, block with `BLOCK_PRECISION_FLOOR` when the median differential is within the contract-declared `ulp_safety_factor` of local ULP; if no factor is declared for a required audit, use the regression-tested default *only inside this precision algorithm* and document it as a numerical safety margin, not a project physics threshold.

- [ ] **Step 4: Run precision tests**

Run: `pytest tests/unit/test_precision_gate.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/audit_precision.py tests/unit/test_precision_gate.py
git commit -m "feat: block dtype and floating point floor defects"
```

### Task 6: Machine-verifiable paired-run contract

**Files:**
- Create: `scripts/audit_pair_contract.py`
- Test: `tests/unit/test_pair_contract.py`

**Interfaces:**
- Produces: `diff_mappings(left, right, ignore_paths=()) -> list[str]`, `audit_pair_contract(ctx) -> GateResult`.

- [ ] **Step 1: Write target/reference invariant tests**

```python
from pathlib import Path
from scripts.audit_pair_contract import audit_pair_contract
from scripts.core import GateContext, GateState


def test_target_reference_material_mismatch_blocks(tmp_path: Path):
    contract = {
        "pair": {
            "kind": "target_reference",
            "left": {"grid": 0.01, "background_sigma": 0.001, "target": {"enabled": True}},
            "right": {"grid": 0.01, "background_sigma": 0.002, "target": {"enabled": False}},
            "allowed_differences": ["target"],
        }
    }
    result = audit_pair_contract(GateContext(tmp_path, contract))
    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_PAIR_CONTRACT"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/unit/test_pair_contract.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement recursive path-aware diff**

Flatten dictionaries to dotted paths, compare scalars/lists, remove differences whose path is equal to or nested below one of `allowed_differences`, and return the remaining unauthorized paths. A cross-material target/reference subtraction must therefore block automatically.

Return `NOT_APPLICABLE` when no pair is declared.

- [ ] **Step 4: Run pair tests**

Run: `pytest tests/unit/test_pair_contract.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/audit_pair_contract.py tests/unit/test_pair_contract.py
git commit -m "feat: enforce paired run invariants"
```

### Task 7: Compose numerical/model preflight registry and CLI stage

**Files:**
- Create: `scripts/preflight.py`
- Create: `scripts/run_manifest.py`
- Create: `scripts/smoke.py`
- Create: `scripts/run_simulation.py`
- Modify: `scripts/cli.py`
- Test: `tests/unit/test_preflight_registry.py`
- Test: `tests/unit/test_smoke_run.py`

**Interfaces:**
- Produces: `build_preflight_registry() -> GateRegistry` and CLI `validate-model`.

- [ ] **Step 1: Write an integration test proving ordering and short-circuit**

```python
from pathlib import Path
from scripts.preflight import build_preflight_registry


def test_preflight_registry_orders_environment_before_precision():
    ids = [g.gate_id for g in build_preflight_registry().for_stage("validate-model")]
    assert ids.index("environment") < ids.index("precision")
    assert ids.index("materials") < ids.index("geometry")
```

Add a CLI fixture with missing environment identity but otherwise valid geometry; `validate-model` must exit `2`, write environment `BLOCK`, and not claim a passing precision gate.

- [ ] **Step 2: Run integration tests and verify failure**

Run: `pytest tests/unit/test_preflight_registry.py -v`

Expected: FAIL.

- [ ] **Step 3: Register gates with explicit dependencies**

Register in this logical order:

```text
environment
→ materials
→ grid
→ cfl
→ time_window
→ pml
→ geometry
→ model_purpose
→ pair_contract
→ precision
```

`validate-model` loads the contract, runs this stage, writes `gates/validate-model.json`, and returns non-zero on any `BLOCK`.

- [ ] **Step 4: Run all Plan 2 tests**

Run:

```bash
pytest tests/unit/test_environment_gate.py tests/unit/test_numerics_gate.py tests/unit/test_material_gate.py tests/unit/test_geometry_gate.py tests/unit/test_precision_gate.py tests/unit/test_pair_contract.py tests/unit/test_preflight_registry.py tests/unit/test_smoke_run.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/preflight.py scripts/cli.py tests/unit/test_preflight_registry.py
git commit -m "feat: compose numerical model preflight"
```


### Task 8: Geometry-only smoke, guarded full run, and run manifest

**Files:**
- Create: `scripts/run_manifest.py`
- Create: `scripts/smoke.py`
- Create: `scripts/run_simulation.py`
- Modify: `scripts/cli.py`
- Test: `tests/unit/test_smoke_run.py`

**Interfaces:**
- Produces: `new_run_id(model_id, now=None) -> str`, `build_run_manifest(ctx, command, run_id) -> dict`, `ensure_run_allowed(project_root) -> GateResult`, `run_geometry_smoke(ctx) -> GateResult`, `run_physics_smoke(ctx) -> GateResult`, `run_full_simulation(ctx) -> GateResult`.
- Adds CLI: `smoke` and `run`.

- [ ] **Step 1: Write fail-closed execution tests using a fake runner**

```python
# tests/unit/test_smoke_run.py
from pathlib import Path
from scripts.core import GateState
from scripts.run_simulation import ensure_run_allowed


def test_blocked_preflight_prevents_execution(tmp_path: Path):
    gates = tmp_path / "gates"
    gates.mkdir()
    (gates / "validate-model.json").write_text(
        '{"results":[{"gate_id":"grid","state":"BLOCK","code":"BLOCK_GRID",'
        '"summary":"bad","evidence":[],"invalidates":[]}]}',
        encoding="utf-8",
    )
    result = ensure_run_allowed(tmp_path)
    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_UPSTREAM_GATE"
```

Add a fake runner script that records received argv into a file and exits `0`. A smoke contract declares:

```yaml
runtime:
  runner_argv: [python, tests/fixtures/fake_gprmax_runner.py]
  geometry_only_args: [--geometry-only]
model:
  input_file: model.in
smoke:
  physics_input_file: smoke_model.in
```

Assert `smoke` first invokes the configured geometry-only arguments, then invokes `smoke.physics_input_file` as a separate low-cost physics run when declared, and `run` never invokes the full runner while an upstream gate is blocking.

- [ ] **Step 2: Run the tests and verify failure**

Run: `pytest tests/unit/test_smoke_run.py -v`

Expected: FAIL because guarded execution modules do not exist.

- [ ] **Step 3: Implement execution guards and manifest creation**

`ensure_run_allowed` reads the latest required gate reports and blocks on any `BLOCK` or `STALE`. It must not treat missing required reports as success.

`run_geometry_smoke` builds the command exclusively from `runtime.runner_argv`, `runtime.geometry_only_args`, and `model.input_file`; it writes stdout/stderr and return code to `logs/smoke/geometry/` and returns `BLOCK_SMOKE_FAILED` on non-zero exit. `run_physics_smoke` is executed only when `smoke.physics_input_file` is declared; it runs that explicitly low-cost model, writes its artifacts under `logs/smoke/physics/`, and requires contract-declared sanity checks such as finite Rx data, expected causal arrival ordering, or monotonic loss trend. A physics-smoke failure blocks full execution.

`run_full_simulation` uses the same configured runner without geometry-only args, creates a unique run ID, writes `manifests/<run_id>.json`, captures command, environment artifact, input hashes, declared numerics, start/end timestamps, output paths, and process return code. It returns `BLOCK_RUN_FAILED` on non-zero exit.

Use an injectible clock for deterministic unit tests:

```python
def new_run_id(model_id: str, now: datetime | None = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", model_id)
    return f"{stamp}_{safe}_{secrets.token_hex(3)}"
```

- [ ] **Step 4: Run smoke/run and all Plan 2 tests**

Run:

```bash
pytest tests/unit/test_smoke_run.py tests/unit/test_environment_gate.py tests/unit/test_numerics_gate.py tests/unit/test_material_gate.py tests/unit/test_geometry_gate.py tests/unit/test_precision_gate.py tests/unit/test_pair_contract.py tests/unit/test_preflight_registry.py tests/unit/test_smoke_run.py -q
```

Expected: PASS. The fake full runner is not called in the blocked fixture.

- [ ] **Step 5: Commit guarded execution**

```bash
git add scripts/run_manifest.py scripts/smoke.py scripts/run_simulation.py scripts/cli.py tests/unit/test_smoke_run.py tests/fixtures/fake_gprmax_runner.py
git commit -m "feat: gate smoke and full gprmax execution"
```

## Plan 2 completion gate

Run the Plan 2 unit suite plus the Plan 1 core suite. Then run one deliberately broken float32 fixture and one unauthorized target/reference material mismatch fixture through `validate-model`; both must exit `2` and emit their specific `BLOCK_*` codes.
