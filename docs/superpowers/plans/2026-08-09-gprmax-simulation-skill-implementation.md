# gprMax Simulation Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the frozen general-purpose, fail-closed gprMax simulation Skill as a modular, testable package with machine-enforced gates, regression tests, provenance, and claim sign-off.

**Architecture:** A thin `SKILL.md` routes tasks through a Python gate engine and modular technical references. The gate engine validates a single simulation contract, produces machine-readable statuses, blocks promotion on critical defects, invalidates stale downstream claims, and keeps project-specific tunnel-face values isolated in case studies rather than core defaults.

**Tech Stack:** Python 3.11+, `argparse`, `dataclasses`, `pathlib`, PyYAML, jsonschema, NumPy, h5py, pytest; gprMax is an external runtime used only by smoke/regression tests that declare it as required.

## Global Constraints

- Generic core must not hard-code project-specific frequency bands, target distances, relative permittivity, conductivity, transmitter power, isolation, receiver noise figure, window function, or resolution threshold.
- Blocking numerical, physical, processing, calibration, or evidence defects stop promotion; there is no warning-only bypass for blocking gates.
- Raw simulation evidence is immutable; every derived artifact records provenance.
- A successful `.out` file is not equivalent to physical or engineering validation.
- Historical failures enter mandatory logic only when the root cause, fix, scope, and regression are confirmed.
- Detailed technical rules live in modular references and are loaded only when relevant; `SKILL.md` remains orchestration-focused.
- Upstream changes invalidate dependent downstream claims to `STALE` until revalidated.
- Implementation uses TDD and each task ends in a passing, reviewable deliverable and a focused commit.

---

## Plan decomposition

The frozen design spans several independently reviewable subsystems. Implement them in this order:

1. [`2026-08-09-gprmax-core-contract-gates-plan.md`](2026-08-09-gprmax-core-contract-gates-plan.md) — package skeleton, schemas, contract loader, gate engine, fidelity promotion, dependency invalidation, CLI foundation.
2. [`2026-08-09-gprmax-numerical-model-gates-plan.md`](2026-08-09-gprmax-numerical-model-gates-plan.md) — environment, grid/CFL/time/PML, materials, geometry, precision, pair contracts, model-purpose preflight.
3. [`2026-08-09-gprmax-source-sfcw-plan.md`](2026-08-09-gprmax-source-sfcw-plan.md) — source audit, exact-tone complex extraction, delay de-embedding, regularized deconvolution, SFCW/range rules, reference policy.
4. [`2026-08-09-gprmax-antenna-system-plan.md`](2026-08-09-gprmax-antenna-system-plan.md) — feed topology, port/power identities, field-to-power calibration, direct coupling/isolation, receiver/noise/ADC chain.
5. [`2026-08-09-gprmax-analysis-evidence-plan.md`](2026-08-09-gprmax-analysis-evidence-plan.md) — RAW/CALIBRATED/DISPLAY separation, detection/localization/resolution/inversion gates, Pd/Pfa, provenance, claim ledger, evidence freeze.
6. [`2026-08-09-gprmax-skill-docs-regression-plan.md`](2026-08-09-gprmax-skill-docs-regression-plan.md) — SKILL orchestration, references, historical failure catalog, regression suite, deliberately broken fixtures, end-to-end acceptance.

## Cross-plan interface contract

All plans share these stable interfaces created in Plan 1:

```python
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Mapping

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

@dataclass
class GateContext:
    project_root: Path
    contract: Mapping[str, Any]
    artifacts: dict[str, Any] = field(default_factory=dict)

GateFunction = Callable[[GateContext], GateResult]
```

Every gate function consumes a `GateContext` and returns one `GateResult`. It may read files and place explicitly derived values into `context.artifacts`, but it may not mutate raw simulation files.

## Integration acceptance command

After all six plans are implemented, the final repository-level check is:

```bash
python -m pytest -q
python -m scripts.cli preflight tests/fixtures/contracts/minimal_valid.yaml --project-root tests/fixtures/projects/minimal
python -m scripts.cli signoff tests/fixtures/contracts/minimal_valid.yaml --project-root tests/fixtures/projects/minimal
```

Expected final behavior:

- full pytest suite passes;
- valid minimal fixture reaches the highest claim state supported by its declared fidelity, without inventing unsupported hardware claims;
- every deliberately broken fixture exits non-zero and writes a `BLOCK_*` gate result;
- a modified upstream source/timebase fixture marks dependent claims `STALE`;
- no core file contains tunnel-face-specific numerical defaults.


## Writing-plans self-review

### Spec coverage

- Design §§1–5 (purpose, non-goals, claim-first contract, fail-closed state machine) → Plan 1 Tasks 1–6.
- Design §6 (F0–F5) → Plan 1 Tasks 4–5 plus Plan 2 F0 analytic report and guarded smoke/run.
- Design §7 (environment/grid/CFL/time/PML/material numerics/precision/convergence) → Plan 2 Tasks 1–7.
- Design §8 (source/waveform/SFCW) → Plan 3 Tasks 1–7, including exact-tone, complex phase, source-delay, deconvolution, zero-padding, reference policy, and sweep-position semantics.
- Design §9 (antenna/port/system) → Plan 4 Tasks 1–7.
- Design §10 (materials/geometry/targets) → Plan 2 Tasks 3–6, with material provenance, dispersion, geometry truth, dimensionality barriers, and pair contracts.
- Design §11 (processing/detection/resolution/inversion) → Plan 5 Tasks 1–5.
- Design §12 (run manifests, immutable evidence, claim ledger, failure memory, supersession/freeze) → Plan 2 Task 8, Plan 5 Tasks 6–8, Plan 6 Tasks 3–5.
- Design §§13–15 (software architecture, staged executor, dependency invalidation) → Plan 1 and Plan 2 Task 8; all stage commands from the design are explicitly assigned.
- Design §16 (unit/synthetic/minimal-gprMax/historical regression testing) → Plans 1–6, with real-gprMax tests isolated under the `gprmax` marker.
- Design §§17–18 (case-study isolation, profiles, self-update process) → Plan 6 Tasks 1–3; profiles remain optional and are not required for the first generic release.
- Design §19 (Definition of Done) → Plan 6 Tasks 6–9 and the umbrella integration acceptance command.

Gaps found during self-review and fixed inline: explicit `smoke`/`run` implementation, low-cost physics smoke support, F0 analytic-sanity artifact, formal run-manifest writer, runtime `failure_events.jsonl`, residual source-delay blocking code, truth-reference engineering-scope blocking code, and real-gprMax regression layer.

### Placeholder scan

All plan files were scanned for the writing-plans red-flag placeholder patterns. No unresolved placeholder token remains.

### Type/interface consistency

The shared state interface is fixed in Plan 1: `GateContext`, `GateResult`, `GateState`, `ClaimState`, `GateRegistry`, and dependency invalidation. Later plans consume these names rather than redefining them. CLI stages are additive and share exit code `2` for blocking failures. Raw evidence is never mutated by a gate function.
