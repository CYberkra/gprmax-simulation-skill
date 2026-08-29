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
6. Run a waveform parse smoke for every custom excitation file: expected header,
   sample duration covering the simulation time window, and explicit fill value
   (see [source-and-sfcw.md](source-and-sfcw.md)).

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

## Batch runs

For a parameter scan:

1. Define dimensions in the contract (`scan:` section) or a CSV matrix
   (cartesian product or explicit case list).
2. Expand into cases with independent case IDs and a parameter snapshot.
3. Validate every case before any run: grid alignment, target overlap/gaps,
   PML clearance, resolvable materials, numerical gates (cells/λ, CFL, time
   window). Failed cases are reported and excluded from the run queue.
4. Execute with per-case logs and a status machine
   (pending/running/done/fail); support resume by skipping existing outputs;
   prefer a live progress view.
5. Summarise case → status → output path, and classify failures by root cause
   (geometry / material / numerical / timeout).

## Processing results for inspection

gprMax raw outputs usually need processing to be visibly informative as
A-scan / B-scan. Recommend a processing chain matched to the question — raw
display, standard chain (direct-wave removal, diagnostic background
subtraction, SFCW fusion), advanced chain (deconvolution, windowing,
zero-padded inverse transform, Hilbert envelope), optional imaging, and
display-only enhancement. Follow the user's explicit processing choice when
given. Keep display-only enhancement separate from quantitative metrics, and
record the chain parameters for reproducibility.
