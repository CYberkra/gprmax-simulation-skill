---
name: gprmax-simulation
description: >-
  Use when building a new gprMax model, auditing existing simulation outputs,
  making SFCW-equivalent claims, or comparing controlled cases; route generic
  GPR presentation to a presentation skill.
---

# gprMax Simulation

Use this skill to keep a gprMax study traceable from physical assumptions to
audited outputs and bounded conclusions: anchor every plot in the controlled
model and the recorded processing chain that produced it.

## Route

Sections are reference modules; follow the path for your branch rather than the
file order.

| Branch | Path |
|--------|------|
| New model | §Start with the local contract → §Follow the study directory convention → §Drive the model from a guided setup → §Validate before expensive execution → §Run controlled batches (if sweep) → §Process results for inspection → §Respect fidelity and gate states → §Close the evidence package |
| Audit existing outputs | §Audit outputs before interpreting them → §Follow the study directory convention → §Keep comparisons controlled → §Respect fidelity and gate states → §Close the evidence package |
| SFCW claim | §Start with the local contract → §Follow the study directory convention → §Audit outputs before interpreting them → §Reconstruct SFCW faithfully → §Process results for inspection → §Match the metric to the claim → §Respect fidelity and gate states → §Close the evidence package |
| Compare results | §Audit outputs before interpreting them → §Keep comparisons controlled → §Match the metric to the claim → §Respect fidelity and gate states → §Close the evidence package |

## Start with the local contract

Read the repository's `AGENTS.md`, study README, and supplied case materials
before changing a model. They can define project-specific requirements; keep
those values scoped to this project rather than carrying them elsewhere.

Work **claim-first**: identify the reference case, the scientific question, the
permitted claim, and the study design: a single-variable study with one factor,
or a multi-factor design with a factor list. Record the full contract per
[simulation-contract.md](references/simulation-contract.md) — the factors, their
levels, and every invariant held constant, plus the design type
(`single_variable` | `multi_factor`) and every domain, mesh, material,
geometry, source/receiver, boundary, time-window, precision, and processing
field the schema requires. The contract is complete when it validates against
`schemas/simulation_contract.schema.json`, names a reference case and design
type, and records every factor level and invariant.

For new or changed geometry and solver settings, read
[simulation-contract.md](references/simulation-contract.md) and
[numerical-model-validity.md](references/numerical-model-validity.md).

## Drive the model from a guided setup

When the user wants to build a new model type, run the guided setup before
writing any input: interview the user to establish the scenario, target and
surrounding medium, frequency band and whether an SFCW-equivalent conclusion is
needed, fidelity intent, and the run environment. Resolve unknown material
parameters by researching literature and authoritative sources; present options
with recommended, compromise, and not-recommended choices plus provenance, and
record material entries in the local material library only after user
confirmation. For each configuration axis (antenna, SFCW, dispersion, noise and
clutter targets, target geometry, model dimension, precision) recommend a value
with a fold-open rationale, then generate a geometry sketch and the
`simulation_contract.yaml` skeleton for confirmation.

Probe the local environment (GPU, memory, disk, Python version, gprMax
presence) to inform the choice, and let the user decide local or server.

For the interview order, answer validation, and configuration-axis
recommendations (including the L1–L4 irregular-geometry tiers and fidelity
intents), read
[guided-setup.md](references/guided-setup.md). For the material-library schema,
research-need identification, and scene-template progressive accumulation, read
[study-materials.md](references/study-materials.md).

Generate a geometry cross-section sketch at wizard dump time
(`gprmax-skill wizard dump --sketch <out.png>`) so the user sees the domain,
host medium, target at depth, and Tx/Rx before any mesh exists. When the model
is established, produce a model-card report
(`gprmax-skill report model-card <contract>`) that consolidates the contract,
numerical gates, sensitivity, processing chain, and environment into a single
deliverable. The guided setup is complete when the user has confirmed the
interview answers, the geometry sketch is generated, and the model-card report
is delivered.

## Run controlled batches

For a parameter scan, read
[preflight-and-audit.md](references/preflight-and-audit.md) for the
expand-validate-run-resume procedure, per-case logs, failure classification,
and the status table.

**Batch only after the model is established.** A new project must first
complete the guided setup (contract with a declared dimension, resolved
medium/target materials, and a frequency band) and run at least one single-case
verification that produces auditable ``.out`` evidence. Run
`gprmax-skill dataset check-model` to inspect readiness;
`gprmax-skill dataset sample --force` skips the gate explicitly. The batch is
complete when the run queue is exhausted, every case has a recorded status, and
the status table is delivered.

## Process results for inspection

Raw gprMax outputs usually need processing before they are readable as A-scan /
B-scan. Recommend a processing chain matched to the question; read
[preflight-and-audit.md](references/preflight-and-audit.md) for the chain
categories, display-only discipline, and the user-priority rule. Processing is
complete when the chain is chosen, its parameters recorded, and the labeled
artifact delivered per §Close the evidence package.

## Keep comparisons controlled

For a controlled comparison, state the factor(s) and every retained
control. A target-present/background pair must match in domain, mesh, retained
materials, source/receiver configuration, waveform, time window, boundary
treatment, and precision. Compare only outputs with identically defined
receiver observables. Complex subtraction (for example background subtraction)
requires matching sampling grids; any comparison that resamples must declare
and validate the resampling before use.

Reuse an intact, audited compatible run instead of spending compute to rerun it.
If an output is missing, corrupt, stale, or cannot be reconciled with its input,
record the limitation and obtain authority before requesting replacement compute.
The comparison is complete when the factor(s) and every retained control are
stated, and every compared pair matches on the invariants above. Read
[simulation-contract.md](references/simulation-contract.md) for the
controlled-pair contract format and pair-compatibility rules.

## Validate before expensive execution

Align critical dimensions, sources, receivers, and interfaces to the mesh and
report the discretised dimensions as cell counts times cell spacings. Declare and
record every change to physical properties, geometry, source/receiver placement,
waveform, boundary treatment, or precision. Run focused geometry/configuration
checks when provided; keep costly gprMax execution outside unit tests.

Before GPU execution, prepare a manifest and case list. Record the command,
solver version/build, requested precision, GPU mapping, case order, and log
paths. Confirm that the selected build and allocated hardware support the
requested calculation. Stop on a repeated simulation error and report it; change
precision or model only with recorded authority. Validation is complete when
the discretised dimensions are reported, the manifest is prepared, and any
geometry/configuration tests pass or are waived with recorded authority.

## Respect fidelity and gate states

Interpret every check through the shared gate vocabulary in
[gates-and-claims.md](references/gates-and-claims.md). Promotion is
**fail-closed**: a blocked or stale gate stops promotion; an upstream change
invalidates downstream evidence to `STALE` until revalidated.

A claim licenses only the fidelity it earns — read
[gates-and-claims.md](references/gates-and-claims.md) for the `F0`–`F5` ladder
and the minimum fidelity each claim class requires before interpreting any gate
report or signing a claim. The gate check is complete when every gate state is
interpreted against the `F0`–`F5` ladder and any blocked or stale result is
recorded with its effect on the claim.

## Audit outputs before interpreting them

Read [preflight-and-audit.md](references/preflight-and-audit.md) for the HDF5
output audit procedure (dataset existence, dtype, shape, timestep, sample count,
and manifest reconciliation). Missing, duplicate, truncated, stale, or unmapped
outputs are audit failures, not analysable results. The audit is complete when
every expected output is reconciled against its manifest entry, and any
missing/corrupt/unmapped output is recorded as an audit failure.

## Reconstruct SFCW faithfully

gprMax normally solves a time-domain FDTD excitation. A broadband pulse followed
by complex extraction at selected tones is a **broadband-to-SFCW-equivalent**
result, not a direct stepped-frequency acquisition. State that distinction.
Preserve complex phase throughout transfer-function estimation, conditioning,
pair subtraction, and inverse reconstruction.

For SFCW work, read [source-and-sfcw.md](references/source-and-sfcw.md). It
covers source support, exact-tone extraction, source deconvolution, background
handling, frequency grids, inverse transforms, and envelope construction.
Before promoting an SFCW processing result, run the packaged
`gprmax-skill validate-source <config.json> --project-root <study>` gate with
the actual source array. A blocking source or SFCW policy result returns exit
code 2 and stops downstream processing evidence; preserve both the gate report
and its processing-detail sidecar in the study package. Reconstruction is
complete when the SFCW processing chain is declared, the source gate is run,
and its result (pass or blocking with sidecar) is preserved in the study
package.

## Match the metric to the claim

Work **claim-first** here too: the metric must answer the claim it was
declared for. Keep raw, physically calibrated, and display-only products
separate. Freeze the processing chain and metric definition before comparative
evaluation. A peak,
envelope valley, -3 dB width, detection statistic, localization estimate,
two-interface separation, and thickness estimate answer different questions;
none automatically proves another.

For finite 3-D objects, apply infinite-plane or one-dimensional
interface-polarity expectations only where the model has been validated for that
scattering regime. Use waveform polarity only where the physical representation
supports it; use declared energy/envelope metrics for amplitude separability.

Read [interpretation-and-claims.md](references/interpretation-and-claims.md)
before making detection, resolution, thickness, inversion, or system-performance
claims. Metric selection is complete when the metric is declared, the chain is
frozen, and the metric's scope (detection, localization, resolution, thickness)
is stated and matched to the claim.

## Follow the study directory convention

Maintain the standard directory layout and naming conventions defined in
[study-layout.md](references/study-layout.md). Record every intentional change
in the study README. Create a new dated directory for a materially changed
model; keep frozen packages frozen.

Run `gprmax-skill layout audit <study-dir>` before scaffolding or auditing a
study. The directory check is complete when the study layout matches the
standard, the layout audit passes, and any intentional change is recorded in the
README.

## Close the evidence package

Preserve the deliverable set defined in
[preflight-and-audit.md](references/preflight-and-audit.md#deliverable-contents).
Every reported time or distance figure must state its coordinate datum,
propagation/range-mapping convention, exact processing chain, and scope of
validity. Present a background-subtracted residual as a residual, with the
subtraction operator and raw data identified; keep raw field measurements
and calibrated hardware results separate. The evidence package is complete when
the deliverable set defined in the reference above is present and every reported
figure carries the required labeling.
