import json
from pathlib import Path

import pytest

from scripts.core import GateContext, GateResult, GateState
from scripts.gates import GateContractError, GateRegistry, run_stage, write_gate_report


def test_source_change_invalidates_all_downstream():
    """Catches invalidation that stops before reaching downstream claims."""
    from scripts.gates import DependencyGraph

    graph = DependencyGraph()
    graph.add("source", "processing")
    graph.add("processing", "metrics")
    graph.add("metrics", "claims")

    assert graph.invalidate({"source"}) == {"processing", "metrics", "claims"}


def test_default_graph_invalidates_canonical_source_downstream_stages():
    """Catches a default graph that omits a canonical source dependency."""
    from scripts.gates import default_dependency_graph

    assert default_dependency_graph().invalidate({"source"}) == {
        "geometry_materials",
        "antenna_system",
        "simulation",
        "processing",
        "metrics",
        "claims",
    }


def test_mark_stale_changes_only_affected_results_and_preserves_evidence():
    """Catches stale propagation that loses evidence or rewrites unaffected results."""
    from scripts.gates import mark_stale

    report = {
        "results": [
            {
                "gate_id": "source",
                "state": "PASS",
                "code": "PASS_SOURCE",
                "summary": "source verified",
                "evidence": ["evidence/source.json"],
                "invalidates": ["processing"],
            },
            {
                "gate_id": "claims",
                "state": "PASS_WITH_LIMITATION",
                "code": "LIMITED_CLAIM",
                "summary": "claim conditional",
                "evidence": ["evidence/claim.json"],
                "invalidates": [],
            },
        ]
    }

    stale_report = mark_stale(report, {"claims"})

    assert stale_report == {
        "results": [
            {
                "gate_id": "source",
                "state": "PASS",
                "code": "PASS_SOURCE",
                "summary": "source verified",
                "evidence": ["evidence/source.json"],
                "invalidates": ["processing"],
            },
            {
                "gate_id": "claims",
                "state": "STALE",
                "code": "STALE_INVALIDATED",
                "summary": "invalidated by upstream change",
                "evidence": ["evidence/claim.json"],
                "invalidates": [],
            },
        ]
    }
    assert report["results"][1]["state"] == "PASS_WITH_LIMITATION"


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
    """Catches ambiguous registration without a stable contract error."""
    registry = GateRegistry()
    gate = lambda ctx: GateResult("shared", GateState.PASS, "PASS", "ok")
    registry.register("preflight", "shared", gate)

    with pytest.raises(GateContractError) as exc:
        registry.register("postflight", "shared", gate)

    assert exc.value.code == "BLOCK_GATE_DUPLICATE_ID"
    assert exc.value.path == "gate_id"
    assert exc.value.details == "duplicate gate_id: shared"


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


def test_callback_result_id_mismatch_is_a_stable_contract_error(tmp_path: Path):
    """Catches a callback result recorded under an ID other than its registered gate."""
    registry = GateRegistry()
    registry.register(
        "preflight",
        "registered",
        lambda ctx: GateResult("reported", GateState.PASS, "PASS", "wrong identity"),
    )

    with pytest.raises(GateContractError) as exc:
        run_stage(registry, "preflight", GateContext(tmp_path, {}))

    assert exc.value.code == "BLOCK_GATE_RESULT_ID"
    assert exc.value.path == "registered.gate_id"
    assert exc.value.details == "expected registered, got reported"


def test_invalid_callback_return_type_is_a_stable_contract_error(tmp_path: Path):
    """Catches callbacks that bypass the GateResult result contract."""
    registry = GateRegistry()
    registry.register("preflight", "registered", lambda ctx: "PASS")

    with pytest.raises(GateContractError) as exc:
        run_stage(registry, "preflight", GateContext(tmp_path, {}))

    assert exc.value.code == "BLOCK_GATE_RESULT_TYPE"
    assert exc.value.path == "registered"
    assert exc.value.details == "expected GateResult, got str"


def test_invalid_callback_state_is_a_stable_contract_error(tmp_path: Path):
    """Catches callback results whose runtime state is outside GateState."""
    registry = GateRegistry()
    registry.register(
        "preflight",
        "registered",
        lambda ctx: GateResult("registered", "INVALID", "BAD", "bad state"),
    )

    with pytest.raises(GateContractError) as exc:
        run_stage(registry, "preflight", GateContext(tmp_path, {}))

    assert exc.value.code == "BLOCK_GATE_RESULT_STATE"
    assert exc.value.path == "registered.state"
    assert exc.value.details == "expected GateState, got str"


def test_invalid_report_does_not_create_destination(tmp_path: Path):
    """Catches validation that writes a malformed report before rejecting it."""
    output = tmp_path / "reports" / "gates.json"

    with pytest.raises(GateContractError) as exc:
        write_gate_report(output, [GateResult("source", GateState.PASS, "", "missing code")])

    assert exc.value.code == "BLOCK_GATE_REPORT_SCHEMA"
    assert exc.value.path == "results.0.code"
    assert exc.value.details == "'' should be non-empty"
    assert not output.exists()


def test_invalid_report_does_not_overwrite_destination(tmp_path: Path):
    """Catches report validation that replaces an existing report before rejection."""
    output = tmp_path / "gates.json"
    output.write_text("existing report\n", encoding="utf-8")

    with pytest.raises(GateContractError):
        write_gate_report(output, [GateResult("source", GateState.PASS, "", "missing code")])

    assert output.read_text(encoding="utf-8") == "existing report\n"


@pytest.mark.parametrize("field", ["evidence", "invalidates"])
def test_malformed_report_collection_is_a_stable_contract_error(tmp_path: Path, field: str):
    """Catches iterable fields that crash serialization before report validation."""
    output = tmp_path / "gates.json"
    result = GateResult("source", GateState.PASS, "PASS", "ok", **{field: None})

    with pytest.raises(GateContractError) as exc:
        write_gate_report(output, [result])

    assert exc.value.code == "BLOCK_GATE_REPORT_FIELD_TYPE"
    assert exc.value.path == f"results.0.{field}"
    assert exc.value.details == "expected tuple[str, ...], got NoneType"
    assert not output.exists()
