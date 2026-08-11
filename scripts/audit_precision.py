from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
import hashlib
from itertools import product
import json
import math
from numbers import Real
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
from typing import Any

import h5py
import numpy as np

from scripts.core import GateContext, GateResult, GateState
from scripts.gprmax_static_profile import (
    LEGACY_STATIC_DECK_PROFILE,
    validated_legacy_static_deck_profile,
)


_PRECISION_RISK_FLAGS = frozenset(
    {
        "weak_differential",
        "long_distance",
        "coherent_phase",
        "high_dynamic_range",
        "fine_delay_fit",
    }
)
_RUNTIME_DTYPE_PAIRS = {
    ("float32", "complex64"): 32,
    ("float64", "complex128"): 64,
}
_RUN_MANIFEST_ENVIRONMENT_FIELDS = (
    "gprmax_version",
    "banner",
    "import_path",
    "backend",
    "real_dtype",
    "complex_dtype",
)
_RUN_MANIFEST_PRECISION_DTYPES = {
    "float32": ("float32", "complex64"),
    "float64": ("float64", "complex128"),
}
_RUN_VARIANT_OUTPUT_FIELDS = frozenset({"hdf5", "receiver_dataset_sha256"})
_LEGACY_STATIC_DECK_COMMANDS = frozenset(
    {
        "domain",
        "dx_dy_dz",
        "time_window",
        "title",
        "messages",
        "num_threads",
        "time_step_stability_factor",
        "pml_formulation",
        "pml_cells",
        "excitation_file",
        "src_steps",
        "rx_steps",
        "taguchi",
        "end_taguchi",
        "output_dir",
        "geometry_view",
        "geometry_objects_write",
        "material",
        "soil_peplinski",
        "add_dispersion_debye",
        "add_dispersion_lorentz",
        "add_dispersion_drude",
        "waveform",
        "voltage_source",
        "hertzian_dipole",
        "magnetic_dipole",
        "transmission_line",
        "rx",
        "rx_array",
        "snapshot",
        "pml_cfs",
        "include_file",
        "geometry_objects_read",
        "edge",
        "plate",
        "triangle",
        "box",
        "sphere",
        "cylinder",
        "cylindrical_sector",
        "fractal_box",
        "add_surface_roughness",
        "add_surface_water",
        "add_grass",
    }
)
_DYNAMIC_DECK_COMMANDS = frozenset({"python", "end_python"})

# This is an algorithm-local rounding margin: a median residual at or below
# eight representable steps is too close to the storage dtype's quantization
# floor to establish a differential. It is not a physics, detection, or
# project-acceptance threshold. Projects may declare a larger or smaller
# ``numerics.ulp_safety_factor`` when their numerical error budget justifies it.
_DEFAULT_ULP_SAFETY_FACTOR = 8.0
_MAX_HDF5_BLOCK_ELEMENTS = 1_048_576


class _PrecisionAuditError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def local_ulp(values: np.ndarray) -> np.ndarray:
    """Return the absolute adjacent representable spacing in the input dtype.

    ULP is evaluated sample-by-sample without promoting FP32 totals to Python
    or NumPy FP64. The diagnostic is intentionally defined for real floating
    arrays because gprMax receiver time histories are real-valued datasets.
    """
    arr = np.asarray(values)
    if arr.dtype.kind != "f":
        raise ValueError("local_ulp requires a real floating-point array")
    return np.abs(np.spacing(arr))


def precision_floor_ratio(total: np.ndarray, differential: np.ndarray) -> float:
    """Return median ``abs(differential) / local_ulp(total)``.

    The total and differential must be aligned. Empty arrays have no observed
    floor and therefore return infinity; gate-level evidence validation rejects
    empty diagnostics before calling this helper.
    """
    total_array = np.asarray(total)
    differential_array = np.asarray(differential)
    if total_array.shape != differential_array.shape:
        raise ValueError("total and differential must have identical shapes")
    if differential_array.dtype.kind != "f":
        raise ValueError("differential must be a real floating-point array")
    ulp = local_ulp(total_array.astype(total_array.dtype, copy=False))
    mask = ulp > 0
    ratios = np.abs(differential_array[mask]) / ulp[mask]
    return float(np.nanmedian(ratios)) if ratios.size else float("inf")


def audit_precision(ctx: GateContext) -> GateResult:
    """Audit runtime/output precision, FP32 exceptions, and the local ULP floor."""
    report: dict[str, Any] = {}
    evidence: list[str] = []
    try:
        numerics = _mapping(ctx.contract.get("numerics"), "numerics", "BLOCK_PRECISION_CONTRACT")
        requirement = _precision_requirement(numerics)
        risk_flags = _risk_flags(ctx.contract, numerics)
        safety_factor, safety_factor_source = _ulp_safety_factor(numerics)
        precision_audit_required = _precision_audit_required(ctx.contract, numerics)
        report["policy"] = {
            "precision_requirement": requirement,
            "risk_flags": list(risk_flags),
            "fp64_required": requirement == "float64" or bool(risk_flags),
            "precision_audit_required": precision_audit_required,
        }

        output = _inspect_output(ctx)
        evidence.append(output["path"])
        report["output"] = {
            "path": output["path"],
            "dataset": output["dataset"],
            "dtype": output["dtype"],
            "finite": True,
        }
        if requirement == "float64" and output["component_bits"] < 64:
            raise _PrecisionAuditError(
                "BLOCK_OUTPUT_DTYPE",
                "precision_requirement float64 is not satisfied by the actual HDF5 receiver dtype",
            )

        runtime = _runtime_dtypes(ctx)
        report["runtime"] = {
            "real_dtype": runtime["real_dtype"],
            "complex_dtype": runtime["complex_dtype"],
        }
        if requirement == "float64" and runtime["component_bits"] < 64:
            raise _PrecisionAuditError(
                "BLOCK_RUNTIME_DTYPE",
                "precision_requirement float64 is not satisfied by runtime dtype evidence",
            )
        expected_output_dtype = runtime["real_dtype"]
        if output["dtype"] != expected_output_dtype:
            raise _PrecisionAuditError(
                "BLOCK_OUTPUT_DTYPE",
                f"actual HDF5 dtype {output['dtype']} does not match runtime {expected_output_dtype}",
            )

        if risk_flags and output["component_bits"] < 64:
            raw_adequacy = numerics.get("fp32_adequacy_evidence")
            if raw_adequacy is None:
                raise _PrecisionAuditError(
                    "BLOCK_FP64_REQUIRED",
                    "risk-flagged FP32 execution requires explicit passing FP32 adequacy evidence",
                )
            adequacy, adequacy_ref = _audit_fp32_adequacy(ctx, raw_adequacy, output)
            report["fp32_adequacy"] = adequacy
            evidence.append(adequacy_ref)
            if not adequacy["passed"]:
                raise _PrecisionAuditError(
                    "BLOCK_FP32_ADEQUACY",
                    "FP32 candidate does not pass the declared FP64 comparison tolerances",
                )
        else:
            report["fp32_adequacy"] = {"status": "not_required"}

        report["precision_floor"] = _audit_precision_floor(
            ctx,
            output,
            safety_factor,
            safety_factor_source,
            precision_audit_required,
        )
        if report["precision_floor"]["status"] == "blocked":
            raise _PrecisionAuditError(
                "BLOCK_PRECISION_FLOOR",
                "median differential is within the local ULP numerical safety margin",
            )
    except _PrecisionAuditError as error:
        publish_error = _try_publish(ctx, report)
        if publish_error is not None:
            error = publish_error
        return _result(GateState.BLOCK, error.code, str(error), evidence)
    except (OSError, TypeError, ValueError) as error:
        publish_error = _try_publish(ctx, report)
        if publish_error is not None:
            error = publish_error
        return _result(GateState.BLOCK, "BLOCK_PRECISION_EVIDENCE", str(error), evidence)

    publish_error = _try_publish(ctx, report)
    if publish_error is not None:
        return _result(GateState.BLOCK, publish_error.code, str(publish_error), evidence)
    return _result(
        GateState.PASS,
        "PASS_PRECISION",
        "runtime, HDF5 dtype, finiteness, and precision budget pass",
        evidence,
    )


def _precision_requirement(numerics: Mapping[str, Any]) -> str:
    value = numerics.get("precision_requirement")
    if not isinstance(value, str) or not value.strip():
        raise _PrecisionAuditError(
            "BLOCK_PRECISION_CONTRACT", "numerics.precision_requirement must be non-empty text"
        )
    normalized = value.strip().lower()
    if normalized not in {"auto", "float32", "float64"}:
        raise _PrecisionAuditError(
            "BLOCK_PRECISION_CONTRACT",
            "numerics.precision_requirement must be auto, float32, or float64",
        )
    return normalized


def _risk_flags(contract: Mapping[str, Any], numerics: Mapping[str, Any]) -> tuple[str, ...]:
    locations = [numerics.get("risk_flags")]
    if "risk_flags" in contract:
        locations.append(contract.get("risk_flags"))
    task = contract.get("task")
    if isinstance(task, Mapping) and "risk_flags" in task:
        locations.append(task.get("risk_flags"))

    flags: set[str] = set()
    for raw in locations:
        if raw is None:
            continue
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise _PrecisionAuditError(
                "BLOCK_PRECISION_CONTRACT", "risk_flags must be a sequence of strings"
            )
        for item in raw:
            if not isinstance(item, str) or not item.strip():
                raise _PrecisionAuditError(
                    "BLOCK_PRECISION_CONTRACT", "risk_flags must contain non-empty strings"
                )
            if item not in _PRECISION_RISK_FLAGS:
                raise _PrecisionAuditError(
                    "BLOCK_PRECISION_CONTRACT",
                    f"unsupported precision risk flag {item!r}",
                )
            flags.add(item)
    return tuple(sorted(flags))


def _ulp_safety_factor(numerics: Mapping[str, Any]) -> tuple[float, str]:
    raw = numerics.get("ulp_safety_factor")
    if raw is None:
        return _DEFAULT_ULP_SAFETY_FACTOR, "algorithmic_numerical_margin"
    value = _nonnegative_finite(
        raw, "numerics.ulp_safety_factor", "BLOCK_PRECISION_CONTRACT"
    )
    if value <= 0.0:
        raise _PrecisionAuditError(
            "BLOCK_PRECISION_CONTRACT", "numerics.ulp_safety_factor must be positive"
        )
    return value, "contract"


def _precision_audit_required(
    contract: Mapping[str, Any], numerics: Mapping[str, Any]
) -> bool:
    value = numerics.get("precision_audit_required", False)
    if not isinstance(value, bool):
        raise _PrecisionAuditError(
            "BLOCK_PRECISION_CONTRACT", "numerics.precision_audit_required must be boolean"
        )
    evidence = contract.get("evidence")
    if evidence is None:
        return value
    if not isinstance(evidence, Mapping):
        raise _PrecisionAuditError(
            "BLOCK_PRECISION_CONTRACT", "evidence must be a mapping when supplied"
        )
    required_outputs = evidence.get("required_outputs", ())
    if not isinstance(required_outputs, Sequence) or isinstance(required_outputs, (str, bytes)):
        raise _PrecisionAuditError(
            "BLOCK_PRECISION_CONTRACT", "evidence.required_outputs must be a sequence"
        )
    for item in required_outputs:
        if not isinstance(item, str) or not item.strip():
            raise _PrecisionAuditError(
                "BLOCK_PRECISION_CONTRACT",
                "evidence.required_outputs must contain non-empty strings",
            )
    return value or any(item.strip().lower() == "precision_audit" for item in required_outputs)


def _inspect_output(ctx: GateContext) -> dict[str, Any]:
    outputs = _mapping(ctx.contract.get("outputs"), "outputs", "BLOCK_OUTPUT_EVIDENCE")
    path_ref = _required_text(outputs, "hdf5", "outputs.hdf5", "BLOCK_OUTPUT_EVIDENCE")
    dataset_ref = _required_text(
        outputs, "receiver_dataset", "outputs.receiver_dataset", "BLOCK_OUTPUT_EVIDENCE"
    )
    path = _resolve_project_regular_file(
        ctx.project_root, path_ref.strip(), "BLOCK_OUTPUT_EVIDENCE"
    )
    try:
        with _open_verified_hdf5(
            path, "BLOCK_OUTPUT_EVIDENCE", "receiver HDF5 output"
        ) as handle:
            dataset = _local_nonvirtual_dataset(
                handle, dataset_ref, "BLOCK_OUTPUT_EVIDENCE", "receiver dataset"
            )
            dtype = np.dtype(dataset.dtype)
            if dtype.kind != "f" or dtype.name not in {"float32", "float64"}:
                raise _PrecisionAuditError(
                    "BLOCK_OUTPUT_DTYPE",
                    f"receiver dataset dtype {dtype} is not supported by the real-valued ULP audit",
                )
            if dataset.size == 0:
                raise _PrecisionAuditError(
                    "BLOCK_OUTPUT_EVIDENCE", "receiver dataset must contain samples"
                )
            if not _dataset_is_finite(dataset):
                raise _PrecisionAuditError(
                    "BLOCK_OUTPUT_NONFINITE", "receiver dataset contains non-finite samples"
                )
            shape = tuple(dataset.shape)
    except _PrecisionAuditError:
        raise
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise _PrecisionAuditError(
            "BLOCK_OUTPUT_EVIDENCE", f"HDF5 output is unreadable: {error}"
        ) from error
    return {
        "path": path_ref.strip(),
        "resolved": path,
        "dataset": dataset_ref.strip(),
        "dtype": dtype.name,
        "kind": dtype.kind,
        "component_bits": dtype.itemsize * 8,
        "shape": shape,
    }


def _runtime_dtypes(ctx: GateContext) -> dict[str, Any]:
    environment = ctx.artifacts.get("environment")
    if not isinstance(environment, Mapping):
        raise _PrecisionAuditError(
            "BLOCK_RUNTIME_DTYPE", "artifacts.environment runtime dtype evidence is required"
        )
    real_dtype = environment.get("real_dtype")
    complex_dtype = environment.get("complex_dtype")
    if not isinstance(real_dtype, str) or not isinstance(complex_dtype, str):
        raise _PrecisionAuditError(
            "BLOCK_RUNTIME_DTYPE", "runtime real_dtype and complex_dtype must be strings"
        )
    pair = (real_dtype.strip().lower(), complex_dtype.strip().lower())
    if pair not in _RUNTIME_DTYPE_PAIRS:
        raise _PrecisionAuditError(
            "BLOCK_RUNTIME_DTYPE",
            "runtime dtype evidence must be a consistent float32/complex64 or float64/complex128 pair",
        )
    return {
        "real_dtype": pair[0],
        "complex_dtype": pair[1],
        "component_bits": _RUNTIME_DTYPE_PAIRS[pair],
    }


def _audit_fp32_adequacy(
    ctx: GateContext, raw: object, output: Mapping[str, Any]
) -> tuple[dict[str, Any], str]:
    evidence = _mapping(
        raw, "numerics.fp32_adequacy_evidence", "BLOCK_FP32_ADEQUACY_EVIDENCE"
    )
    fixture_ref = _required_text(
        evidence,
        "comparison_fixture",
        "numerics.fp32_adequacy_evidence.comparison_fixture",
        "BLOCK_FP32_ADEQUACY_EVIDENCE",
    )
    candidate_ref = _required_text(
        evidence,
        "fp32_dataset",
        "numerics.fp32_adequacy_evidence.fp32_dataset",
        "BLOCK_FP32_ADEQUACY_EVIDENCE",
    )
    reference_ref = _required_text(
        evidence,
        "fp64_dataset",
        "numerics.fp32_adequacy_evidence.fp64_dataset",
        "BLOCK_FP32_ADEQUACY_EVIDENCE",
    )
    rtol = _nonnegative_finite(
        evidence.get("rtol"), "fp32 adequacy rtol", "BLOCK_FP32_ADEQUACY_EVIDENCE"
    )
    atol = _nonnegative_finite(
        evidence.get("atol"), "fp32 adequacy atol", "BLOCK_FP32_ADEQUACY_EVIDENCE"
    )
    fixture_path = _resolve_project_regular_file(
        ctx.project_root,
        fixture_ref.strip(),
        "BLOCK_FP32_ADEQUACY_EVIDENCE",
    )
    if fixture_path == output["resolved"]:
        raise _PrecisionAuditError(
            "BLOCK_FP32_ADEQUACY_EVIDENCE",
            "FP32 adequacy comparison fixture must be independent of the audited output",
        )
    try:
        with _open_verified_hdf5(
            fixture_path,
            "BLOCK_FP32_ADEQUACY_EVIDENCE",
            "FP32 adequacy fixture",
        ) as handle:
            candidate_dataset = _local_nonvirtual_dataset(
                handle,
                candidate_ref,
                "BLOCK_FP32_ADEQUACY_EVIDENCE",
                "FP32 candidate dataset",
            )
            reference_dataset = _local_nonvirtual_dataset(
                handle,
                reference_ref,
                "BLOCK_FP32_ADEQUACY_EVIDENCE",
                "FP64 reference dataset",
            )
            if np.dtype(candidate_dataset.dtype).name != "float32" or np.dtype(
                reference_dataset.dtype
            ).name != "float64":
                raise _PrecisionAuditError(
                    "BLOCK_FP32_ADEQUACY_EVIDENCE",
                    "adequacy fixture requires an FP32 candidate and FP64 reference",
                )
            if candidate_dataset.shape != reference_dataset.shape or candidate_dataset.size == 0:
                raise _PrecisionAuditError(
                    "BLOCK_FP32_ADEQUACY_EVIDENCE",
                    "FP32 candidate and FP64 reference must be non-empty and shape-aligned",
                )
            if not _candidate_equals_audited_output(candidate_dataset, output):
                raise _PrecisionAuditError(
                    "BLOCK_FP32_ADEQUACY_EVIDENCE",
                    "FP32 candidate must exactly equal the actual audited receiver dataset",
                )
            candidate_hash = _dataset_sha256(candidate_dataset)
            reference_hash = _dataset_sha256(reference_dataset)
            matched_run = _matched_run_manifests(
                ctx,
                evidence,
                candidate_hash,
                reference_hash,
            )
            passed, max_abs_error, max_relative_error = _compare_adequacy_datasets(
                candidate_dataset, reference_dataset, rtol, atol
            )
    except _PrecisionAuditError:
        raise
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise _PrecisionAuditError(
            "BLOCK_FP32_ADEQUACY_EVIDENCE", f"FP32 adequacy fixture is unreadable: {error}"
        ) from error
    return (
        {
            "status": "pass" if passed else "blocked",
            "passed": passed,
            "comparison_fixture": fixture_ref.strip(),
            "fp32_dataset": candidate_ref.strip(),
            "fp64_dataset": reference_ref.strip(),
            "rtol": rtol,
            "atol": atol,
            "max_abs_error": max_abs_error,
            "max_relative_error": max_relative_error,
            "matched_run": {
                "candidate_run_id": matched_run["candidate_run_id"],
                "reference_run_id": matched_run["reference_run_id"],
                "candidate_manifest": matched_run["candidate_manifest"],
                "reference_manifest": matched_run["reference_manifest"],
                "input_root": matched_run["input_root"],
                "primary_input": matched_run["primary_input"],
                "static_deck_profile": matched_run["static_deck_profile"],
                "dependencies": list(matched_run["dependencies"]),
                "dependency_count": matched_run["dependency_count"],
                "geometry_hdf5_dependencies": list(
                    matched_run["geometry_hdf5_dependencies"]
                ),
                "inputs_sha256": matched_run["inputs_sha256"],
                "candidate_precision": "float32",
                "reference_precision": "float64",
                "derived_change_projection": [
                    "numerics.precision",
                    "environment.real_dtype",
                    "environment.complex_dtype",
                ],
                "candidate_dataset_sha256": candidate_hash,
                "reference_dataset_sha256": reference_hash,
            },
        },
        fixture_ref.strip(),
    )


def _matched_run_manifests(
    ctx: GateContext,
    evidence: Mapping[str, Any],
    candidate_dataset_sha256: str,
    reference_dataset_sha256: str,
) -> dict[str, Any]:
    code = "BLOCK_FP32_ADEQUACY_EVIDENCE"
    matched = _mapping(
        evidence.get("matched_run"),
        "numerics.fp32_adequacy_evidence.matched_run",
        code,
    )
    required_keys = {"candidate_manifest", "reference_manifest"}
    if set(matched) != required_keys:
        raise _PrecisionAuditError(
            code,
            "matched_run must contain only candidate_manifest and reference_manifest",
        )
    candidate_ref = _canonical_project_relative_posix_path(
        _required_text(
            matched, "candidate_manifest", "matched_run.candidate_manifest", code
        ),
        "matched_run.candidate_manifest",
        code,
    )
    reference_ref = _canonical_project_relative_posix_path(
        _required_text(
            matched, "reference_manifest", "matched_run.reference_manifest", code
        ),
        "matched_run.reference_manifest",
        code,
    )
    candidate_path = _resolve_project_regular_file(ctx.project_root, candidate_ref, code)
    reference_path = _resolve_project_regular_file(ctx.project_root, reference_ref, code)
    if candidate_path == reference_path:
        raise _PrecisionAuditError(code, "matched-run manifests must be distinct files")

    candidate = _validated_run_manifest(
        ctx,
        candidate_path,
        expected_precision="float32",
        expected_dataset_sha256=candidate_dataset_sha256,
    )
    reference = _validated_run_manifest(
        ctx,
        reference_path,
        expected_precision="float64",
        expected_dataset_sha256=reference_dataset_sha256,
    )
    actual_environment = _mapping(
        ctx.artifacts.get("environment"),
        "artifacts.environment",
        code,
    )
    if not _strict_json_equal(candidate["environment"], actual_environment):
        raise _PrecisionAuditError(
            code,
            "FP32 run manifest environment must exactly match actual runtime evidence",
        )
    if candidate["run_id"] == reference["run_id"]:
        raise _PrecisionAuditError(code, "matched FP32 and FP64 manifests need distinct run IDs")
    if candidate["input_root"] != reference["input_root"]:
        raise _PrecisionAuditError(code, "matched-run input_root values must be identical")
    if candidate["primary_input"] != reference["primary_input"]:
        raise _PrecisionAuditError(code, "matched-run primary_input values must be identical")
    try:
        shared_output = candidate["output_path"].samefile(reference["output_path"])
    except OSError as error:
        raise _PrecisionAuditError(
            code, "matched-run output identity could not be verified"
        ) from error
    if shared_output:
        raise _PrecisionAuditError(code, "matched runs must have distinct HDF5 output files")
    if candidate["receiver_dataset"] != reference["receiver_dataset"]:
        raise _PrecisionAuditError(
            code, "matched runs must bind the same receiver dataset path"
        )
    if not _strict_json_equal(
        candidate["stable_outputs"], reference["stable_outputs"]
    ):
        raise _PrecisionAuditError(
            code,
            "matched-run outputs may differ only in HDF5 path and receiver hash",
        )
    if candidate["inputs"] != reference["inputs"]:
        raise _PrecisionAuditError(code, "matched-run canonical input hash maps must be identical")
    if candidate["inputs_sha256"] != reference["inputs_sha256"]:
        raise _PrecisionAuditError(code, "matched-run canonical input-set hashes must be identical")
    if candidate["dependencies"] != reference["dependencies"]:
        raise _PrecisionAuditError(
            code, "matched-run static dependency closures must be identical"
        )
    if not _strict_json_equal(
        candidate["geometry_hdf5_dependencies"],
        reference["geometry_hdf5_dependencies"],
    ):
        raise _PrecisionAuditError(
            code, "matched-run geometry HDF5 dataset closures must be identical"
        )
    if not _strict_json_equal(
        candidate["nonprecision_numerics"], reference["nonprecision_numerics"]
    ):
        raise _PrecisionAuditError(
            code, "matched-run numerics may differ only in precision"
        )
    if not _strict_json_equal(
        candidate["nonprecision_environment"],
        reference["nonprecision_environment"],
    ):
        raise _PrecisionAuditError(
            code,
            "matched-run environment may differ only in real_dtype and complex_dtype",
        )
    if candidate["command"] != reference["command"]:
        raise _PrecisionAuditError(code, "matched-run commands must be identical")
    if not _strict_json_equal(
        candidate["stable_metadata"], reference["stable_metadata"]
    ):
        raise _PrecisionAuditError(
            code, "matched-run metadata outside the allowed run projection must be identical"
        )
    return {
        "candidate_run_id": candidate["run_id"],
        "reference_run_id": reference["run_id"],
        "candidate_manifest": candidate_ref,
        "reference_manifest": reference_ref,
        "input_root": candidate["input_root"],
        "primary_input": candidate["primary_input"],
        "static_deck_profile": dict(LEGACY_STATIC_DECK_PROFILE),
        "dependencies": candidate["dependencies"],
        "dependency_count": len(candidate["dependencies"]),
        "geometry_hdf5_dependencies": candidate[
            "geometry_hdf5_dependencies"
        ],
        "inputs_sha256": candidate["inputs_sha256"],
    }


def _validated_run_manifest(
    ctx: GateContext,
    path: Path,
    *,
    expected_precision: str,
    expected_dataset_sha256: str,
) -> dict[str, Any]:
    code = "BLOCK_FP32_ADEQUACY_EVIDENCE"
    manifest = _read_strict_json_object(path, code)
    raw_run_id = _required_text(manifest, "run_id", "run manifest run_id", code)
    run_id = raw_run_id.strip()
    if raw_run_id != run_id or path.stem != run_id:
        raise _PrecisionAuditError(
            code, "run manifest run_id must exactly match its manifest filename"
        )
    _required_text(manifest, "started_at", "run manifest started_at", code)
    _required_text(manifest, "finished_at", "run manifest finished_at", code)
    return_code = manifest.get("return_code")
    if isinstance(return_code, bool) or not isinstance(return_code, int) or return_code != 0:
        raise _PrecisionAuditError(code, "matched-run manifest return_code must be integer zero")

    numerics = _mapping(manifest.get("numerics"), "run manifest numerics", code)
    precision = _required_text(
        numerics, "precision", "run manifest numerics.precision", code
    ).strip()
    if precision != expected_precision:
        raise _PrecisionAuditError(
            code, f"run manifest precision must be exactly {expected_precision}"
        )
    nonprecision_numerics = dict(numerics)
    nonprecision_numerics.pop("precision")
    environment_evidence = _validated_manifest_environment(
        manifest, expected_precision, code
    )
    command = _validated_manifest_command(manifest, code)
    input_root = _canonical_project_relative_posix_path(
        _required_text(manifest, "input_root", "run manifest input_root", code),
        "run manifest input_root",
        code,
    )
    primary_input = _canonical_project_relative_posix_path(
        _required_text(
            manifest, "primary_input", "run manifest primary_input", code
        ),
        "run manifest primary_input",
        code,
    )
    root_parts = PurePosixPath(input_root).parts
    primary_parts = PurePosixPath(primary_input).parts
    if (
        len(primary_parts) <= len(root_parts)
        or primary_parts[: len(root_parts)] != root_parts
    ):
        raise _PrecisionAuditError(
            code, "run manifest primary_input must be a file within input_root"
        )
    if command.count(primary_input) != 1:
        raise _PrecisionAuditError(
            code, "run manifest command must reference primary_input exactly once"
        )
    run_variant_fields = {
        "run_id",
        "environment",
        "command",
        "return_code",
        "numerics",
        "inputs",
        "inputs_sha256",
        "outputs",
        "started_at",
        "finished_at",
    }
    stable_metadata = {
        key: value for key, value in manifest.items() if key not in run_variant_fields
    }

    inputs = _validated_manifest_inputs(
        ctx.project_root, manifest, input_root, primary_input, code
    )
    inputs_sha256 = _required_sha256(manifest, "inputs_sha256", "run manifest inputs_sha256")
    if inputs_sha256 != _canonical_hash_map_sha256(inputs):
        raise _PrecisionAuditError(
            code, "run manifest canonical input-set SHA-256 does not match its input map"
        )
    dependencies, geometry_hdf5_dependencies = _audit_static_dependency_closure(
        ctx.project_root,
        input_root,
        primary_input,
        inputs,
        code,
    )

    outputs = _mapping(manifest.get("outputs"), "run manifest outputs", code)
    hdf5_ref = _canonical_project_relative_posix_path(
        _required_text(outputs, "hdf5", "run manifest outputs.hdf5", code),
        "run manifest outputs.hdf5",
        code,
    )
    dataset_ref = _required_text(
        outputs,
        "receiver_dataset",
        "run manifest outputs.receiver_dataset",
        code,
    )
    if dataset_ref != dataset_ref.strip():
        raise _PrecisionAuditError(
            code, "run manifest outputs.receiver_dataset must be exact text"
        )
    declared_dataset_hash = _required_sha256(
        outputs,
        "receiver_dataset_sha256",
        "run manifest outputs.receiver_dataset_sha256",
    )
    output_path = _resolve_project_regular_file(ctx.project_root, hdf5_ref, code)
    stable_outputs = {
        key: value
        for key, value in outputs.items()
        if key not in _RUN_VARIANT_OUTPUT_FIELDS and key != "receiver_dataset"
    }
    try:
        with _open_verified_hdf5(
            output_path, code, "matched-run HDF5 output"
        ) as handle:
            dataset = _local_nonvirtual_dataset(
                handle, dataset_ref, code, "matched-run receiver dataset"
            )
            actual_dataset_hash = _dataset_sha256(dataset)
    except _PrecisionAuditError:
        raise
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise _PrecisionAuditError(code, f"matched-run HDF5 output is unreadable: {error}") from error
    if declared_dataset_hash != actual_dataset_hash:
        raise _PrecisionAuditError(code, "run manifest receiver dataset SHA-256 is incorrect")
    if actual_dataset_hash != expected_dataset_sha256:
        raise _PrecisionAuditError(
            code, "run manifest receiver dataset does not match comparison evidence"
        )
    return {
        "run_id": run_id,
        "input_root": input_root,
        "primary_input": primary_input,
        "inputs": inputs,
        "inputs_sha256": inputs_sha256,
        "dependencies": dependencies,
        "geometry_hdf5_dependencies": geometry_hdf5_dependencies,
        "nonprecision_numerics": nonprecision_numerics,
        "environment": environment_evidence["environment"],
        "nonprecision_environment": environment_evidence["nonprecision"],
        "command": command,
        "output_path": output_path,
        "receiver_dataset": dataset_ref,
        "stable_outputs": stable_outputs,
        "stable_metadata": stable_metadata,
    }


def _validated_manifest_environment(
    manifest: Mapping[str, Any], expected_precision: str, code: str
) -> dict[str, Any]:
    environment = _mapping(
        manifest.get("environment"), "run manifest environment", code
    )
    for field in _RUN_MANIFEST_ENVIRONMENT_FIELDS:
        _required_text(
            environment,
            field,
            f"run manifest environment.{field}",
            code,
        )
    expected_real, expected_complex = _RUN_MANIFEST_PRECISION_DTYPES[
        expected_precision
    ]
    if (
        environment["real_dtype"] != expected_real
        or environment["complex_dtype"] != expected_complex
    ):
        raise _PrecisionAuditError(
            code,
            "run manifest environment dtypes do not match its declared precision",
        )
    try:
        profile = validated_legacy_static_deck_profile(
            environment.get("static_deck_profile")
        )
    except ValueError as error:
        raise _PrecisionAuditError(
            code, f"run manifest {error}"
        ) from error
    if environment["gprmax_version"] != profile["internal_version"]:
        raise _PrecisionAuditError(
            code,
            "run manifest gprmax_version must match the reviewed static deck profile",
        )
    return {
        "environment": dict(environment),
        "nonprecision": {
            key: value
            for key, value in environment.items()
            if key not in {"real_dtype", "complex_dtype"}
        },
    }


def _validated_manifest_command(
    manifest: Mapping[str, Any], code: str
) -> tuple[str, ...]:
    command = manifest.get("command")
    if not isinstance(command, list) or any(
        not isinstance(argument, str) for argument in command
    ):
        raise _PrecisionAuditError(
            code, "run manifest command must be a JSON array of strings"
        )
    return tuple(command)


def _validated_manifest_inputs(
    project_root: Path,
    manifest: Mapping[str, Any],
    input_root: str,
    primary_input: str,
    code: str,
) -> dict[str, str]:
    raw = _mapping(manifest.get("inputs"), "run manifest inputs", code)
    if not raw:
        raise _PrecisionAuditError(code, "run manifest inputs must be non-empty")
    declared: dict[str, str] = {}
    for path_ref, declared_hash in raw.items():
        canonical_ref = _canonical_project_relative_posix_path(
            path_ref, "run manifest input path", code
        )
        normalized_hash = _sha256_text(
            declared_hash, f"run manifest inputs[{path_ref!r}]", code
        )
        declared[canonical_ref] = normalized_hash
    if primary_input not in declared:
        raise _PrecisionAuditError(code, "run manifest inputs must contain primary_input")
    actual = _inventory_input_root(project_root, input_root, code)
    if declared != actual:
        raise _PrecisionAuditError(
            code,
            "run manifest inputs must exactly match the complete input_root inventory",
        )
    return actual


def _audit_static_dependency_closure(
    project_root: Path,
    input_root: str,
    primary_input: str,
    inventory: Mapping[str, str],
    code: str,
) -> tuple[tuple[str, ...], tuple[dict[str, Any], ...]]:
    """Prove file closure for the supported legacy static gprMax deck profile.

    The solver historically tries the process working directory before the input
    directory for file commands. FP32 exception evidence deliberately removes
    that ambiguity: every dependency token must be an exact, canonical,
    project-root-relative POSIX path beneath ``input_root``.
    """
    root_parts = PurePosixPath(input_root).parts
    dependencies: set[str] = {primary_input}
    geometry_hdf5_dependencies: list[dict[str, Any]] = []
    active_includes: list[str] = []

    def bind_dependency(token: str, label: str) -> tuple[str, Path]:
        canonical_ref = _canonical_project_relative_posix_path(token, label, code)
        parts = PurePosixPath(canonical_ref).parts
        if len(parts) <= len(root_parts) or parts[: len(root_parts)] != root_parts:
            raise _PrecisionAuditError(
                code, f"{label} must remain within run manifest input_root"
            )
        declared_hash = inventory.get(canonical_ref)
        if declared_hash is None:
            raise _PrecisionAuditError(
                code, f"{label} must be present in the verified input_root inventory"
            )
        path = _resolve_project_regular_file(project_root, canonical_ref, code)
        if _file_sha256(path, code) != declared_hash:
            raise _PrecisionAuditError(
                code, f"{label} changed after input_root inventory verification"
            )
        return canonical_ref, path

    def add_dependency(
        token: str,
        label: str,
        *,
        include: bool = False,
        geometry_hdf5: bool = False,
    ) -> None:
        canonical_ref, path = bind_dependency(token, label)
        if canonical_ref in active_includes:
            raise _PrecisionAuditError(code, "static deck include cycle detected")
        if canonical_ref in dependencies:
            raise _PrecisionAuditError(code, "static deck dependency is referenced twice")
        dependencies.add(canonical_ref)
        if include:
            visit_deck(canonical_ref, path)
        elif geometry_hdf5:
            geometry_hdf5_dependencies.append(
                _verified_geometry_hdf5_dependency(
                    path,
                    canonical_ref,
                    inventory[canonical_ref],
                    code,
                )
            )

    def visit_deck(deck_ref: str, path: Path) -> None:
        active_includes.append(deck_ref)
        try:
            with _open_verified_binary_file(path, code, "static gprMax input deck") as handle:
                payload = handle.read()
            if hashlib.sha256(payload).hexdigest() != inventory[deck_ref]:
                raise _PrecisionAuditError(
                    code, "static gprMax input deck changed after inventory verification"
                )
            try:
                text = payload.decode("utf-8-sig")
            except UnicodeDecodeError as error:
                raise _PrecisionAuditError(
                    code, "static gprMax input deck must be UTF-8 or UTF-8 with BOM"
                ) from error

            for line_number, raw_line in enumerate(text.splitlines(), start=1):
                line = raw_line.strip()
                if not line or line.startswith("##") or not line.startswith("#"):
                    continue
                command_token, separator, arguments = line.partition(":")
                command = command_token[1:]
                if not separator or not command:
                    raise _PrecisionAuditError(
                        code,
                        f"malformed static deck command at {deck_ref}:{line_number}",
                    )
                if command in _DYNAMIC_DECK_COMMANDS:
                    raise _PrecisionAuditError(
                        code, "dynamic Python deck commands cannot prove static file closure"
                    )
                if command not in _LEGACY_STATIC_DECK_COMMANDS:
                    raise _PrecisionAuditError(
                        code,
                        f"unsupported command #{command}: cannot prove static file closure",
                    )

                tokens = arguments.split()
                location = f"{deck_ref}:{line_number} #{command}"
                if command == "include_file":
                    if len(tokens) != 1:
                        raise _PrecisionAuditError(
                            code, "#include_file requires exactly one file token"
                        )
                    add_dependency(tokens[0], location, include=True)
                elif command == "geometry_objects_read":
                    if len(tokens) != 5:
                        raise _PrecisionAuditError(
                            code, "#geometry_objects_read requires exactly five parameters"
                        )
                    add_dependency(
                        tokens[3],
                        f"{location} geometry file",
                        geometry_hdf5=True,
                    )
                    add_dependency(tokens[4], f"{location} materials file")
                elif command == "excitation_file":
                    if len(tokens) not in {1, 3}:
                        raise _PrecisionAuditError(
                            code, "#excitation_file requires exactly one or three parameters"
                        )
                    add_dependency(tokens[0], f"{location} excitation file")
        finally:
            active_includes.pop()

    primary_ref, primary_path = bind_dependency(
        primary_input, "run manifest primary_input"
    )
    visit_deck(primary_ref, primary_path)
    return (
        tuple(sorted(dependencies)),
        tuple(
            sorted(
                geometry_hdf5_dependencies,
                key=lambda item: item["container_path"],
            )
        ),
    )


def _verified_geometry_hdf5_dependency(
    path: Path,
    container_ref: str,
    container_sha256: str,
    code: str,
) -> dict[str, Any]:
    """Bind every dataset the reviewed geometry reader can load."""
    optional_paths = ("/rigidE", "/rigidH", "/ID")
    try:
        with _open_verified_binary_file(
            path, code, "geometry objects HDF5 input"
        ) as raw:
            digest = hashlib.sha256()
            while block := raw.read(_MAX_HDF5_BLOCK_ELEMENTS):
                digest.update(block)
            if digest.hexdigest() != container_sha256:
                raise _PrecisionAuditError(
                    code, "geometry HDF5 container changed after inventory verification"
                )
            raw.seek(0)
            with h5py.File(raw, "r", driver="fileobj") as handle:
                present = tuple(
                    handle.get(dataset_ref, getlink=True) is not None
                    for dataset_ref in optional_paths
                )
                if any(present) and not all(present):
                    raise _PrecisionAuditError(
                        code,
                        "geometry HDF5 rigidE, rigidH, and ID datasets must be all present or all absent",
                    )
                dataset_paths = ("/data",) + (
                    optional_paths if all(present) else ()
                )
                datasets: list[dict[str, str]] = []
                for dataset_ref in dataset_paths:
                    dataset = _local_nonvirtual_dataset(
                        handle,
                        dataset_ref,
                        code,
                        f"geometry HDF5 dataset {dataset_ref}",
                    )
                    if dataset.size == 0:
                        raise _PrecisionAuditError(
                            code,
                            f"geometry HDF5 dataset {dataset_ref} must be non-empty",
                        )
                    datasets.append(
                        {
                            "dataset_path": dataset_ref,
                            "sha256": _dataset_sha256(dataset),
                        }
                    )
    except _PrecisionAuditError:
        raise
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise _PrecisionAuditError(
            code, f"geometry HDF5 dependency is unreadable: {error}"
        ) from error
    return {
        "container_path": container_ref,
        "container_sha256": container_sha256,
        "datasets": datasets,
    }


def _canonical_project_relative_posix_path(
    value: object, label: str, code: str
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(character.isspace() for character in value)
        or "\\" in value
    ):
        raise _PrecisionAuditError(
            code, f"{label} must be a canonical project-relative POSIX path"
        )
    parts = value.split("/")
    if (
        PurePosixPath(value).is_absolute()
        or PureWindowsPath(value).drive
        or any(not part or part in {".", ".."} for part in parts)
    ):
        raise _PrecisionAuditError(
            code, f"{label} must be a canonical project-relative POSIX path"
        )
    return value


def _inventory_input_root(
    project_root: Path, input_root_ref: str, code: str
) -> dict[str, str]:
    root = _resolve_project_directory(project_root, input_root_ref, code)
    resolved_project = project_root.resolve(strict=True)
    inventory: dict[str, str] = {}
    identities: dict[tuple[int, int], str] = {}
    identity_fallback_paths: list[Path] = []

    def visit(directory: Path) -> None:
        try:
            with os.scandir(directory) as scanned:
                entries = sorted(scanned, key=lambda entry: entry.name)
        except OSError as error:
            raise _PrecisionAuditError(
                code, f"input_root {input_root_ref!r} could not be enumerated"
            ) from error
        for entry in entries:
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise _PrecisionAuditError(
                    code, f"input_root entry {entry.path!r} could not be inspected"
                ) from error
            file_attributes = getattr(metadata, "st_file_attributes", 0)
            reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            if stat.S_ISLNK(metadata.st_mode) or file_attributes & reparse_flag:
                raise _PrecisionAuditError(
                    code, "input_root must not contain symlinks or reparse points"
                )
            path = Path(entry.path)
            if stat.S_ISDIR(metadata.st_mode):
                visit(path)
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise _PrecisionAuditError(
                    code, "input_root may contain only ordinary files and directories"
                )
            canonical_ref = _canonical_project_relative_posix_path(
                path.relative_to(resolved_project).as_posix(),
                "input_root inventory path",
                code,
            )
            identity = (metadata.st_dev, metadata.st_ino)
            try:
                duplicate_identity = (
                    identity in identities
                    if metadata.st_ino
                    else any(path.samefile(other) for other in identity_fallback_paths)
                )
            except OSError as error:
                raise _PrecisionAuditError(
                    code, "input_root file identity could not be verified"
                ) from error
            if duplicate_identity:
                raise _PrecisionAuditError(
                    code,
                    "input_root contains duplicate paths for one resolved file identity",
                )
            if metadata.st_ino:
                identities[identity] = canonical_ref
            else:
                identity_fallback_paths.append(path)
            inventory[canonical_ref] = _file_sha256(path, code)
    visit(root)
    return inventory


def _canonical_hash_map_sha256(value: Mapping[str, str]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _strict_json_equal(left: object, right: object) -> bool:
    def canonical(value: object) -> str:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    return canonical(left) == canonical(right)


def _file_sha256(path: Path, code: str) -> str:
    digest = hashlib.sha256()
    with _open_verified_binary_file(path, code, "manifest input") as handle:
        while block := handle.read(_MAX_HDF5_BLOCK_ELEMENTS):
            digest.update(block)
    return digest.hexdigest()


def _read_strict_json_object(path: Path, code: str) -> Mapping[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON key {key!r}")
            value[key] = item
        return value

    def reject_nonfinite_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant {value}")

    try:
        with _open_verified_binary_file(path, code, "run manifest") as handle:
            payload = handle.read().decode("utf-8")
        parsed = json.loads(
            payload,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite_constant,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise _PrecisionAuditError(code, f"run manifest is not strict JSON: {error}") from error
    if not isinstance(parsed, Mapping):
        raise _PrecisionAuditError(code, "run manifest must be a JSON object")
    return parsed


def _file_fingerprint(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        int(metadata.st_dev),
        int(metadata.st_ino),
        stat.S_IFMT(metadata.st_mode),
        int(metadata.st_size),
        int(metadata.st_mtime_ns),
    )


def _file_identity_unchanged(
    path: Path, snapshots: Sequence[os.stat_result]
) -> bool:
    del path  # Retained as an injectable boundary for deterministic race regressions.
    return (
        bool(snapshots)
        and all(stat.S_ISREG(item.st_mode) for item in snapshots)
        and len({_file_fingerprint(item) for item in snapshots}) == 1
    )


def _verified_path_stat(path: Path, code: str, label: str) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise _PrecisionAuditError(code, f"{label} identity could not be inspected") from error
    file_attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if (
        stat.S_ISLNK(metadata.st_mode)
        or file_attributes & reparse_flag
        or not stat.S_ISREG(metadata.st_mode)
    ):
        raise _PrecisionAuditError(
            code, f"{label} must remain an ordinary non-reparse file"
        )
    return metadata


@contextmanager
def _open_verified_binary_file(
    path: Path, code: str, label: str
) -> Iterator[Any]:
    descriptor: int | None = None
    raw: Any | None = None
    try:
        before = _verified_path_stat(path, code, label)
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        after_open = _verified_path_stat(path, code, label)
        if not _file_identity_unchanged(path, (before, opened, after_open)):
            raise _PrecisionAuditError(code, f"{label} identity changed while opening")
        raw = os.fdopen(descriptor, "rb", buffering=0)
        descriptor = None
        try:
            yield raw
        finally:
            final_open = os.fstat(raw.fileno())
            final_path = _verified_path_stat(path, code, label)
            unchanged = _file_identity_unchanged(
                path, (opened, final_open, final_path)
            )
            raw.close()
            raw = None
            if not unchanged:
                raise _PrecisionAuditError(
                    code, f"{label} identity changed while reading"
                )
    except _PrecisionAuditError:
        raise
    except OSError as error:
        raise _PrecisionAuditError(code, f"{label} could not be read safely: {error}") from error
    finally:
        if raw is not None:
            raw.close()
        if descriptor is not None:
            os.close(descriptor)


@contextmanager
def _open_verified_hdf5(
    path: Path, code: str, label: str
) -> Iterator[h5py.File]:
    with _open_verified_binary_file(path, code, label) as raw:
        with h5py.File(raw, "r", driver="fileobj") as handle:
            yield handle


def _resolve_project_regular_file(project_root: Path, path_ref: str, code: str) -> Path:
    try:
        root = project_root.resolve(strict=True)
        raw_path = Path(path_ref)
        candidate = raw_path if raw_path.is_absolute() else root / raw_path
        lexical = Path(os.path.abspath(candidate))
        relative = lexical.relative_to(root)
        current = root
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        for part in relative.parts:
            current = current / part
            metadata = current.lstat()
            file_attributes = getattr(metadata, "st_file_attributes", 0)
            if stat.S_ISLNK(metadata.st_mode) or file_attributes & reparse_flag:
                raise _PrecisionAuditError(
                    code, f"evidence path {path_ref!r} must not traverse symlinks or reparse points"
                )
        resolved = lexical.resolve(strict=True)
        resolved.relative_to(root)
        if not stat.S_ISREG(resolved.stat().st_mode):
            raise _PrecisionAuditError(code, f"evidence path {path_ref!r} must be a regular file")
        return resolved
    except _PrecisionAuditError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise _PrecisionAuditError(
            code, f"evidence path {path_ref!r} must be a regular file under project_root"
        ) from error


def _resolve_project_directory(project_root: Path, path_ref: str, code: str) -> Path:
    try:
        root = project_root.resolve(strict=True)
        lexical = Path(os.path.abspath(root / path_ref))
        relative = lexical.relative_to(root)
        current = root
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        for part in relative.parts:
            current = current / part
            metadata = current.lstat()
            file_attributes = getattr(metadata, "st_file_attributes", 0)
            if stat.S_ISLNK(metadata.st_mode) or file_attributes & reparse_flag:
                raise _PrecisionAuditError(
                    code,
                    f"input_root {path_ref!r} must not traverse symlinks or reparse points",
                )
        resolved = lexical.resolve(strict=True)
        resolved.relative_to(root)
        if not stat.S_ISDIR(resolved.stat().st_mode):
            raise _PrecisionAuditError(
                code, f"input_root {path_ref!r} must be an ordinary directory"
            )
        return resolved
    except _PrecisionAuditError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise _PrecisionAuditError(
            code, f"input_root {path_ref!r} must be a directory under project_root"
        ) from error


def _audit_precision_floor(
    ctx: GateContext,
    output: Mapping[str, Any],
    safety_factor: float,
    safety_factor_source: str,
    required: bool,
) -> dict[str, Any]:
    raw = ctx.artifacts.get("precision_audit")
    if raw is None:
        if required:
            raise _PrecisionAuditError(
                "BLOCK_PRECISION_AUDIT_EVIDENCE",
                "contract-required precision_audit total/differential evidence is missing",
            )
        return {"status": "not_provided"}
    audit = _mapping(raw, "artifacts.precision_audit", "BLOCK_PRECISION_AUDIT_EVIDENCE")
    if "total" not in audit or "differential" not in audit:
        raise _PrecisionAuditError(
            "BLOCK_PRECISION_AUDIT_EVIDENCE",
            "precision_audit must contain total and differential arrays",
        )
    total = np.asarray(audit["total"])
    differential = np.asarray(audit["differential"])
    if total.shape != differential.shape or total.shape != output["shape"] or total.size == 0:
        raise _PrecisionAuditError(
            "BLOCK_PRECISION_AUDIT_EVIDENCE",
            "precision_audit arrays must be non-empty and aligned with the receiver dataset",
        )
    if total.dtype.kind != "f" or differential.dtype.kind != "f":
        raise _PrecisionAuditError(
            "BLOCK_PRECISION_AUDIT_EVIDENCE", "precision_audit arrays must be real floating point"
        )
    if total.dtype.name != output["dtype"] or differential.dtype.name != output["dtype"]:
        raise _PrecisionAuditError(
            "BLOCK_PRECISION_AUDIT_EVIDENCE",
            "precision_audit arrays must retain the actual receiver dataset dtype",
        )
    if not np.isfinite(total).all() or not np.isfinite(differential).all():
        raise _PrecisionAuditError(
            "BLOCK_PRECISION_AUDIT_EVIDENCE", "precision_audit arrays must be finite"
        )
    if not _receiver_equals_total(output, total):
        raise _PrecisionAuditError(
            "BLOCK_PRECISION_AUDIT_EVIDENCE",
            "precision_audit total must exactly equal the actual HDF5 receiver dataset",
        )
    ratio = precision_floor_ratio(total, differential)
    blocked = ratio <= safety_factor
    return {
        "ratio": ratio,
        "safety_factor": safety_factor,
        "safety_factor_source": safety_factor_source,
        "status": "blocked" if blocked else "pass",
    }


def _dataset_is_finite(dataset: h5py.Dataset) -> bool:
    return all(
        np.isfinite(np.asarray(dataset[selection])).all()
        for selection in _bounded_hdf5_slices(tuple(dataset.shape))
    )


def _local_nonvirtual_dataset(
    handle: h5py.File,
    dataset_ref: str,
    code: str,
    label: str,
) -> h5py.Dataset:
    parts = tuple(part for part in dataset_ref.strip().split("/") if part)
    if not parts or any(part in {".", ".."} for part in parts):
        raise _PrecisionAuditError(code, f"{label} path is invalid")
    current: h5py.Group = handle
    for index, part in enumerate(parts):
        link = current.get(part, getlink=True)
        if link is None:
            raise _PrecisionAuditError(code, f"{label} {dataset_ref!r} is missing")
        if not isinstance(link, h5py.HardLink):
            raise _PrecisionAuditError(
                code, f"{label} must not traverse external or symbolic HDF5 links"
            )
        value = current.get(part)
        if index < len(parts) - 1:
            if not isinstance(value, h5py.Group):
                raise _PrecisionAuditError(code, f"{label} path traverses a non-group object")
            current = value
            continue
        if not isinstance(value, h5py.Dataset):
            raise _PrecisionAuditError(code, f"{label} must resolve to an HDF5 dataset")
        if value.is_virtual:
            raise _PrecisionAuditError(code, f"{label} must not be a virtual HDF5 dataset")
        if value.external:
            raise _PrecisionAuditError(
                code, f"{label} must not use HDF5 external raw storage"
            )
        return value
    raise _PrecisionAuditError(code, f"{label} {dataset_ref!r} is missing")


def _candidate_equals_audited_output(
    candidate: h5py.Dataset, output: Mapping[str, Any]
) -> bool:
    try:
        with _open_verified_hdf5(
            output["resolved"],
            "BLOCK_FP32_ADEQUACY_EVIDENCE",
            "audited receiver HDF5 output",
        ) as handle:
            audited = _local_nonvirtual_dataset(
                handle,
                output["dataset"],
                "BLOCK_FP32_ADEQUACY_EVIDENCE",
                "audited receiver dataset",
            )
            if (
                np.dtype(candidate.dtype) != np.dtype(audited.dtype)
                or tuple(candidate.shape) != tuple(audited.shape)
            ):
                return False
            return all(
                np.array_equal(
                    np.asarray(candidate[selection]), np.asarray(audited[selection])
                )
                for selection in _bounded_hdf5_slices(tuple(candidate.shape))
            )
    except _PrecisionAuditError:
        raise
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise _PrecisionAuditError(
            "BLOCK_FP32_ADEQUACY_EVIDENCE",
            f"audited receiver could not be compared with FP32 candidate: {error}",
        ) from error


def _dataset_sha256(dataset: h5py.Dataset) -> str:
    digest = hashlib.sha256()
    digest.update(
        json.dumps(
            {"dtype": np.dtype(dataset.dtype).name, "shape": list(dataset.shape)},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    digest.update(b"\n")
    for selection in _bounded_hdf5_slices(tuple(dataset.shape)):
        digest.update(np.ascontiguousarray(dataset[selection]).tobytes(order="C"))
    return digest.hexdigest()


def _compare_adequacy_datasets(
    candidate: h5py.Dataset,
    reference: h5py.Dataset,
    rtol: float,
    atol: float,
) -> tuple[bool, float, float]:
    passed = True
    max_abs_error = 0.0
    max_relative_error = 0.0
    for selection in _bounded_hdf5_slices(tuple(candidate.shape)):
        candidate_block = np.asarray(candidate[selection], dtype=np.float64)
        reference_block = np.asarray(reference[selection], dtype=np.float64)
        if not np.isfinite(candidate_block).all() or not np.isfinite(reference_block).all():
            raise _PrecisionAuditError(
                "BLOCK_FP32_ADEQUACY_EVIDENCE", "FP32 adequacy datasets must be finite"
            )
        with np.errstate(over="ignore", invalid="ignore"):
            absolute_error = np.abs(candidate_block - reference_block)
            tolerance = atol + rtol * np.abs(reference_block)
        if not np.isfinite(tolerance).all():
            raise _PrecisionAuditError(
                "BLOCK_FP32_ADEQUACY_EVIDENCE",
                "FP32 adequacy per-sample tolerances must remain finite",
            )
        if not np.isfinite(absolute_error).all():
            raise _PrecisionAuditError(
                "BLOCK_FP32_ADEQUACY_EVIDENCE",
                "FP32 adequacy per-sample errors must remain finite",
            )
        passed = passed and bool(np.all(absolute_error <= tolerance))
        max_abs_error = max(max_abs_error, float(np.max(absolute_error)))
        nonzero_reference = np.abs(reference_block) > 0.0
        if np.any(nonzero_reference):
            with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
                relative_error = absolute_error[nonzero_reference] / np.abs(
                    reference_block[nonzero_reference]
                )
            if not np.isfinite(relative_error).all():
                raise _PrecisionAuditError(
                    "BLOCK_FP32_ADEQUACY_EVIDENCE",
                    "FP32 adequacy relative errors must remain finite",
                )
            max_relative_error = max(
                max_relative_error,
                float(np.max(relative_error)),
            )
    return passed, max_abs_error, max_relative_error


def _receiver_equals_total(output: Mapping[str, Any], total: np.ndarray) -> bool:
    try:
        with _open_verified_hdf5(
            output["resolved"],
            "BLOCK_PRECISION_AUDIT_EVIDENCE",
            "precision-audit receiver HDF5 output",
        ) as handle:
            dataset = _local_nonvirtual_dataset(
                handle,
                output["dataset"],
                "BLOCK_PRECISION_AUDIT_EVIDENCE",
                "receiver dataset",
            )
            if tuple(dataset.shape) != total.shape:
                return False
            return all(
                np.array_equal(np.asarray(dataset[selection]), total[selection])
                for selection in _bounded_hdf5_slices(tuple(dataset.shape))
            )
    except _PrecisionAuditError:
        raise
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise _PrecisionAuditError(
            "BLOCK_PRECISION_AUDIT_EVIDENCE",
            f"receiver output could not be rebound to precision_audit total: {error}",
        ) from error


def _bounded_hdf5_slices(shape: tuple[int, ...]) -> Iterator[tuple[slice, ...]]:
    if not shape:
        yield ()
        return
    block_shape = [1] * len(shape)
    remaining = _MAX_HDF5_BLOCK_ELEMENTS
    for axis in range(len(shape) - 1, -1, -1):
        block_shape[axis] = min(shape[axis], max(1, remaining))
        remaining = max(1, remaining // block_shape[axis])
    starts = [range(0, length, block) for length, block in zip(shape, block_shape, strict=True)]
    for origin in product(*starts):
        yield tuple(
            slice(start, min(start + block, length))
            for start, block, length in zip(origin, block_shape, shape, strict=True)
        )


def _resolve_project_file(project_root: Path, path_ref: str, code: str) -> Path:
    path = Path(path_ref.strip())
    if not path.is_absolute():
        path = project_root / path
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(project_root.resolve(strict=False))
    except (OSError, RuntimeError, ValueError) as error:
        raise _PrecisionAuditError(code, f"evidence path {path_ref!r} must resolve under project_root") from error
    if not resolved.is_file():
        raise _PrecisionAuditError(code, f"evidence path {path_ref!r} must be a file")
    return resolved


def _mapping(value: object, path: str, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _PrecisionAuditError(code, f"{path} must be a mapping")
    return value


def _required_text(value: Mapping[str, Any], key: str, path: str, code: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise _PrecisionAuditError(code, f"{path} must be non-empty text")
    return raw


def _required_sha256(value: Mapping[str, Any], key: str, path: str) -> str:
    code = "BLOCK_FP32_ADEQUACY_EVIDENCE"
    return _sha256_text(value.get(key), path, code)


def _sha256_text(value: object, path: str, code: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _PrecisionAuditError(code, f"{path} must be an exact SHA-256 hex digest")
    raw = value.lower()
    if len(raw) != 64 or any(character not in "0123456789abcdef" for character in raw):
        raise _PrecisionAuditError(code, f"{path} must be a 64-character SHA-256 hex digest")
    return raw


def _nonnegative_finite(value: object, path: str, code: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise _PrecisionAuditError(code, f"{path} must be a non-negative finite number")
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise _PrecisionAuditError(code, f"{path} must be a non-negative finite number")
    return number


def _try_publish(ctx: GateContext, report: Mapping[str, Any]) -> _PrecisionAuditError | None:
    if not report:
        return None
    derived = ctx.artifacts.get("derived")
    if derived is not None and not isinstance(derived, dict):
        return _PrecisionAuditError(
            "BLOCK_PRECISION_EVIDENCE", "artifacts.derived must be a mutable mapping"
        )
    namespace = ctx.artifacts.setdefault("derived", {})
    namespace["precision"] = dict(report)
    return None


def _result(
    state: GateState, code: str, summary: str, evidence: Sequence[str]
) -> GateResult:
    return GateResult(
        "precision",
        state,
        code,
        summary,
        evidence=tuple(evidence),
        invalidates=("simulation", "claims"),
    )
