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
Use the Hilbert envelope when the question is event strength or peak-to-valley
separation. An envelope peak does not prove a distinct physical interface by
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
