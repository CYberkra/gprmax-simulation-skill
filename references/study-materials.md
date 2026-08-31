# Materials, research, and template library

Use this reference when the guided setup identifies a material not in the local
library, when a scene template is matched to a contract, or when a completed
study is proposed as a template. It covers the material library format
(`scripts/materials.py`), the research-need identification
(`scripts/research.py`), and the scene template library
(`scripts/templates_lib.py`).

## Material library (`materials` module)

Every material entry is a YAML file in the `materials/` directory tree. The
`validate_entry` function enforces the schema below on load, write, and
propose; invalid entries are skipped during index builds.

```yaml
name: 砂岩（干燥）
category: rock            # rock / soil / concrete / metal / water / void / composite / other
properties:
  eps_r: 4.5 ± 0.5        # scalar permittivity; or set `model` and use eps_inf
  sigma_s_m: 1e-4         # static conductivity
  model: none             # none / debye / lorentz / drude / measured_complex
  eps_inf: null           # infinite-frequency permittivity (dispersion models)
  delta_eps: null         # permittivity difference (Debye/Lorentz)
  tau_s: null             # relaxation time (s), Debye/Lorentz
frequency_valid: [10, 1000]  # MHz — optional
condition: null           # moisture / porosity etc — optional
source:
  kind: literature        # measured / literature / assumed / sensitivity
  ref: "Knight & Nur 1987 (Stanford)"
  url: null
confidence: 4             # 1–5, optional (default 3)
notes: null
```

Key rules:

- every entry must carry a permittivity — either `eps_r` (scalar) or a
  dispersion model (`debye`/`lorentz`/`drude`/`measured_complex`) with the
  corresponding parameters (`eps_inf`, `delta_eps`, `tau_s`). No entry without
  a permittivity is accepted.
- `condition` is the dimension that makes geological materials sensitive:
  dry sand ε_r ≈ 3–5, wet sand ε_r ≈ 20–30. Record the known condition;
  scope claims to that condition.
- `source.kind` + `source.ref` must be non-empty. A material with no source
  provenance is a sketch, not a frozen entry.
- confidence 1–5: 1 = guessed, 3 = single literature source, 5 = multiple
  independent measurements. The confidence floor is project-dependent.
- `frequency_valid` is advisory — when absent, the entry is assumed valid for
  the frequency range of the referencing study; the agent should note this.

## Research-need identification (`research` module)

`identify_research_needs(contract, materials_dir, scenarios_dir)` returns a
list of `ResearchNeed` records — material needs and scenario-convention needs.
The actual web research is delegated to the agent layer; this module only
identifies what is missing from the local libraries.

Material needs arise when the contract names a medium or target that is not in
the local material library. Scenario-convention needs arise when the contract
signature does not match any verified scene template.

The output is a structured list the agent can act on:

```text
围岩介质 (medium_material) is not in the local material library → research
目标材料 (target_material) already in library → skip
No verified scene template matches the contract → research typical conventions
```

## Scene template library (`templates_lib` module)

A scene template captures a verified scenario — frozen medium, target, antenna,
grid, waveform, link, and band. Only templates marked `verified` are consulted
by `match_scenario`, and only under a strict match: every key in the template's
`match:` signature must equal the study's value. Partial or nearest matches are
never used — that would drag a wrong scenario's frozen values into an unrelated
study.

Template format (YAML):

```yaml
name: coal_tunnel_sfcw
scenario: 煤矿巷道 SFCW 超前探测
status: verified
verified_by:
  - GAP1M 基准包 (20260820)
match:
  scenario_type: tunnel        # strict-match key (required)
  needs_sfcw: true             # bool (required)
  depth_range_m: [50, 100]     # optional — pass if depth is within range
frozen_parameters:
  medium: { ... }
  target: { ... }
  antenna: { ... }
  grid: { ... }
  waveform: { ... }
  link_budget: { ... }
  processing: { ... }
```

### Progressive accumulation

Templates are accumulated, not curated from scratch:

1. **`extract_from_study(study_root)`** — reads `simulation_contract.yaml` +
   `manifest.json` from a completed study and builds a draft template entry.
   The contract's `medium`/`waveform`/`numerics`/`project` blocks become
   `frozen_parameters`; the `task.objective` becomes `match.scenario_type`.
   Fail-closed: missing or unreadable contract/manifest → `TemplateError`.
2. **`extract_study_auto(study_root, scenarios_dir)`** — automated
   progressive-accumulation hook: extract + propose as draft. A verified
   template of the same name is never overwritten.
3. **`verify_template(name, scenarios_dir, verified_by)`** — promote a draft to
   verified, recording the validating packages. Only verified templates
   participate in `match_scenario`.
4. **`match_scenario(signature, scenarios_dir)`** — strict-match a study
   signature against verified templates. Returns the matched template entry or
   `None`. Unverified (draft) templates are never consulted, preventing
   unvalidated values from leaking into a new study.

The initial template library is seeded by the first validated study (e.g. the
coal-tunnel SFCW project). Each subsequent study that passes its gates can be
extracted, reviewed, and verified — the library grows as the skill is used.