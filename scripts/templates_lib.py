"""Scene template library for the guided setup.

A scene template captures a *verified* typical scenario — frozen medium,
target, antenna, grid, waveform, link, and band — so that a matching study
does not re-derive them from scratch. Only templates marked ``verified`` may
be consulted, and only under a **strict** match: the study's scenario
signature must equal the template's match signature on every key. If a study
does not match a verified template, it gets no template reference at all —
never a partial or nearest match (that would drag a wrong scenario's frozen
values into an unrelated study).

Progressive accumulation: a completed and validated study may be proposed as
a ``draft`` template, which becomes ``verified`` only after user confirmation
with the validating packages recorded. ``extract_from_study`` automates the
proposal step by reading a study directory (contract + manifest + README)
and producing a draft entry.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

import yaml

SCENARIO_TYPES = {
    "tunnel",
    "landslide",
    "archaeology",
    "geotechnical",
    "inspection",
    "other",
}
STATUSES = {"draft", "verified"}

# Contract files required for automatic extraction (fail-closed).
_EXTRACT_REQUIRED_FILES = ("simulation_contract.yaml", "manifest.json")


class TemplateError(ValueError):
    """Invalid scene template entry or library layout."""


# Template names become filenames; keep them filesystem-safe.
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_\-]+$")


def validate_entry(value: Mapping[str, Any], path: str = "<template>") -> dict[str, Any]:
    """Validate and normalise a scene template entry."""
    if not isinstance(value, Mapping):
        raise TemplateError(f"{path}: template entry must be a mapping")

    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        raise TemplateError(f"{path}: 'name' is required and must be non-empty")
    name = name.strip()
    if not _NAME_PATTERN.match(name):
        raise TemplateError(
            f"{path}: 'name' {name!r} must match {_NAME_PATTERN.pattern} "
            "(letters, digits, '_', '-') — it becomes a filename"
        )
    entry = dict(value)
    entry["name"] = name

    scenario = entry.get("scenario")
    if not isinstance(scenario, str) or not scenario.strip():
        raise TemplateError(f"{path}: 'scenario' is required")
    entry["scenario"] = scenario.strip()

    status = entry.get("status", "draft")
    if status not in STATUSES:
        raise TemplateError(f"{path}: status must be one of {sorted(STATUSES)}")
    entry["status"] = status

    verified_by = entry.get("verified_by", [])
    if not isinstance(verified_by, list) or not all(
        isinstance(item, str) and item.strip() for item in verified_by
    ):
        raise TemplateError(
            f"{path}: 'verified_by' must be a list of non-empty strings"
        )
    if status == "verified" and not verified_by:
        raise TemplateError(
            f"{path}: a verified template must record verified_by packages"
        )
    entry["verified_by"] = [item.strip() for item in verified_by]

    match = entry.get("match")
    if not isinstance(match, Mapping) or not isinstance(match.get("scenario_type"), str):
        raise TemplateError(
            f"{path}: 'match.scenario_type' is required (strict-match key)"
        )
    if not match["scenario_type"].strip():
        raise TemplateError(f"{path}: 'match.scenario_type' must be non-empty")
    needs_sfcw = match.get("needs_sfcw")
    if not isinstance(needs_sfcw, bool):
        raise TemplateError(f"{path}: 'match.needs_sfcw' must be a boolean")
    depth_range = match.get("depth_range_m")
    if depth_range is not None:
        if not (
            isinstance(depth_range, (list, tuple))
            and len(depth_range) == 2
            and all(isinstance(v, (int, float)) for v in depth_range)
            and 0 <= depth_range[0] <= depth_range[1]
        ):
            raise TemplateError(
                f"{path}: 'match.depth_range_m' must be [lo, hi] with 0 <= lo <= hi"
            )
    geometry_type = match.get("geometry_type")
    if geometry_type is not None and geometry_type not in ("regular", "irregular"):
        raise TemplateError(
            f"{path}: 'match.geometry_type' must be 'regular' or 'irregular'"
        )
    entry["match"] = {
        "scenario_type": match["scenario_type"],
        "needs_sfcw": needs_sfcw,
        "depth_range_m": tuple(depth_range) if depth_range is not None else None,
        "geometry_type": geometry_type,
    }

    if "frozen_parameters" not in entry or not isinstance(
        entry.get("frozen_parameters"), Mapping
    ):
        raise TemplateError(f"{path}: 'frozen_parameters' is required")
    entry["frozen_parameters"] = dict(entry["frozen_parameters"])
    return entry


def load_template(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        raise TemplateError(f"{path}: unreadable YAML ({error})") from error
    return validate_entry(value, str(path))


def build_index(scenarios_dir: Path) -> dict[str, dict[str, str]]:
    """Scan a scenarios directory and build {name: {path, status, scenario}}."""
    scenarios_dir = Path(scenarios_dir)
    index: dict[str, dict[str, str]] = {}
    if not scenarios_dir.is_dir():
        return index
    for path in sorted(scenarios_dir.rglob("*.yaml")):
        try:
            entry = load_template(path)
        except TemplateError:
            continue
        index[entry["name"]] = {
            "path": str(path.relative_to(scenarios_dir)),
            "status": entry["status"],
            "scenario": entry["scenario"],
        }
    return index


def match_scenario(
    signature: Mapping[str, Any], scenarios_dir: Path
) -> dict[str, Any] | None:
    """Strict-match a study signature against *verified* templates only.

    Collects all templates that strictly match the required keys
    (``scenario_type``, ``needs_sfcw``) and any optional constraints
    (``depth_range_m``, ``geometry_type``) that the signature also provides.
    If a template declares an optional constraint that the signature does
    *not* provide, the template is skipped (fail-closed — the constraint
    cannot be verified). Among the remaining templates, the one with the
    most satisfied optional constraints (most specific) is returned; ties
    are broken by template name (stable).

    Unverified (draft) templates are never consulted.
    """
    scenario_type = signature.get("scenario_type")
    if not isinstance(scenario_type, str):
        raise TemplateError("signature.scenario_type is required")
    needs_sfcw = signature.get("needs_sfcw")
    if not isinstance(needs_sfcw, bool):
        raise TemplateError("signature.needs_sfcw is required")

    index = build_index(scenarios_dir)
    candidates: list[tuple[int, str, dict[str, Any]]] = []  # (specificity, name, entry)

    for name, meta in index.items():
        if meta["status"] != "verified":
            continue
        entry = load_template(scenarios_dir / meta["path"])
        match = entry["match"]
        if match["scenario_type"] != scenario_type:
            continue
        if match["needs_sfcw"] != needs_sfcw:
            continue

        specificity = 0
        ok = True

        depth_range = match.get("depth_range_m")
        if depth_range is not None:
            depth = signature.get("target_depth_m")
            if depth is None:
                ok = False  # template constrains depth but study does not say
            else:
                try:
                    depth_float = float(depth)
                except (TypeError, ValueError) as error:
                    raise TemplateError(
                        f"signature.target_depth_m must be numeric, got {depth!r}"
                    ) from error
                if depth_range[0] <= depth_float <= depth_range[1]:
                    specificity += 1
                else:
                    ok = False

        geometry_type = match.get("geometry_type")
        if geometry_type is not None:
            sig_geom = signature.get("geometry_type")
            if sig_geom is None:
                ok = False  # template constrains geometry but study does not say
            elif sig_geom == geometry_type:
                specificity += 1
            else:
                ok = False

        if ok:
            candidates.append((specificity, name, entry))

    if not candidates:
        return None
    # Highest specificity first; tie-break by name (stable).
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][2]


def propose_template(
    entry: Mapping[str, Any], scenarios_dir: Path, force_draft: bool = True
) -> Path:
    """Store a study summary as a template entry (draft unless verified_by set).

    This is the progressive-accumulation entry point: the agent proposes the
    entry after a validated study; ``verify_template`` later promotes it.
    """
    validated = validate_entry(entry)
    if force_draft:
        validated["status"] = "draft"
        validated["verified_by"] = []
    scenarios_dir = Path(scenarios_dir)
    scenarios_dir.mkdir(parents=True, exist_ok=True)
    target = scenarios_dir / f"{validated['name']}.yaml"
    if target.exists():
        existing = load_template(target)
        if existing.get("status") == "verified":
            raise TemplateError(
                f"template {validated['name']!r} already exists and is verified; "
                "refusing to overwrite a verified template — pick a new name"
            )
    target.write_text(
        yaml.safe_dump(validated, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return target


def verify_template(
    name: str, scenarios_dir: Path, verified_by: list[str]
) -> Path:
    """Promote a draft template to verified, recording the validating packages."""
    index = build_index(scenarios_dir)
    if name not in index:
        raise TemplateError(f"template {name!r} not found")
    if not isinstance(verified_by, list) or not verified_by:
        raise TemplateError("verified_by must list at least one validating package")
    path = scenarios_dir / index[name]["path"]
    entry = load_template(path)
    entry["status"] = "verified"
    entry["verified_by"] = list(verified_by)
    path.write_text(
        yaml.safe_dump(entry, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return path


def list_templates(scenarios_dir: Path) -> list[dict[str, str]]:
    index = build_index(scenarios_dir)
    return [
        {"name": name, **meta}
        for name, meta in sorted(index.items())
    ]


def signature_from_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Derive a match signature from a simulation_contract draft."""
    task = contract.get("task", {}) if isinstance(contract.get("task"), Mapping) else {}
    waveform = (
        contract.get("waveform", {})
        if isinstance(contract.get("waveform"), Mapping)
        else {}
    )
    geometry = (
        contract.get("geometry", {})
        if isinstance(contract.get("geometry"), Mapping)
        else {}
    )
    measurement = waveform.get("measurement_mode", "time_domain")
    signature: dict[str, Any] = {
        "scenario_type": task.get("objective", "other"),
        "needs_sfcw": measurement == "sfcw_equivalent",
    }
    depth = contract.get("project", {}).get("target_depth_m") if isinstance(
        contract.get("project"), Mapping
    ) else None
    if depth is not None:
        signature["target_depth_m"] = float(depth)
    target_level = geometry.get("target_level")
    if target_level in ("L1", "L2"):
        signature["geometry_type"] = "regular"
    elif target_level in ("L3", "L4"):
        signature["geometry_type"] = "irregular"
    return signature


# ---------------------------------------------------------------------------
# progressive accumulation from a completed study
# ---------------------------------------------------------------------------

_STUDY_NAME_RE = re.compile(r"[^A-Za-z0-9]+")


def _template_name_from_study(study_root: Path) -> str:
    """Normalise a study directory name into a template name.

    ``01_20260830_SFCW_SLIDE_WET`` -> ``01_20260830_sfcw_slide_wet``; if the
    directory name is generic (``study``, ``my_study``), fall back to the
    README first heading so the template is still identifiable.
    """
    stem = study_root.name.strip()
    candidate = _STUDY_NAME_RE.sub("_", stem).strip("_").lower()
    if len(candidate) < 4 or candidate in {"study", "test", "tmp"}:
        readme = study_root / "README.md"
        if readme.is_file():
            try:
                text = readme.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as error:
                raise TemplateError(
                    f"{readme} is unreadable ({error}) — cannot derive a template name"
                ) from error
            for line in text.splitlines():
                heading = line.strip().lstrip("#").strip()
                if heading:
                    candidate = _STUDY_NAME_RE.sub("_", heading).strip("_").lower()
                    break
    if not candidate:
        raise TemplateError(f"cannot derive a template name from study {study_root}")
    return candidate


def extract_from_study(study_root: Path) -> dict[str, Any]:
    """Build a draft template entry from a completed study directory.

    Reads ``simulation_contract.yaml`` (match signature + frozen parameters)
    and ``manifest.json`` (evidence / verification packages). Missing or
    unparseable contract/manifest raise ``TemplateError`` — extraction is
    fail-closed because a template with wrong frozen values is worse than
    no template at all.

    The returned entry is a draft by default; if the manifest records
    ``verified_by`` / ``packages`` it is returned as ``verified``. Call
    :func:`extract_study_auto` to store it (forces draft unless told
    otherwise), or :func:`verify_template` to promote later once the
    validating packages are confirmed.
    """
    study_root = Path(study_root)
    contract_path = study_root / "simulation_contract.yaml"
    manifest_path = study_root / "manifest.json"
    for filename in _EXTRACT_REQUIRED_FILES:
        if not (study_root / filename).is_file():
            raise TemplateError(
                f"study {study_root} is missing {filename} — cannot extract a "
                "template from incomplete evidence"
            )
    try:
        contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        raise TemplateError(f"{contract_path}: unreadable YAML ({error})") from error
    if not isinstance(contract, Mapping):
        raise TemplateError(f"{contract_path}: contract must be a mapping")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TemplateError(f"{manifest_path}: unreadable JSON ({error})") from error

    signature = signature_from_contract(contract)

    # Frozen parameters: keep the contract's medium/waveform/numerics blocks
    # plus the top-level project block (depth etc.). These are the values a
    # matching study would otherwise re-derive.
    frozen: dict[str, Any] = {}
    for key in ("medium", "waveform", "numerics", "project"):
        value = contract.get(key)
        if isinstance(value, Mapping) and value:
            frozen[key] = dict(value)

    verified_by: list[str] = []
    if isinstance(manifest, Mapping):
        packages = manifest.get("verified_by") or manifest.get("packages") or []
        if isinstance(packages, list):
            verified_by = [str(p) for p in packages if str(p).strip()]
        status = "verified" if verified_by else "draft"
    else:
        status = "draft"

    entry: dict[str, Any] = {
        "name": _template_name_from_study(study_root),
        "scenario": signature["scenario_type"],
        "status": status,
        "verified_by": verified_by,
        "match": {
            "scenario_type": signature["scenario_type"],
            "needs_sfcw": signature["needs_sfcw"],
            "depth_range_m": None,
            "geometry_type": signature.get("geometry_type"),
        },
        "frozen_parameters": frozen,
        "provenance": {
            "study_root": str(study_root),
            "contract": "simulation_contract.yaml",
            "manifest": "manifest.json",
        },
    }
    return validate_entry(entry)


def extract_study_auto(
    study_root: Path, scenarios_dir: Path, *, force_draft: bool = True
) -> Path:
    """Extract a completed study into the template library as a draft.

    This is the progressive-accumulation hook: after a study is validated and
    its results recorded, the agent calls this to propose it as a template
    (draft unless ``force_draft=False`` and the manifest records verified
    packages). A verified template of the same name is never overwritten.
    """
    entry = extract_from_study(study_root)
    if force_draft:
        entry["status"] = "draft"
        entry["verified_by"] = []
    return propose_template(entry, scenarios_dir)