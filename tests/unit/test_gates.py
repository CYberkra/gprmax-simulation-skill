import json
from pathlib import Path

import pytest

from scripts.core import GateContext, GateResult, GateState
from scripts.gates import GateRegistry, run_stage, write_gate_report


def test_block_stops_remaining_gates(tmp_path: Path):
    """Catches a runner that executes gates after a BLOCK result."""
    calls = []
    registry = GateRegistry()

    def first(ctx):
        calls.append("first")
        return GateResult("first", GateState.BLOCK, "BLOCK_TEST", "stop")

    def second(ctx):
        calls.append("second")
        return GateResult("second", GateState.PASS, "PASS", "should not run")

    registry.register("preflight", "first", first)
    registry.register("preflight", "second", second, depends_on=("first",))

    results = run_stage(registry, "preflight", GateContext(tmp_path, {}))

    assert calls == ["first"]
    assert [result.state for result in results] == [GateState.BLOCK]


def test_pass_with_limitation_does_not_become_pass(tmp_path: Path):
    """Catches normalization that drops an explicitly reported limitation."""
    registry = GateRegistry()
    registry.register(
        "preflight",
        "conditional",
        lambda ctx: GateResult("conditional", GateState.PASS_WITH_LIMITATION, "LIMITED", "conditional"),
    )

    result = run_stage(registry, "preflight", GateContext(tmp_path, {}))[0]

    assert result.state is GateState.PASS_WITH_LIMITATION


def test_unsatisfied_dependency_marks_gate_stale_without_calling_it(tmp_path: Path):
    """Catches a runner that evaluates a gate without its declared dependency."""
    calls = []
    registry = GateRegistry()
    registry.register(
        "preflight",
        "dependent",
        lambda ctx: calls.append("dependent") or GateResult("dependent", GateState.PASS, "PASS", "ran"),
        depends_on=("missing",),
    )

    results = run_stage(registry, "preflight", GateContext(tmp_path, {}))

    assert calls == []
    assert results == [
        GateResult("dependent", GateState.STALE, "STALE_DEPENDENCY", "dependency not satisfied")
    ]


def test_duplicate_gate_id_is_rejected():
    """Catches registration that permits ambiguous gate identifiers."""
    registry = GateRegistry()
    gate = lambda ctx: GateResult("shared", GateState.PASS, "PASS", "ok")
    registry.register("preflight", "shared", gate)

    with pytest.raises(ValueError, match="duplicate gate_id: shared"):
        registry.register("postflight", "shared", gate)


def test_write_gate_report_preserves_serialized_gate_evidence(tmp_path: Path):
    """Catches report writing that changes evidence or emits an invalid report shape."""
    output = tmp_path / "reports" / "gates.json"
    evidence = ("logs/run.json", "artifacts/trace.h5")

    write_gate_report(
        output,
        [GateResult("source", GateState.PASS_WITH_LIMITATION, "LIMITED", "source idealized", evidence)],
    )

    assert json.loads(output.read_text(encoding="utf-8")) == {
        "results": [
            {
                "gate_id": "source",
                "state": "PASS_WITH_LIMITATION",
                "code": "LIMITED",
                "summary": "source idealized",
                "evidence": ["logs/run.json", "artifacts/trace.h5"],
                "invalidates": [],
            }
        ]
    }
