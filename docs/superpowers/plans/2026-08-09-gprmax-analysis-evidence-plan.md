# gprMax Analysis, Claims, and Evidence Chain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement processing-layer separation, metric-specific acceptance, detection/localization/resolution/inversion claim gates, statistical validation, claim ledgers, immutable provenance, and evidence freeze.

**Architecture:** `scripts/audit_processing.py` validates what transformations are allowed to feed metrics. `scripts/audit_claims.py` validates metric-to-claim compatibility and statistical evidence. `scripts/freeze_evidence.py` hashes and freezes artifacts and marks downstream claims stale when upstream inputs change.

**Tech Stack:** Python 3.11+, NumPy, pytest, standard-library `hashlib`, `json`, `pathlib`.

## Global Constraints

- RAW, CALIBRATED/PHYSICAL, and DISPLAY_ONLY layers are distinct; display-only outputs never feed quantitative metrics.
- Processing choices used for comparison are frozen before outcome inspection.
- Detection, localization, resolution, thickness, inversion, and hardware/system claims use different gates.
- -3 dB width is descriptive unless a project contract explicitly defines it as the accepted separability criterion.
- Pd/Pfa claims require fixed detector policy, positive and negative populations, seed provenance, sample size, and confidence interval.
- Claim states are `UNVERIFIED`, `CONDITIONAL`, `VERIFIED`, `REJECTED`, or `STALE`.
- Every signed claim is traceable to runs, artifacts, gate results, and hashes.

---

## File map

- Create: `scripts/audit_processing.py`
- Create: `scripts/metrics.py`
- Create: `scripts/audit_claims.py`
- Create: `scripts/freeze_evidence.py`
- Create: `scripts/failure_memory.py`
- Create: `schemas/claim_ledger.schema.json`
- Create: `schemas/failure_event.schema.json`
- Create: `templates/claim_ledger.yaml`
- Modify: `scripts/cli.py`
- Test: `tests/unit/test_processing_layers.py`
- Test: `tests/unit/test_detection_localization.py`
- Test: `tests/unit/test_resolution_metrics.py`
- Test: `tests/unit/test_statistics.py`
- Test: `tests/unit/test_claim_ledger.py`
- Test: `tests/unit/test_evidence_freeze.py`
- Test: `tests/unit/test_failure_memory.py`
- Test: `tests/regression/test_guard_selection.py`
- Test: `tests/regression/test_resolution_overclaim.py`

### Task 1: Data-layer and processing-contract enforcement

**Files:**
- Create: `scripts/audit_processing.py`
- Test: `tests/unit/test_processing_layers.py`

**Interfaces:**
- Produces: `DataLayer`, `ProcessingStep`, `audit_processing(ctx) -> GateResult`.

- [ ] **Step 1: Write display-data misuse and post-hoc processing tests**

```python
from pathlib import Path
from scripts.audit_processing import audit_processing
from scripts.core import GateContext, GateState


def test_display_only_data_cannot_feed_metric(tmp_path: Path):
    contract = {
        "processing": {
            "artifacts": {"pretty_trace": {"layer": "DISPLAY_ONLY"}},
            "metrics": {"snr": {"input_artifact": "pretty_trace"}},
        }
    }
    result = audit_processing(GateContext(tmp_path, contract))
    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_DISPLAY_DATA_METRIC"
```

Add a comparative-band fixture whose window/filter is marked `selected_after_results=true`; expect `BLOCK_OUTCOME_DEPENDENT_PROCESSING`.

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/unit/test_processing_layers.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement layer and processing policy**

```python
class DataLayer(StrEnum):
    RAW = "RAW"
    CALIBRATED = "CALIBRATED"
    DISPLAY_ONLY = "DISPLAY_ONLY"
```

Allow quantitative metrics to consume RAW or CALIBRATED only. Require every CALIBRATED artifact to declare `parents`, `operation`, and `parameters_hash`. Require comparative processing steps to declare `predeclared=true`; otherwise block formal comparison claims.

- [ ] **Step 4: Run processing tests**

Run: `pytest tests/unit/test_processing_layers.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/audit_processing.py tests/unit/test_processing_layers.py
git commit -m "feat: separate quantitative and display processing layers"
```

### Task 2: Detection and localization metrics remain separate

**Files:**
- Create: `scripts/metrics.py`
- Test: `tests/unit/test_detection_localization.py`

**Interfaces:**
- Produces: `peak_to_guard_ratio(signal, target_slice, guard_slice)`, `localize_peak(signal, search_slice)`, `audit_detection_localization(ctx)`.

- [ ] **Step 1: Write a case where strongest target-window peak is not the front interface**

```python
import numpy as np
from scripts.metrics import localize_peak


def test_localization_uses_declared_search_region_only():
    x = np.array([0.0, 2.0, 0.5, 5.0, 0.0])
    assert localize_peak(x, slice(0, 3)) == 1
```

Add a contract where `detection.window == localization.window` and the physical localization feature is `front_interface` but the window spans both interfaces; require `BLOCK_DETECTION_LOCALIZATION_COUPLING` unless a separate physical localization rule is declared.

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/unit/test_detection_localization.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement simple deterministic metrics and gate**

`peak_to_guard_ratio` must use only predeclared slices and return a linear ratio; any dB conversion is performed by an explicit caller. `localize_peak` returns the index of maximum absolute amplitude inside the declared search region and maps it back to full-array index.

- [ ] **Step 4: Run detection/localization tests**

Run: `pytest tests/unit/test_detection_localization.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/metrics.py tests/unit/test_detection_localization.py
git commit -m "feat: separate detection and localization metrics"
```

### Task 3: Resolution definitions, PSF valley stability, and -3 dB barrier

**Files:**
- Modify: `scripts/metrics.py`
- Create: `scripts/audit_claims.py`
- Test: `tests/unit/test_resolution_metrics.py`
- Test: `tests/regression/test_resolution_overclaim.py`

**Interfaces:**
- Produces: `stable_first_valley(profile, peak_index, min_prominence, min_width)`, `minus3db_width(profile, spacing)`, `audit_resolution_claim(ctx)`.

- [ ] **Step 1: Write stable-valley and overclaim tests**

```python
import numpy as np
from scripts.metrics import stable_first_valley


def test_single_sample_noise_dip_is_not_stable_valley():
    profile = np.array([0.0, 1.0, 0.98, 0.2, 0.21, 0.22])
    idx = stable_first_valley(profile, peak_index=1, min_prominence=0.5, min_width=2)
    assert idx == 3
```

Create a regression fixture with `evidence.metric="minus3db_width"` and `claim="two_target_separable"` but no contract declaring -3 dB as the acceptance criterion; expect `BLOCK_RESOLUTION_DEFINITION`.

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/unit/test_resolution_metrics.py tests/regression/test_resolution_overclaim.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement metric-family compatibility**

`audit_resolution_claim` permits a resolution claim only when the metric family matches one of the contract-declared families: `psf`, `two_target`, `two_interface`, `thickness_recovery`, `minus3db`, or custom named metric. `minus3db` may certify separability only when the acceptance contract explicitly selects it.

`stable_first_valley` must require both persistence/width and prominence; it may not return the first numerical local minimum unconditionally.

- [ ] **Step 4: Run resolution tests**

Run: `pytest tests/unit/test_resolution_metrics.py tests/regression/test_resolution_overclaim.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/metrics.py scripts/audit_claims.py tests/unit/test_resolution_metrics.py tests/regression/test_resolution_overclaim.py
git commit -m "feat: enforce resolution metric claim compatibility"
```

### Task 4: Thickness/inversion tiers and complex-physics requirement

**Files:**
- Modify: `scripts/audit_claims.py`
- Test: `tests/unit/test_resolution_metrics.py`

**Interfaces:**
- Produces: `audit_thickness_claim(ctx) -> GateResult`.

- [ ] **Step 1: Add tests for T0/T1/T2 and real-only fitting block**

Create fixtures:

- `T1` with one deterministic case requesting a general `method_recovers_thickness` claim → `BLOCK_THICKNESS_SIGNOFF`.
- `T2` with multiple truth thicknesses, negative control, uncertainty runs, complex fit, material velocity, polarity bounds → PASS.
- precision delay fit with `fit_domain="real_only"` → `BLOCK_INVERSION_COMPLEX_PHASE`.

- [ ] **Step 2: Run targeted tests**

Run: `pytest tests/unit/test_resolution_metrics.py -v`

Expected: FAIL until tier logic exists.

- [ ] **Step 3: Implement tier rules**

T0 may only claim qualitative interface information. T1 may claim the returned estimate for that specific case. T2 requires at least two distinct truth values, declared uncertainty/negative controls, physics-constrained bounds, and complex response for coherent delay/thickness claims.

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_resolution_metrics.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/audit_claims.py tests/unit/test_resolution_metrics.py
git commit -m "feat: gate thickness and inversion claim tiers"
```

### Task 5: SNR guard policy, Monte Carlo semantics, Pd/Pfa, and confidence intervals

**Files:**
- Modify: `scripts/metrics.py`
- Modify: `scripts/audit_claims.py`
- Test: `tests/unit/test_statistics.py`
- Test: `tests/regression/test_guard_selection.py`

**Interfaces:**
- Produces: `wilson_interval(successes, trials, z=1.959963984540054)`, `audit_statistics(ctx)`.

- [ ] **Step 1: Write statistical and target-aware guard tests**

```python
from scripts.metrics import wilson_interval


def test_wilson_interval_bounds_probability():
    low, high = wilson_interval(90, 100)
    assert 0.0 <= low <= 0.9 <= high <= 1.0
```

Create a guard fixture with `selection="chosen_after_truth_location"`; expect `BLOCK_TARGET_AWARE_GUARD_SELECTION`. Create a Pd fixture with no negative population/Pfa evidence; expect `BLOCK_STATISTICAL_EVIDENCE`.

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/unit/test_statistics.py tests/regression/test_guard_selection.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement Wilson interval and statistical contract checks**

```python
def wilson_interval(successes: int, trials: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if trials <= 0 or not 0 <= successes <= trials:
        raise ValueError("invalid binomial counts")
    p = successes / trials
    denom = 1 + z*z/trials
    centre = (p + z*z/(2*trials)) / denom
    margin = z * ((p*(1-p)/trials + z*z/(4*trials*trials)) ** 0.5) / denom
    return max(0.0, centre-margin), min(1.0, centre+margin)
```

`audit_statistics` requires every Monte Carlo random variable to declare distribution, correlation, signal-chain location, and sampling cadence (`per_tone`, `per_trace`, `per_run`, or named custom cadence). Detector and threshold policy must be frozen before trials.

- [ ] **Step 4: Run statistical tests**

Run: `pytest tests/unit/test_statistics.py tests/regression/test_guard_selection.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/metrics.py scripts/audit_claims.py tests/unit/test_statistics.py tests/regression/test_guard_selection.py
git commit -m "feat: validate statistical detection evidence"
```

### Task 6: Claim ledger schema and deterministic status updates

**Files:**
- Create: `schemas/claim_ledger.schema.json`
- Create: `templates/claim_ledger.yaml`
- Modify: `scripts/audit_claims.py`
- Test: `tests/unit/test_claim_ledger.py`

**Interfaces:**
- Produces: `load_claim_ledger(path)`, `evaluate_claim(claim, gate_results) -> ClaimState`, `update_claim_ledger(...)`.

- [ ] **Step 1: Write ledger-status tests**

```python
from scripts.core import ClaimState, GateResult, GateState
from scripts.audit_claims import evaluate_claim


def test_blocking_required_gate_rejects_claim():
    claim = {"required_gates": ["resolution"]}
    results = {"resolution": GateResult("resolution", GateState.BLOCK, "BLOCK_RES", "bad")}
    assert evaluate_claim(claim, results) is ClaimState.REJECTED


def test_missing_required_gate_is_unverified():
    claim = {"required_gates": ["resolution"]}
    assert evaluate_claim(claim, {}) is ClaimState.UNVERIFIED
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/unit/test_claim_ledger.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement ledger schema and state evaluation**

A claim entry must include `claim_id`, `text`, `required_gates`, `supporting_runs`, `supporting_artifacts`, `limitations`, and `forbidden_upgrades`. `PASS_WITH_LIMITATION` on any required gate yields `CONDITIONAL`; all required gates PASS yields `VERIFIED`; explicit negative evidence may set `REJECTED`; upstream invalidation sets `STALE` regardless of prior verification.

- [ ] **Step 4: Run ledger tests**

Run: `pytest tests/unit/test_claim_ledger.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add schemas/claim_ledger.schema.json templates/claim_ledger.yaml scripts/audit_claims.py tests/unit/test_claim_ledger.py
git commit -m "feat: add machine readable claim ledger"
```

### Task 7: Immutable evidence freeze and stale-on-change behavior

**Files:**
- Create: `scripts/freeze_evidence.py`
- Create: `scripts/failure_memory.py`
- Create: `schemas/failure_event.schema.json`
- Test: `tests/unit/test_evidence_freeze.py`
- Test: `tests/unit/test_failure_memory.py`

**Interfaces:**
- Produces: `sha256_file(path)`, `build_evidence_manifest(project_root, paths)`, `freeze_evidence(ctx) -> Path`, `detect_changed_inputs(frozen_manifest, project_root) -> set[str]`.

- [ ] **Step 1: Write hash and stale detection tests**

```python
from pathlib import Path
from scripts.freeze_evidence import sha256_file, build_evidence_manifest, detect_changed_inputs


def test_changed_input_is_detected(tmp_path: Path):
    p = tmp_path / "input.in"
    p.write_text("a", encoding="utf-8")
    manifest = build_evidence_manifest(tmp_path, [Path("input.in")])
    p.write_text("b", encoding="utf-8")
    assert detect_changed_inputs(manifest, tmp_path) == {"input.in"}
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/unit/test_evidence_freeze.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement immutable manifest writing**

`freeze_evidence` writes:

```text
evidence_manifest.json
SHA256SUMS.txt
claim_ledger.json
gate_summary.json
```

under a new timestamped freeze directory. It must refuse to overwrite an existing freeze directory. `detect_changed_inputs` feeds Plan 1 dependency invalidation so upstream changes mark affected claims `STALE`.

- [ ] **Step 4: Run evidence tests**

Run: `pytest tests/unit/test_evidence_freeze.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/freeze_evidence.py schemas/failure_event.schema.json tests/unit/test_evidence_freeze.py
git commit -m "feat: freeze evidence with cryptographic provenance"
```


### Task 8: Failure-event journal with schema validation

**Files:**
- Create: `scripts/failure_memory.py`
- Modify: `schemas/failure_event.schema.json`
- Test: `tests/unit/test_failure_memory.py`

**Interfaces:**
- Produces: `validate_failure_event(event) -> None`, `append_failure_event(project_root, event) -> Path`.
- Runtime journal path: `failure_events.jsonl` at project root; historical promoted incidents remain a separate curated catalog in Plan 6.

- [ ] **Step 1: Write schema and append-only journal tests**

```python
from pathlib import Path
import json
import pytest
from scripts.failure_memory import append_failure_event, validate_failure_event


def test_failure_event_requires_root_cause_state(tmp_path: Path):
    event = {
        "failure_id": "evt-1",
        "category": "precision",
        "symptom": "residual floor",
        "root_cause_status": "unconfirmed",
        "diagnostic": "compare against ULP",
        "scope": "current run"
    }
    path = append_failure_event(tmp_path, event)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["root_cause_status"] == "unconfirmed"


def test_invalid_failure_event_is_rejected():
    with pytest.raises(ValueError):
        validate_failure_event({"category": "precision"})
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/unit/test_failure_memory.py -v`

Expected: FAIL because the runtime failure journal does not exist.

- [ ] **Step 3: Implement append-only runtime incidents without auto-promotion**

The schema must require `failure_id`, `category`, `symptom`, `root_cause_status`, `diagnostic`, and `scope`. `root_cause_status` is one of `unconfirmed`, `confirmed`, or `superseded`. Optional `fix`, `minimal_reproducer`, `preventive_gate`, and `regression_test` fields may be present after investigation.

`append_failure_event` validates, creates one compact sorted JSON object per line, opens the journal in append mode, and never rewrites earlier events. It must not alter the curated failure catalog or convert an unconfirmed event into a mandatory rule.

- [ ] **Step 4: Run failure-journal and evidence tests**

Run: `pytest tests/unit/test_failure_memory.py tests/unit/test_evidence_freeze.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/failure_memory.py schemas/failure_event.schema.json tests/unit/test_failure_memory.py
git commit -m "feat: add append only simulation failure journal"
```

### Task 9: Analyze/signoff/freeze CLI stages

**Files:**
- Modify: `scripts/cli.py`
- Test: `tests/unit/test_claim_ledger.py`
- Test: `tests/unit/test_evidence_freeze.py`
- Test: `tests/unit/test_failure_memory.py`

**Interfaces:**
- Adds CLI: `analyze`, `signoff`, `freeze`.

- [ ] **Step 1: Add CLI tests for unsupported claim and clean freeze**

The unsupported-claim fixture must exit `2`. A valid numerical-only fixture with all required gates must write a claim ledger and freeze directory with exit `0`.

- [ ] **Step 2: Run targeted CLI tests**

Run: `pytest tests/unit/test_claim_ledger.py tests/unit/test_evidence_freeze.py -v`

Expected: FAIL until CLI wiring exists.

- [ ] **Step 3: Wire stages without bypassing earlier gate reports**

`analyze` runs processing/metric gates; `signoff` evaluates the ledger only from stored gate results; `freeze` requires no blocking/stale required gate for any claim marked VERIFIED and then writes immutable evidence.

- [ ] **Step 4: Run all Plan 5 tests**

Run:

```bash
pytest tests/unit/test_processing_layers.py tests/unit/test_detection_localization.py tests/unit/test_resolution_metrics.py tests/unit/test_statistics.py tests/unit/test_claim_ledger.py tests/unit/test_evidence_freeze.py tests/unit/test_failure_memory.py tests/regression/test_guard_selection.py tests/regression/test_resolution_overclaim.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/cli.py tests/unit/test_claim_ledger.py tests/unit/test_evidence_freeze.py
git commit -m "feat: add analysis signoff and evidence freeze stages"
```

## Plan 5 completion gate

Run valid and deliberately invalid fixtures for display-only metric input, shared detection/localization maximum, unstable PSF valley, -3 dB overclaim, target-aware guard, incomplete Pd/Pfa evidence, and stale input hash. Each defect must be blocked with a specific code; clean claims must remain scoped to the evidence actually present.
