import json
from pathlib import Path

import pytest

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
