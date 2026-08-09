from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
import hashlib
from itertools import product
import json
import math
from numbers import Real
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from scripts.core import GateContext, GateResult, GateState


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
            normalized = item.strip().lower()
            if normalized not in _PRECISION_RISK_FLAGS:
                raise _PrecisionAuditError(
                    "BLOCK_PRECISION_CONTRACT",
                    f"unsupported precision risk flag {normalized!r}",
                )
            flags.add(normalized)
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
    path = _resolve_project_file(ctx.project_root, path_ref, "BLOCK_OUTPUT_EVIDENCE")
    try:
        with h5py.File(path, "r") as handle:
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
    matched_run = _matched_run_provenance(evidence)
    fixture_path = _resolve_project_file(
        ctx.project_root, fixture_ref, "BLOCK_FP32_ADEQUACY_EVIDENCE"
    )
    if fixture_path == output["resolved"]:
        raise _PrecisionAuditError(
            "BLOCK_FP32_ADEQUACY_EVIDENCE",
            "FP32 adequacy comparison fixture must be independent of the audited output",
        )
    try:
        with h5py.File(fixture_path, "r") as handle:
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
            if candidate_hash != matched_run["candidate_dataset_sha256"]:
                raise _PrecisionAuditError(
                    "BLOCK_FP32_ADEQUACY_EVIDENCE",
                    "FP32 candidate dataset SHA-256 does not match matched-run provenance",
                )
            if reference_hash != matched_run["reference_dataset_sha256"]:
                raise _PrecisionAuditError(
                    "BLOCK_FP32_ADEQUACY_EVIDENCE",
                    "FP64 reference dataset SHA-256 does not match matched-run provenance",
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
                "inputs_sha256": matched_run["candidate_inputs_sha256"],
                "candidate_precision": "float32",
                "reference_precision": "float64",
                "declared_changes": ["precision"],
                "candidate_dataset_sha256": candidate_hash,
                "reference_dataset_sha256": reference_hash,
            },
        },
        fixture_ref.strip(),
    )


def _matched_run_provenance(evidence: Mapping[str, Any]) -> dict[str, str]:
    code = "BLOCK_FP32_ADEQUACY_EVIDENCE"
    matched = _mapping(
        evidence.get("matched_run"),
        "numerics.fp32_adequacy_evidence.matched_run",
        code,
    )
    candidate_run_id = _required_text(
        matched, "candidate_run_id", "matched_run.candidate_run_id", code
    ).strip()
    reference_run_id = _required_text(
        matched, "reference_run_id", "matched_run.reference_run_id", code
    ).strip()
    if candidate_run_id == reference_run_id:
        raise _PrecisionAuditError(code, "matched FP32 and FP64 runs must have distinct run IDs")
    candidate_inputs_hash = _required_sha256(
        matched, "candidate_inputs_sha256", "matched_run.candidate_inputs_sha256"
    )
    reference_inputs_hash = _required_sha256(
        matched, "reference_inputs_sha256", "matched_run.reference_inputs_sha256"
    )
    if candidate_inputs_hash != reference_inputs_hash:
        raise _PrecisionAuditError(
            code, "matched FP32 and FP64 runs must have identical input SHA-256 values"
        )
    candidate_precision = _required_text(
        matched, "candidate_precision", "matched_run.candidate_precision", code
    ).strip().lower()
    reference_precision = _required_text(
        matched, "reference_precision", "matched_run.reference_precision", code
    ).strip().lower()
    if candidate_precision != "float32" or reference_precision != "float64":
        raise _PrecisionAuditError(
            code, "matched-run precision must change from float32 candidate to float64 reference"
        )
    declared_changes = matched.get("declared_changes")
    if not isinstance(declared_changes, Sequence) or isinstance(
        declared_changes, (str, bytes)
    ):
        raise _PrecisionAuditError(code, "matched_run.declared_changes must be a sequence")
    if tuple(declared_changes) != ("precision",):
        raise _PrecisionAuditError(
            code, "precision must be the sole declared matched-run change"
        )
    return {
        "candidate_run_id": candidate_run_id,
        "reference_run_id": reference_run_id,
        "candidate_inputs_sha256": candidate_inputs_hash,
        "reference_inputs_sha256": reference_inputs_hash,
        "candidate_dataset_sha256": _required_sha256(
            matched, "candidate_dataset_sha256", "matched_run.candidate_dataset_sha256"
        ),
        "reference_dataset_sha256": _required_sha256(
            matched, "reference_dataset_sha256", "matched_run.reference_dataset_sha256"
        ),
    }


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
        return value
    raise _PrecisionAuditError(code, f"{label} {dataset_ref!r} is missing")


def _candidate_equals_audited_output(
    candidate: h5py.Dataset, output: Mapping[str, Any]
) -> bool:
    try:
        with h5py.File(output["resolved"], "r") as handle:
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
        with h5py.File(output["resolved"], "r") as handle:
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
    raw = _required_text(value, key, path, code).strip().lower()
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
