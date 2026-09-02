---
name: gprmax-simulation
description: Plan, build, run, reconstruct, and audit reproducible gprMax FDTD simulations, including SFCW or broadband-to-SFCW-equivalent GPR studies. Use for building or running gprMax cases and sweeps, auditing existing outputs, SFCW reconstruction, controlled comparisons, or defensible detection/resolution/thickness claims on gprMax cases or outputs; route generic GPR presentation to a presentation skill.
metadata:
  short-description: Reproducible gprMax and SFCW simulation workflow
---

# gprMax Simulation

Use this skill to keep a gprMax study traceable from physical assumptions to
audited outputs and bounded conclusions. Preserve solver physics and evidence;
anchor every plot in the controlled model and the recorded processing chain that
produced it.

## Route

| Branch | Path |
|--------|------|
| New model | §Start with the local contract → §Follow the study directory convention → §Drive the model from a guided setup → §Validate before expensive execution → §Run controlled batches (if sweep) → §Process results for inspection → §Respect fidelity and gate states → §Close the evidence package |
| Audit existing outputs | §Audit outputs before interpreting them → §Follow the study directory convention → §Keep comparisons controlled → §Respect fidelity and gate states → §Close the evidence package |
| SFCW claim | §Start with the local contract → §Audit outputs before interpreting them → §Reconstruct SFCW faithfully → §Process results for inspection → §Match the metric to the claim → §Respect fidelity and gate states → §Close the evidence package |
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
clutter targets, target geometry, mesh, precision) recommend a value with a
fold-open rationale, then generate a geometry sketch and the
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
(`gprmax-skill wizard dump --sketch <out.png>`) so the user sees the domain, host medium,
target at depth, and Tx/Rx before any mesh exists. When the model is
established, produce a model-card report (`gprmax-skill report model-card <contract>`) that
consolidates the contract, numerical gates, sensitivity, processing chain, and
environment into a single deliverable.

## Run controlled batches

For a parameter scan, define dimensions in the contract or a CSV matrix, expand
into cases, and validate every case (grid alignment, overlap, PML clearance,
resolvable materials, numerical gates) before any run. Failed cases do not
enter the run queue. Prefer the study's runner for execution; record per-case
logs, support resume on existing outputs, and produce a status table with a
live progress view.

**Batch only after the model is established.** A new project must first
complete the guided setup (contract with a declared dimension, resolved
medium/target materials, and a frequency band) and run at least one single-case
verification that produces auditable ``.out`` evidence. Run ``gprmax-skill dataset check-model``
to inspect readiness; ``gprmax-skill dataset sample --force`` skips the gate explicitly.

## Process results for inspection

gprMax raw outputs usually need processing to be visibly informative as A-scan /
B-scan. Recommend a processing chain matched to the question (raw display,
standard chain, advanced deconvolution/windowing/envelope, optional imaging,
display-only enhancement) and keep display enhancement separate from
quantitative metrics. Recommend a processing chain matched to the question; adopt
the user's explicit choice when one is given. Record the chain parameters for
reproducibility. The processed
result (A-scan, B-scan, or figure) is the artifact; label it per §Close the
evidence package before delivering.

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
precision or model only with recorded authority.

## Respect fidelity and gate states

Interpret every check through the shared gate vocabulary:
`PASS` / `PASS_WITH_LIMITATION` / `BLOCK` / `STALE` / `NOT_APPLICABLE` for
gates, and `UNVERIFIED` / `CONDITIONAL` / `VERIFIED` / `REJECTED` / `STALE` for
claims. Promotion is **fail-closed**: a blocked or stale gate stops promotion; an
upstream change invalidates downstream evidence to `STALE` until revalidated.
Treat a stale result as invalid until it is revalidated.

Claims license only the fidelity they earn: `F0` analytic sanity, `F1` minimal
numerical physics, `F2` reduced-dimensional propagation, `F3` simplified 3-D,
`F4` high-fidelity 3-D physical model, `F5` calibrated hardware/system closure.
Sign-off requires the claim's minimum fidelity (for example engineering
detection needs `F5`, physical resolution needs `F4`). Read
[gates-and-claims.md](references/gates-and-claims.md) before interpreting any
gate report or signing a claim.

## Audit outputs before interpreting them

Confirm the declared receiver dataset exists, is finite and nonempty, and has
the expected dtype, shape, timestep, and sample count. Reconcile each output
with its case identifier, input/configuration hash, run status, executable,
environment, and output path/checksum. Missing, duplicate, truncated, stale, or
unmapped outputs are audit failures, not analysable results.

Use [preflight-and-audit.md](references/preflight-and-audit.md) for the manifest
and HDF5 audit details.

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
and its processing-detail sidecar in the study package.

## Match the metric to the claim

Keep raw, physically calibrated, and display-only products separate. Freeze the
processing chain and metric definition before comparative evaluation. A peak,
envelope valley, -3 dB width, detection statistic, localization estimate,
two-interface separation, and thickness estimate answer different questions;
none automatically proves another.

For finite 3-D objects, apply infinite-plane or one-dimensional
interface-polarity expectations only where the model has been validated for that
scattering regime. Use waveform polarity only where the physical representation
supports it; use declared energy/envelope metrics for amplitude separability.

Read [interpretation-and-claims.md](references/interpretation-and-claims.md)
before making detection, resolution, thickness, inversion, or system-performance
claims.

## Follow the study directory convention

Maintain a standard directory layout: `README.md`, `simulation_contract.yaml`,
`manifest.json`, `materials/`, `waveforms/`, `cases/`, `scripts/`, `tests/`,
`logs/`, `outputs/` (read-only raw evidence), `analysis/`, `results/`, and
`evidence/`. Name study directories with a date and key parameters
(`01_20260830_SFCW_SLIDE_WET`). Record every intentional change in the study
README. Create a new dated directory for a materially changed model; keep frozen
packages frozen.

Read [study-layout.md](references/study-layout.md) for the full layout, naming
conventions, discipline rules, and the `gprmax-skill layout audit` check before
scaffolding or auditing a study.

## Close the evidence package

Preserve raw outputs, inputs, generated geometry or its deterministic generator,
materials, manifests, run logs, audit results, analysis code, figures/tables,
and a concise result record. Every reported time or distance figure states its
coordinate datum, propagation/range-mapping convention, exact processing chain,
and scope of validity. Present a background-subtracted residual as a residual,
with the subtraction operator and raw data identified; keep raw field measurements
and calibrated hardware results separate.
