# gprMax Skill Orchestration, References, and Historical Regression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the tested gate engine into a compact reusable Agent Skill, document each technical module, encode confirmed historical failures as regression fixtures, and prove end-to-end fail-closed behavior without leaking tunnel-face-specific defaults into the generic core.

**Architecture:** `SKILL.md` is a thin orchestration document that directs the Agent to create/validate the simulation contract, load only the references needed by the task, run staged gates, stop on blocks, and preserve evidence. Technical details live in `references/`; historical incidents live in `case-studies/` and regression fixtures, never in core defaults.

**Tech Stack:** Markdown Skill files, Python/pytest regression suite from Plans 1–5, standard shell grep/search checks for leakage and placeholders.

## Global Constraints

- `SKILL.md` must remain orchestration-focused and must not duplicate every technical formula.
- References are loaded conditionally based on the simulation contract.
- Historical tunnel-face values may appear in case-study evidence only; they may not appear as generic defaults or mandatory thresholds.
- Every promoted historical rule must state symptom, confirmed root cause, diagnostic, fix, preventive gate, scope, and regression ID.
- Deliberately broken regression fixtures must be blocked, not merely warned.
- Skill completion requires a full test run and explicit verification-before-completion before claiming success.

---

## File map

- Create: `SKILL.md`
- Create: `references/01-physics-contract.md`
- Create: `references/02-fidelity-promotion.md`
- Create: `references/03-numerical-validity.md`
- Create: `references/04-source-waveform.md`
- Create: `references/05-sfcw.md`
- Create: `references/06-antenna-port-system.md`
- Create: `references/07-materials.md`
- Create: `references/08-geometry-targets.md`
- Create: `references/09-postprocessing.md`
- Create: `references/10-detection-resolution-inversion.md`
- Create: `references/11-evidence-provenance.md`
- Create: `references/12-failure-catalog.md`
- Create: `case-studies/historical-gprmax-lessons/README.md`
- Create: `case-studies/historical-gprmax-lessons/incidents.yaml`
- Create: `tests/regression/test_fp32_floor.py`
- Create: `tests/regression/test_source_delay.py`
- Create: `tests/regression/test_real_only_phase.py`
- Create: `tests/regression/test_interface_polarity.py`
- Create: `tests/regression/test_feed_open_circuit.py`
- Create: `tests/regression/test_cross_reference.py`
- Create: `tests/regression/test_skill_fail_closed.py`
- Create: `tests/integration/test_end_to_end.py`
- Create: `tests/gprmax/test_minimal_solver.py`
- Create: `tests/fixtures/gprmax/` minimal solver input fixtures
- Create: `tests/unit/test_skill_content.py`

### Task 1: Write the thin orchestration SKILL.md under the skill-creator rules

**Required sub-skill before this task:** Read and follow `superpowers:writing-skills`; do not author or revise `SKILL.md` before that skill has been invoked.

**Files:**
- Create: `SKILL.md`
- Test: `tests/unit/test_skill_content.py`

**Interfaces:**
- The Agent-facing contract is procedural: classify task → create/load simulation contract → determine required references → run stages → stop on block → sign only supported claims → freeze evidence.

- [ ] **Step 1: Write content tests before authoring the Skill**

```python
from pathlib import Path


def test_skill_contains_required_fail_closed_language():
    text = Path("SKILL.md").read_text(encoding="utf-8")
    for phrase in (
        "fail-closed",
        "simulation_contract",
        "F0",
        "F5",
        "BLOCK",
        "STALE",
        "claim",
        "evidence",
    ):
        assert phrase in text


def test_skill_does_not_embed_case_specific_defaults():
    text = Path("SKILL.md").read_text(encoding="utf-8")
    forbidden = ("40–200", "80–200", "100 m", "37 dBm", "60 dB", "5×10⁻⁴")
    assert all(value not in text for value in forbidden)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/unit/test_skill_content.py -v`

Expected: FAIL because `SKILL.md` does not exist.

- [ ] **Step 3: Author SKILL.md as orchestration, not a textbook**

The Skill must contain these sections with operational imperative language:

```text
When to use
Non-negotiable fail-closed rules
Task intake and simulation contract
F0–F5 fidelity promotion
Reference routing table
Stage execution order
Stop/root-cause/regression workflow
Claim-scope rules
Evidence freeze
Output expectations
```

The reference routing table must map conditions such as `measurement_mode=sfcw_equivalent` → `references/05-sfcw.md`, A1/A2 antenna representations → `references/06-antenna-port-system.md`, dispersive materials → `references/07-materials.md`, resolution/inversion objectives → `references/10-detection-resolution-inversion.md`.

Do not put project-specific example numbers in the generic skill.

- [ ] **Step 4: Run content tests**

Run: `pytest tests/unit/test_skill_content.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add SKILL.md tests/unit/test_skill_content.py
git commit -m "docs: add fail closed gprmax orchestration skill"
```

### Task 2: Write modular technical references from the frozen design

**Files:**
- Create all `references/01-...` through `references/11-...`
- Test: `tests/unit/test_skill_content.py`

**Interfaces:**
- Each reference has: applicability trigger, required inputs, blocking conditions/codes, allowed outputs/claims, and links to the exact audit script/tests.

- [ ] **Step 1: Extend tests to require all reference files and no duplicated case defaults**

```python
def test_all_routed_references_exist():
    expected = [
        "01-physics-contract.md", "02-fidelity-promotion.md", "03-numerical-validity.md",
        "04-source-waveform.md", "05-sfcw.md", "06-antenna-port-system.md",
        "07-materials.md", "08-geometry-targets.md", "09-postprocessing.md",
        "10-detection-resolution-inversion.md", "11-evidence-provenance.md",
    ]
    for name in expected:
        assert (Path("references") / name).exists()
```

- [ ] **Step 2: Run the test and verify failure**

Run: `pytest tests/unit/test_skill_content.py -v`

Expected: FAIL because references are absent.

- [ ] **Step 3: Author each reference with exact responsibility boundaries**

Required mappings:

```text
01 → Simulation Contract and claim-first intake
02 → F0–F5 meanings, skip justification, minimum fidelity
03 → environment/grid/CFL/time/PML/precision/convergence
04 → excitation waveform, spectrum, DC, tail, time references
05 → exact-tone complex SFCW, deconvolution, delay, windows, zero-padding, REF semantics
06 → A0/A1/A2, feed topology, port/power/calibration, receiver chain
07 → provenance, nondispersive/dispersive materials, sensitivity
08 → coordinates, quantization, occupancy, smoothing, finite targets, pair/model purpose
09 → RAW/CALIBRATED/DISPLAY, frozen processing, background/gain policy
10 → detection/localization/resolution/thickness/inversion/SNR/Pd-Pfa/Monte Carlo
11 → manifests, hashes, claim ledger, invalidation, freeze
```

Every blocking code documented in a reference must correspond to code implemented by Plans 1–5; do not invent unimplemented codes.

- [ ] **Step 4: Run reference/content tests**

Run: `pytest tests/unit/test_skill_content.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add references tests/unit/test_skill_content.py
git commit -m "docs: add modular gprmax validation references"
```

### Task 3: Build confirmed historical failure catalog with supersession metadata

**Files:**
- Create: `references/12-failure-catalog.md`
- Create: `case-studies/historical-gprmax-lessons/README.md`
- Create: `case-studies/historical-gprmax-lessons/incidents.yaml`
- Test: `tests/unit/test_skill_content.py`

**Interfaces:**
- Each incident entry contains `failure_id`, `category`, `symptom`, `root_cause`, `why_it_looked_plausible`, `diagnostic`, `minimal_reproducer`, `fix`, `preventive_gate`, `scope`, `classification`, `active`, `superseded_by`, `regression_test`.

- [ ] **Step 1: Add schema-like content tests for incident completeness**

```python
import yaml


def test_every_promoted_incident_has_confirmed_fields():
    incidents = yaml.safe_load(Path("case-studies/historical-gprmax-lessons/incidents.yaml").read_text(encoding="utf-8"))
    required = {
        "failure_id", "category", "symptom", "root_cause", "diagnostic", "minimal_reproducer",
        "fix", "preventive_gate", "scope", "classification", "active", "regression_test"
    }
    for item in incidents:
        assert required <= item.keys()
        assert item["classification"] in {"UNIVERSAL", "CONDITIONAL", "CASE_STUDY"}
```

- [ ] **Step 2: Run the test and verify failure**

Run: `pytest tests/unit/test_skill_content.py -v`

Expected: FAIL until catalog exists.

- [ ] **Step 3: Encode only confirmed incidents**

Initial promoted incident families:

```text
FP32 differential ULP floor
exact-tone vs nearest-bin SFCW extraction
artificial source delay left in phase/range
real-only / carrier-phase-losing inversion
missing opposite-polarity two-interface constraint
electrically disconnected transmission-line feed edge
configured isolation not applied to signal path
cross-case target/reference subtraction
-3 dB width used beyond its declared claim
truth-aware guard-region selection
```

Project-specific frequencies/distances/powers may be mentioned in case-study narrative evidence, but every `preventive_gate` and `scope` must be written generically. Mark obsolete historical interpretations `active: false` with `superseded_by` when later audits corrected them.

- [ ] **Step 4: Run content tests**

Run: `pytest tests/unit/test_skill_content.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add references/12-failure-catalog.md case-studies/historical-gprmax-lessons tests/unit/test_skill_content.py
git commit -m "docs: encode confirmed gprmax failure memory"
```

### Task 4: Add historical numerical/SFCW regression tests

**Files:**
- Create: `tests/regression/test_fp32_floor.py`
- Create: `tests/regression/test_source_delay.py`
- Create: `tests/regression/test_real_only_phase.py`
- Create: `tests/regression/test_interface_polarity.py`

**Interfaces:**
- Consumes production functions from Plans 2–3; each test corresponds to one `regression_test` ID in `incidents.yaml`.

- [ ] **Step 1: Write the four regressions with explicit expected failure prevention**

Use:

```text
REG-FP32-001 → `precision_floor_ratio` detects ~ULP residual scale.
REG-SFCW-002 → known artificial delay de-embeds to near-zero residual group delay.
REG-SFCW-003 → complex fit distinguishes delays that a real-only reduction cannot certify.
REG-SFCW-004 → two-interface helper enforces opposite-polarity model when declared.
```

Each regression must assert the production gate/function behavior, not just reproduce a plot.

- [ ] **Step 2: Run the new regressions**

Run:

```bash
pytest tests/regression/test_fp32_floor.py tests/regression/test_source_delay.py tests/regression/test_real_only_phase.py tests/regression/test_interface_polarity.py -v
```

Expected: PASS because Plans 2–3 already implement the fixes; if any fails, stop and repair the production gate before continuing.

- [ ] **Step 3: Link regression IDs back to incidents.yaml**

Set exact paths such as `tests/regression/test_fp32_floor.py::test_fp32_subtraction_floor_is_blocked` in the incident `regression_test` field.

- [ ] **Step 4: Re-run regressions and catalog-content test**

Run: `pytest tests/regression/test_fp32_floor.py tests/regression/test_source_delay.py tests/regression/test_real_only_phase.py tests/regression/test_interface_polarity.py tests/unit/test_skill_content.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/regression case-studies/historical-gprmax-lessons/incidents.yaml
git commit -m "test: lock numerical and sfcw failure regressions"
```

### Task 5: Add antenna/reference and fail-closed regressions

**Files:**
- Create: `tests/regression/test_feed_open_circuit.py`
- Create: `tests/regression/test_cross_reference.py`
- Create: `tests/regression/test_skill_fail_closed.py`

**Interfaces:**
- Consumes Plan 2/4 gates and Plan 1 gate runner.

- [ ] **Step 1: Write three regressions**

`test_feed_open_circuit.py` supplies a geometry topology fixture where the feed edge exists but lacks signal-conductor contact; expect `BLOCK_FEED_TOPOLOGY`.

`test_cross_reference.py` supplies target/reference models with different background material and only target declared as allowable difference; expect `BLOCK_PAIR_CONTRACT`.

`test_skill_fail_closed.py` registers a blocking source gate followed by a fake expensive run gate; assert the expensive gate is never called.

- [ ] **Step 2: Run regressions**

Run: `pytest tests/regression/test_feed_open_circuit.py tests/regression/test_cross_reference.py tests/regression/test_skill_fail_closed.py -v`

Expected: PASS.

- [ ] **Step 3: Link exact regression paths in incidents.yaml**

Update only the relevant incident entries; do not change core default values.

- [ ] **Step 4: Re-run affected regression/content suite**

Run: `pytest tests/regression/test_feed_open_circuit.py tests/regression/test_cross_reference.py tests/regression/test_skill_fail_closed.py tests/unit/test_skill_content.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/regression case-studies/historical-gprmax-lessons/incidents.yaml
git commit -m "test: lock antenna reference and fail closed regressions"
```

### Task 6: End-to-end valid and deliberately broken integration fixtures

**Files:**
- Create: `tests/integration/test_end_to_end.py`
- Create: `tests/gprmax/test_minimal_solver.py`
- Create: `tests/fixtures/gprmax/` minimal solver input fixtures
- Create fixture contracts/files under `tests/fixtures/integration/`

**Interfaces:**
- Exercises CLI stages from `init` through `freeze` using small synthetic/local artifacts; no expensive gprMax run is required for this acceptance layer.

- [ ] **Step 1: Write integration tests for one valid and five broken paths**

Valid path: numerical-scope, time-domain, relative-field contract with complete environment/material/geometry evidence and no unsupported hardware claim; reaches signoff/freeze.

Broken paths:

```text
float32 output where FP64 is required → BLOCK_OUTPUT_DTYPE
known source delay left undeembedded → BLOCK_SOURCE_DELAY_NOT_DEEMBEDDED
point Ez requested as absolute dBm without calibration → BLOCK_ABSOLUTE_POWER_UNCALIBRATED
truth-only reference requested as engineering input → blocking SFCW/reference policy code
-3 dB evidence requested as two-target separability without contract acceptance → BLOCK_RESOLUTION_DEFINITION
```

- [ ] **Step 2: Run integration tests and inspect any interface mismatch**

Run: `pytest tests/integration/test_end_to_end.py -v`

Expected: PASS once all stage interfaces are consistent. Any mismatch is repaired in the owning production module rather than bypassed in the integration test.

- [ ] **Step 3: Add stale-on-upstream-change integration check**

Freeze the valid fixture, modify its source/timebase artifact, run change detection, and assert dependent processing/metric/claim states become `STALE`.

- [ ] **Step 4: Run integration suite**

Run: `pytest tests/integration/test_end_to_end.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/integration tests/fixtures/integration
git commit -m "test: verify end to end gprmax skill gates"
```

### Task 7: Generic-core leakage, placeholder, and documentation consistency audit

**Files:**
- Modify: `tests/unit/test_skill_content.py`
- No production code changes unless the audit finds a real defect.

**Interfaces:**
- Produces automated content guards for future edits.

- [ ] **Step 1: Add leakage scan over core files but exempt case studies**

Scan `SKILL.md`, `references/`, `scripts/`, `schemas/`, and `templates/` for known tunnel-face case literals used in the historical project; the test must not scan `case-studies/` or regression fixture values because those are intentionally historical.

Also scan production files for unresolved implementation markers constructed in the test as `"T" + "ODO"`, `"T" + "BD"`, `"implement " + "later"`, and `"fill in " + "details"` so the plan document itself does not contain a live red-flag token.

- [ ] **Step 2: Run content audit**

Run: `pytest tests/unit/test_skill_content.py -v`

Expected: PASS after removing any accidental core leakage or placeholder marker.

- [ ] **Step 3: Verify every documented blocking code exists in production**

In `tests/unit/test_skill_content.py`, extract tokens matching `BLOCK_[A-Z0-9_]+` from every reference and from `scripts/*.py`. Assert that every documented token appears in production source. Also assert that every production `BLOCK_*` token is documented in at least one reference or in the generic orchestration Skill. This source-to-documentation comparison is deterministic and does not introduce a second block-code registry.

- [ ] **Step 4: Run the entire unit/content suite**

Run: `pytest tests/unit -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_skill_content.py scripts references SKILL.md schemas templates
git commit -m "test: guard generic skill content and block codes"
```


### Task 8: Minimal real-gprMax solver regression layer

**Files:**
- Create: `tests/gprmax/test_minimal_solver.py`
- Create: `tests/fixtures/gprmax/uniform_medium.in`
- Create: `tests/fixtures/gprmax/single_interface.in`
- Create: `tests/fixtures/gprmax/lossy_short_path.in`
- Create: `tests/fixtures/gprmax/pec_reflector.in`
- Modify: `pyproject.toml` pytest marker configuration

**Interfaces:**
- Exercises the actual configured gprMax runtime rather than the fake runner used by unit tests.
- Produces regression evidence for runtime banner, HDF5 receiver dtype, propagation timing trend, loss trend, and deterministic small-model execution.

- [ ] **Step 1: Add an explicit `gprmax` pytest marker and runtime resolver**

Configure:

```toml
[tool.pytest.ini_options]
markers = [
  "gprmax: requires an installed and runnable gprMax solver",
]
```

In the test module, resolve the runner from environment variable `GPRMAX_RUNNER_JSON`, containing a JSON argv list such as `["python", "-m", "gprMax"]`. If absent, call `pytest.skip("real gprMax runner not configured")`; the final release verification records this skip as an external-runtime limitation rather than silently treating it as a solver pass.

- [ ] **Step 2: Write four tiny solver tests**

The tests must run the fixture through the configured runner in a temporary output directory and assert:

```text
uniform_medium → process exit 0, expected Rx dataset exists, samples finite
single_interface → reflected feature occurs after direct feature
lossy_short_path → higher declared loss case has lower received energy than lower-loss companion under identical geometry/source
pec_reflector → a strong causal reflection appears in the physically permitted window
```

Do not use project-specific mine dimensions, materials, bands, powers, or acceptance thresholds. Use intentionally tiny generic fixtures whose purpose is solver/regression sanity, not engineering performance.

- [ ] **Step 3: Run real-solver tests**

Run:

```bash
pytest -m gprmax tests/gprmax -v
```

Expected when a runner is configured: PASS. If tests are skipped because no actual gprMax runtime is configured, record the release as `CONDITIONAL_EXTERNAL_GPRMAX_RUNTIME_UNVERIFIED`; do not claim the solver integration was verified.

- [ ] **Step 4: Run the normal suite to ensure the optional external layer does not weaken fail-closed core tests**

Run: `pytest -q`

Expected: PASS; any real-gprMax skip remains visible in pytest output and release notes.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/gprmax tests/fixtures/gprmax
git commit -m "test: add minimal real gprmax solver regressions"
```

### Task 9: Final verification and skill package freeze

**Files:**
- No new feature files.
- Output: release/freeze artifacts under a non-overwriting `dist/` or evidence directory if the execution workflow chooses to package the Skill.

**Interfaces:**
- Requires the Superpowers `verification-before-completion` sub-skill before any success claim.

- [ ] **Step 1: Run the complete test suite**

```bash
pytest -q
```

Expected: all tests PASS.

- [ ] **Step 2: Run CLI acceptance commands**

```bash
python -m scripts.cli preflight tests/fixtures/contracts/minimal_valid.yaml --project-root tests/fixtures/projects/minimal
python -m scripts.cli signoff tests/fixtures/contracts/minimal_valid.yaml --project-root tests/fixtures/projects/minimal
```

Expected: exit code `0` for the supported numerical-scope fixture.

- [ ] **Step 3: Run deliberately broken integration fixtures**

```bash
pytest tests/integration/test_end_to_end.py -v
```

Expected: the test suite passes because each invalid fixture is correctly blocked by its expected `BLOCK_*` code.

- [ ] **Step 4: Run leakage/placeholder scan through pytest**

```bash
pytest tests/unit/test_skill_content.py -v
```

Expected: PASS.

- [ ] **Step 5: Run configured real-gprMax regression layer**

```bash
pytest -m gprmax tests/gprmax -v
```

Expected with `GPRMAX_RUNNER_JSON` configured: PASS. If skipped because no real solver is configured, the implementation may be packaged but must be labeled `CONDITIONAL_EXTERNAL_GPRMAX_RUNTIME_UNVERIFIED` rather than fully verified.

- [ ] **Step 6: Commit the verified release state**

```bash
git status --short
git add -A
git commit -m "chore: verify gprmax simulation skill release"
```

Only after the verification sub-skill confirms fresh command output may the implementation be described as complete.

## Plan 6 completion gate

The Skill is complete only when a fresh full-suite run passes, deliberately broken fixtures are actually blocked, the generic-core leakage audit passes, historical incidents have regression links, and evidence/claim invalidation works end-to-end.
