---
name: gprmax-simulation
description: >-
  Use when building a new gprMax model, auditing existing simulation outputs,
  making SFCW-equivalent claims, or comparing controlled cases.
---

# gprMax Simulation

Use this skill to keep a gprMax study traceable from physical assumptions to
audited outputs and bounded conclusions: anchor every plot in the controlled
model and the recorded processing chain that produced it.

## Route

Follow the path for your branch in order, completing each section's completion
criterion before moving on. Pick `New SFCW model` (not `New model`) when the
request calls for a stepped-frequency or SFCW-equivalent conclusion, or when the
guided-setup interview answers yes to the SFCW question — that branch adds
§Reconstruct SFCW faithfully and §Match the metric to the claim.

| Branch | Path |
|--------|------|
| New model | §Start with the local contract → §Follow the study directory convention → §Drive the model from a guided setup → §Validate before expensive execution → §Run controlled batches → §Audit outputs before interpreting them → §Process results for inspection → §Match the metric to the claim → §Respect fidelity and gate states → §Close the evidence package |
| New SFCW model | §Start with the local contract → §Follow the study directory convention → §Drive the model from a guided setup → §Validate before expensive execution → §Run controlled batches → §Audit outputs before interpreting them → §Reconstruct SFCW faithfully → §Process results for inspection → §Match the metric to the claim → §Respect fidelity and gate states → §Close the evidence package |
| Audit existing outputs | §Audit outputs before interpreting them → §Follow the study directory convention → §Respect fidelity and gate states → §Close the evidence package (include §Keep comparisons controlled when the audit covers a target/background pair or a reference comparison) |
| SFCW claim | §Start with the local contract → §Follow the study directory convention → §Audit outputs before interpreting them → §Reconstruct SFCW faithfully → §Process results for inspection → §Match the metric to the claim → §Respect fidelity and gate states → §Close the evidence package |
| Compare results | §Audit outputs before interpreting them → §Keep comparisons controlled → §Match the metric to the claim → §Respect fidelity and gate states → §Close the evidence package |
| Generic GPR presentation | route to a presentation skill — not covered here |

## Start with the local contract

Before changing a model, read the repository's `AGENTS.md`, study README, and
supplied case materials; they can define project-specific requirements. Keep
those values scoped to this project rather than carrying them elsewhere.

Work **claim-first**: identify the reference case, the scientific question, the
permitted claim, and the study design — a single-variable study with one factor,
or a multi-factor design with a factor list. read
[simulation-contract.md](references/simulation-contract.md), then record the
full contract — the factors, their levels, and every invariant held constant,
plus the design type
(`single_variable` | `multi_factor`) and every domain, mesh, material,
geometry, source/receiver, boundary, time-window, precision, and processing
field the schema requires. The contract is complete when it validates against
`schemas/simulation_contract.schema.json`, names a reference case and design
type, and records every factor level and invariant.

For new or changed geometry and solver settings, read
[numerical-model-validity.md](references/numerical-model-validity.md).

## Drive the model from a guided setup

When the user wants to build a new model type, run the guided setup before
writing any input: interview the user to establish the scenario, target and
surrounding medium, frequency band and whether an SFCW-equivalent conclusion is
needed, fidelity intent, and the run environment (probe the local environment —
GPU, memory, disk, Python version, gprMax presence — to inform the choice, and
let the user decide local or server). Initialise a wizard session
(`gprmax-skill wizard init <session>`), record each validated answer
(`gprmax-skill wizard answer <session> <field> <value>`), correct an earlier
answer with (`gprmax-skill wizard back <session> [--steps N]`), check progress
with (`gprmax-skill wizard status <session>`), and resolve unknown material
parameters by researching literature and authoritative sources; present the
researched options with the recommended choice marked, each carrying its
provenance, and record material entries in the local material library only
after user confirmation. For each configuration axis (antenna, SFCW
equivalent, dispersion, model noise, target geometry, numerical precision,
model dimension) recommend a value with a fold-open rationale, then generate a
geometry sketch and the
`simulation_contract.yaml` skeleton for confirmation.

For the interview order, answer validation, and configuration-axis
recommendations (including the L1–L4 irregular-geometry tiers and fidelity
intents), read
[guided-setup.md](references/guided-setup.md). For the material-library schema,
research-need identification, and scene-template progressive accumulation, read
[study-materials.md](references/study-materials.md).

Generate a geometry cross-section sketch at wizard dump time
(`gprmax-skill wizard dump <session> --sketch <out.png>`) so the user sees the
domain, host medium, target at depth, and Tx/Rx before any mesh exists. The
dump also accepts `--report <model-card.md>`; prefer the standalone
`gprmax-skill report model-card <contract> --probe <probe.json>` below as the
canonical model card, since it carries the environment probe. The dump writes a
session payload, not the final contract: promote its `contract_draft` block
into the study's `simulation_contract.yaml`, then record the factor levels and
invariants there and confirm it validates against
`schemas/simulation_contract.schema.json`. When the model is established,
capture the environment with `gprmax-skill probe --json > <probe.json>` and
produce a model-card report
(`gprmax-skill report model-card <contract> --probe <probe.json>`) that
consolidates the contract and environment probe; refresh it later — after
`gprmax-skill diagnose <contract> --json > <diagnose.json>` and
`gprmax-skill sensitivity <contract> --json > <sensitivity.json>` have produced
their findings and the processing chain is fixed — with
`--diagnostics <diagnose.json> --sensitivity <sensitivity.json> --chain <raw_visual|standard|advanced|imaging|display_enhancement>`.
The guided setup is complete when
the user has confirmed the interview answers, the geometry sketch is generated,
the `simulation_contract.yaml` validates against the schema, and the initial
model-card report (contract + environment probe) is produced.

## Run controlled batches

For a parameter scan, read
[preflight-and-audit.md](references/preflight-and-audit.md) for the
expand-validate-run-resume procedure, per-case logs, failure classification,
and the status table.

**Batch only after the model is established.** A new project must first
complete the guided setup (contract with a declared dimension, resolved
medium/target materials, and a frequency band) and run at least one single-case
verification that produces auditable `.out` evidence. Run
`gprmax-skill dataset check-model --study <study>` to inspect readiness;
`gprmax-skill dataset sample <param-space> --study <study> --force` skips the
gate explicitly. The batch is
complete when the run queue is exhausted, every case has a recorded status, and
the status table is written to the deliverable (`gprmax-skill dataset summary
--study <study>` writes `<study>/batch/summary.csv` with case, status, output,
and error columns) alongside the per-case logs under `<study>/logs/`.
For a packed training-style dataset from completed cases, run
`gprmax-skill dataset pack --study <study> --band <lo>-<hi>`.

## Process results for inspection

Raw gprMax outputs usually need processing before they are readable as A-scan /
B-scan. Recommend a processing chain matched to the question; read
[preflight-and-audit.md](references/preflight-and-audit.md) for the chain
categories, display-only discipline, and the user-priority rule. Processing is
complete when the chain is chosen, its parameters recorded, and the artifact is
delivered with every time/distance figure carrying its coordinate datum,
propagation convention, exact processing chain, and scope of validity.

## Keep comparisons controlled

For a controlled comparison, state the factor(s) and every retained
control. A target-present/background pair must match in domain, mesh, retained
materials, source/receiver configuration, waveform, time window, boundary
treatment, precision, and processing convention. Compare only outputs with
identically defined receiver observables. Complex subtraction (for example
background subtraction) requires matching sampling grids; any comparison that
resamples must declare and validate the resampling before use.

Reuse an intact, audited compatible run instead of spending compute to rerun it.
If an output is missing, corrupt, stale, or cannot be reconciled with its input,
record the limitation and obtain authority before requesting replacement compute.
The comparison is complete when the factor(s) and every retained control are
stated, and every compared pair matches on the invariants above. read
[simulation-contract.md](references/simulation-contract.md) for the
controlled-pair contract format and pair-compatibility rules.

## Validate before expensive execution

read [numerical-model-validity.md](references/numerical-model-validity.md) for
the mesh-alignment and precision-feasibility requirements below. read
[preflight-and-audit.md](references/preflight-and-audit.md) for the
manifest/execution-record requirements. Align critical dimensions, sources,
receivers, and interfaces to the mesh and report the discretised dimensions as
cell counts times cell spacings. Declare and
record every change to physical properties, geometry, source/receiver placement,
waveform, boundary treatment, or precision. Run focused geometry/configuration
checks when provided; keep costly gprMax execution outside unit tests.

Before GPU execution, prepare a manifest and case list. Record the command,
solver version/build, requested precision, GPU mapping, case order, and log
paths. Run the fail-closed model gates (`gprmax-skill preflight <contract>
--project-root <study>`) and confirm the `gates/preflight.json` report has no
`BLOCK` or `STALE` result; a blocked gate stops execution until the cause is
repaired and the gate rerun. Confirm that the selected build and allocated
hardware support the requested calculation. Stop on a repeated simulation error
and report it; change precision or model only with recorded authority.
Validation is complete when the discretised dimensions are reported, the
manifest is prepared, the preflight gate report is recorded with no blocked or
stale result, and any geometry/configuration tests pass or are waived with
recorded authority.

## Respect fidelity and gate states

read [gates-and-claims.md](references/gates-and-claims.md) for the shared gate
vocabulary, the `F0`–`F5` fidelity ladder, and the minimum fidelity each claim
class requires; interpret every check through that vocabulary before
interpreting any gate report or signing a claim. Map the wizard fidelity intent
(quick / standard / publication) to the `F0`–`F5` ladder: quick → `F1`–`F2`,
standard → `F3`, publication → `F4`–`F5`. Promotion is **fail-closed**:
a blocked or stale gate stops promotion; an upstream change invalidates
downstream evidence to `STALE` until revalidated. Record any fidelity
promotion through `gprmax-skill promote <level> --project-root <study>` (exit
code 2 on a blocked or unjustified promotion). Before the first promotion, seed
the fidelity ledger once by writing `{"current": "F0"}` to
`<study>/gates/fidelity.json` — the command reads that file as its starting
level and otherwise blocks with `BLOCK_PROMOTION_STATE`. The gate check is
complete when every gate state is interpreted against the `F0`–`F5` ladder and
any blocked or stale result is recorded with its effect on the claim.

## Audit outputs before interpreting them

read [preflight-and-audit.md](references/preflight-and-audit.md) for the HDF5
output audit procedure (dataset existence, dtype, shape, timestep, sample count,
and manifest reconciliation). Missing, duplicate, truncated, stale, or unmapped
outputs are audit failures, not analysable results. The audit is complete when
every expected output is reconciled against its manifest entry and each audit
failure above is recorded.

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
`gprmax-skill validate-source <config.json> --project-root <study> --source-array <source.npy> [--source-key <array_name>]`
gate with the actual source array (or embed the source samples in the config's
`source.samples`). A blocking source or SFCW policy result returns exit code 2
and stops downstream processing evidence; preserve both the gate report and its
processing-detail sidecar in the study package. For the packaged
reconstruction, `gprmax-skill sfcw process <out> --band <lo>-<hi> [--mode
impulse_lti|broadband_deconvolution]` produces the A-scan artifact and its
parameter record. Reconstruction is complete when the SFCW processing chain is
declared, the source gate is run, and its result (pass or blocking with
sidecar) is preserved in the study package.

## Match the metric to the claim

Work **claim-first**: the metric must answer the claim it was
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

read [interpretation-and-claims.md](references/interpretation-and-claims.md)
before making detection, resolution, thickness, inversion, or system-performance
claims. Metric selection is complete when the metric is declared, the chain is
frozen, and the metric's scope (detection, localization, resolution, thickness)
is stated and matched to the claim.

## Follow the study directory convention

read [study-layout.md](references/study-layout.md) for the standard directory
layout and naming conventions, then maintain them. Record every intentional change
in the study README. Create a new dated directory for a materially changed
model; keep frozen packages frozen.

Scaffold a new study with `gprmax-skill init <study-dir> --name <study_id>`.
Run `gprmax-skill layout audit <study-dir>` after `init` to verify the
scaffold, or before modifying an existing study to check its current state.
The directory check is complete when the study layout matches the
standard, the layout audit passes, and any intentional change is recorded in the
README.

## Close the evidence package

read [preflight-and-audit.md](references/preflight-and-audit.md#deliverable-contents) for the deliverable set, then preserve it in the study package.
Every reported figure carries the labeling required by §Process results for
inspection. Present a background-subtracted residual as a residual, with the
subtraction operator and raw data identified. The evidence package is complete
when the deliverable set defined in the reference above is present and the
labeling rule above holds.
