import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from scripts.core import GateContext, GateState
from scripts.audit_environment import audit_environment, collect_environment


_LEGACY_STATIC_DECK_PROFILE = {
    "profile_id": "gprmax-legacy-static-deck-v1",
    "source_archive_sha256": (
        "b98b4ee28f56a993506c51ac1acdb831657fcb1809e1efe6f6c6cd7eb627f75e"
    ),
    "source_tree_label": "gprMax-v.3.1.7",
    "internal_version": "3.1.6",
    "codename": "Big Smoke",
}


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


def test_reviewed_static_deck_profile_is_validated_and_preserved(tmp_path: Path):
    """Catches environment collection discarding the source identity precision needs."""
    log = tmp_path / "logs" / "runtime.json"
    log.parent.mkdir()
    manifest = {
        "gprmax_version": "3.1.6",
        "banner": "gprMax 3.1.6 (Big Smoke)",
        "import_path": "/opt/gprMax/gprMax/__init__.py",
        "backend": "cpu",
        "real_dtype": "float32",
        "complex_dtype": "complex64",
        "static_deck_profile": dict(_LEGACY_STATIC_DECK_PROFILE),
    }
    log.write_text(json.dumps(manifest), encoding="utf-8")
    ctx = GateContext(tmp_path, {"runtime": {"manifest": "logs/runtime.json"}})

    result = audit_environment(ctx)

    assert result.state is GateState.PASS
    assert ctx.artifacts["environment"] == manifest


@pytest.mark.parametrize(
    "mutation",
    [
        "not_an_object",
        "missing_field",
        "extra_field",
        "boolean_field",
        "version_disagreement",
    ],
)
def test_declared_static_deck_profile_structurally_validated(
    tmp_path: Path, mutation: str
):
    """Profile structure and version consistency are enforced; the specific
    values (archive hash, codename, etc.) are not locked to a legacy build —
    the generic skill accepts any well-formed profile."""
    manifest = {
        "gprmax_version": "3.1.6",
        "banner": "gprMax 3.1.6 (Big Smoke)",
        "import_path": "/opt/gprMax/gprMax/__init__.py",
        "backend": "cpu",
        "real_dtype": "float32",
        "complex_dtype": "complex64",
        "static_deck_profile": dict(_LEGACY_STATIC_DECK_PROFILE),
    }
    profile = manifest["static_deck_profile"]
    if mutation == "not_an_object":
        manifest["static_deck_profile"] = "gprmax-legacy-static-deck-v1"
    elif mutation == "missing_field":
        profile.pop("codename")
    elif mutation == "extra_field":
        profile["unreviewed_source"] = "accepted"
    elif mutation == "boolean_field":
        profile["internal_version"] = True
    elif mutation == "version_disagreement":
        manifest["gprmax_version"] = "3.1.7"
    log = tmp_path / "logs" / "runtime.json"
    log.parent.mkdir()
    log.write_text(json.dumps(manifest), encoding="utf-8")
    ctx = GateContext(tmp_path, {"runtime": {"manifest": "logs/runtime.json"}})

    result = audit_environment(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_ENVIRONMENT_UNRESOLVED"
    assert "environment" not in ctx.artifacts


def test_static_deck_profile_accepts_custom_build_values(tmp_path: Path):
    """A well-formed profile for a different (non-legacy) build is accepted."""
    manifest = {
        "gprmax_version": "3.2.0",
        "banner": "gprMax 3.2.0",
        "import_path": "/opt/gprMax/gprMax/__init__.py",
        "backend": "cpu",
        "real_dtype": "float32",
        "complex_dtype": "complex64",
        "static_deck_profile": {
            "profile_id": "gprmax-project-deck-v1",
            "source_archive_sha256": "0" * 64,
            "source_tree_label": "gprMax-v.3.2.0",
            "internal_version": "3.2.0",
            "codename": "Custom Build",
        },
    }
    log = tmp_path / "logs" / "runtime.json"
    log.parent.mkdir()
    log.write_text(json.dumps(manifest), encoding="utf-8")
    ctx = GateContext(tmp_path, {"runtime": {"manifest": "logs/runtime.json"}})

    result = audit_environment(ctx)

    assert result.state is GateState.PASS
    assert ctx.artifacts["environment"] == manifest


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
        "input_root": "inputs",
        "primary_input": "inputs/model.in",
        "environment": {
            "gprmax_version": "3.1.7",
            "banner": "gprMax 3.1.7",
            "import_path": "/opt/gprMax/gprMax/__init__.py",
            "backend": "cpu",
            "real_dtype": "float64",
            "complex_dtype": "complex128",
        },
        "command": ["python", "-m", "gprMax", "inputs/model.in"],
        "inputs": {"inputs/model.in": "a" * 64},
        "inputs_sha256": "b" * 64,
        "numerics": {},
        "outputs": {
            "hdf5": "runs/run-1.h5",
            "receiver_dataset": "/rxs/rx1/Ez",
            "receiver_dataset_sha256": "c" * 64,
        },
        "started_at": "2026-08-09T00:00:00Z",
        "finished_at": "2026-08-09T00:00:01Z",
        "return_code": 0,
    }
    manifest["environment"][field] = " \t "

    errors = list(Draft202012Validator(schema).iter_errors(manifest))

    assert errors
    assert list(errors[0].path) == ["environment", field]


@pytest.mark.parametrize(
    "mutation",
    [
        "not_an_object",
        "missing_field",
        "extra_field",
        "boolean_field",
    ],
)
def test_run_manifest_schema_rejects_malformed_static_deck_profile(
    mutation: str,
):
    """Schema rejects structurally malformed profiles. Specific profile values
    (archive hash, version, codename) are NOT locked: a generic skill accepts
    any well-formed build profile; version consistency is an audit-layer
    concern, not a schema const."""
    schema = json.loads(
        Path("schemas/run_manifest.schema.json").read_text(encoding="utf-8")
    )
    manifest = {
        "run_id": "run-1",
        "input_root": "inputs",
        "primary_input": "inputs/model.in",
        "environment": {
            "gprmax_version": "3.1.6",
            "banner": "gprMax 3.1.6 (Big Smoke)",
            "import_path": "/opt/gprMax/gprMax/__init__.py",
            "backend": "cpu",
            "real_dtype": "float64",
            "complex_dtype": "complex128",
            "static_deck_profile": dict(_LEGACY_STATIC_DECK_PROFILE),
        },
        "command": ["python", "-m", "gprMax", "inputs/model.in"],
        "inputs": {"inputs/model.in": "a" * 64},
        "inputs_sha256": "b" * 64,
        "numerics": {},
        "outputs": {
            "hdf5": "runs/run-1.h5",
            "receiver_dataset": "/rxs/rx1/Ez",
            "receiver_dataset_sha256": "c" * 64,
        },
        "started_at": "2026-08-09T00:00:00Z",
        "finished_at": "2026-08-09T00:00:01Z",
        "return_code": 0,
    }
    validator = Draft202012Validator(schema)
    assert validator.is_valid(manifest)
    generic_manifest = json.loads(json.dumps(manifest))
    generic_manifest["environment"].pop("static_deck_profile")
    generic_manifest["environment"]["gprmax_version"] = "3.1.7"
    assert validator.is_valid(generic_manifest)
    profile = manifest["environment"]["static_deck_profile"]
    if mutation == "not_an_object":
        manifest["environment"]["static_deck_profile"] = "legacy-v1"
    elif mutation == "missing_field":
        profile.pop("codename")
    elif mutation == "extra_field":
        profile["unreviewed_source"] = "accepted"
    elif mutation == "boolean_field":
        profile["internal_version"] = True

    errors = list(validator.iter_errors(manifest))

    assert errors
