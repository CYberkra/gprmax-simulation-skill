import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from scripts.core import GateContext, GateState
from scripts.audit_environment import audit_environment, collect_environment


def test_missing_runtime_identity_blocks(tmp_path: Path):
    """Catches a gate that accepts an undeclared runtime manifest."""
    ctx = GateContext(tmp_path, {"runtime": {}})

    result = audit_environment(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_ENVIRONMENT_UNRESOLVED"
    assert "environment" not in ctx.artifacts


def test_banner_import_path_and_precision_are_recorded(tmp_path: Path):
    """Catches a gate that passes without recording actual runtime precision."""
    log = tmp_path / "logs" / "runtime.json"
    log.parent.mkdir()
    log.write_text(
        json.dumps(
            {
                "gprmax_version": "3.1.7",
                "banner": "gprMax 3.1.7",
                "import_path": "/opt/gprMax/gprMax/__init__.py",
                "backend": "gpu",
                "real_dtype": "float64",
                "complex_dtype": "complex128",
                "python_version": "3.11.9",
            }
        ),
        encoding="utf-8",
    )
    ctx = GateContext(tmp_path, {"runtime": {"manifest": "logs/runtime.json"}})

    result = audit_environment(ctx)

    assert result.state is GateState.PASS
    assert result.code == "PASS_ENVIRONMENT_LOCKED"
    assert ctx.artifacts["environment"] == {
        "gprmax_version": "3.1.7",
        "banner": "gprMax 3.1.7",
        "import_path": "/opt/gprMax/gprMax/__init__.py",
        "backend": "gpu",
        "real_dtype": "float64",
        "complex_dtype": "complex128",
        "python_version": "3.11.9",
    }


@pytest.mark.parametrize("field", ["gprmax_version", "banner", "import_path", "backend", "real_dtype", "complex_dtype"])
def test_missing_required_manifest_field_blocks_without_recording_artifact(tmp_path: Path, field: str):
    """Catches acceptance of a runtime identity with one unverifiable required field."""
    manifest = {
        "gprmax_version": "3.1.7",
        "banner": "gprMax 3.1.7",
        "import_path": "/opt/gprMax/gprMax/__init__.py",
        "backend": "cpu",
        "real_dtype": "float64",
        "complex_dtype": "complex128",
    }
    manifest[field] = ""
    log = tmp_path / "logs" / "runtime.json"
    log.parent.mkdir()
    log.write_text(json.dumps(manifest), encoding="utf-8")
    ctx = GateContext(tmp_path, {"runtime": {"manifest": "logs/runtime.json"}})

    with pytest.raises(ValueError):
        collect_environment(ctx)

    result = audit_environment(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_ENVIRONMENT_UNRESOLVED"
    assert "environment" not in ctx.artifacts


def test_runtime_manifest_resolution_error_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Catches a symlink-resolution RuntimeError that escapes the fail-closed gate."""
    ctx = GateContext(tmp_path, {"runtime": {"manifest": "logs/runtime.json"}})

    def raise_symlink_loop(*_args, **_kwargs):
        raise RuntimeError("symlink loop")

    # A real symlink loop is not portable on Windows without elevated symlink privileges.
    monkeypatch.setattr("scripts.audit_environment.Path.resolve", raise_symlink_loop)

    result = audit_environment(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_ENVIRONMENT_UNRESOLVED"


def test_runtime_manifest_outside_logs_blocks(tmp_path: Path):
    """Catches a declared manifest path that escapes the allowed log evidence directory."""
    outside_manifest = tmp_path / "runtime.json"
    outside_manifest.write_text("{}", encoding="utf-8")
    ctx = GateContext(tmp_path, {"runtime": {"manifest": "runtime.json"}})

    result = audit_environment(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_ENVIRONMENT_UNRESOLVED"


@pytest.mark.parametrize("content", ["{", "[]", "null"])
def test_malformed_or_non_object_runtime_manifest_blocks(tmp_path: Path, content: str):
    """Catches malformed JSON and JSON values that cannot represent a runtime manifest."""
    log = tmp_path / "logs" / "runtime.json"
    log.parent.mkdir()
    log.write_text(content, encoding="utf-8")
    ctx = GateContext(tmp_path, {"runtime": {"manifest": "logs/runtime.json"}})

    result = audit_environment(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_ENVIRONMENT_UNRESOLVED"
    assert "environment" not in ctx.artifacts


@pytest.mark.parametrize("field", ["gprmax_version", "banner", "import_path", "backend", "real_dtype", "complex_dtype"])
def test_run_manifest_schema_rejects_whitespace_required_environment_identity(field: str):
    """Catches schema validation that accepts identity values erased to whitespace."""
    schema = json.loads(Path("schemas/run_manifest.schema.json").read_text(encoding="utf-8"))
    manifest = {
        "run_id": "run-1",
        "environment": {
            "gprmax_version": "3.1.7",
            "banner": "gprMax 3.1.7",
            "import_path": "/opt/gprMax/gprMax/__init__.py",
            "backend": "cpu",
            "real_dtype": "float64",
            "complex_dtype": "complex128",
        },
        "command": ["python", "-m", "gprMax"],
        "inputs": {},
        "numerics": {},
        "outputs": {},
        "started_at": "2026-08-09T00:00:00Z",
        "finished_at": "2026-08-09T00:00:01Z",
        "return_code": 0,
    }
    manifest["environment"][field] = " \t "

    errors = list(Draft202012Validator(schema).iter_errors(manifest))

    assert errors
    assert list(errors[0].path) == ["environment", field]
