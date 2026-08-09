from pathlib import Path

import h5py
import numpy as np
import pytest

from scripts.audit_precision import audit_precision, local_ulp, precision_floor_ratio
from scripts.core import GateContext, GateState


def _write_dataset(path: Path, dataset: str, values: np.ndarray) -> None:
    with h5py.File(path, "w") as handle:
        handle.create_dataset(dataset, data=values)


def _runtime(real_dtype: str = "float32", complex_dtype: str = "complex64") -> dict[str, str]:
    return {"real_dtype": real_dtype, "complex_dtype": complex_dtype}


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
    tmp_path: Path, environment: dict[str, str] | None
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
    with h5py.File(tmp_path / "adequacy.h5", "w") as handle:
        handle.create_dataset("candidate", data=np.array([1.0, 1.2], dtype=np.float32))
        handle.create_dataset("reference", data=np.array([1.0, 1.0], dtype=np.float64))
    ctx = _context(
        tmp_path,
        numerics={
            "precision_requirement": "float32",
            "risk_flags": ["high_dynamic_range"],
            "fp32_adequacy_evidence": {
                "comparison_fixture": "adequacy.h5",
                "fp32_dataset": "/candidate",
                "fp64_dataset": "/reference",
                "rtol": 1e-5,
                "atol": 1e-8,
            },
        },
    )

    result = audit_precision(ctx)

    assert result.state is GateState.BLOCK
    assert result.code == "BLOCK_FP32_ADEQUACY"


def test_passing_fp32_comparison_fixture_allows_risk_flag_exception(tmp_path: Path):
    """Catches ignoring valid explicit FP32 adequacy evidence for risk-flagged work."""
    with h5py.File(tmp_path / "adequacy.h5", "w") as handle:
        handle.create_dataset("candidate", data=np.array([1.0, 1.000001], dtype=np.float32))
        handle.create_dataset("reference", data=np.array([1.0, 1.0000011], dtype=np.float64))
    ctx = _context(
        tmp_path,
        numerics={
            "precision_requirement": "float32",
            "risk_flags": ["fine_delay_fit"],
            "fp32_adequacy_evidence": {
                "comparison_fixture": "adequacy.h5",
                "fp32_dataset": "/candidate",
                "fp64_dataset": "/reference",
                "rtol": 1e-5,
                "atol": 1e-8,
            },
        },
    )

    result = audit_precision(ctx)

    assert result.state is GateState.PASS
    assert result.code == "PASS_PRECISION"
    assert result.evidence == ("run.h5", "adequacy.h5")
    assert ctx.artifacts["derived"]["precision"]["fp32_adequacy"]["passed"] is True


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
