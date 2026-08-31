from pathlib import Path

import pytest
import yaml

from scripts.contracts import ContractError, load_contract


def test_minimal_contract_loads(tmp_path: Path):
    path = tmp_path / "contract.yaml"
    path.write_text(
        "task:\n  objective: detection\n  claim_scope: numerical\n"
        "medium:\n  model_type: nondispersive\n  parameter_source: assumed\n"
        "waveform:\n  excitation_mode: pulse_broadband\n  measurement_mode: time_domain\n"
        "numerics:\n  precision_requirement: auto\n"
        "acceptance:\n  negative_controls: []\n  sensitivity_tests: []\n"
        "evidence:\n  required_outputs: []\n  provenance_level: strict\n",
        encoding="utf-8",
    )

    value = load_contract(path)

    assert value["task"]["objective"] == "detection"


def test_missing_claim_scope_is_blocking_schema_error(tmp_path: Path):
    path = tmp_path / "bad.yaml"
    path.write_text("task:\n  objective: detection\n", encoding="utf-8")

    with pytest.raises(ContractError) as exc:
        load_contract(path)

    assert exc.value.code == "BLOCK_CONTRACT_SCHEMA"


def test_generic_template_has_no_tunnel_face_defaults():
    text = Path("templates/simulation_contract.yaml").read_text(encoding="utf-8")

    for forbidden in ("80-200", "40-200", "100 m", "3.5", "5e-4", "37 dBm", "60 dB"):
        assert forbidden not in text


def _full_contract(**overrides):
    payload = {
        "task": {"objective": "detection", "claim_scope": "numerical"},
        "medium": {"model_type": "nondispersive", "parameter_source": "assumed"},
        "waveform": {"excitation_mode": "pulse_broadband", "measurement_mode": "time_domain"},
        "numerics": {"precision_requirement": "auto"},
        "acceptance": {"negative_controls": [], "sensitivity_tests": []},
        "evidence": {"required_outputs": [], "provenance_level": "strict"},
    }
    payload.update(overrides)
    return payload


def test_contract_accepts_2_5d_dimension(tmp_path: Path):
    """Regression: model.dimension must accept the 2.5d thin-slice tier."""
    payload = _full_contract(model={"dimension": "2.5d"})
    path = tmp_path / "c.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    value = load_contract(path)

    assert value["model"]["dimension"] == "2.5d"


def test_contract_rejects_unknown_dimension(tmp_path: Path):
    payload = _full_contract(model={"dimension": "4d"})
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractError) as exc:
        load_contract(path)

    assert exc.value.code == "BLOCK_CONTRACT_SCHEMA"
