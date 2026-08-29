"""Material library: YAML entries with a JSON index.

Entries live as YAML files in a `materials/` directory; a JSON index makes
lookups fast. A project-local `materials_override/` directory may shadow
library entries. Only entries carrying a provenance trail are treated as
frozen references; everything else is a draft.

Entry schema (see references/simulation-contract.md):

    name: 砂岩（干燥）
    category: rock
    properties: {eps_r, sigma_s_m, model, eps_inf, delta_eps, tau_s}
    frequency_valid: [lo_mhz, hi_mhz]   # optional
    condition: null                      # moisture / porosity etc (optional)
    source: {kind, ref, url}             # kind in measured/literature/assumed/sensitivity
    confidence: 1-5                      # optional, default 3
    notes: null
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import yaml

CATEGORIES = {
    "rock",
    "soil",
    "concrete",
    "metal",
    "water",
    "void",
    "composite",
    "other",
}
SOURCE_KINDS = {"measured", "literature", "assumed", "sensitivity"}


class MaterialError(ValueError):
    """Invalid material entry or library layout."""


def validate_entry(value: Mapping[str, Any], path: str = "<entry>") -> dict[str, Any]:
    """Validate and normalise a material entry mapping."""
    if not isinstance(value, Mapping):
        raise MaterialError(f"{path}: material entry must be a mapping")

    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        raise MaterialError(f"{path}: 'name' is required and must be non-empty")
    entry = dict(value)
    entry["name"] = name.strip()

    category = entry.get("category")
    if category not in CATEGORIES:
        raise MaterialError(
            f"{path}: 'category' must be one of {sorted(CATEGORIES)}, got {category!r}"
        )

    properties = entry.get("properties")
    if not isinstance(properties, Mapping) or not properties:
        raise MaterialError(f"{path}: 'properties' is required and must be a mapping")
    if not _has_permittivity(properties):
        raise MaterialError(
            f"{path}: 'properties' must carry a permittivity (eps_r, or a "
            "dispersion model with its parameters)"
        )

    source = entry.get("source")
    if not isinstance(source, Mapping):
        raise MaterialError(f"{path}: 'source' is required and must be a mapping")
    kind = source.get("kind")
    if kind not in SOURCE_KINDS:
        raise MaterialError(
            f"{path}: source.kind must be one of {sorted(SOURCE_KINDS)}, got {kind!r}"
        )
    ref = source.get("ref")
    if not isinstance(ref, str) or not ref.strip():
        raise MaterialError(f"{path}: source.ref must be non-empty text")

    confidence = entry.get("confidence", 3)
    if not isinstance(confidence, int) or not 1 <= confidence <= 5:
        raise MaterialError(f"{path}: 'confidence' must be an integer 1-5")

    model = properties.get("model", "none")
    if model not in {"none", "debye", "lorentz", "drude", "measured_complex"}:
        raise MaterialError(f"{path}: properties.model={model!r} is not supported")

    entry["properties"] = dict(properties)
    entry["source"] = dict(source)
    entry["confidence"] = confidence
    return entry


def _has_permittivity(properties: Mapping[str, Any]) -> bool:
    if "eps_r" in properties:
        return True
    if properties.get("model") in {"debye", "lorentz", "drude"}:
        return any(properties.get(field) is not None for field in ("eps_inf", "eps_s"))
    return False


def _category_of(path: Path) -> str:
    # Infer category from the library subdirectory: materials/<category>/x.yaml
    parts = path.parts
    if len(parts) >= 2 and parts[-2] != "materials":
        return parts[-2]
    return "other"


def load_material(path: Path) -> dict[str, Any]:
    """Load and validate a material entry from a YAML file."""
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        raise MaterialError(f"{path}: unreadable YAML ({error})") from error
    return validate_entry(value, str(path))


def build_index(materials_dir: Path) -> dict[str, dict[str, str]]:
    """Scan a materials directory tree and build {name: {path, category}}.

    YAML files are validated; invalid entries are skipped and their names are
    collected under an `_invalid` key so the caller can surface them.
    """
    materials_dir = Path(materials_dir)
    index: dict[str, dict[str, str]] = {}
    invalid: list[str] = []
    if not materials_dir.is_dir():
        return index
    for path in sorted(materials_dir.rglob("*.yaml")):
        try:
            entry = load_material(path)
        except MaterialError:
            invalid.append(str(path))
            continue
        index[entry["name"]] = {
            "path": str(path.relative_to(materials_dir)),
            "category": entry["category"],
        }
    if invalid:
        index["_invalid"] = {"paths": "; ".join(invalid)}
    return index


def write_index(index: Mapping[str, Any], target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(index, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def resolve_entry(
    name: str, materials_dir: Path, override_dir: Path | None = None
) -> Path | None:
    """Resolve an entry by name, preferring the override directory."""
    candidates: list[Path] = []
    if override_dir is not None:
        candidates.extend(Path(override_dir).rglob("*.yaml"))
    candidates.extend(Path(materials_dir).rglob("*.yaml"))
    for path in candidates:
        try:
            entry = load_material(path)
        except MaterialError:
            continue
        if entry["name"] == name:
            return path
    return None


def list_entries(materials_dir: Path, override_dir: Path | None = None) -> list[str]:
    index = build_index(materials_dir)
    names = sorted(
        name for name in index if name != "_invalid"
    )
    if override_dir is not None and Path(override_dir).is_dir():
        for path in sorted(Path(override_dir).rglob("*.yaml")):
            try:
                entry = load_material(path)
            except MaterialError:
                continue
            if entry["name"] not in names:
                names.append(entry["name"])
    return sorted(names)