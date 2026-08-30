from pathlib import Path
import json

import pytest

import scripts.cli as cli
from scripts.core import GateResult, GateState
from scripts.gates import GateRegistry
from scripts.cli import main


def test_minimal_fixture_preflight_blocks_incomplete(tmp_path: Path):
    """A minimal contract without runtime/geometry/etc. BLOCKs (fail-closed)."""
    project_root = tmp_path / "minimal"
    report_path = project_root / "gates" / "preflight.json"
    assert not report_path.exists()

    rc = main(
        [
            "preflight",
            "tests/fixtures/contracts/minimal_valid.yaml",
            "--project-root",
            str(project_root),
        ]
    )

    assert rc == 2
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    results = report.get("results", [])
    assert len(results) > 0
    assert results[0]["state"] == "BLOCK"


def test_init_copies_generic_contract_template(tmp_path: Path):
    rc = main(["init", str(tmp_path)])

    assert rc == 0
    assert (tmp_path / "simulation_contract.yaml").read_text(
        encoding="utf-8"
    ) == Path("templates/simulation_contract.yaml").read_text(encoding="utf-8")


def test_invalid_contract_returns_blocking_exit(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("task:\n  objective: detection\n", encoding="utf-8")

    rc = main(["preflight", str(bad), "--project-root", str(tmp_path)])

    assert rc == 2


def test_promote_reads_stored_fidelity_and_writes_allowed_decision(tmp_path: Path):
    gates = tmp_path / "gates"
    gates.mkdir()
    (gates / "fidelity.json").write_text('{"current": "F0"}\n', encoding="utf-8")
    (gates / "preflight.json").write_text('{"results": []}\n', encoding="utf-8")

    rc = main(["promote", "F1", "--project-root", str(tmp_path)])

    assert rc == 0
    assert json.loads((gates / "fidelity.json").read_text(encoding="utf-8")) == {
        "current": "F1"
    }
    assert json.loads((gates / "promotion.json").read_text(encoding="utf-8")) == {
        "allowed": True,
        "code": "ALLOW_FIDELITY_PROMOTION",
        "current": "F0",
        "requested": "F1",
        "summary": "Promotion to F1 is allowed.",
    }


def test_promote_refuses_stored_block_and_preserves_current_fidelity(tmp_path: Path):
    gates = tmp_path / "gates"
    gates.mkdir()
    (gates / "fidelity.json").write_text('{"current": "F0"}\n', encoding="utf-8")
    (gates / "preflight.json").write_text(
        json.dumps(
            {
                "results": [
                    {
                        "gate_id": "environment",
                        "state": "BLOCK",
                        "code": "BLOCK_ENVIRONMENT_UNRESOLVED",
                        "summary": "runtime unresolved",
                        "evidence": [],
                        "invalidates": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    rc = main(["promote", "F1", "--project-root", str(tmp_path)])

    assert rc == 2
    assert json.loads((gates / "fidelity.json").read_text(encoding="utf-8")) == {
        "current": "F0"
    }
    assert json.loads((gates / "promotion.json").read_text(encoding="utf-8"))["code"] == (
        "BLOCK_PROMOTION_GATE"
    )


def test_promote_without_stored_fidelity_blocks_without_fabricating_default(tmp_path: Path):
    rc = main(["promote", "F1", "--project-root", str(tmp_path)])

    assert rc == 2
    assert not (tmp_path / "gates" / "fidelity.json").exists()


def test_promote_allows_limited_evidence_only_when_explicitly_conditional(tmp_path: Path):
    gates = tmp_path / "gates"
    gates.mkdir()
    (gates / "fidelity.json").write_text('{"current": "F0"}\n', encoding="utf-8")
    (gates / "preflight.json").write_text(
        json.dumps(
            {
                "results": [
                    {
                        "gate_id": "source",
                        "state": "PASS_WITH_LIMITATION",
                        "code": "LIMITED_SOURCE",
                        "summary": "source evidence is conditional",
                        "evidence": [],
                        "invalidates": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    rc = main(
        ["promote", "F1", "--project-root", str(tmp_path), "--allow-conditional"]
    )

    assert rc == 0
    assert json.loads((gates / "promotion.json").read_text(encoding="utf-8"))["code"] == (
        "ALLOW_FIDELITY_PROMOTION_WITH_LIMITATION"
    )


def test_preflight_malformed_gate_result_returns_blocking_exit(
    tmp_path: Path, monkeypatch
):
    contract = tmp_path / "simulation_contract.yaml"
    contract.write_text(
        Path("templates/simulation_contract.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    registry = GateRegistry()
    registry.register("preflight", "environment", lambda context: "PASS")
    monkeypatch.setattr(cli, "build_core_registry", lambda: registry)

    rc = main(["preflight", str(contract), "--project-root", str(tmp_path)])

    assert rc == 2
    result = json.loads(
        (tmp_path / "gates" / "preflight.json").read_text(encoding="utf-8")
    )["results"][0]
    assert result["state"] == "BLOCK"
    assert result["code"] == "BLOCK_GATE_RESULT_TYPE"


def test_preflight_report_serialization_error_persists_sanitized_block(
    tmp_path: Path, monkeypatch
):
    contract = tmp_path / "simulation_contract.yaml"
    contract.write_text(
        Path("templates/simulation_contract.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    registry = GateRegistry()
    registry.register(
        "preflight",
        "environment",
        lambda context: GateResult(
            "environment",
            GateState.PASS,
            "PASS_ENVIRONMENT",
            "environment ready",
            evidence=(1,),
        ),
    )
    monkeypatch.setattr(cli, "build_core_registry", lambda: registry)

    rc = main(["preflight", str(contract), "--project-root", str(tmp_path)])

    assert rc == 2
    result = json.loads(
        (tmp_path / "gates" / "preflight.json").read_text(encoding="utf-8")
    )["results"][0]
    assert result == {
        "gate_id": "gate_engine",
        "state": "BLOCK",
        "code": "BLOCK_GATE_REPORT_SCHEMA",
        "summary": result["summary"],
        "evidence": [],
        "invalidates": [],
    }
    assert isinstance(result["summary"], str) and result["summary"]


@pytest.mark.parametrize(
    "malformed_result",
    [
        {
            "gate_id": 7,
            "state": "PASS",
            "code": "PASS_ENVIRONMENT",
            "summary": "environment ready",
            "evidence": [],
            "invalidates": [],
        },
        {
            "gate_id": "environment",
            "state": "PASS",
            "code": 7,
            "summary": "environment ready",
            "evidence": [],
            "invalidates": [],
        },
        {
            "gate_id": "environment",
            "state": "PASS",
            "code": "PASS_ENVIRONMENT",
            "summary": "",
            "evidence": [],
            "invalidates": [],
        },
        {
            "gate_id": "environment",
            "state": "PASS",
            "code": "PASS_ENVIRONMENT",
            "summary": "environment ready",
            "evidence": [],
            "invalidates": [],
            "unexpected": True,
        },
    ],
    ids=["numeric-gate-id", "numeric-code", "empty-summary", "extra-property"],
)
def test_promote_rejects_malformed_stored_gate_report_without_changing_fidelity(
    tmp_path: Path, malformed_result: dict[str, object]
):
    gates = tmp_path / "gates"
    gates.mkdir()
    (gates / "fidelity.json").write_text('{"current": "F0"}\n', encoding="utf-8")
    (gates / "preflight.json").write_text(
        json.dumps({"results": [malformed_result]}), encoding="utf-8"
    )

    rc = main(["promote", "F1", "--project-root", str(tmp_path)])

    assert rc == 2
    assert json.loads((gates / "fidelity.json").read_text(encoding="utf-8")) == {
        "current": "F0"
    }
    assert json.loads((gates / "promotion.json").read_text(encoding="utf-8"))[
        "code"
    ] == "BLOCK_PROMOTION_STATE"
