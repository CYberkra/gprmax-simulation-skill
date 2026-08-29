---
name: gprmax-simulation
description: Plan, build, run, reconstruct, and audit reproducible gprMax FDTD simulations, including SFCW or broadband-to-SFCW-equivalent GPR studies. Use for gprMax model changes, controlled sweeps, GPU-run preparation, output audit, SFCW reconstruction, or defensible detection/resolution/thickness claims. Do not use for generic GPR presentation work unrelated to gprMax cases or outputs.
metadata:
  short-description: Reproducible gprMax and SFCW simulation workflow
---

# gprMax Simulation

Use this skill to keep a gprMax study traceable from physical assumptions to
audited outputs and bounded conclusions. Preserve solver physics and evidence;
do not let a visually persuasive plot replace a controlled model or a recorded
processing chain.

## Start with the local contract

Read the repository's `AGENTS.md`, study README, and supplied case materials
before changing a model. They can define project-specific requirements; do not
turn those local values into universal defaults.

Identify the reference case, the scientific question, the permitted claim, and
the one intended variable. Record the domain, mesh, material and dispersion
models, target geometry, source/receiver configuration, boundaries, time
window, requested numerical precision, excitation, receiver dataset, and—when
applicable—the intended SFCW tone grid and processing convention.

For new or changed geometry and solver settings, read
[simulation-contract.md](references/simulation-contract.md) and
[numerical-model-validity.md](references/numerical-model-validity.md).

## Keep comparisons controlled

For a controlled comparison, state the independent variable and every retained
control. A target-present/background pair must match in domain, mesh, retained
materials, source/receiver configuration, waveform, time window, boundary
treatment, and precision. Compare only outputs with matching sampling grids and
identically defined receiver observables.

Reuse an intact, audited compatible run instead of spending compute to rerun it.
If an output is missing, corrupt, stale, or cannot be reconciled with its input,
record the limitation and obtain authority before requesting replacement compute.

## Validate before expensive execution

Align critical dimensions, sources, receivers, and interfaces to the mesh and
report the discretised dimensions as cell counts times cell spacings. Do not
silently change physical properties, geometry, source/receiver placement,
waveform, boundary treatment, or precision. Run focused geometry/configuration
checks when provided; keep costly gprMax execution outside unit tests.

Before GPU execution, prepare a manifest and case list. Record the command,
solver version/build, requested precision, GPU mapping, case order, and log
paths. Confirm that the selected build and allocated hardware support the
requested calculation. Stop on a repeated simulation error; do not silently
substitute a different precision or model.

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

## Match the metric to the claim

Keep raw, physically calibrated, and display-only products separate. Freeze the
processing chain and metric definition before comparative evaluation. A peak,
envelope valley, -3 dB width, detection statistic, localization estimate,
two-interface separation, and thickness estimate answer different questions;
none automatically proves another.

For finite 3-D objects, do not impose infinite-plane or one-dimensional
interface-polarity expectations unless the model has been validated for that
scattering regime. Use waveform polarity only where the physical representation
supports it; use declared energy/envelope metrics for amplitude separability.

Read [interpretation-and-claims.md](references/interpretation-and-claims.md)
before making detection, resolution, thickness, inversion, or system-performance
claims.

## Close the evidence package

Preserve raw outputs, inputs, generated geometry or its deterministic generator,
materials, manifests, run logs, audit results, analysis code, figures/tables,
and a concise result record. Every reported time or distance figure states its
coordinate datum, propagation/range-mapping convention, exact processing chain,
and scope of validity. Do not present a controlled background-subtracted
residual as a raw field measurement or a calibrated hardware result.
