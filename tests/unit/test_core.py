from pathlib import Path

from scripts.core import ClaimState, GateContext, GateResult, GateState, write_json


def test_gate_result_serializes_stably():
    result = GateResult(
        gate_id="environment",
        state=GateState.BLOCK,
        code="BLOCK_ENVIRONMENT_UNRESOLVED",
        summary="runtime banner is missing",
        evidence=("logs/run.log",),
        invalidates=("source", "claims"),
    )
    assert result.to_dict() == {
        "gate_id": "environment",
        "state": "BLOCK",
        "code": "BLOCK_ENVIRONMENT_UNRESOLVED",
        "summary": "runtime banner is missing",
        "evidence": ["logs/run.log"],
        "invalidates": ["source", "claims"],
    }


def test_gate_context_has_mutable_derived_artifacts_only(tmp_path: Path):
    ctx = GateContext(project_root=tmp_path, contract={"task": {"objective": "detection"}})
    ctx.artifacts["computed"] = 3
    assert ctx.artifacts == {"computed": 3}
    assert ClaimState.STALE.value == "STALE"


def test_write_json_creates_parent_and_writes_deterministic_json(tmp_path: Path):
    output_path = tmp_path / "derived" / "result.json"

    write_json(output_path, {"z": 1, "a": {"b": 2}})

    assert output_path.read_text(encoding="utf-8") == '{\n  "a": {\n    "b": 2\n  },\n  "z": 1\n}\n'
