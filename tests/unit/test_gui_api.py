"""Tests for the GUI API layer (gui/api.py).

Uses FastAPI's TestClient with synthetic contracts and the real gprMax
fixture. Asserts each new phase-2 endpoint returns 200 with the expected
shape, and that malformed inputs are rejected with 422.
"""

from pathlib import Path
import json

import pytest
from fastapi.testclient import TestClient

from gui.api import app

client = TestClient(app)

FIXTURE_OUT = Path("tests/fixtures/real_out/mini_3d_rx1.out")


def _contract(**overrides):
    contract = {
        "project": {"target_depth_m": 80.0, "target_size_m": 4.0},
        "model": {"dimension": "3d"},
        "task": {"objective": "tunnel", "claim_scope": "numerical"},
        "medium": {
            "target_material": "WET",
            "medium_material": "coal",
            "model_type": "debye",
            "parameter_source": "literature",
            "eps_r": 2.8,
        },
        "waveform": {
            "excitation_mode": "unit_impulse",
            "measurement_mode": "sfcw_equivalent",
            "processing_route": "impulse_lti",
            "band_mhz": "30-240",
        },
        "numerics": {
            "precision_requirement": "fp32",
            "pml_layers": 20,
            "dx_m": 0.04,
            "dy_m": 0.05,
            "dz_m": 0.05,
            "dt_s": 1.9e-11,
            "time_window_s": 2.0e-6,
        },
        "geometry": {"target_level": "L3", "antenna": "ideal_hertzian", "noise": "none"},
        "domain_m": [120.0, 20.0, 100.0],
        "acceptance": {"negative_controls": [], "sensitivity_tests": []},
        "evidence": {"required_outputs": ["rxs/rx1/Ez"], "provenance_level": "strict"},
    }
    contract.update(overrides)
    return contract


# --------------------------------------------------------------------------
# wizard (phase 1, still intact)
# --------------------------------------------------------------------------

def test_wizard_fields_endpoint():
    res = client.get("/api/wizard/fields")
    assert res.status_code == 200
    assert "scenario" in res.json()
    assert "fidelity" in res.json()


def test_wizard_roundtrip():
    res = client.post("/api/wizard/init")
    assert res.status_code == 200
    session_dir = res.json()["session_dir"]
    for field, value in (
        ("scenario_type", "tunnel"),
        ("target_depth_m", "80"),
        ("target_material", "WET"),
        ("medium_material", "coal"),
        ("needs_sfcw", "true"),
        ("band_mhz", "30-240"),
        ("fidelity", "standard"),
        ("dimension", "3d"),
        ("run_env", "server"),
    ):
        r = client.post("/api/wizard/answer", json={"session_dir": session_dir, "field": field, "value": value})
        assert r.status_code == 200, f"answer {field} failed: {r.text}"
    dump = client.post("/api/wizard/dump", json={"session_dir": session_dir})
    assert dump.status_code == 200
    assert dump.json()["contract_draft"]["model"]["dimension"] == "3d"


# --------------------------------------------------------------------------
# phase-2 endpoints
# --------------------------------------------------------------------------

def test_sketch_endpoint_returns_png():
    res = client.post("/api/sketch", json={"contract": _contract()})
    assert res.status_code == 200
    png_b64 = res.json()["png_b64"]
    assert png_b64
    import base64
    assert base64.b64decode(png_b64)[:8] == b"\x89PNG\r\n\x1a\n"


def test_sketch_endpoint_rejects_malformed():
    res = client.post("/api/sketch", json={"contract": {"project": {}}})
    assert res.status_code == 422


def test_diagnose_endpoint_returns_findings():
    res = client.post("/api/diagnose", json={"contract": _contract()})
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body["findings"], list)
    assert all("severity" in f for f in body["findings"])
    assert "text" in body


def test_sensitivity_endpoint_returns_results():
    res = client.post("/api/sensitivity", json={"contract": _contract()})
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body["results"], list)
    assert body["results"], "sensitivity should produce results for a valid contract"
    assert all("parameter" in r for r in body["results"])


def test_report_endpoint_returns_markdown():
    res = client.post("/api/report", json={"contract": _contract()})
    assert res.status_code == 200
    markdown = res.json()["markdown"]
    assert "## 任务与声明" in markdown
    assert "## 处理链" in markdown


def test_study_endpoints_roundtrip(tmp_path):
    study = tmp_path / "01_20260830_GUI_TEST"

    # init
    res = client.post("/api/study/init", json={"path": str(study), "name": study.name})
    assert res.status_code == 200, res.text
    assert len(res.json()["created"]) >= 10

    # audit (fresh skeleton should have no BLOCK)
    res = client.post("/api/study/audit", json={"path": str(study)})
    assert res.status_code == 200
    assert all(f["severity"] != "BLOCK" for f in res.json()["findings"])

    # hash with an evidence file
    (study / "outputs" / "case.out").write_bytes(b"evidence")
    res = client.post("/api/study/hash", json={"path": str(study)})
    assert res.status_code == 200
    assert res.json()["count"] == 1

    # check-model after contract + hash -> established
    (study / "simulation_contract.yaml").write_text(
        _to_yaml(_contract()), encoding="utf-8"
    )
    res = client.post("/api/study/check", json={"path": str(study)})
    assert res.status_code == 200
    assert res.json()["established"] is True


def test_process_endpoint_with_real_fixture(tmp_path):
    if not FIXTURE_OUT.is_file():
        pytest.skip("real gprMax fixture missing")
    res = client.post(
        "/api/process",
        json={"out_path": str(FIXTURE_OUT), "band": "200-350", "df_mhz": 50},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["png_b64"]
    assert '"mode": "impulse_lti"' in body["params_json"]


def test_process_endpoint_rejects_missing_file():
    res = client.post("/api/process", json={"out_path": "does_not_exist.out"})
    assert res.status_code == 422


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _to_yaml(payload: dict) -> str:
    import yaml
    return yaml.safe_dump(payload, sort_keys=False)
