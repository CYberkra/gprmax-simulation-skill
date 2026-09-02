# Simulation contract and controlled comparisons

Use this reference before changing a gprMax input, generating a parameter sweep,
or comparing two cases.

## Define the case before execution

Create a concise machine-readable or human-readable contract containing:

- study and case identifiers, purpose, allowed claims, and reference case;
- domain dimensions, `dx_dy_dz`, PML/boundary setup, time window, and precision;
- material model, parameters, units, dispersion model, provenance, and valid
  frequency context;
- nominal and mesh-realised target geometry, orientation, position, and the
  target's intended contrast mechanism;
- transmitter, receiver, polarization/component, waveform, receiver observable,
  and coordinate convention;
- intended processing chain and any SFCW tone grid, source reference, range
  datum, or calibration reference.

The canonical machine-readable form is validated against
`schemas/simulation_contract.schema.json`, with `templates/simulation_contract.yaml`
as the starting skeleton and `templates/model_purpose.yaml` for the claim
statement (allowed vs forbidden claims). The schema is contract-first: new
fields (for example batch `scan:` dimensions, fidelity intent, material
`condition`) are added to the schema before any consumer depends on them.

Record the actual discretised values separately from nominal values. A declared
dimension is not necessarily representable on a Yee grid.

## Controlled-pair contract

For every comparison, list the independent variable, invariant fields, permitted
differences, and expected outputs. Target-present and matched-background cases
may differ only in the declared target definition. A comparison is invalid if a
retained material, mesh, source/receiver, waveform, boundary, time window,
precision, or processing convention differs without being part of the question.

Do not infer pair compatibility from similarly named files. Compare inputs and
configuration hashes, then verify matching receiver observable, `dt`, sample
count, and relevant metadata before joint processing.

## Geometry and material checks

- Express key target dimensions, gaps, source/receiver locations, and interfaces
  in integer cells whenever the model requires exact alignment.
- Check overlapping objects, gaps, geometry-definition ordering, material
  overrides, and clearance from PML.
- Record whether a target represents an infinite interface, a finite scatterer,
  a 2-D approximation, or a 3-D body. Do not transfer conclusions across those
  representations without validation.
- Keep material assumptions explicit. A constant permittivity/conductivity, or
  a Debye/Lorentz model, needs units, provenance, and relevance to the used band.

## Change management

Use a new case or dated study package for a materially changed physical model.
Preserve frozen sources and results. A regenerated geometry file may be omitted
from a lightweight archive only when its deterministic generator, parameters,
and recorded hash make regeneration auditable.

## Study directory convention

Maintain the standard directory layout and naming conventions defined in
[study-layout.md](study-layout.md). Never silently change physical parameters;
record every intentional change in the study README.

## Material library

Maintain a material library as YAML files with a JSON index for fast lookup.
Each entry stores:

- name, category, properties (ε_r, σ, dispersion model with parameters),
  valid frequency range, optional condition (moisture, porosity — geological
  materials vary strongly with water content), source (kind, reference, doi),
  confidence (1-5), and notes.

Materials are stored in the skill repository and may be overridden by a
project-local `materials_override/` directory. Only commit entries after user
confirmation. An entry without a provenance trail is a draft, not a frozen
reference.
