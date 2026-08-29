# Preflight and output audit

Use this reference to prepare a case for execution and to audit new gprMax
outputs before analysis.

## Preflight checklist

1. Preserve frozen packages; create a new dated study package for a material
   physics change when the local repository convention requires it.
2. Generate related inputs from one parameter source where possible. Record case
   IDs, input/configuration hashes, geometry/material files, waveform, domain,
   mesh, PML, time window, Tx/Rx, intended precision, receiver dataset/schema,
   and expected sample count (or deterministic derivation) in a manifest.
3. Verify critical dimensions and positions are grid aligned and report the
   realised cell-count dimensions.
4. Run supplied focused geometry/configuration tests from the artifact root; do
   not place costly gprMax execution in the test suite.
5. Verify compatible target/background inputs before a comparison is authorised.

## Execution record

Prefer the study's supplied runner. Save case order, command, start/finish time,
GPU mapping, solver version/build, requested precision, environment identity,
stdout/stderr logs, input/configuration hash, output path, output size/checksum,
and exit status. Treat a nonzero exit code, missing output, incomplete log, or
unmapped output as a failed run.

## HDF5 output audit

For every expected `.out` file:

- confirm the declared receiver dataset (for example `rxs/rx1/Ez`) exists;
- confirm it is finite and nonempty;
- record dtype, shape, timestep, sample count, and relevant receiver metadata;
- compare schema, timestep, and sample count with the manifest and all traces
  intended for joint processing;
- reconcile expected, completed, missing, extra, duplicate, and stale outputs.

Inspect the HDF5 dtype for a formal precision claim. A command-line flag or
filename alone is insufficient. When an artifact update is requested, write the
audit result next to the study results; for a read-only review, report findings
without modifying the package.

## Deliverable contents

Keep inputs, deterministic geometry source or generated geometry, materials,
manifest, execution record, logs, raw outputs, audit result, analysis code,
figures/tables, and a short result record. State exact SFCW frequency samples,
window, source conditioning, background treatment, inverse method, envelope
method, and coordinate datum in any derived figure or table.
