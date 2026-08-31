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
import math
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
    model = properties.get("model")
    if model == "measured_complex":
        # A measured complex permittivity implies a data source provides the
        # frequency-dependent values; no scalar eps_r is required.
        return True
    if model in {"debye", "lorentz", "drude"}:
        return any(properties.get(field) is not None for field in ("eps_inf", "eps_s"))
    return False


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


# ---------------------------------------------------------------------------
# similar-material suggestion (M10 innovation: "you may also need")
# ---------------------------------------------------------------------------

def _eps_scalar(properties: Mapping[str, Any]) -> float | None:
    """Return a single permittivity figure for ranking (eps_r or eps_inf)."""
    if properties.get("eps_r") is not None:
        try:
            return float(properties["eps_r"])
        except (TypeError, ValueError):
            return None
    for field in ("eps_inf", "eps_s"):
        value = properties.get(field)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None


def _sigma_scalar(properties: Mapping[str, Any]) -> float:
    try:
        return float(properties.get("sigma_s_m", 0.0))
    except (TypeError, ValueError):
        return 0.0


def suggest_similar(
    query: str | Mapping[str, Any],
    materials_dir: Path,
    override_dir: Path | None = None,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Return library materials similar to *query*, nearest first.

    ``query`` may be an entry name (resolved from the library) or a properties
    mapping. Similarity uses relative-permittivity distance, log-scaled
    conductivity distance, dispersion-model agreement, and category agreement.
    Results are deterministic (tie-break by name).
    """
    materials_dir = Path(materials_dir)
    query_name: str | None = None
    if isinstance(query, str):
        query_name = query
        path = resolve_entry(query, materials_dir, override_dir=override_dir)
        if path is None:
            raise MaterialError(f"material {query!r} not found in library")
        query_entry = load_material(path)
        query_props = query_entry.get("properties", {})
    elif isinstance(query, Mapping):
        query_entry = None
        query_props = dict(query.get("properties", query))
    else:
        raise MaterialError("query must be a material name or a properties mapping")

    q_eps = _eps_scalar(query_props)
    q_sigma = _sigma_scalar(query_props)
    q_model = query_props.get("model", "none")

    # Collect every library + override entry once.
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for directory in ([Path(override_dir)] if override_dir is not None else []) + [materials_dir]:
        for path in sorted(directory.rglob("*.yaml")):
            try:
                entry = load_material(path)
            except MaterialError:
                continue
            if entry["name"] in seen or entry["name"] == query_name:
                continue
            seen.add(entry["name"])
            entries.append(entry)

    scored: list[tuple[float, str, dict[str, Any]]] = []
    for entry in entries:
        props = entry.get("properties", {})
        c_eps = _eps_scalar(props)
        c_sigma = _sigma_scalar(props)
        c_model = props.get("model", "none")

        eps_dist = 0.0
        if q_eps is not None and c_eps is not None and c_eps > 0:
            eps_dist = abs(q_eps - c_eps) / max(q_eps, 1e-9)
        elif q_eps is not None and c_eps is None:
            eps_dist = 1.0  # incomparable permittivity is a strong mismatch

        # Conductivity spans decades -> compare on log10 scale.
        if q_sigma > 0 and c_sigma > 0:
            sigma_dist = abs(math.log10(q_sigma) - math.log10(c_sigma))
        elif q_sigma == c_sigma:
            sigma_dist = 0.0
        else:
            sigma_dist = 2.0  # zero vs non-zero conductivity

        model_bonus = 1.0 if c_model == q_model else 0.0
        category_bonus = 1.0 if entry.get("category") == (query_entry or {}).get("category") else 0.0

        # Lower distance is better; higher bonuses are better.
        distance = 0.6 * eps_dist + 0.4 * sigma_dist - 0.15 * model_bonus - 0.1 * category_bonus
        scored.append((distance, entry["name"], entry))

    scored.sort(key=lambda item: (item[0], item[1]))
    return [
        {
            "name": entry["name"],
            "category": entry.get("category"),
            "distance": round(distance, 4),
            "eps": _eps_scalar(entry.get("properties", {})),
            "sigma_s_m": _sigma_scalar(entry.get("properties", {})),
            "model": entry.get("properties", {}).get("model", "none"),
            "source": (entry.get("source", {}) or {}).get("ref", ""),
            "confidence": entry.get("confidence", 3),
        }
        for distance, _, entry in scored[:top_k]
    ]