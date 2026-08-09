# gprMax Simulation Skill — Design Specification

**Date:** 2026-08-09  
**Status:** Design frozen / implementation not started  
**Architecture:** General-purpose gprMax simulation master Skill with modular references, machine-enforced fail-closed gates, automatic fidelity promotion, regression tests, and evidence provenance.  
**Scope:** Generic gprMax workflows. Project-specific tunnel-face / coal-mine parameters are allowed only as case studies or optional profiles, never as core defaults.

---

## 1. Purpose

Create a reusable Agent Skill that manages the complete lifecycle of a gprMax simulation task:

1. define the scientific/engineering claim;
2. derive the minimum physics and numerical requirements;
3. select model fidelity automatically;
4. build and preflight models;
5. run low-cost validation before expensive simulation;
6. execute simulation only after all blocking gates pass;
7. perform physically valid post-processing;
8. separate detection, localization, resolution, inversion, and hardware/system claims;
9. preserve evidence and provenance;
10. learn from confirmed failures through regression tests.

The Skill is intentionally **fail-closed**. A blocking numerical, physical, processing, calibration, or evidence defect stops promotion. It must never continue on the basis that a result “looks plausible.”

---

## 2. Non-goals

The generic core must not hard-code project-specific values such as a particular:

- frequency band;
- target distance;
- relative permittivity;
- conductivity;
- transmitter power;
- isolation value;
- receiver noise figure;
- window function;
- resolution threshold.

Such values may exist only in explicit project profiles or historical case studies.

The Skill must not claim that simulation alone proves real-world field performance when calibration, hardware characterization, or site material measurements are missing.

---

## 3. Core design principles

### 3.1 Claim-first simulation

The model must be derived from the claim, not the reverse. Every task begins with a machine-readable simulation contract declaring the exact claim, minimum observable, material assumptions, waveform regime, required metrics, uncertainty model, and evidence requirements.

### 3.2 Fail-closed promotion

Blocking failure means:

- stop expensive execution;
- identify the smallest failing layer;
- reduce to a minimal reproducer;
- establish the root cause;
- add or update a regression test;
- repair;
- rerun all invalidated gates;
- resume only after a pass.

### 3.3 Distinguish numerical, physical, and engineering validity

A successful `.out` file is not physical validation. Physical validation is not hardware validation. Hardware/system claims require a calibrated signal chain.

### 3.4 Preserve raw evidence

Raw simulation outputs are immutable. Every calibration, subtraction, filtering, deconvolution, imaging, display transform, and inference creates a new derived artifact with explicit provenance.

### 3.5 Historical failures become tests, not folklore

Only confirmed incidents with a known root cause, validated fix, and defined scope may be promoted into mandatory rules.

---

## 4. Global execution state machine

```text
TASK DEFINITION
      ↓
PHYSICS CONTRACT
      ↓
ANALYTIC SANITY CHECK
      ↓
MODEL FIDELITY SELECTION
      ↓
STATIC PREFLIGHT
      ↓
NUMERICAL PRECISION GATE
      ↓
GEOMETRY-ONLY / SMOKE TEST
      ↓
LOW-COST PHYSICS VALIDATION
      ↓
FULL SIMULATION
      ↓
POSTPROCESSING VALIDATION
      ↓
PHYSICAL CONSISTENCY AUDIT
      ↓
ENGINEERING / SCIENTIFIC ACCEPTANCE
      ↓
EVIDENCE & PROVENANCE FREEZE
      ↓
CLAIM SIGN-OFF
```

Blocking failure:

```text
FAIL → STOP → ROOT CAUSE → REPAIR → REGRESSION TEST → RERUN AFFECTED GATES
```

Forbidden path:

```text
FAIL → “probably fine” → continue expensive simulation
```

Global claim states:

- `UNVERIFIED`
- `CONDITIONAL`
- `VERIFIED`
- `REJECTED`
- `STALE` for previously valid claims invalidated by an upstream change.

---

## 5. Simulation Contract

Every task creates a `simulation_contract.yaml` or equivalent validated structure.

Representative fields:

```yaml
task:
  objective: detection | localization | resolution | thickness | attenuation | antenna | system | imaging | inversion
  claim_scope: numerical | physical | engineering
  dimensionality_target: auto

medium:
  model_type: nondispersive | debye | lorentz | drude | measured_complex
  parameter_source: measured | literature | assumed | sensitivity
  uncertainty: {}

target:
  geometry: {}
  material: {}
  distance: null
  required_observable: null

waveform:
  excitation_mode: pulse_broadband | explicit_single_tone | explicit_multi_run_cw | custom
  measurement_mode: time_domain | sfcw_equivalent | frequency_response | antenna_characterization
  physical_band: null
  analysis_band: null
  source_delay: null

numerics:
  precision_requirement: auto
  grid: auto
  time_window: auto
  pml: auto
  smoothing: auto
  backend: auto

acceptance:
  metric: null
  threshold: null
  negative_controls: []
  sensitivity_tests: []

evidence:
  required_outputs: []
  provenance_level: strict
```

The contract is the single source of truth for all downstream gates.

---

## 6. Automatic fidelity promotion: F0–F5

### F0 — Analytical sanity

No gprMax run. Derive:

- wavelength and grid scale;
- CFL implications;
- round-trip time and required time window;
- SFCW tone spacing / unambiguous range where applicable;
- bandwidth-derived resolution scale as a sanity bound, not a final proof;
- attenuation order of magnitude;
- domain/PML clearance;
- compute and memory estimate.

If analytically infeasible: `BLOCK_ANALYTIC_INFEASIBLE`.

### F1 — Minimal numerical physics

Use the smallest model capable of testing solver/material/source/post-processing correctness:

- uniform medium;
- single interface;
- PEC reflector;
- short lossy propagation;
- small target/reference diagnostic pair.

Typical gates: propagation speed, loss trend, source timing, Rx component, dtype, exact-tone extraction.

### F2 — Reduced-dimensional propagation

2D/2.5D or symmetry-reduced models for parameter scanning, frequency screening, conductivity sensitivity, time-window/PML sensitivity, and method triage.

F2 may not certify final 3D scattering, antenna coupling, finite-target 3D resolution, or engineering Pd/Pfa.

### F3 — Simplified 3D physics

Use true 3D geometry with simplified field source / equivalent phase-center antenna if appropriate. Valid for finite-target diffraction, multipath, polarization, and spatial response. A Hertzian/point source remains an idealized source and cannot independently support S11 or absolute hardware power claims.

### F4 — High-fidelity 3D

Include task-required finite targets, realistic geometry, dispersive materials, convergence checks, negative controls, multiple positions/distances/thicknesses, and uncertainty perturbations. May support physical claim sign-off.

### F5 — Hardware/system closure

Add calibrated antenna/port behavior and receiver chain, including where relevant:

- accepted Tx power;
- effective receive mapping;
- coupling/isolation;
- NF and bandwidth;
- gain/phase jitter;
- ADC and dynamic range;
- coherent/incoherent averaging;
- Pd/Pfa.

Only F5 may support absolute received dBm or system-level detection claims.

Promotion is gate-controlled. Skipping a fidelity level requires an explicit, logged justification.

---

## 7. Numerical Validity Gate

### N1 — Environment and version lock

Record actual runtime version/banner, package/import path, Python environment, CPU/GPU backend, CUDA/driver where used, real/complex precision, input/script hashes, and output schema.

Failure to resolve the actual runtime: `BLOCK_ENVIRONMENT_UNRESOLVED`.

### N2 — Grid adequacy

Grid requirement is derived from:

- shortest relevant wavelength;
- maximum relevant permittivity;
- target smallest scale;
- antenna/feed smallest scale;
- dispersion tolerance;
- required phase or position accuracy.

No universal hard-coded `λ/10` rule. Formal claims may require grid convergence.

### N3 — CFL and timebase

Use the actual solver `dt`; post-processing may not independently assume a different time step. Mismatch: `BLOCK_TIMEBASE_MISMATCH`.

### N4 — Time-window and causality

Time window must cover source delay/tail, longest propagation path, target back interface, dispersive broadening, multipath, and guard time without contaminated boundary returns.

### N5 — PML / boundary validity

PML and domain size are treated as numerical model parameters, not assumptions. Formal claims may require PML/domain sensitivity.

### N6 — Material numerical realization

Check frequency-domain implications of nondispersive and dispersive models, including stability, passivity, valid frequency range, phase velocity, and attenuation.

### N7 — Precision / FP64 gate

Use a precision budget. FP64 becomes mandatory for weak-differential, high-dynamic-range, long-distance, coherent phase, or small-residual tasks unless FP32 adequacy is explicitly demonstrated.

The check must include runtime implementation and final HDF5 dtype, not only Python type declarations.

A dedicated `precision_floor_test` compares differential signal scale against local floating-point ULP behavior. Residuals near the precision floor are blocking.

### N8 — Numerical convergence and backend consistency

Require risk-appropriate checks such as grid, time window, PML, CPU/GPU, or precision convergence.

---

## 8. Source / Waveform / SFCW Gate

### 8.1 Excitation vs measurement-mode separation

The Skill must distinguish an actual gprMax excitation from a synthesized measurement regime. A broadband pulse followed by exact complex extraction at discrete tones is `pulse_broadband + sfcw_equivalent`, not a direct physical per-tone SFCW simulation.

### 8.2 Source audit

Audit waveform, source spectrum, phase, DC, usable support, peak time, and tail. Analysis tones near a source spectral null are blocked.

### 8.3 Source delay / time-reference audit

Track simulation t=0, waveform origin, source main peak, electrical phase reference, and processed range-zero reference separately. Any artificial source delay must be removed exactly once. Residual group delay consistent with source delay is blocking.

### 8.4 SFCW tone contract

Explicitly define tone grid, spacing, count, and uniformity. Derive unambiguous-range and bandwidth sanity limits from the task and medium rather than copying project numbers.

### 8.5 Exact-tone complex extraction

For broadband-to-SFCW equivalent processing, formal extraction evaluates the DTFT/DFT at the exact physical tone frequencies. Nearest-bin FFT or unvalidated FFT interpolation is diagnostic-only.

### 8.6 Preserve complex phase

Coherent ranging and thickness/phase inversion require complex response. Real-only or magnitude-only fitting may not support high-precision delay or thickness sign-off.

### 8.7 Source deconvolution

Use a documented regularized deconvolution, not blind division by source spectrum. Regularization must be predeclared and provenance-tracked.

### 8.8 No hidden per-tone normalization

Per-tone, per-trace, or per-distance normalization that destroys amplitude physics is forbidden in the quantitative chain. Display-only normalization must remain isolated.

### 8.9 Window contract

Window choice is predeclared and claim-specific. Generic core does not force Hann or any other single window.

### 8.10 Zero padding

Zero padding can change numerical range-bin sampling / display smoothness, but cannot create physical bandwidth or true resolution. Claims to the contrary are blocked.

### 8.11 Range mapping

Use the correct material velocity model. Significant dispersion requires group-delay / frequency-dependent or calibrated range mapping rather than an unjustified single constant permittivity.

### 8.12 Multi-interface physical constraints

Thickness/inversion models must honor expected interface polarity, physical separation bounds, material velocity, complex phase, and negative controls.

### 8.13 Target/reference policy

Reference data is classified as solver truth, calibration reference, or engineering background reference. Perfect target-minus-reference subtraction is not automatically an engineering input.

### 8.14 SFCW spatial acquisition semantics

A stationary SFCW sweep completes all tones at one antenna position before moving to the next, unless the contract explicitly models motion during sweep.

---

## 9. Antenna / Port / System Closure Gate

### 9.1 Representation levels

- `A0`: idealized field source;
- `A1`: electromagnetic antenna model;
- `A2`: calibrated hardware/system model.

Claims may not cross these boundaries without explicit calibration.

### 9.2 Electrical topology audit

Entity/port models must validate electrical feed connectivity on the actual Yee topology, not just visual geometry. Check feed edge, conductors, return path, loading elements, unintended material overrides, and grid alignment.

### 9.3 Geometry-only antenna preflight

Inspect the discretized model at feed, conductor, substrate, load, source, and receiver regions before full simulation.

### 9.4 Port sanity

Where meaningful, validate port V/I and impedance definitions before using S11-like quantities. A ratio may only be called S11 when the reference-wave definition is valid.

### 9.5 Power identity

Distinguish generator output, available power, incident power, accepted power, radiated power, and EIRP. Arbitrary source amplitude cannot be relabeled dBm without calibration.

### 9.6 Field-to-voltage/power bridge

Point E/H fields are relative field observables unless an analytical or numerical receive calibration maps them to voltage and power. Absolute dBm, receiver SNR, and hardware Pd require this closure.

### 9.7 Polarization and reciprocity

Audit Tx/Rx orientation, field component, target/interface orientation, and reciprocity assumptions.

### 9.8 Direct coupling and isolation

Physical coupling, numerical coupling, hardware isolation, and background cancellation are separate mechanisms. A configured isolation value must be proven to enter the actual data path.

Dead parameters are blocking: `BLOCK_DEAD_SYSTEM_PARAMETER`.

### 9.9 Receiver-chain ordering

Receiver chain explicitly defines ordering of common response, isolation/cancellation, gain/loss, jitter, thermal/receiver noise, filtering, ADC, and averaging.

### 9.10 Noise and averaging

Noise parameters are frozen before observing detection results. Coherent averaging benefits only eligible random components; static or correlated errors may not be divided by `sqrt(N)` by default.

### 9.11 ADC / dynamic range

System claims require saturation, full scale, ENOB/quantization, largest common response, target signal, and noise-floor checks.

### 9.12 Usable band is an intersection

The final usable band is the intersection of source support, antenna behavior, propagation, target response, receiver behavior, calibration validity, and processing stability.

---

## 10. Materials / Geometry / Target Gate

### 10.1 Material provenance

Every material records model type, parameters, provenance, source, valid frequency range, environmental conditions where known, and uncertainty.

Provenance classes include measured, literature, manufacturer, assumed baseline, and sensitivity-only.

### 10.2 Frequency relevance of material parameters

Permittivity and conductivity are interpreted over the actual band. A literature constant is not assumed universally valid.

### 10.3 Dispersion gate

Validate Debye/Lorentz/Drude parameters for sign, units, passivity/stability, and band validity; inspect frequency-dependent permittivity, loss, phase velocity, and attenuation.

### 10.4 Sensitivity

Non-measured parameters require risk-appropriate sensitivity analysis. Prefer staged screening over blind full Cartesian sweeps.

### 10.5 Coordinate contract

A single coordinate system and geometry reference convention is mandatory across model generation, result analysis, and reporting.

### 10.6 Nominal vs discretized geometry

Preserve both intended geometry and actual Yee-grid representation. Validation uses the appropriate truth level.

### 10.7 Geometry quantization

Audit cells across critical features and relative representation error.

### 10.8 Interface occupancy and smoothing

Detect overlap, gaps, definition-order overrides, grid alignment, and smoothing impact. Smoothing is a declared modeling choice, not a universal default.

### 10.9 Finite-target physics

Finite objects are not interchangeable with infinite interfaces. Check dimensions, orientation, edge diffraction, aspect ratio, and boundary clearance.

### 10.10 2D-to-3D claim barrier

Reduced-dimensional success cannot directly certify 3D finite-target, antenna, B-scan, or hardware performance.

### 10.11 Target physics contract

Each target defines its physical class, contrast mechanism, geometry, orientation, expected scattering mechanism, and interfaces.

### 10.12 Interface polarity

Where applicable, inversion and interpretation enforce physically expected reflection polarity relationships.

### 10.13 Negative controls and multi-case robustness

Formal detection, localization, resolution, or inversion claims require suitable negative controls and more than one hand-picked favorable case.

### 10.14 Target/reference pair contract

Target/reference and other paired comparisons explicitly declare invariant fields and permitted differences. Unauthorized differences block subtraction and comparison.

### 10.15 Model-purpose registry

Every model declares its purpose, allowed claims, and forbidden claims before execution.

---

## 11. Post-processing / Detection / Resolution / Inversion Gate

### 11.1 Data-layer separation

Maintain `RAW`, `CALIBRATED/PHYSICAL`, and `DISPLAY_ONLY` layers. Display transforms cannot feed quantitative metrics.

### 11.2 Predeclared processing contract

Freeze source reference, deconvolution, band, window, filter, background method, gain, envelope, range mapping, and detector before comparative evaluation.

### 11.3 Detection hierarchy

- `D0 CAUSAL_RESPONSE`: truth-assisted numerical causality;
- `D1 NUMERICAL_DETECTION`: realistic target-only or field-available chain;
- `D2 ENGINEERING_DETECTION`: calibrated receiver/system chain with statistics.

### 11.4 Detection vs localization

Amplitude detection and localization use separately defined windows/estimators. A global maximum may not silently serve both roles.

### 11.5 Resolution definition

Resolution must declare its metric family: PSF characteristic, Rayleigh/two-target criterion, two-interface separability, model-based thickness recoverability, or another explicit contract.

### 11.6 -3 dB limitation

-3 dB width can characterize a response but cannot automatically prove two-target or two-interface separability unless the project contract defines it as the accepted criterion.

### 11.7 PSF stability

PSF valley-based metrics require prominence/persistence/noise robustness rather than accepting the first numerical local minimum.

### 11.8 Two-target vs two-interface

Independent targets and the two interfaces of a finite layer obey different physics and are not interchangeable validation models.

### 11.9 Thickness validation tiers

- T0 qualitative interface information;
- T1 deterministic single-case estimate;
- T2 robust multi-case/uncertainty-supported estimation.

Only T2 supports a general thickness-recovery claim.

### 11.10 Physics-constrained inversion

Forward model, parameter bounds, polarity, material velocity, phase, loss, nuisance parameters, and optimizer are explicit. Magnitude-only or real-only fits cannot support precision complex-delay claims.

### 11.11 SNR definition

Define signal statistic, noise estimate, processing stage, units, and guard policy. Target-aware post-hoc noise-window selection is blocking.

### 11.12 Pd/Pfa

Statistical claims require fixed detector/threshold policy, positive and negative populations, seed provenance, sample size, and confidence interval. Generic core does not hard-code acceptance thresholds.

### 11.13 Monte Carlo semantics

Every random variable identifies distribution, correlation, physical location in the signal chain, and whether it is per-tone, per-trace, per-run, before/after averaging, or before/after cancellation.

### 11.14 Band-selection bias

Use exploration then independent confirmation. The same data should not both optimize and certify a frequency band without an explicit bias limitation.

### 11.15 Observability vs recoverability

The existence of target-correlated information does not automatically prove robust recovery of target parameters.

---

## 12. Evidence / Provenance / Failure Memory Gate

### 12.1 Run manifest

Every formal run receives a unique run ID and records environment, inputs, numerics, outputs, and cryptographic hashes.

### 12.2 Immutable raw evidence

Raw outputs are immutable. Derived products are separately versioned.

### 12.3 Machine-verifiable pair contracts

Target/reference, coarse/fine, CPU/GPU, precision, and baseline/perturbed pairs define invariants and allowed differences and are automatically diffed.

### 12.4 Claim ledger

Every scientific/engineering claim records status, required gates, supporting runs/artifacts, limitations, and forbidden upgrades.

### 12.5 Failure memory schema

Confirmed failures use:

```yaml
failure_id:
category:
symptom:
root_cause:
why_it_looked_plausible:
diagnostic:
minimal_reproducer:
fix:
preventive_gate:
scope:
superseded_by:
evidence:
```

### 12.6 Rule classification

Historical experience is classified:

- `UNIVERSAL`;
- `CONDITIONAL`;
- `CASE_STUDY`.

Only universal/conditional rules may affect core logic. Project-specific values remain isolated.

### 12.7 Supersession

Rules are versioned. Superseded rules remain for provenance but may not guide new simulations.

### 12.8 Incident promotion criteria

An observation becomes a mandatory rule only after root-cause confirmation, minimal reproduction, verified fix, defined scope, and regression coverage.

### 12.9 Provenance freeze

Before sign-off, produce evidence manifest, hashes, claim ledger, and gate summary. Changes to upstream inputs automatically invalidate affected claims to `STALE`.

---

## 13. Software architecture

```text
gprmax-simulation/
├── SKILL.md
├── references/
│   ├── 01-physics-contract.md
│   ├── 02-fidelity-promotion.md
│   ├── 03-numerical-validity.md
│   ├── 04-source-waveform.md
│   ├── 05-sfcw.md
│   ├── 06-antenna-port-system.md
│   ├── 07-materials.md
│   ├── 08-geometry-targets.md
│   ├── 09-postprocessing.md
│   ├── 10-detection-resolution-inversion.md
│   ├── 11-evidence-provenance.md
│   └── 12-failure-catalog.md
├── schemas/
│   ├── simulation_contract.schema.json
│   ├── run_manifest.schema.json
│   ├── gate_status.schema.json
│   ├── claim_ledger.schema.json
│   └── failure_event.schema.json
├── scripts/
│   ├── preflight.py
│   ├── audit_environment.py
│   ├── audit_geometry.py
│   ├── audit_precision.py
│   ├── audit_source.py
│   ├── audit_sfcw.py
│   ├── audit_pair_contract.py
│   ├── audit_antenna_port.py
│   ├── audit_receiver_chain.py
│   ├── audit_processing.py
│   ├── audit_claims.py
│   └── freeze_evidence.py
├── tests/
│   ├── unit/
│   ├── synthetic/
│   ├── regression/
│   └── fixtures/
├── case-studies/
│   └── historical-gprmax-lessons/
└── templates/
    ├── simulation_contract.yaml
    ├── model_purpose.yaml
    ├── gate_status.yaml
    └── claim_ledger.yaml
```

`SKILL.md` remains an orchestration layer. Detailed technical rules live in modular references and are loaded only when relevant.

---

## 14. Automatic executor

Stage-oriented commands:

```text
gprmax-skill init
gprmax-skill preflight
gprmax-skill validate-source
gprmax-skill validate-model
gprmax-skill smoke
gprmax-skill promote
gprmax-skill run
gprmax-skill analyze
gprmax-skill signoff
gprmax-skill freeze
```

The executor may orchestrate stages automatically, but no blocking failure may be bypassed by the orchestration layer.

Standard gate states:

- `PASS`
- `PASS_WITH_LIMITATION`
- `BLOCK`
- `STALE`
- `NOT_APPLICABLE`

Examples of blocking codes:

- `BLOCK_ENVIRONMENT_UNRESOLVED`
- `BLOCK_GEOMETRY_UNDERSAMPLED`
- `BLOCK_TIMEBASE_MISMATCH`
- `BLOCK_SOURCE_SPECTRAL_SUPPORT`
- `BLOCK_PRECISION_FLOOR`
- `BLOCK_FEED_TOPOLOGY`
- `BLOCK_ABSOLUTE_POWER_UNCALIBRATED`
- `BLOCK_PAIR_CONTRACT`
- `BLOCK_DISPLAY_DATA_METRIC`
- `BLOCK_RESOLUTION_DEFINITION`
- `BLOCK_CLAIM_SCOPE`

---

## 15. Dependency invalidation

Gates form a dependency graph. Changes upstream invalidate downstream claims.

Representative dependency:

```text
Environment
   ↓
Numerics
   ↓
Source
   ↓
Geometry / Materials
   ↓
Antenna / System
   ↓
Simulation
   ↓
Processing
   ↓
Metrics
   ↓
Claims
```

If source delay is corrected after analysis, all downstream SFCW/range/thickness/detection results become `STALE` until revalidated.

---

## 16. Testing strategy

### 16.1 Unit tests

Fast tests for schemas, units, CFL calculations, wavelength/grid estimates, SFCW range formulas, range mapping, provenance hashes, dependency invalidation, and claim-scope logic.

### 16.2 Synthetic signal tests

Mathematically known signals verify:

- exact delay recovery;
- source-delay removal;
- exact-tone phase behavior when tones do not lie on FFT bins;
- two-interface complex response and polarity;
- zero-padding non-resolution;
- deconvolution behavior near source notches.

### 16.3 Minimal gprMax regression tests

Small real gprMax models validate solver version, dtype, propagation velocity, conductivity attenuation trend, source timing, feed connectivity, and selected CPU/GPU consistency behavior.

### 16.4 Historical failure regression tests

Initial abstracted regressions should include:

- FP32 differential-floor artifact;
- exact-tone vs nearest-bin frequency extraction;
- residual source delay;
- real-only fitting / missing carrier phase;
- missing interface-polarity constraint;
- electrically disconnected feed edge;
- configured-but-unused isolation parameter;
- cross-case target/reference subtraction;
- misuse of -3 dB width as a separability proof;
- target-aware guard-region selection.

The regressions encode general failure patterns, not project-specific frequency bands or coal-mine constants.

---

## 17. Case-study isolation and optional profiles

Historical tunnel-face / coal-mine work is stored only in `case-studies/` and is loaded for debugging or explanation, not as a default behavioral source.

Optional `profiles/` may prefill domain-specific values such as coal mine, concrete, soil, or antenna bench scenarios. A profile may suggest values but may never bypass a core gate.

Rule:

```text
profile can suggest
core can veto
```

---

## 18. Skill self-update process

A new failure is integrated only through:

```text
incident
↓
root cause verified
↓
scope classified
↓
minimal reproducer
↓
regression test
↓
rule classification
↓
reference update
↓
version bump
```

The main `SKILL.md` is not edited ad hoc for every incident.

---

## 19. Definition of Done

Implementation is complete only when:

1. `SKILL.md` can independently route a new gprMax task through the lifecycle;
2. all schemas validate;
3. every core gate has explicit stop conditions;
4. major confirmed historical failure modes are mapped to generic patterns;
5. high-value failure modes have regression tests;
6. generic core contains no tunnel-face project-specific numerical defaults;
7. SFCW, FP64, antenna/port, material, metric, and evidence modules load conditionally;
8. claim ledger and provenance freeze work end-to-end;
9. intentionally broken fixtures are truly blocked rather than merely warned;
10. all tests needed for the supported scope pass.

---

## 20. Design review checklist

Before implementation, review the design for:

- project-specific leakage into generic defaults;
- rules based on unconfirmed historical observations;
- warning-only behavior where fail-closed is required;
- duplicated gates across modules;
- overly broad mandatory tests that would make simple tasks impractical;
- claim/fidelity mismatches;
- inability to invalidate stale downstream evidence;
- missing distinction among raw, calibrated, and display data;
- missing distinction among field, antenna, calibrated receiver, and system claims;
- missing synthetic regressions for SFCW/precision failures.

