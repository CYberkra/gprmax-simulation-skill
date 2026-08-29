from pathlib import Path
import json

import pytest

import scripts.wizard as wizard


def _complete_session(tmp_path: Path) -> wizard.Session:
    session = wizard.create_session(tmp_path / "session")
    for field, value in (
        ("scenario_type", "landslide"),
        ("target_depth_m", "20"),
        ("target_material", "含水滑带"),
        ("medium_material", "风化泥岩"),
        ("needs_sfcw", "true"),
        ("band_mhz", "10-100"),
        ("fidelity", "standard"),
        ("run_env", "server"),
    ):
        wizard.answer(session, field, value)
    return session


def test_create_and_load_session(tmp_path: Path):
    session = wizard.create_session(tmp_path / "s")
    assert session.state_path.is_file()

    loaded = wizard.load_session(tmp_path / "s")
    assert loaded.answers == {}


def test_answer_validates_types(tmp_path: Path):
    session = wizard.create_session(tmp_path / "s")
    with pytest.raises(wizard.WizardError):
        wizard.answer(session, "target_depth_m", "-5")
    with pytest.raises(wizard.WizardError):
        wizard.answer(session, "scenario_type", "not_a_scenario")
    with pytest.raises(wizard.WizardError):
        wizard.answer(session, "needs_sfcw", "maybe")


def test_answer_stores_normalised_value(tmp_path: Path):
    session = wizard.create_session(tmp_path / "s")
    wizard.answer(session, "needs_sfcw", "yes")
    assert session.answers["needs_sfcw"] is True
    wizard.answer(session, "target_depth_m", "20.5")
    assert session.answers["target_depth_m"] == 20.5


def test_back_removes_latest_answer(tmp_path: Path):
    session = wizard.create_session(tmp_path / "s")
    wizard.answer(session, "scenario_type", "other")
    wizard.answer(session, "target_depth_m", "10")
    removed = wizard.back(session, 1)
    assert removed == ["target_depth_m"]
    assert "target_depth_m" not in session.answers
    assert "scenario_type" in session.answers


def test_back_empty_raises(tmp_path: Path):
    session = wizard.create_session(tmp_path / "s")
    with pytest.raises(wizard.WizardError):
        wizard.back(session)


def test_status_tracks_progress(tmp_path: Path):
    session = _complete_session(tmp_path)
    state = wizard.status(session)
    assert state["complete"] is True
    assert state["remaining_fields"] == []
    assert state["incomplete_steps"] == []


def test_dump_full_payload(tmp_path: Path):
    session = _complete_session(tmp_path)
    payload = wizard.dump(session)

    assert payload["answers"]["scenario_type"] == "landslide"
    assert payload["recommendations"]["sfcw"]["option"] == "on"
    assert payload["recommendations"]["geometry"]["option"] == "L3"
    assert any("最高频点" in marker for marker in payload["dependency_markers"])
    assert payload["numerics"] is not None
    assert payload["numerics"]["mesh"]["ok"] is True

    contract = payload["contract_draft"]
    assert contract["waveform"]["excitation_mode"] == "impulse_lti"
    assert contract["geometry"]["target_level"] == "L3"
    assert contract["project"]["design_type"] == "multi_factor"


def test_dump_without_numbers_omits_numerics(tmp_path: Path):
    session = wizard.create_session(tmp_path / "s")
    wizard.answer(session, "scenario_type", "other")
    wizard.answer(session, "fidelity", "quick")
    payload = wizard.dump(session)
    assert payload["numerics"] is None


def test_dump_to_yaml_serialises(tmp_path: Path):
    session = _complete_session(tmp_path)
    text = wizard.dump_to_yaml(session)
    assert "recommendations" in text
    assert "contract_draft" in text


def test_unknown_field_raises(tmp_path: Path):
    session = wizard.create_session(tmp_path / "s")
    with pytest.raises(wizard.WizardError):
        wizard.answer(session, "no_such_field", "x")