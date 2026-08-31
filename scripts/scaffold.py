"""Study directory scaffolding.

Creates the standard gprMax study layout so every study is immediately
auditable and comparable:

    README.md, simulation_contract.yaml, manifest.json,
    materials/ waveforms/ cases/ scripts/ tests/ logs/
    outputs/ analysis/ results/ evidence/

`outputs/` is the immutable raw-evidence directory; nothing in a scaffold
changes that invariant.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

# Standard study layout (documented in references/simulation-contract.md).
STANDARD_DIRECTORIES = (
    "materials",
    "waveforms",
    "cases",
    "scripts",
    "tests",
    "logs",
    "outputs",
    "analysis",
    "results",
    "evidence",
)
STANDARD_FILES = ("README.md", "simulation_contract.yaml", "manifest.json")

# Manuals that must not be silently overwritten.
_NON_OVERWRITABLE = frozenset({"README.md", "simulation_contract.yaml", "manifest.json"})


class ScaffoldError(ValueError):
    """Invalid study name or scaffold target."""


_NAME_PATTERN = re.compile(r"^\d{2}_\d{8}_[A-Za-z0-9]+(?:_[A-Za-z0-9]+)*$")


def validate_study_name(name: str) -> str:
    """Validate the study_id convention: 01_20260830_SFCW_SLIDE_WET."""
    if not _NAME_PATTERN.match(name.strip()):
        raise ScaffoldError(
            f"study name {name!r} must match <nn>_<yyyymmdd>_<TOPIC> "
            "(e.g. 01_20260830_SFCW_SLIDE_WET)"
        )
    return name.strip()


def contract_template() -> Path:
    return Path(__file__).resolve().parents[1] / "templates" / "simulation_contract.yaml"


def _manifest_skeleton() -> str:
    return json.dumps(
        {
            "study": None,
            "cases": [],
            "generated_at": None,
            "note": "Fill after the guided setup; hashes and status are recorded per case.",
        },
        indent=2,
        ensure_ascii=False,
    ) + "\n"


def _readme_template(name: str) -> str:
    return (
        f"# {name}\n\n"
        "- Study purpose:\n"
        "- Frozen parameters (record every intentional change here):\n"
        "- Allowed claims:\n"
        "- Processing chain:\n"
    )


def create_study_skeleton(project_root: Path, name: str | None = None) -> list[Path]:
    """Create the standard layout under *project_root*.

    If *name* is given it must follow the study_id convention and is written
    into the README and manifest. Existing non-empty files are never
    overwritten; missing directories are created.
    """
    project_root = Path(project_root)
    if name:
        name = validate_study_name(name)

    created: list[Path] = []
    project_root.mkdir(parents=True, exist_ok=True)

    for directory in STANDARD_DIRECTORIES:
        target = project_root / directory
        target.mkdir(parents=True, exist_ok=True)
        created.append(target)

    for filename in STANDARD_FILES:
        target = project_root / filename
        if target.exists() and filename in _NON_OVERWRITABLE:
            continue  # never clobber an existing contract/README/manifest
        if filename == "simulation_contract.yaml":
            shutil.copyfile(contract_template(), target)
        elif filename == "manifest.json":
            target.write_text(_manifest_skeleton(), encoding="utf-8")
        elif filename == "README.md":
            target.write_text(
                _readme_template(name or project_root.name), encoding="utf-8"
            )
        else:  # pragma: no cover - defensive
            continue
        created.append(target)

    # Keep empty directories visible in git.
    for directory in STANDARD_DIRECTORIES:
        keep = project_root / directory / ".gitkeep"
        if not keep.exists():
            keep.write_text("", encoding="utf-8")

    return created


def describe_layout(project_root: Path) -> list[str]:
    """Return the expected layout as a flat path list (for tests/reporting)."""
    return [str(project_root / item) for item in STANDARD_DIRECTORIES] + [
        str(project_root / item) for item in STANDARD_FILES
    ]