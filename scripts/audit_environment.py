from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from scripts.core import GateContext, GateResult, GateState


_REQUIRED_FIELDS = (
    "gprmax_version",
    "banner",
    "import_path",
    "backend",
    "real_dtype",
    "complex_dtype",
)
_OPTIONAL_FIELDS = ("python_version", "cuda_version", "gpu", "driver_version")


class EnvironmentResolutionError(ValueError):
    """The declared runtime manifest cannot establish a complete identity."""


def collect_environment(ctx: GateContext) -> dict[str, Any]:
    """Resolve and normalize the runtime identity declared by the contract."""
    runtime = ctx.contract.get("runtime")
    if not isinstance(runtime, Mapping):
        raise EnvironmentResolutionError("runtime configuration must be a mapping")
    manifest_ref = runtime.get("manifest")
    if not isinstance(manifest_ref, str) or not manifest_ref.strip():
        raise EnvironmentResolutionError("runtime.manifest must be a non-empty path")

    manifest_path = _resolve_manifest_path(ctx.project_root, manifest_ref)
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EnvironmentResolutionError("runtime manifest is unreadable JSON") from error
    if not isinstance(value, Mapping):
        raise EnvironmentResolutionError("runtime manifest must be a JSON object")

    environment = {field: _required_text(value, field) for field in _REQUIRED_FIELDS}
    for field in _OPTIONAL_FIELDS:
        optional_value = value.get(field)
        if optional_value is not None:
            environment[field] = _optional_text(optional_value, field)

    ctx.artifacts["environment"] = environment
    return environment


def audit_environment(ctx: GateContext) -> GateResult:
    """Fail closed unless the runtime identity comes from a complete declared manifest."""
    try:
        collect_environment(ctx)
    except EnvironmentResolutionError as error:
        ctx.artifacts.pop("environment", None)
        return GateResult(
            "environment",
            GateState.BLOCK,
            "BLOCK_ENVIRONMENT_UNRESOLVED",
            str(error),
        )

    manifest_ref = str(ctx.contract["runtime"]["manifest"]).strip()
    return GateResult(
        "environment",
        GateState.PASS,
        "PASS_ENVIRONMENT_LOCKED",
        "runtime identity resolved from declared manifest",
        evidence=(manifest_ref,),
        invalidates=("numerics",),
    )


def _resolve_manifest_path(project_root: Path, manifest_ref: str) -> Path:
    path = Path(manifest_ref.strip())
    if not path.is_absolute():
        path = project_root / path
    try:
        resolved = path.resolve(strict=True)
        logs_root = (project_root / "logs").resolve(strict=False)
        resolved.relative_to(logs_root)
    except (OSError, RuntimeError, ValueError) as error:
        raise EnvironmentResolutionError("runtime.manifest must resolve under logs/") from error
    return resolved


def _required_text(value: Mapping[str, Any], field: str) -> str:
    if field not in value:
        raise EnvironmentResolutionError(f"runtime manifest missing {field}")
    return _optional_text(value[field], field)


def _optional_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not (normalized := value.strip()):
        raise EnvironmentResolutionError(f"runtime manifest field {field} must be non-empty text")
    return normalized
