# Study layout and directory discipline

Use this reference when scaffolding a new study, auditing a study directory, or
interpreting a `layout audit` report. The layout is defined by
`scripts/scaffold.py`; the discipline gates (`audit_layout`) are the enforcement
layer.

## Standard layout

Every study follows the same directory tree so that an agent (or another
engineer) can navigate any study without a custom index:

```
<study_id>/
├── README.md                    # purpose, frozen parameters, decision log, change log
├── simulation_contract.yaml     # contract (wizard output or hand-written)
├── manifest.json                # run manifest: case IDs, hashes, precision, status
├── materials/                   # local material definitions (or overrides)
├── waveforms/                   # waveform files (impulse / custom)
├── cases/                       # .in input files (generated or hand-written)
├── scripts/                     # generation, validation, and analysis scripts
├── tests/                       # pytest geometry checks
├── logs/                        # run logs, one per case
├── outputs/                     # raw .out — immutable, read-only
├── analysis/                    # processing code + intermediates
├── results/                     # final figures, tables, conclusions
├── model_card.md                # model-card report (contract, probe, diagnostics)
└── evidence/                    # audit reports, hashes, manifest copies
```

### Study ID convention

`<nn>_<yyyymmdd>_<TOPIC>[_<KEY_PARAM>]` — e.g. `01_20260830_SFCW_SLIDE_WET`.
The name is validated by `validate_study_name`.

### Case ID convention

UPPER_SNAKE_CASE of `SCENARIO_TARGET_TYPE_TRACE` — e.g. `SLIDE_WET_H1_T007`.

### Discipline rules

- `outputs/` is **immutable raw evidence** — `.in`, `.py`, `.sh`, `.bat` files
  are never placed there. Writing to `outputs/` after the run is a discipline
  violation. Every evidence file (`.out`/`.h5`/`.hdf5`) is SHA-256 hashed into
  `manifest.json["outputs_sha256"]` via `gprmax-skill layout hash`; `layout
  audit` compares live files against the recorded hashes and BLOCKs on
  tampering or unrecorded evidence. Re-hash explicitly after a legitimate
  regeneration.
- `results/` holds derived conclusions; anything in `results/` must be
  reproducible from `outputs/` + `analysis/`.
- `evidence/` holds audit reports, manifest snapshots, and hash checksums so
  the study's integrity can be verified without re-running everything.
- `README.md` records every intentional parameter change (never silently modify
  a frozen value).
- Freeze a study by creating a new dated directory; do not overwrite old
  deliveries.

## Layout audit (`audit_layout`)

`audit_layout(study_root)` inspects a study directory against the standard
layout and returns a list of findings with severity `OK | WARN | BLOCK`:

| Check | Triggers | Severity |
|---|---|---|
| standard directories present | missing `materials/`, `waveforms/`, `cases/`, `scripts/`, `tests/`, `logs/`, `outputs/`, `analysis/`, `results/`, `evidence/` | BLOCK |
| standard files present | missing `README.md`, `simulation_contract.yaml`, `manifest.json` | BLOCK |
| `outputs/` read-only | empty `outputs/` (WARN); `.py`/`.in`/`.sh`/`.bat` inside `outputs/` (BLOCK) | WARN / BLOCK |
| `outputs/` hash integrity | evidence file unrecorded in `manifest.json["outputs_sha256"]` or hash mismatch (evidence modified) | BLOCK |
| stray study-root material | `.py`/`.in` files directly under the study root (belong in `scripts/` or `cases/`) | WARN |
| naming convention | study name does not match `<nn>_<yyyymmdd>_<TOPIC>` | WARN |
| contract parseability | `simulation_contract.yaml` missing, unreadable, or not a mapping | BLOCK |

The CLI command `gprmax-skill layout audit <study-dir>` runs the check and
exits with code 2 when any BLOCK is found (fail-closed).

## Scaffold command

`gprmax-skill init [<study-dir>] [--name <study_id>]` creates the full layout
from the template. Existing non-overwritable files (`README.md`,
`simulation_contract.yaml`, `manifest.json`) are never replaced — the command
is safe to re-run on an existing study.

The `init` command also copies the standard contract template
(`templates/simulation_contract.yaml`) and writes a skeleton manifest
(`manifest.json`) with placeholders.