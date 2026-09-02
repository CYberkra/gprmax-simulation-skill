# Guided setup: wizard and configuration axes

Use this reference when starting a new gprMax study or changing one of the
configuration axes. It documents the wizard-driven requirements capture
(`scripts/wizard.py`) and the configuration-axis recommendations
(`scripts/axes.py`), so the agent asks the right questions and knows what each
axis option licenses.

## Wizard flow (`wizard` CLI)

The wizard is a dialogue, not a form: ask the questions in order, record
validated answers, and only dump a contract when the session is complete.
Session state is persisted so a run can be interrupted and resumed.

Questions are organised into five steps (`STEP_FIELDS`), with a `back` step to
correct earlier answers:

| Step | Fields | Purpose |
|---|---|---|
| `scenario` | `scenario_type`, `target_depth_m`, `domain_m` (opt), `pml_layers` (opt) | Scene positioning: tunnel / landslide / archaeology / geotechnical / inspection / other, target depth or range |
| `target_medium` | `target_material`, `medium_material`, `medium_eps_r` (opt), `scan_factors` (opt) | Target and host medium; unknowns are marked `unknown` (research later); `scan_factors` declares multi-factor sweep factors vs. invariants |
| `band_mode` | `needs_sfcw`, `band_mhz` | Whether the study needs an SFCW-system conclusion and the frequency range (known, or derived from target depth) |
| `fidelity` | `fidelity`, `dimension`, `custom_cells_m` (opt) | Fidelity intent (see below) + model dimension (2d/2.5d/3d) — drives antenna, irregularity, dimension, and grid tiers |
| `environment` | `run_env` | local vs. server — decided by the user; the probe only informs |

Rules:

- validate every answer against the field spec before recording it
  (`_validate_answer`); invalid values are rejected, never silently accepted;
- before a dump, validate the full session: band format, axis options, numeric
  ranges, and session completeness (`validate_for_dump`); a session that is not
  complete is not a contract;
- `dump` produces the simulation contract YAML (`simulation_contract.yaml`),
  which then feeds the numerical gates (`references/numerical-model-validity.md`)
  and the study scaffold (`references/study-layout.md`);
- `scan_factors` distinguishes declared sweep factors from fixed parameters and
  invariants — a filled depth/band/target list alone is *not* a multi-factor
  design.

## Configuration axes (`axes` module)

Seven axes cover the choices a model needs. Every axis option carries a
recommendation basis; the agent presents the option set with the recommended
option marked and lets the user confirm or override (user-specified choices
always win).

| Axis | Options | Recommendation basis |
|---|---|---|
| Antenna | ideal hertzian dipole / physical antenna / none (plane-wave injection) | scene research + fidelity intent |
| SFCW equivalent | off (broadband direct) / on (LTI impulse-response, Liu 2021) | whether an SFCW-system conclusion is needed |
| Dispersion model | constant / Debye / Lorentz / Drude / measured complex | material research + band |
| Model noise | none / AWGN (SNR/D) / clutter objects | whether noise/statistical analysis is needed; clutter list from scene research |
| Target geometry | regular (box/cylinder) / irregular L1–L4 | avoiding coherent artifacts from flat interfaces + fidelity |
| Numerical precision | auto fp32/fp64 | required dynamic range vs. fp32 floor (≈ −90 dB) |
| Model dimension | 2d / 2.5d / 3d | project stage + fidelity (see below) |

Grid sizing (dx/dy/dz, PML layers) is derived from the axes above (cells/λ ≥ 10
+ time window + domain size); the run environment (local / server) is a user
decision that the probe only informs. Neither is an axis.

### Model dimension and project stage

The model dimension is a first-class axis and must be declared before any run
(2d = single-cell slice, TM mode; 2.5d = thin-slice 3D, 3–5 cells in the
invariant direction, keeps 3D physics at lower cost; 3d = full 3D). gprMax's
native 2D is a one-cell-thick slice and forces the source polarisation along
the invariant direction (TM mode) — record that constraint when 2d is chosen.

Stage-to-dimension recommendation (defaults; the user's explicit choice always
wins):

| Project stage | Recommended dimension |
|---|---|
| Quick screening / concept verification | 2d |
| Parameter scan / intermediate validation | 2.5d |
| Formal conclusion / criteria / publication | 3d |

Deep-scene studies (tunnel, landslide) or studies needing an SFCW-system
conclusion are nudged up one tier because formal conclusions need 3D physics.
A 2d model can never certify an engineering or 3-D-objective claim (see
`audit_geometry`).

### Irregular geometry tiers (L1–L4)

Irregularity is progressive and composable — pick the tier that matches the
fidelity intent, do not jump straight to L4:

- **L1** — regular solids (`#box` / `#cylinder`);
- **L2** — regular solids + rough interface (Gaussian σ ≈ 5–10 cm, correlation
  length 15–20 cm);
- **L3** — irregular outline via mask HDF5 (`#geometry_objects_read`, spline /
  Bezier cross-sections extruded along x);
- **L4** — naturalistic: fractal roughness (fBm) + graded material transition
  layers + internal heterogeneous nesting.

Higher tiers cost more cells and validation effort; record the tier in the
contract so comparisons stay within one representation level.

### Dependency flow

Choices are not independent. The recommendation order is:
`SFCW → tone grid → grid+precision → VRAM → environment`. When the user changes
an upstream axis, re-derive the downstream recommendations and mark stale
choices rather than silently keeping them.

### Fidelity intents

`axes.FIDELITY_INTENTS = ("quick", "standard", "publication")` maps user intent
to concrete option bundles. The mapping is the bridge between "how realistic
should the model be?" and the antenna, irregularity, and grid tiers above.
"quick" favours a small grid and simple geometry; "standard" is the default
research tier; "publication" raises cells/λ, antenna fidelity, and irregularity
(L2–L4) with the corresponding VRAM/time cost surfaced up front.
