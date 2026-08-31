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

import hashlib
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


# ---------------------------------------------------------------------------
# layout discipline audit
# ---------------------------------------------------------------------------

# File suffixes that are *never* allowed inside outputs/ (raw evidence must
# stay read-only; input/executable material there indicates a write-back).
_OUTPUTS_FORBIDDEN_SUFFIXES = (".py", ".in", ".sh", ".bat")

# Suffixes treated as raw simulation evidence for hashing.
_OUTPUTS_EVIDENCE_SUFFIXES = (".out", ".h5", ".hdf5")


def sha256_file(path: Path) -> str:
    """Streaming SHA-256 of a file's full content."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def output_hashes(study_root: Path) -> dict[str, str]:
    """Map every evidence file in ``outputs/`` to its SHA-256 (relative name)."""
    study_root = Path(study_root)
    outputs = study_root / "outputs"
    if not outputs.is_dir():
        return {}
    hashes: dict[str, str] = {}
    for path in sorted(outputs.rglob("*")):
        if path.is_file() and path.suffix.lower() in _OUTPUTS_EVIDENCE_SUFFIXES:
            hashes[path.name] = sha256_file(path)
    return hashes


def record_output_hashes(study_root: Path) -> Path:
    """Record SHA-256 of every evidence file under ``outputs/`` into manifest.

    Writes ``manifest.json["outputs_sha256"] = {name: sha256, ...}``. Returns
    the manifest path. Missing manifest raises ``ScaffoldError`` (fail-closed:
    hashes without a manifest cannot be audited later).
    """
    study_root = Path(study_root)
    manifest_path = study_root / "manifest.json"
    if not manifest_path.is_file():
        raise ScaffoldError(
            f"{study_root} has no manifest.json — create the study skeleton first"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ScaffoldError(f"{manifest_path} is unreadable JSON ({error})") from error
    if not isinstance(manifest, dict):
        raise ScaffoldError(f"{manifest_path} must contain a JSON object")

    hashes = output_hashes(study_root)
    manifest["outputs_sha256"] = hashes
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def audit_layout(study_root: Path) -> list[dict[str, str]]:
    """Audit a study directory against the standard layout discipline.

    Returns a list of findings, each ``{"check", "severity", "message"}``
    with severity in ``OK | WARN | BLOCK``:

    - standard directories and files exist (missing directory -> BLOCK,
      missing non-optional file -> BLOCK)
    - ``outputs/`` is non-empty and contains no input/executable material
      (raw-evidence read-only discipline; a forbidden file -> BLOCK)
    - the study directory name matches the study_id convention (-> WARN)
    - no stray ``.py``/``.in`` files directly under the study root
      (-> WARN; study-level orchestration scripts belong in ``scripts/``)
    - ``simulation_contract.yaml`` exists and parses (unparseable -> BLOCK)
    """
    study_root = Path(study_root)
    findings: list[dict[str, str]] = []

    def add(check: str, severity: str, message: str) -> None:
        findings.append({"check": check, "severity": severity, "message": message})

    # 1. Standard directory layout.
    missing_dirs = [
        name for name in STANDARD_DIRECTORIES if not (study_root / name).is_dir()
    ]
    if missing_dirs:
        add(
            "layout",
            "BLOCK",
            f"missing standard directories: {', '.join(missing_dirs)}",
        )
    else:
        add("layout", "OK", "standard directories present")

    missing_files = [
        name for name in STANDARD_FILES if not (study_root / name).is_file()
    ]
    if missing_files:
        add(
            "files",
            "BLOCK",
            f"missing standard files: {', '.join(missing_files)}",
        )
    else:
        add("files", "OK", "standard files present")

    # 2. outputs/ read-only discipline.
    outputs = study_root / "outputs"
    if outputs.is_dir():
        entries = [p for p in outputs.iterdir() if p.is_file()]
        if not entries:
            add("outputs", "WARN", "outputs/ is empty (no raw evidence yet)")
        else:
            add("outputs", "OK", f"outputs/ holds {len(entries)} raw file(s)")
        forbidden = [
            p.name
            for p in outputs.rglob("*")
            if p.is_file() and p.suffix.lower() in _OUTPUTS_FORBIDDEN_SUFFIXES
        ]
        if forbidden:
            add(
                "outputs",
                "BLOCK",
                "outputs/ must stay read-only raw evidence; found input/executable "
                f"material: {', '.join(forbidden[:5])}",
            )
    else:
        add("outputs", "BLOCK", "outputs/ directory missing")

    # 3. outputs/ hash integrity (raw-evidence immutability).
    manifest_path = study_root / "manifest.json"
    evidence = output_hashes(study_root)
    recorded: dict[str, str] = {}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(manifest, dict) and isinstance(
                manifest.get("outputs_sha256"), dict
            ):
                recorded = {
                    str(k): str(v)
                    for k, v in manifest["outputs_sha256"].items()
                    if isinstance(v, str)
                }
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            recorded = {}  # unreadable manifest: nothing to compare against
    if evidence:
        missing = sorted(set(evidence) - set(recorded))
        mismatched = sorted(
            name for name in evidence if name in recorded and recorded[name] != evidence[name]
        )
        if missing or mismatched:
            parts = []
            if missing:
                parts.append(f"unrecorded evidence: {', '.join(missing[:5])}")
            if mismatched:
                parts.append(f"hash mismatch (evidence modified): {', '.join(mismatched[:5])}")
            add(
                "outputs_hashes",
                "BLOCK",
                "; ".join(parts) + " — run `layout hash` after a legitimate regeneration",
            )
        else:
            add(
                "outputs_hashes",
                "OK",
                f"{len(evidence)} evidence file(s) match manifest SHA-256",
            )
    else:
        add("outputs_hashes", "WARN", "no raw evidence in outputs/ to hash")

    # 4. Study name convention (WARN — the name is a strong convention).
    try:
        validate_study_name(study_root.name)
        add("naming", "OK", f"study name {study_root.name!r} matches <nn>_<yyyymmdd>_<TOPIC>")
    except ScaffoldError as error:
        add("naming", "WARN", str(error))

    # 5. Stray study-root material.
    stray = [
        p.name
        for p in study_root.iterdir()
        if p.is_file()
        and p.name not in STANDARD_FILES
        and p.suffix.lower() in (".py", ".in")
    ]
    if stray:
        add(
            "stray",
            "WARN",
            "scripts/input files directly under study root (belong in "
            f"scripts/ or cases/): {', '.join(stray[:5])}",
        )
    else:
        add("stray", "OK", "no stray scripts/inputs at study root")

    # 6. Contract parseability.
    contract = study_root / "simulation_contract.yaml"
    if contract.is_file():
        try:
            import yaml

            value = yaml.safe_load(contract.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                add("contract", "BLOCK", "simulation_contract.yaml must be a mapping")
            else:
                add("contract", "OK", "simulation_contract.yaml parses")
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
            add("contract", "BLOCK", f"simulation_contract.yaml unreadable ({error})")
    else:
        add("contract", "BLOCK", "simulation_contract.yaml missing")

    return findings