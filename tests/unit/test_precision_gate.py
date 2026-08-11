import hashlib
import json
import os
from pathlib import Path

import h5py
from jsonschema import Draft202012Validator
import numpy as np
import pytest

import scripts.audit_precision as precision_module
from scripts.audit_precision import audit_precision, local_ulp, precision_floor_ratio
from scripts.core import GateContext, GateState


_LEGACY_STATIC_DECK_PROFILE = {
    "profile_id": "gprmax-legacy-static-deck-v1",
    "source_archive_sha256": (
        "b98b4ee28f56a993506c51ac1acdb831657fcb1809e1efe6f6c6cd7eb627f75e"
    ),
    "source_tree_label": "gprMax-v.3.1.7",
    "internal_version": "3.1.6",
    "codename": "Big Smoke",
}


def _write_dataset(path: Path, dataset: str, values: np.ndarray) -> None:
    with h5py.File(path, "w") as handle:
        handle.create_dataset(dataset, data=values)


def _write_external_storage_dataset(
    path: Path, dataset: str, values: np.ndarray, raw_path: Path
) -> None:
    with h5py.File(path, "w") as handle:
        stored = handle.create_dataset(
            dataset,
            shape=values.shape,
            dtype=values.dtype,
            external=[(str(raw_path), 0, values.nbytes)],
        )
        stored[...] = values


def _write_geometry_input(path: Path, *, optional_arrays: bool = False) -> None:
    """Write a real local geometry HDF5 fixture matching the reviewed read paths."""
    with h5py.File(path, "w") as handle:
        handle.attrs["dx_dy_dz"] = np.array([0.1, 0.1, 0.1], dtype=np.float64)
        handle.create_dataset(
            "/data", data=np.zeros((1, 2, 2), dtype=np.int16)
        )
        if optional_arrays:
            handle.create_dataset(
                "/rigidE", data=np.zeros((12, 1, 2, 2), dtype=np.int8)
            )
            handle.create_dataset(
                "/rigidH", data=np.ones((6, 1, 2, 2), dtype=np.int8)
            )
            handle.create_dataset(
                "/ID", data=np.zeros((6, 1, 2, 2), dtype=np.uint32)
            )


def _runtime(
    real_dtype: str = "float32", complex_dtype: str = "complex64"
) -> dict[str, object]:
    return {
        "gprmax_version": "3.1.6",
        "banner": "gprMax 3.1.6 (Big Smoke)",
        "import_path": "C:/gprmax/gprMax/__init__.py",
        "backend": "cpu",
        "real_dtype": real_dtype,
        "complex_dtype": complex_dtype,
        "static_deck_profile": dict(_LEGACY_STATIC_DECK_PROFILE),
    }


def _legacy_self_attested_evidence(
    candidate: np.ndarray, reference: np.ndarray
) -> dict[str, object]:
    return {
        "comparison_fixture": "adequacy.h5",
        "fp32_dataset": "/candidate",
        "fp64_dataset": "/reference",
        "rtol": 1e-5,
        "atol": 1e-8,
        "matched_run": {
            "candidate_run_id": "run-fp32",
            "reference_run_id": "run-fp64",
            "candidate_inputs_sha256": "a" * 64,
            "reference_inputs_sha256": "a" * 64,
            "candidate_precision": "float32",
            "reference_precision": "float64",
            "declared_changes": ["precision"],
            "candidate_dataset_sha256": _array_sha256(candidate),
            "reference_dataset_sha256": _array_sha256(reference),
        },
    }


def _array_sha256(values: np.ndarray) -> str:
    array = np.asarray(values)
    digest = hashlib.sha256()
    digest.update(
        json.dumps(
            {"dtype": array.dtype.name, "shape": list(array.shape)},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    digest.update(b"\n")
    digest.update(np.ascontiguousarray(array).tobytes(order="C"))
    return digest.hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash_map_sha256(value: dict[str, str]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _adequacy_evidence(
    project_root: Path,
    candidate: np.ndarray,
    reference: np.ndarray,
    *,
    fixture: str = "adequacy.h5",
    rtol: float = 1e-5,
    atol: float = 1e-8,
) -> dict[str, object]:
    manifests = project_root / "manifests"
    manifests.mkdir(exist_ok=True)
    inputs_dir = project_root / "inputs"
    inputs_dir.mkdir(exist_ok=True)
    (inputs_dir / "geometry.bin").write_bytes(b"geometry-v1\x00\x01")
    (inputs_dir / "model.in").write_bytes(b"#domain: 1 1 1\n")
    input_hashes = {
        "inputs/geometry.bin": _file_sha256(inputs_dir / "geometry.bin"),
        "inputs/model.in": _file_sha256(inputs_dir / "model.in"),
    }
    inputs_sha256 = _canonical_hash_map_sha256(input_hashes)
    shared_numerics = {"grid_sha256": "c" * 64, "subgrid_count": 1}
    runs = project_root / "runs"
    runs.mkdir(exist_ok=True)
    _write_dataset(runs / "run-fp32.h5", "/rxs/rx1/Ez", candidate)
    _write_dataset(runs / "run-fp64.h5", "/rxs/rx1/Ez", reference)
    candidate_manifest = {
        "run_id": "run-fp32",
        "input_root": "inputs",
        "primary_input": "inputs/model.in",
        "environment": _runtime("float32", "complex64"),
        "command": ["python", "-m", "gprMax", "inputs/model.in"],
        "return_code": 0,
        "numerics": {**shared_numerics, "precision": "float32"},
        "inputs": input_hashes,
        "inputs_sha256": inputs_sha256,
        "outputs": {
            "hdf5": "runs/run-fp32.h5",
            "receiver_dataset": "/rxs/rx1/Ez",
            "receiver_dataset_sha256": _array_sha256(candidate),
        },
        "started_at": "2026-08-09T00:00:00Z",
        "finished_at": "2026-08-09T00:01:00Z",
        "source_configuration": {"model": "inputs/model.in", "seed": 1},
    }
    reference_manifest = {
        "run_id": "run-fp64",
        "input_root": "inputs",
        "primary_input": "inputs/model.in",
        "environment": _runtime("float64", "complex128"),
        "command": ["python", "-m", "gprMax", "inputs/model.in"],
        "return_code": 0,
        "numerics": {**shared_numerics, "precision": "float64"},
        "inputs": input_hashes,
        "inputs_sha256": inputs_sha256,
        "outputs": {
            "hdf5": "runs/run-fp64.h5",
            "receiver_dataset": "/rxs/rx1/Ez",
            "receiver_dataset_sha256": _array_sha256(reference),
        },
        "started_at": "2026-08-09T00:02:00Z",
        "finished_at": "2026-08-09T00:03:00Z",
        "source_configuration": {"model": "inputs/model.in", "seed": 1},
    }
    (manifests / "run-fp32.json").write_text(
        json.dumps(candidate_manifest), encoding="utf-8"
    )
    (manifests / "run-fp64.json").write_text(
        json.dumps(reference_manifest), encoding="utf-8"
    )
    return {
        "comparison_fixture": fixture,
        "fp32_dataset": "/candidate",
        "fp64_dataset": "/reference",
        "rtol": rtol,
        "atol": atol,
        "matched_run": {
            "candidate_manifest": "manifests/run-fp32.json",
            "reference_manifest": "manifests/run-fp64.json",
        },
    }


def _refresh_manifest_input_inventory(project_root: Path) -> None:
    """Rebind both matched-run manifests to the current complete input tree."""
    input_hashes = {
        path.relative_to(project_root).as_posix(): _file_sha256(path)
        for path in sorted((project_root / "inputs").rglob("*"))
        if path.is_file()
    }
    for run_id in ("run-fp32", "run-fp64"):
        path = project_root / "manifests" / f"{run_id}.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["inputs"] = input_hashes
        manifest["inputs_sha256"] = _canonical_hash_map_sha256(input_hashes)
        path.write_text(json.dumps(manifest), encoding="utf-8")


def _write_static_deck(
    project_root: Path,
    primary: str,
    *,
    extra_files: dict[str, str | bytes] | None = None,
) -> None:
    """Install a UTF-8-BOM deck fixture and refresh its manifest inventory."""
    (project_root / "inputs" / "model.in").write_text(
        primary, encoding="utf-8-sig"
    )
    for relative_ref, payload in (extra_files or {}).items():
        path = project_root / relative_ref
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(payload, bytes):
            path.write_bytes(payload)
        else:
            path.write_text(payload, encoding="utf-8-sig")
    _refresh_manifest_input_inventory(project_root)


def _context(
    tmp_path: Path,
    *,
    values: np.ndarray | None = None,
    numerics: dict[str, object] | None = None,
    artifacts: dict[str, object] | None = None,
) -> GateContext:
    if values is None:
        values = np.array([1.0, 2.0], dtype=np.float32)
    _write_dataset(tmp_path / "run.h5", "/rxs/rx1/Ez", values)
    return GateContext(
        tmp_path,
        {
            "numerics": numerics or {"precision_requirement": "auto"},
            "outputs": {"hdf5": "run.h5", "receiver_dataset": "/rxs/rx1/Ez"},
        },
        artifacts=artifacts if artifacts is not None else {"environment": _runtime()},
    )


def test_float32_ulp_floor_is_detectable():
    """Catches computation of the floor in Python float64 rather than the total's dtype."""
    total = np.array([1.0], dtype=np.float32)
    differential = np.array([1.1920928955078125e-7], dtype=np.float32)

    assert local_ulp(total).dtype == np.dtype("float32")
    assert precision_floor_ratio(total, differential) == pytest.approx(1.0)


def test_precision_floor_ratio_uses_the_median_local_ulp_ratio():
    """Catches reducing amplitudes before comparing each sample to its local ULP."""
    total = np.array([1.0, 2.0, 4.0], dtype=np.float32)
    differential = np.array(
        [
            1.1920928955078125e-7,
            9.5367431640625e-7,
            1.9073486328125e-6,
        ],
        dtype=np.float32,
    )

    assert precision_floor_ratio(total, differential) == pytest.approx(4.0)


def test_required_fp64_blocks_float32_output_before_missing_runtime_evidence(tmp_path: Path):
    """Catches trusting the contract precision instead of the actual receiver dataset dtype."""
    _write_dataset(
        tmp_path / "run.h5", "/rxs/rx1/Ez", np.array([1.0, 2.0], dtype=np.float32)
    )
    ctx = GateContext(
        tmp_path,
        {
            "numerics": {"precision_requirement": "float64"},
            "outputs": {"hdf5": "run.h5", "receiver_dataset": "/rxs/rx1/Ez"},
        },
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_OUTPUT_DTYPE"


@pytest.mark.parametrize(
    ("outputs", "code"),
    [
        ({}, "BLOCK_OUTPUT_EVIDENCE"),
        ({"hdf5": "missing.h5", "receiver_dataset": "/rxs/rx1/Ez"}, "BLOCK_OUTPUT_EVIDENCE"),
        ({"hdf5": "run.h5", "receiver_dataset": "/missing"}, "BLOCK_OUTPUT_EVIDENCE"),
    ],
)
def test_missing_required_output_evidence_fails_closed(
    tmp_path: Path, outputs: dict[str, str], code: str
):
    """Catches an absent file or dataset being treated as unverified-but-acceptable."""
    _write_dataset(
        tmp_path / "run.h5", "/rxs/rx1/Ez", np.array([1.0, 2.0], dtype=np.float32)
    )
    ctx = GateContext(
        tmp_path,
        {"numerics": {"precision_requirement": "auto"}, "outputs": outputs},
        artifacts={"environment": _runtime()},
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == code


def test_nonfinite_receiver_data_blocks(tmp_path: Path):
    """Catches checking only HDF5 dtype while accepting unusable numeric samples."""
    ctx = _context(
        tmp_path,
        values=np.array([1.0, np.nan], dtype=np.float64),
        artifacts={"environment": _runtime("float64", "complex128")},
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_OUTPUT_NONFINITE"


@pytest.mark.parametrize("link_kind", ["external", "virtual"])
def test_receiver_rejects_dereferenced_hdf5_sources_outside_project(
    tmp_path: Path, link_kind: str
):
    """Catches link/VDS dereferencing that bypasses project-root containment."""
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.h5"
    values = np.array([1.0, 2.0], dtype=np.float32)
    _write_dataset(outside, "/data", values)
    with h5py.File(project / "run.h5", "w", libver="latest") as handle:
        if link_kind == "external":
            handle["receiver"] = h5py.ExternalLink(str(outside), "/data")
        else:
            layout = h5py.VirtualLayout(shape=values.shape, dtype=values.dtype)
            layout[:] = h5py.VirtualSource(str(outside), "/data", shape=values.shape)
            handle.create_virtual_dataset("receiver", layout)
    ctx = GateContext(
        project,
        {
            "numerics": {"precision_requirement": "auto"},
            "outputs": {"hdf5": "run.h5", "receiver_dataset": "/receiver"},
        },
        artifacts={"environment": _runtime()},
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_OUTPUT_EVIDENCE"


def test_receiver_rejects_external_raw_storage_outside_project(tmp_path: Path):
    """Catches a local HDF5 dataset proxying its raw bytes from outside project_root."""
    project = tmp_path / "project"
    project.mkdir()
    values = np.array([1.0, 2.0], dtype=np.float32)
    _write_external_storage_dataset(
        project / "run.h5", "/receiver", values, tmp_path / "outside.raw"
    )
    ctx = GateContext(
        project,
        {
            "numerics": {"precision_requirement": "auto"},
            "outputs": {"hdf5": "run.h5", "receiver_dataset": "/receiver"},
        },
        artifacts={"environment": _runtime()},
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_OUTPUT_EVIDENCE"


@pytest.mark.parametrize(
    "environment",
    [
        None,
        {"real_dtype": "float32"},
        _runtime("float32", "complex128"),
        _runtime("double", "complex128"),
    ],
)
def test_missing_or_inconsistent_runtime_dtype_evidence_blocks(
    tmp_path: Path, environment: dict[str, object] | None
):
    """Catches acceptance of an unresolved or internally inconsistent runtime precision pair."""
    artifacts = {} if environment is None else {"environment": environment}
    ctx = _context(tmp_path, artifacts=artifacts)

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_RUNTIME_DTYPE"


def test_receiver_dtype_must_match_runtime_real_dtype(tmp_path: Path):
    """Catches a runtime banner claiming FP64 when the receiver was written as FP32."""
    ctx = _context(
        tmp_path,
        values=np.array([1.0, 2.0], dtype=np.float32),
        artifacts={"environment": _runtime("float64", "complex128")},
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_OUTPUT_DTYPE"


def test_complex_receiver_blocks_when_real_ulp_semantics_do_not_apply(tmp_path: Path):
    """Catches passing complex output without a defined component-wise ULP contract."""
    ctx = _context(
        tmp_path,
        values=np.array([1.0 + 2.0j, 3.0 + 4.0j], dtype=np.complex64),
        artifacts={"environment": _runtime()},
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_OUTPUT_DTYPE"


def test_invalid_ulp_safety_factor_is_a_precision_contract_defect(tmp_path: Path):
    """Catches misclassifying a malformed ULP policy as unrelated FP32 evidence."""
    ctx = _context(
        tmp_path,
        numerics={"precision_requirement": "float32", "ulp_safety_factor": "eight"},
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_PRECISION_CONTRACT"


def test_risk_flag_requires_fp64_without_explicit_fp32_adequacy_evidence(tmp_path: Path):
    """Catches risky FP32 runs passing merely because precision_requirement is auto."""
    ctx = _context(
        tmp_path,
        numerics={"precision_requirement": "auto", "risk_flags": ["weak_differential"]},
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_FP64_REQUIRED"


@pytest.mark.parametrize(
    "flag",
    [
        "weak_differential",
        "long_distance",
        "coherent_phase",
        "high_dynamic_range",
        "fine_delay_fit",
    ],
)
def test_every_supported_precision_risk_flag_is_accepted(tmp_path: Path, flag: str):
    """Catches accidental removal of any mandated risk vocabulary entry."""
    ctx = _context(
        tmp_path,
        values=np.array([1.0, 2.0], dtype=np.float64),
        numerics={"precision_requirement": "auto", "risk_flags": [flag]},
        artifacts={"environment": _runtime("float64", "complex128")},
    )

    result = audit_precision(ctx)

    assert result.state is GateState.PASS
    assert result.code == "PASS_PRECISION"


@pytest.mark.parametrize(
    "flag",
    [
        "weak-differential",
        "unknown_precision_risk",
        "WEAK_DIFFERENTIAL",
        " weak_differential ",
        7,
    ],
)
def test_unknown_or_non_string_precision_risk_flag_blocks_contract(
    tmp_path: Path, flag: object
):
    """Catches misspelled/unknown risk declarations being silently discarded."""
    ctx = _context(
        tmp_path,
        values=np.array([1.0, 2.0], dtype=np.float64),
        numerics={"precision_requirement": "auto", "risk_flags": [flag]},
        artifacts={"environment": _runtime("float64", "complex128")},
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_PRECISION_CONTRACT"


def test_fp32_adequacy_fixture_must_exist_and_be_complete(tmp_path: Path):
    """Catches a declared but non-reproducible FP32 policy exception."""
    ctx = _context(
        tmp_path,
        numerics={
            "precision_requirement": "float32",
            "risk_flags": ["coherent_phase"],
            "fp32_adequacy_evidence": {
                "comparison_fixture": "missing.h5",
                "fp32_dataset": "/candidate",
                "fp64_dataset": "/reference",
                "rtol": 1e-5,
                "atol": 1e-8,
            },
        },
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_FP32_ADEQUACY_EVIDENCE"


def test_fp32_adequacy_fixture_must_pass_declared_comparison(tmp_path: Path):
    """Catches accepting FP32 evidence without evaluating it against its FP64 reference."""
    candidate = np.array([1.0, 1.2], dtype=np.float32)
    reference = np.array([1.0, 1.0], dtype=np.float64)
    with h5py.File(tmp_path / "adequacy.h5", "w") as handle:
        handle.create_dataset("candidate", data=candidate)
        handle.create_dataset("reference", data=reference)
    ctx = _context(
        tmp_path,
        values=candidate,
        numerics={
            "precision_requirement": "float32",
            "risk_flags": ["high_dynamic_range"],
            "fp32_adequacy_evidence": _adequacy_evidence(tmp_path, candidate, reference),
        },
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_FP32_ADEQUACY"


def test_passing_fp32_comparison_fixture_allows_risk_flag_exception(tmp_path: Path):
    """Catches ignoring valid explicit FP32 adequacy evidence for risk-flagged work."""
    candidate = np.array([1.0, 1.000001], dtype=np.float32)
    reference = np.array([1.0, 1.0000011], dtype=np.float64)
    with h5py.File(tmp_path / "adequacy.h5", "w") as handle:
        handle.create_dataset("candidate", data=candidate)
        handle.create_dataset("reference", data=reference)
    ctx = _context(
        tmp_path,
        values=candidate,
        numerics={
            "precision_requirement": "float32",
            "risk_flags": ["fine_delay_fit"],
            "fp32_adequacy_evidence": _adequacy_evidence(tmp_path, candidate, reference),
        },
    )

    result = audit_precision(ctx)

    assert result.state is GateState.PASS
    assert result.code == "PASS_PRECISION"
    assert result.evidence == ("run.h5", "adequacy.h5")
    adequacy = ctx.artifacts["derived"]["precision"]["fp32_adequacy"]
    assert adequacy["passed"] is True
    matched_run = adequacy["matched_run"]
    assert matched_run.get("input_root") == "inputs"
    assert matched_run.get("primary_input") == "inputs/model.in"
    assert matched_run.get("static_deck_profile") == _LEGACY_STATIC_DECK_PROFILE
    assert matched_run["derived_change_projection"] == [
        "numerics.precision",
        "environment.real_dtype",
        "environment.complex_dtype",
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_profile",
        "gprmax_4_runtime",
        "wrong_profile_id",
        "wrong_source_archive",
        "wrong_source_tree",
        "wrong_internal_version",
        "wrong_codename",
        "extra_profile_field",
        "boolean_profile_field",
    ],
)
def test_fp32_exception_requires_exact_reviewed_static_deck_profile(
    tmp_path: Path, mutation: str
):
    """Catches a closed parser authorizing source/runtime syntax it never reviewed."""
    candidate = np.array([1.0], dtype=np.float32)
    reference = np.array([1.0], dtype=np.float64)
    _write_dataset(tmp_path / "adequacy.h5", "/candidate", candidate)
    with h5py.File(tmp_path / "adequacy.h5", "a") as handle:
        handle.create_dataset("reference", data=reference)
    evidence = _adequacy_evidence(tmp_path, candidate, reference)

    def apply_mutation(environment: dict[str, object]) -> None:
        profile = environment["static_deck_profile"]
        if mutation == "missing_profile":
            environment.pop("static_deck_profile")
        elif mutation == "gprmax_4_runtime":
            environment["gprmax_version"] = "4.0.0"
            environment["banner"] = "gprMax 4.0.0"
        elif mutation == "wrong_profile_id":
            profile["profile_id"] = "gprmax-legacy-static-deck-v2"
        elif mutation == "wrong_source_archive":
            profile["source_archive_sha256"] = "0" * 64
        elif mutation == "wrong_source_tree":
            profile["source_tree_label"] = "gprMax-v.4.0.0"
        elif mutation == "wrong_internal_version":
            profile["internal_version"] = "3.1.7"
        elif mutation == "wrong_codename":
            profile["codename"] = "Unknown"
        elif mutation == "extra_profile_field":
            profile["unreviewed_source"] = "accepted"
        elif mutation == "boolean_profile_field":
            profile["internal_version"] = True

    for run_id in ("run-fp32", "run-fp64"):
        path = tmp_path / "manifests" / f"{run_id}.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        apply_mutation(manifest["environment"])
        path.write_text(json.dumps(manifest), encoding="utf-8")
    actual_environment = _runtime()
    apply_mutation(actual_environment)
    ctx = _context(
        tmp_path,
        values=candidate,
        artifacts={"environment": actual_environment},
        numerics={
            "precision_requirement": "float32",
            "risk_flags": ["long_distance"],
            "fp32_adequacy_evidence": evidence,
        },
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_FP32_ADEQUACY_EVIDENCE"


@pytest.mark.parametrize(
    "mutation", ["missing_profile", "wrong_source_archive", "import_path_mismatch"]
)
def test_fp32_exception_manifest_environment_must_match_actual_runtime_evidence(
    tmp_path: Path, mutation: str
):
    """Catches matched manifests detached from the environment that produced the FP32 output."""
    candidate = np.array([1.0], dtype=np.float32)
    reference = np.array([1.0], dtype=np.float64)
    _write_dataset(tmp_path / "adequacy.h5", "/candidate", candidate)
    with h5py.File(tmp_path / "adequacy.h5", "a") as handle:
        handle.create_dataset("reference", data=reference)
    evidence = _adequacy_evidence(tmp_path, candidate, reference)
    actual_environment = _runtime()
    if mutation == "missing_profile":
        actual_environment.pop("static_deck_profile")
    elif mutation == "wrong_source_archive":
        actual_environment["static_deck_profile"]["source_archive_sha256"] = "0" * 64
    elif mutation == "import_path_mismatch":
        actual_environment["import_path"] = "C:/different/gprMax/__init__.py"
    ctx = _context(
        tmp_path,
        values=candidate,
        artifacts={"environment": actual_environment},
        numerics={
            "precision_requirement": "float32",
            "risk_flags": ["coherent_phase"],
            "fp32_adequacy_evidence": evidence,
        },
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_FP32_ADEQUACY_EVIDENCE"


def test_fp32_exception_publishes_verified_recursive_static_dependency_closure(
    tmp_path: Path,
):
    """Catches inventory-only evidence that never binds files named by the deck."""
    candidate = np.array([1.0, 1.000001], dtype=np.float32)
    reference = np.array([1.0, 1.0000011], dtype=np.float64)
    _write_dataset(tmp_path / "adequacy.h5", "/candidate", candidate)
    with h5py.File(tmp_path / "adequacy.h5", "a") as handle:
        handle.create_dataset("reference", data=reference)
    evidence = _adequacy_evidence(tmp_path, candidate, reference)
    _write_static_deck(
        tmp_path,
        """## UTF-8 BOM and comments are permitted
#domain: 1 1 1
#include_file: inputs/nested.in
#geometry_objects_read: 0 0 0 inputs/geometry.h5 inputs/materials.txt
#excitation_file: inputs/excitation.txt
""",
        extra_files={
            "inputs/nested.in": "#include_file: inputs/deeper.in\n",
            "inputs/deeper.in": "#material: 4 0 1 0 nested\n",
            "inputs/materials.txt": "#material: 5 0 1 0 imported\n",
            "inputs/excitation.txt": "0 1\n1 0\n",
        },
    )
    _write_geometry_input(tmp_path / "inputs" / "geometry.h5")
    _refresh_manifest_input_inventory(tmp_path)
    ctx = _context(
        tmp_path,
        values=candidate,
        numerics={
            "precision_requirement": "float32",
            "risk_flags": ["fine_delay_fit"],
            "fp32_adequacy_evidence": evidence,
        },
    )

    result = audit_precision(ctx)

    assert result.state is GateState.PASS
    matched_run = ctx.artifacts["derived"]["precision"]["fp32_adequacy"][
        "matched_run"
    ]
    assert matched_run.get("dependency_count") == 6
    assert matched_run.get("dependencies") == [
        "inputs/deeper.in",
        "inputs/excitation.txt",
        "inputs/geometry.h5",
        "inputs/materials.txt",
        "inputs/model.in",
        "inputs/nested.in",
    ]
    assert matched_run.get("geometry_hdf5_dependencies") == [
        {
            "container_path": "inputs/geometry.h5",
            "container_sha256": _file_sha256(
                tmp_path / "inputs" / "geometry.h5"
            ),
            "datasets": [
                {
                    "dataset_path": "/data",
                    "sha256": (
                        "2632e335e5ca8d191ae58955218d8fd4"
                        "f66b18a9b54a4267130d43da28e296a0"
                    ),
                }
            ],
        }
    ]


@pytest.mark.parametrize(
    "attack",
    [
        "data_external_link",
        "data_virtual_dataset",
        "data_external_storage",
        "optional_external_link",
        "partial_optional_arrays",
        "empty_data",
    ],
)
def test_fp32_exception_rejects_geometry_hdf5_dereferenced_payloads(
    tmp_path: Path, attack: str
):
    """Catches a hashed geometry container loading unbound data from another file."""
    candidate = np.array([1.0], dtype=np.float32)
    reference = np.array([1.0], dtype=np.float64)
    _write_dataset(tmp_path / "adequacy.h5", "/candidate", candidate)
    with h5py.File(tmp_path / "adequacy.h5", "a") as handle:
        handle.create_dataset("reference", data=reference)
    evidence = _adequacy_evidence(tmp_path, candidate, reference)
    _write_static_deck(
        tmp_path,
        "#geometry_objects_read: 0 0 0 inputs/geometry.h5 inputs/materials.txt\n",
        extra_files={
            "inputs/materials.txt": "#material: 5 0 1 0 imported\n"
        },
    )
    geometry_path = tmp_path / "inputs" / "geometry.h5"
    geometry_data = np.zeros((1, 2, 2), dtype=np.int16)
    external_hdf5 = tmp_path / "outside-geometry-payload.h5"
    if attack in {"data_external_link", "optional_external_link"}:
        _write_dataset(external_hdf5, "/payload", geometry_data)

    if attack == "data_external_link":
        with h5py.File(geometry_path, "w") as handle:
            handle.attrs["dx_dy_dz"] = [0.1, 0.1, 0.1]
            handle["data"] = h5py.ExternalLink(str(external_hdf5), "/payload")
    elif attack == "data_virtual_dataset":
        _write_dataset(external_hdf5, "/payload", geometry_data)
        layout = h5py.VirtualLayout(shape=geometry_data.shape, dtype=np.int16)
        layout[:] = h5py.VirtualSource(
            str(external_hdf5), "/payload", shape=geometry_data.shape
        )
        with h5py.File(geometry_path, "w", libver="latest") as handle:
            handle.attrs["dx_dy_dz"] = [0.1, 0.1, 0.1]
            handle.create_virtual_dataset("/data", layout)
    elif attack == "data_external_storage":
        _write_external_storage_dataset(
            geometry_path,
            "/data",
            geometry_data,
            tmp_path / "outside-geometry.raw",
        )
        with h5py.File(geometry_path, "a") as handle:
            handle.attrs["dx_dy_dz"] = [0.1, 0.1, 0.1]
    elif attack == "optional_external_link":
        _write_geometry_input(geometry_path)
        with h5py.File(geometry_path, "a") as handle:
            handle["rigidE"] = h5py.ExternalLink(
                str(external_hdf5), "/payload"
            )
            handle.create_dataset(
                "/rigidH", data=np.ones((6, 1, 2, 2), dtype=np.int8)
            )
            handle.create_dataset(
                "/ID", data=np.zeros((6, 1, 2, 2), dtype=np.uint32)
            )
    elif attack == "partial_optional_arrays":
        _write_geometry_input(geometry_path)
        with h5py.File(geometry_path, "a") as handle:
            handle.create_dataset(
                "/rigidE", data=np.zeros((12, 1, 2, 2), dtype=np.int8)
            )
    elif attack == "empty_data":
        with h5py.File(geometry_path, "w") as handle:
            handle.attrs["dx_dy_dz"] = [0.1, 0.1, 0.1]
            handle.create_dataset("/data", data=np.empty((0, 2, 2), dtype=np.int16))
    _refresh_manifest_input_inventory(tmp_path)
    ctx = _context(
        tmp_path,
        values=candidate,
        numerics={
            "precision_requirement": "float32",
            "risk_flags": ["weak_differential"],
            "fp32_adequacy_evidence": evidence,
        },
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_FP32_ADEQUACY_EVIDENCE"


def test_fp32_exception_accepts_and_hashes_complete_local_geometry_arrays(
    tmp_path: Path,
):
    """Catches rejecting the reviewed all-present rigid/ID read branch or omitting its hashes."""
    candidate = np.array([1.0], dtype=np.float32)
    reference = np.array([1.0], dtype=np.float64)
    _write_dataset(tmp_path / "adequacy.h5", "/candidate", candidate)
    with h5py.File(tmp_path / "adequacy.h5", "a") as handle:
        handle.create_dataset("reference", data=reference)
    evidence = _adequacy_evidence(tmp_path, candidate, reference)
    _write_static_deck(
        tmp_path,
        "#geometry_objects_read: 0 0 0 inputs/geometry.h5 inputs/materials.txt\n",
        extra_files={
            "inputs/materials.txt": "#material: 5 0 1 0 imported\n"
        },
    )
    _write_geometry_input(
        tmp_path / "inputs" / "geometry.h5", optional_arrays=True
    )
    _refresh_manifest_input_inventory(tmp_path)
    ctx = _context(
        tmp_path,
        values=candidate,
        numerics={
            "precision_requirement": "float32",
            "risk_flags": ["weak_differential"],
            "fp32_adequacy_evidence": evidence,
        },
    )

    result = audit_precision(ctx)

    assert result.state is GateState.PASS
    geometry_evidence = ctx.artifacts["derived"]["precision"][
        "fp32_adequacy"
    ]["matched_run"].get("geometry_hdf5_dependencies")
    assert geometry_evidence is not None
    assert [item["dataset_path"] for item in geometry_evidence[0]["datasets"]] == [
        "/data",
        "/rigidE",
        "/rigidH",
        "/ID",
    ]
    assert all(
        len(item["sha256"]) == 64
        for item in geometry_evidence[0]["datasets"]
    )


@pytest.mark.parametrize(
    ("directive", "outside_ref"),
    [
        ("#include_file: outside-input-root.in", "outside-input-root.in"),
        ("#include_file: ../outside-include.in", "../outside-include.in"),
        (
            "#geometry_objects_read: 0 0 0 ../outside-geometry.h5 inputs/materials.txt",
            "../outside-geometry.h5",
        ),
        (
            "#geometry_objects_read: 0 0 0 inputs/geometry.h5 ../outside-materials.txt",
            "../outside-materials.txt",
        ),
        (
            "#excitation_file: ../outside-excitation.txt",
            "../outside-excitation.txt",
        ),
    ],
    ids=[
        "include-outside-input-root",
        "include-parent-traversal",
        "geometry-parent-traversal",
        "materials-parent-traversal",
        "excitation-parent-traversal",
    ],
)
def test_fp32_exception_blocks_dependency_outside_input_root(
    tmp_path: Path, directive: str, outside_ref: str
):
    """Catches external file references hidden behind a complete input inventory."""
    candidate = np.array([1.0], dtype=np.float32)
    reference = np.array([1.0], dtype=np.float64)
    _write_dataset(tmp_path / "adequacy.h5", "/candidate", candidate)
    with h5py.File(tmp_path / "adequacy.h5", "a") as handle:
        handle.create_dataset("reference", data=reference)
    evidence = _adequacy_evidence(tmp_path, candidate, reference)
    _write_static_deck(
        tmp_path,
        f"#domain: 1 1 1\n{directive}\n",
        extra_files={
            "inputs/geometry.h5": b"geometry-hdf5-placeholder",
            "inputs/materials.txt": "#material: 5 0 1 0 imported\n",
        },
    )
    _write_geometry_input(tmp_path / "inputs" / "geometry.h5")
    _refresh_manifest_input_inventory(tmp_path)
    (tmp_path / outside_ref).write_bytes(b"external dependency")
    ctx = _context(
        tmp_path,
        values=candidate,
        numerics={
            "precision_requirement": "float32",
            "risk_flags": ["weak_differential"],
            "fp32_adequacy_evidence": evidence,
        },
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_FP32_ADEQUACY_EVIDENCE"


@pytest.mark.parametrize(
    ("primary", "extra_files"),
    [
        ("#include_file: inputs/nested.in inputs/deeper.in\n", {}),
        ("#geometry_objects_read: 0 0 inputs/geometry.h5 inputs/materials.txt\n", {}),
        ("#excitation_file: inputs/excitation.txt 1\n", {}),
        ("#python:\nprint('dynamic')\n#end_python:\n", {}),
        ("#end_python:\n", {}),
        ("#future_load_asset: inputs/future.bin\n", {}),
        (
            "#include_file: inputs/nested.in\n",
            {"inputs/nested.in": "#include_file: inputs/model.in\n"},
        ),
        (
            "#include_file: inputs/nested.in\n#include_file: inputs/nested.in\n",
            {"inputs/nested.in": "#domain: 1 1 1\n"},
        ),
    ],
    ids=[
        "include-arity",
        "geometry-arity",
        "excitation-arity",
        "python-block",
        "orphan-end-python",
        "unknown-command",
        "include-cycle",
        "duplicate-include",
    ],
)
def test_fp32_exception_requires_closed_legacy_static_deck_profile(
    tmp_path: Path,
    primary: str,
    extra_files: dict[str, str | bytes],
):
    """Catches dynamic, unknown, malformed, cyclic, or duplicate deck closure."""
    candidate = np.array([1.0], dtype=np.float32)
    reference = np.array([1.0], dtype=np.float64)
    _write_dataset(tmp_path / "adequacy.h5", "/candidate", candidate)
    with h5py.File(tmp_path / "adequacy.h5", "a") as handle:
        handle.create_dataset("reference", data=reference)
    evidence = _adequacy_evidence(tmp_path, candidate, reference)
    _write_static_deck(tmp_path, primary, extra_files=extra_files)
    ctx = _context(
        tmp_path,
        values=candidate,
        numerics={
            "precision_requirement": "float32",
            "risk_flags": ["coherent_phase"],
            "fp32_adequacy_evidence": evidence,
        },
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_FP32_ADEQUACY_EVIDENCE"


@pytest.mark.parametrize(
    "field",
    ["candidate_manifest", "outputs.hdf5", "outputs.receiver_dataset"],
)
def test_fp32_exception_path_bindings_require_exact_canonical_text(
    tmp_path: Path, field: str
):
    """Catches whitespace-normalized paths authorizing different evidence text."""
    candidate = np.array([1.0], dtype=np.float32)
    reference = np.array([1.0], dtype=np.float64)
    _write_dataset(tmp_path / "adequacy.h5", "/candidate", candidate)
    with h5py.File(tmp_path / "adequacy.h5", "a") as handle:
        handle.create_dataset("reference", data=reference)
    evidence = _adequacy_evidence(tmp_path, candidate, reference)
    if field == "candidate_manifest":
        evidence["matched_run"][field] = " manifests/run-fp32.json "
    else:
        output_field = field.removeprefix("outputs.")
        for run_id in ("run-fp32", "run-fp64"):
            path = tmp_path / "manifests" / f"{run_id}.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["outputs"][output_field] = (
                f" {manifest['outputs'][output_field]} "
            )
            path.write_text(json.dumps(manifest), encoding="utf-8")
    ctx = _context(
        tmp_path,
        values=candidate,
        numerics={
            "precision_requirement": "float32",
            "risk_flags": ["long_distance"],
            "fp32_adequacy_evidence": evidence,
        },
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_FP32_ADEQUACY_EVIDENCE"


def test_fp32_candidate_must_exactly_equal_audited_receiver(tmp_path: Path):
    """Catches unrelated comparison arrays authorizing the audited FP32 output."""
    receiver = np.array([2.0, 2.0], dtype=np.float32)
    candidate = np.array([1.0, 1.0], dtype=np.float32)
    reference = np.array([1.0, 1.0], dtype=np.float64)
    with h5py.File(tmp_path / "adequacy.h5", "w") as handle:
        handle.create_dataset("candidate", data=candidate)
        handle.create_dataset("reference", data=reference)
    ctx = _context(
        tmp_path,
        values=receiver,
        numerics={
            "precision_requirement": "float32",
            "risk_flags": ["weak_differential"],
            "fp32_adequacy_evidence": _adequacy_evidence(tmp_path, candidate, reference),
        },
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_FP32_ADEQUACY_EVIDENCE"


def test_contract_only_self_attestation_cannot_authorize_approximate_reference(
    tmp_path: Path,
):
    """Catches caller-selected run IDs/hashes authorizing an unanchored reference array."""
    candidate = np.array([1.0, 1.000001], dtype=np.float32)
    arbitrary_reference = np.array([1.0, 1.0000011], dtype=np.float64)
    _write_dataset(tmp_path / "adequacy.h5", "/candidate", candidate)
    with h5py.File(tmp_path / "adequacy.h5", "a") as handle:
        handle.create_dataset("reference", data=arbitrary_reference)
    ctx = _context(
        tmp_path,
        values=candidate,
        numerics={
            "precision_requirement": "float32",
            "risk_flags": ["weak_differential"],
            "fp32_adequacy_evidence": _legacy_self_attested_evidence(
                candidate, arbitrary_reference
            ),
        },
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_FP32_ADEQUACY_EVIDENCE"


@pytest.mark.parametrize(
    "mutation",
    [
        "same_run_id",
        "run_id_filename_mismatch",
        "failed_return_code",
        "wrong_reference_precision",
        "other_numerics_change",
        "numerics_json_type_change",
        "incorrect_input_file_hash",
        "incorrect_input_set_hash",
        "incorrect_output_dataset_hash",
        "shared_run_output_file",
        "missing_formal_field",
        "wrong_environment_dtype",
        "environment_metadata_change",
        "command_change",
        "unprojected_top_level_change",
        "stable_metadata_json_type_change",
    ],
)
def test_fp32_adequacy_requires_verified_matched_run_provenance(
    tmp_path: Path, mutation: str
):
    """Catches failed/unmatched runs, unverified files, or changes beyond precision."""
    candidate = np.array([1.0, 1.000001], dtype=np.float32)
    reference = np.array([1.0, 1.0000011], dtype=np.float64)
    with h5py.File(tmp_path / "adequacy.h5", "w") as handle:
        handle.create_dataset("candidate", data=candidate)
        handle.create_dataset("reference", data=reference)
    evidence = _adequacy_evidence(tmp_path, candidate, reference)
    candidate_path = tmp_path / "manifests" / "run-fp32.json"
    reference_path = tmp_path / "manifests" / "run-fp64.json"
    candidate_manifest = json.loads(candidate_path.read_text(encoding="utf-8"))
    reference_manifest = json.loads(reference_path.read_text(encoding="utf-8"))
    if mutation == "same_run_id":
        reference_manifest["run_id"] = candidate_manifest["run_id"]
    elif mutation == "run_id_filename_mismatch":
        reference_manifest["run_id"] = "other-fp64-run"
    elif mutation == "failed_return_code":
        reference_manifest["return_code"] = 1
    elif mutation == "wrong_reference_precision":
        reference_manifest["numerics"]["precision"] = "float32"
    elif mutation == "other_numerics_change":
        reference_manifest["numerics"]["grid_sha256"] = "d" * 64
    elif mutation == "numerics_json_type_change":
        reference_manifest["numerics"]["subgrid_count"] = True
    elif mutation == "incorrect_input_file_hash":
        reference_manifest["inputs"]["inputs/model.in"] = "0" * 64
    elif mutation == "incorrect_input_set_hash":
        reference_manifest["inputs_sha256"] = "0" * 64
    elif mutation == "incorrect_output_dataset_hash":
        reference_manifest["outputs"]["receiver_dataset_sha256"] = "0" * 64
    elif mutation == "shared_run_output_file":
        with h5py.File(tmp_path / "runs" / "run-fp32.h5", "a") as handle:
            handle.create_dataset("reference", data=reference)
        reference_manifest["outputs"]["hdf5"] = "runs/run-fp32.h5"
        reference_manifest["outputs"]["receiver_dataset"] = "/reference"
    elif mutation == "missing_formal_field":
        reference_manifest.pop("environment")
    elif mutation == "wrong_environment_dtype":
        reference_manifest["environment"]["real_dtype"] = "float32"
    elif mutation == "environment_metadata_change":
        reference_manifest["environment"]["backend"] = "gpu"
    elif mutation == "command_change":
        reference_manifest["command"].append("--different-model-setting")
    elif mutation == "unprojected_top_level_change":
        reference_manifest["source_configuration"] = {"antenna": "different"}
    elif mutation == "stable_metadata_json_type_change":
        reference_manifest["source_configuration"]["seed"] = True
    reference_path.write_text(json.dumps(reference_manifest), encoding="utf-8")
    ctx = _context(
        tmp_path,
        values=candidate,
        numerics={
            "precision_requirement": "float32",
            "risk_flags": ["long_distance"],
            "fp32_adequacy_evidence": evidence,
        },
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_FP32_ADEQUACY_EVIDENCE"


@pytest.mark.parametrize(
    "payload",
    [
        "[]",
        '{"run_id":"first","run_id":"duplicate"}',
        '{"run_id":NaN}',
    ],
)
def test_matched_run_manifest_requires_strict_json_object(tmp_path: Path, payload: str):
    """Catches non-object, duplicate-key, and non-finite JSON run evidence."""
    candidate = np.array([1.0], dtype=np.float32)
    reference = np.array([1.0], dtype=np.float64)
    with h5py.File(tmp_path / "adequacy.h5", "w") as handle:
        handle.create_dataset("candidate", data=candidate)
        handle.create_dataset("reference", data=reference)
    evidence = _adequacy_evidence(tmp_path, candidate, reference)
    (tmp_path / "manifests" / "run-fp64.json").write_text(payload, encoding="utf-8")
    ctx = _context(
        tmp_path,
        values=candidate,
        numerics={
            "precision_requirement": "float32",
            "risk_flags": ["coherent_phase"],
            "fp32_adequacy_evidence": evidence,
        },
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_FP32_ADEQUACY_EVIDENCE"


def test_matched_run_manifest_path_must_remain_inside_project(tmp_path: Path):
    """Catches a manifest reference escaping project_root before provenance checks."""
    project = tmp_path / "project"
    project.mkdir()
    candidate = np.array([1.0], dtype=np.float32)
    reference = np.array([1.0], dtype=np.float64)
    with h5py.File(project / "adequacy.h5", "w") as handle:
        handle.create_dataset("candidate", data=candidate)
        handle.create_dataset("reference", data=reference)
    evidence = _adequacy_evidence(project, candidate, reference)
    outside = tmp_path / "outside-manifest.json"
    outside.write_text(
        (project / "manifests" / "run-fp64.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    evidence["matched_run"]["reference_manifest"] = "../outside-manifest.json"
    ctx = _context(
        project,
        values=candidate,
        numerics={
            "precision_requirement": "float32",
            "risk_flags": ["coherent_phase"],
            "fp32_adequacy_evidence": evidence,
        },
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_FP32_ADEQUACY_EVIDENCE"


def test_manifest_input_hashes_are_recomputed_from_actual_project_files(tmp_path: Path):
    """Catches unchanged manifest hashes after an actual input file is modified."""
    candidate = np.array([1.0], dtype=np.float32)
    reference = np.array([1.0], dtype=np.float64)
    with h5py.File(tmp_path / "adequacy.h5", "w") as handle:
        handle.create_dataset("candidate", data=candidate)
        handle.create_dataset("reference", data=reference)
    evidence = _adequacy_evidence(tmp_path, candidate, reference)
    (tmp_path / "inputs" / "model.in").write_bytes(b"tampered input\n")
    ctx = _context(
        tmp_path,
        values=candidate,
        numerics={
            "precision_requirement": "float32",
            "risk_flags": ["weak_differential"],
            "fp32_adequacy_evidence": evidence,
        },
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_FP32_ADEQUACY_EVIDENCE"


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_primary",
        "missing_dependency",
        "alias_path",
        "absolute_path",
        "duplicate_file_identity",
        "primary_absent_from_command",
    ],
)
def test_manifest_inputs_are_a_closed_canonical_command_bound_inventory(
    tmp_path: Path, mutation: str
):
    """Catches a partial, aliased, duplicate, or command-unbound input inventory."""
    candidate = np.array([1.0], dtype=np.float32)
    reference = np.array([1.0], dtype=np.float64)
    with h5py.File(tmp_path / "adequacy.h5", "w") as handle:
        handle.create_dataset("candidate", data=candidate)
        handle.create_dataset("reference", data=reference)
    evidence = _adequacy_evidence(tmp_path, candidate, reference)
    manifest_paths = [
        tmp_path / "manifests" / "run-fp32.json",
        tmp_path / "manifests" / "run-fp64.json",
    ]
    manifests = [json.loads(path.read_text(encoding="utf-8")) for path in manifest_paths]

    if mutation == "duplicate_file_identity":
        os.link(
            tmp_path / "inputs" / "model.in",
            tmp_path / "inputs" / "model-copy.in",
        )
    for manifest in manifests:
        inputs = manifest["inputs"]
        if mutation == "missing_primary":
            inputs.pop("inputs/model.in")
        elif mutation == "missing_dependency":
            inputs.pop("inputs/geometry.bin")
        elif mutation == "alias_path":
            inputs["inputs/./model.in"] = inputs.pop("inputs/model.in")
        elif mutation == "absolute_path":
            inputs[(tmp_path / "inputs" / "model.in").resolve().as_posix()] = inputs.pop(
                "inputs/model.in"
            )
        elif mutation == "duplicate_file_identity":
            inputs["inputs/model-copy.in"] = _file_sha256(
                tmp_path / "inputs" / "model-copy.in"
            )
        elif mutation == "primary_absent_from_command":
            manifest["command"] = ["python", "-m", "gprMax", "inputs/geometry.bin"]
        manifest["inputs_sha256"] = _canonical_hash_map_sha256(inputs)

    for path, manifest in zip(manifest_paths, manifests, strict=True):
        path.write_text(json.dumps(manifest), encoding="utf-8")
    ctx = _context(
        tmp_path,
        values=candidate,
        numerics={
            "precision_requirement": "float32",
            "risk_flags": ["weak_differential"],
            "fp32_adequacy_evidence": evidence,
        },
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_FP32_ADEQUACY_EVIDENCE"


@pytest.mark.parametrize("field", ["input_root", "primary_input"])
def test_run_manifest_schema_requires_closed_input_boundary(
    tmp_path: Path, field: str
):
    """Catches a formal run manifest schema that leaves input closure optional."""
    candidate = np.array([1.0], dtype=np.float32)
    reference = np.array([1.0], dtype=np.float64)
    _adequacy_evidence(tmp_path, candidate, reference)
    manifest = json.loads(
        (tmp_path / "manifests" / "run-fp32.json").read_text(encoding="utf-8")
    )
    manifest.pop(field)
    schema = json.loads(
        Path("schemas/run_manifest.schema.json").read_text(encoding="utf-8")
    )

    errors = list(Draft202012Validator(schema).iter_errors(manifest))

    assert any(error.validator == "required" and field in error.message for error in errors)


@pytest.mark.parametrize(
    ("container", "field"),
    [
        ("manifest", "inputs_sha256"),
        ("outputs", "hdf5"),
        ("outputs", "receiver_dataset"),
        ("outputs", "receiver_dataset_sha256"),
    ],
)
def test_run_manifest_schema_requires_precision_evidence_bindings(
    tmp_path: Path, container: str, field: str
):
    """Catches schema-valid manifests that this precision gate must reject."""
    candidate = np.array([1.0], dtype=np.float32)
    reference = np.array([1.0], dtype=np.float64)
    _adequacy_evidence(tmp_path, candidate, reference)
    manifest = json.loads(
        (tmp_path / "manifests" / "run-fp32.json").read_text(encoding="utf-8")
    )
    target = manifest if container == "manifest" else manifest["outputs"]
    target.pop(field)
    schema = json.loads(
        Path("schemas/run_manifest.schema.json").read_text(encoding="utf-8")
    )

    errors = list(Draft202012Validator(schema).iter_errors(manifest))

    assert any(error.validator == "required" and field in error.message for error in errors)


def test_manifest_output_hash_is_recomputed_from_actual_run_dataset(tmp_path: Path):
    """Catches a reference run output changed after its manifest was recorded."""
    candidate = np.array([1.0], dtype=np.float32)
    reference = np.array([1.0], dtype=np.float64)
    with h5py.File(tmp_path / "adequacy.h5", "w") as handle:
        handle.create_dataset("candidate", data=candidate)
        handle.create_dataset("reference", data=reference)
    evidence = _adequacy_evidence(tmp_path, candidate, reference)
    with h5py.File(tmp_path / "runs" / "run-fp64.h5", "r+") as handle:
        handle["/rxs/rx1/Ez"][...] = np.array([2.0], dtype=np.float64)
    ctx = _context(
        tmp_path,
        values=candidate,
        numerics={
            "precision_requirement": "float32",
            "risk_flags": ["weak_differential"],
            "fp32_adequacy_evidence": evidence,
        },
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_FP32_ADEQUACY_EVIDENCE"


@pytest.mark.parametrize(
    ("field", "candidate_value", "reference_value"),
    [
        ("receiver_position_m", None, [0.0, 0.0, 1.0]),
        ("source_delay_s", None, 1e-9),
        ("sample_count", 1, True),
    ],
)
def test_matched_run_outputs_block_unprojected_key_or_json_type_changes(
    tmp_path: Path,
    field: str,
    candidate_value: object,
    reference_value: object,
):
    """Catches treating the entire outputs object as run-variant evidence."""
    candidate = np.array([1.0], dtype=np.float32)
    reference = np.array([1.0], dtype=np.float64)
    with h5py.File(tmp_path / "adequacy.h5", "w") as handle:
        handle.create_dataset("candidate", data=candidate)
        handle.create_dataset("reference", data=reference)
    evidence = _adequacy_evidence(tmp_path, candidate, reference)
    candidate_path = tmp_path / "manifests" / "run-fp32.json"
    reference_path = tmp_path / "manifests" / "run-fp64.json"
    candidate_manifest = json.loads(candidate_path.read_text(encoding="utf-8"))
    reference_manifest = json.loads(reference_path.read_text(encoding="utf-8"))
    if candidate_value is not None:
        candidate_manifest["outputs"][field] = candidate_value
    reference_manifest["outputs"][field] = reference_value
    candidate_path.write_text(json.dumps(candidate_manifest), encoding="utf-8")
    reference_path.write_text(json.dumps(reference_manifest), encoding="utf-8")
    ctx = _context(
        tmp_path,
        values=candidate,
        numerics={
            "precision_requirement": "float32",
            "risk_flags": ["coherent_phase"],
            "fp32_adequacy_evidence": evidence,
        },
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_FP32_ADEQUACY_EVIDENCE"


@pytest.mark.parametrize(
    ("target_name", "expected_code"),
    [
        ("run.h5", "BLOCK_OUTPUT_EVIDENCE"),
        ("adequacy.h5", "BLOCK_FP32_ADEQUACY_EVIDENCE"),
        ("run-fp32.json", "BLOCK_FP32_ADEQUACY_EVIDENCE"),
        ("model.in", "BLOCK_FP32_ADEQUACY_EVIDENCE"),
        ("run-fp64.h5", "BLOCK_FP32_ADEQUACY_EVIDENCE"),
    ],
)
def test_verified_open_blocks_file_identity_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_name: str,
    expected_code: str,
):
    """Catches path replacement or in-place mutation across a verified evidence read."""
    candidate = np.array([1.0], dtype=np.float32)
    reference = np.array([1.0], dtype=np.float64)
    with h5py.File(tmp_path / "adequacy.h5", "w") as handle:
        handle.create_dataset("candidate", data=candidate)
        handle.create_dataset("reference", data=reference)
    evidence = _adequacy_evidence(tmp_path, candidate, reference)
    ctx = _context(
        tmp_path,
        values=candidate,
        numerics={
            "precision_requirement": "float32",
            "risk_flags": ["weak_differential"],
            "fp32_adequacy_evidence": evidence,
        },
    )
    real_check = getattr(
        precision_module,
        "_file_identity_unchanged",
        lambda _path, _snapshots: True,
    )

    def injected_change(path: Path, snapshots: object) -> bool:
        if path.name == target_name:
            return False
        return real_check(path, snapshots)

    monkeypatch.setattr(
        precision_module,
        "_file_identity_unchanged",
        injected_change,
        raising=False,
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == expected_code


def test_overflowing_per_sample_tolerance_blocks_as_malformed_evidence(tmp_path: Path):
    """Catches infinite allclose tolerances turning any finite FP32 candidate into PASS."""
    candidate = np.array([np.finfo(np.float32).max], dtype=np.float32)
    reference = np.array([np.finfo(np.float64).max], dtype=np.float64)
    with h5py.File(tmp_path / "adequacy.h5", "w") as handle:
        handle.create_dataset("candidate", data=candidate)
        handle.create_dataset("reference", data=reference)
    ctx = _context(
        tmp_path,
        values=candidate,
        numerics={
            "precision_requirement": "float32",
            "risk_flags": ["coherent_phase"],
            "fp32_adequacy_evidence": _adequacy_evidence(
                tmp_path,
                candidate,
                reference,
                rtol=float(np.finfo(np.float64).max),
                atol=0.0,
            ),
        },
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_FP32_ADEQUACY_EVIDENCE"


@pytest.mark.parametrize("link_kind", ["external", "virtual"])
def test_fp32_comparison_rejects_dereferenced_sources_outside_project(
    tmp_path: Path, link_kind: str
):
    """Catches comparison links/VDS loading arrays from outside the evidence root."""
    project = tmp_path / "project"
    project.mkdir()
    candidate = np.array([1.0, 1.000001], dtype=np.float32)
    reference = np.array([1.0, 1.0000011], dtype=np.float64)
    _write_dataset(project / "run.h5", "/rxs/rx1/Ez", candidate)
    outside = tmp_path / "outside-candidate.h5"
    _write_dataset(outside, "/candidate", candidate)
    with h5py.File(project / "adequacy.h5", "w", libver="latest") as handle:
        if link_kind == "external":
            handle["candidate"] = h5py.ExternalLink(str(outside), "/candidate")
        else:
            layout = h5py.VirtualLayout(shape=candidate.shape, dtype=candidate.dtype)
            layout[:] = h5py.VirtualSource(
                str(outside), "/candidate", shape=candidate.shape
            )
            handle.create_virtual_dataset("candidate", layout)
        handle.create_dataset("reference", data=reference)
    ctx = GateContext(
        project,
        {
            "numerics": {
                "precision_requirement": "float32",
                "risk_flags": ["fine_delay_fit"],
                "fp32_adequacy_evidence": _adequacy_evidence(project, candidate, reference),
            },
            "outputs": {"hdf5": "run.h5", "receiver_dataset": "/rxs/rx1/Ez"},
        },
        artifacts={"environment": _runtime()},
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_FP32_ADEQUACY_EVIDENCE"


@pytest.mark.parametrize("external_role", ["candidate", "reference"])
def test_fp32_comparison_rejects_external_raw_storage_outside_project(
    tmp_path: Path, external_role: str
):
    """Catches local comparison datasets sourcing raw bytes outside project_root."""
    candidate = np.array([1.0, 1.000001], dtype=np.float32)
    reference = np.array([1.0, 1.0000011], dtype=np.float64)
    _write_dataset(tmp_path / "run.h5", "/rxs/rx1/Ez", candidate)
    with h5py.File(tmp_path / "adequacy.h5", "w") as handle:
        for role, values in (("candidate", candidate), ("reference", reference)):
            if role == external_role:
                stored = handle.create_dataset(
                    role,
                    shape=values.shape,
                    dtype=values.dtype,
                    external=[(str(tmp_path.parent / f"outside-{role}.raw"), 0, values.nbytes)],
                )
                stored[...] = values
            else:
                handle.create_dataset(role, data=values)
    ctx = GateContext(
        tmp_path,
        {
            "numerics": {
                "precision_requirement": "float32",
                "risk_flags": ["fine_delay_fit"],
                "fp32_adequacy_evidence": _legacy_self_attested_evidence(
                    candidate, reference
                ),
            },
            "outputs": {"hdf5": "run.h5", "receiver_dataset": "/rxs/rx1/Ez"},
        },
        artifacts={"environment": _runtime()},
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_FP32_ADEQUACY_EVIDENCE"


def test_differential_within_declared_ulp_safety_factor_blocks(tmp_path: Path):
    """Catches passing a residual whose median magnitude is still at the numeric floor."""
    total = np.array([1.0, 2.0], dtype=np.float32)
    differential = np.array([2.384185791015625e-7, 4.76837158203125e-7], dtype=np.float32)
    observed = {"total": total, "differential": differential}
    ctx = _context(
        tmp_path,
        values=total,
        numerics={"precision_requirement": "float32", "ulp_safety_factor": 4.0},
        artifacts={"environment": _runtime(), "precision_audit": observed},
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_PRECISION_FLOOR"
    assert ctx.artifacts["precision_audit"] is observed
    summary = ctx.artifacts["derived"]["precision"]["precision_floor"]
    assert summary == {
        "ratio": pytest.approx(2.0),
        "safety_factor": 4.0,
        "safety_factor_source": "contract",
        "status": "blocked",
    }


def test_default_ulp_margin_is_algorithmic_and_blocks_four_ulp_residual(tmp_path: Path):
    """Catches silently treating a missing safety factor as no precision-floor check."""
    total = np.array([1.0], dtype=np.float32)
    differential = np.array([4.76837158203125e-7], dtype=np.float32)
    ctx = _context(
        tmp_path,
        values=total,
        numerics={"precision_requirement": "float32"},
        artifacts={
            "environment": _runtime(),
            "precision_audit": {"total": total, "differential": differential},
        },
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_PRECISION_FLOOR"
    summary = ctx.artifacts["derived"]["precision"]["precision_floor"]
    assert summary["safety_factor"] == 8.0
    assert summary["safety_factor_source"] == "algorithmic_numerical_margin"


def test_contract_required_precision_audit_fails_closed_when_pair_is_missing(tmp_path: Path):
    """Catches a required ULP-floor audit being silently treated as optional evidence."""
    ctx = _context(
        tmp_path,
        numerics={"precision_requirement": "float32", "precision_audit_required": True},
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_PRECISION_AUDIT_EVIDENCE"


def test_required_outputs_precision_audit_fails_closed_when_pair_is_missing(tmp_path: Path):
    """Catches ignoring the repository's standard required-output declaration."""
    ctx = _context(tmp_path)
    ctx.contract["evidence"] = {"required_outputs": ["precision_audit"]}

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_PRECISION_AUDIT_EVIDENCE"


def test_precision_total_must_equal_the_actual_receiver_dataset(tmp_path: Path):
    """Catches arbitrary same-shaped totals manipulating the local ULP denominator."""
    receiver = np.array([1.0], dtype=np.float32)
    unrelated_total = np.array([1e-20], dtype=np.float32)
    differential = np.array([4.76837158203125e-7], dtype=np.float32)
    ctx = _context(
        tmp_path,
        values=receiver,
        numerics={"precision_requirement": "float32"},
        artifacts={
            "environment": _runtime(),
            "precision_audit": {
                "total": unrelated_total,
                "differential": differential,
            },
        },
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_PRECISION_AUDIT_EVIDENCE"


def test_safe_differential_passes_and_publishes_only_a_derived_summary(tmp_path: Path):
    """Catches mutation/replacement of observed evidence while publishing precision results."""
    total = np.array([1.0], dtype=np.float64)
    differential = np.array([2.220446049250313e-13], dtype=np.float64)
    environment = _runtime("float64", "complex128")
    observed = {"total": total, "differential": differential}
    artifacts: dict[str, object] = {
        "environment": environment,
        "precision_audit": observed,
        "derived": {"numerics": {"dt_s": 1e-12}},
    }
    ctx = _context(
        tmp_path,
        values=total,
        numerics={"precision_requirement": "float64", "ulp_safety_factor": 32.0},
        artifacts=artifacts,
    )

    result = audit_precision(ctx)

    assert result.state is GateState.PASS
    assert result.code == "PASS_PRECISION"
    assert ctx.artifacts["environment"] is environment
    assert ctx.artifacts["precision_audit"] is observed
    assert ctx.artifacts["derived"]["numerics"] == {"dt_s": 1e-12}
    summary = ctx.artifacts["derived"]["precision"]
    assert summary["output"] == {
        "path": "run.h5",
        "dataset": "/rxs/rx1/Ez",
        "dtype": "float64",
        "finite": True,
    }
    assert summary["runtime"] == {"real_dtype": "float64", "complex_dtype": "complex128"}
    assert summary["precision_floor"]["status"] == "pass"
    assert "total" not in summary and "differential" not in summary
