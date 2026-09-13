# Interpretation and claim boundaries

Use this reference before reporting detection, localization, separability,
thickness, inversion, or system performance.

## Separate data layers

Maintain raw solver output, physically calibrated/conditioned data, and
display-only products as distinct artifacts. Plot normalization, clipping,
cosmetic smoothing, and contrast adjustment may aid reading but must not feed a
quantitative metric unless explicitly made part of a frozen physical processing
chain.

Freeze the source reference, deconvolution, band, window, filter, background
method, gain, envelope method, range mapping, detector, and threshold before a
comparative evaluation. State any exploratory tuning separately from independent
confirmation evidence.

## Finite targets, polarity, and interfaces

An infinite planar interface, a finite slab, and a compact 3-D object can have
different scattering, edge diffraction, phase, and apparent polarity. Do not
force a one-dimensional plane-wave polarity rule onto a finite object merely
because its geometry has two nominal faces. Validate the interpretation against
the model class and the selected receiver observable.

Use the signed/complex A-scan when polarity or coherent phase is the question.
For a real A-scan use its Hilbert envelope; for the Liu2021 complex IFFT profile
use its magnitude directly. An envelope peak does not prove a distinct physical interface by
itself; it must be connected to a declared forward model or controlled sweep.

## Match the metric to the claim

Before evaluation, specify the target window, guard/noise region, estimator,
units, threshold, and failure rule. Do not choose a guard region after inspecting
the known target response.

- A detection metric demonstrates a declared response above a declared
  reference/guard statistic; it is not automatically localization or thickness.
- Localization requires a coordinate datum and a separately declared event
  estimator/search window.
- A PSF width or -3 dB feature is descriptive unless the project contract has
  explicitly selected it as the separability criterion.
- Two-target and two-interface studies are different physical validation cases.
- A single deterministic thickness result is case-specific. A broader thickness
  recovery claim needs multiple truth values, material/velocity assumptions,
  negative controls, uncertainty treatment, and a fixed estimator.
- Coherent delay or phase inversion requires complex information; magnitude-only
  or real-only fitting cannot justify a high-precision complex-delay claim.

For a peak-to-valley envelope criterion, record both peak definitions, the valley
search interval, whether amplitudes or powers enter the dB conversion, and the
threshold. Require a stable/prominent valley rather than treating a one-sample
numerical dip as a physical separation.

## Validate the selector before searching a size limit

Test a single-reflection response with realistic band weighting, known two-echo
controls across spacing and amplitude ratio, and available physical ablation
controls. A single reflection with sidelobes must not certify two interfaces.
Freeze validation tolerances and target/noise assumptions before new comparative
evaluation; do not raise thresholds post hoc merely until one counterexample
passes. A prominence or amplitude threshold alone is not a proven replacement.

The D80 historical region picker v2 selects local maxima by theoretical-time
distance and requires separation plus a 3.0103 dB valley. A single ideal echo
was shown to pass it with a roughly 37.62 dB valley. Consequently, its RESOLVED
label means a historical numerical metric passed, not validated interface
resolution. Keep its old results intact; register a newly validated selector as
a separate version and reanalyse compatible raw outputs.

Using true geometry to guide a selector is acceptable for a model-informed
diagnostic but is not blind localization/detection. Report this dependency.
Validate candidate identity as thickness changes; do not let the picker silently
switch from an interface-associated peak to a sidelobe or unrelated response.

## Ablation evidence

State exactly which voxels/material regions changed. Extending the first occupied
slice is not the same geometry as retaining the whole target and filling each
occupied transverse ray behind its last target cell. Neither directly simulates
a pure rear-only reflection.

Compare original response, extended-target response and their complex difference.
The latter includes interactions caused by the changed geometry; amplitude ratios
are not additive energy/contribution percentages. Exact complex closure follows
from subtraction and is an algebraic check, not independent physical validation.

Derive or load peak positions from versioned current results, and compute each
declared acceptance condition. No unconditional physical PASS or hardcoded anchor
can replace that evaluation. Examine the artificial terminal, other paths and
band-limited leakage before claiming the original rear interface was isolated.

## Thickness and occupied volume

Report grid-realised front/back face coordinates, occupied span and target-voxel
volume separately from nominal bounding dimensions. A changing irregular mask
also changes scattering geometry; do not treat it as a pure planar-thickness
perturbation. Compare different shape/fill families separately.

Scan thickness and transverse dimensions, then test joint combinations. Do not
multiply separately found minima. Preserve non-monotonic outcomes and untested
cells. An adaptive search gives the smallest tested passing case; a finite-set
minimum additionally requires excluding all smaller candidates in that set.
Retest final candidates for interface association and relevant numerical
sensitivity; stochastic robustness requires actual independent realizations,
not repeated deterministic geometry labels.

## Detection probability and system claims

`P_D`/`P_FA` claims require a frozen detector and threshold, positive and
negative populations, random-seed provenance, sample size, and confidence
intervals. A target-minus-background residual can be useful causal evidence but
cannot alone stand in for a field-available engineering detector.

Absolute power, receiver SNR, dynamic-range, or hardware claims additionally
require a validated link from simulated fields to the claimed receive chain.

## Reporting scope

For every conclusion, state the model class, materials, geometry, band,
processing chain, noise/background treatment, and criterion. Use bounded wording
such as “for the audited simulated case” when validation has not covered the
variation needed for a general statement.
