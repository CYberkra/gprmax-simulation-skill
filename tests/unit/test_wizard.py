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
        ("medium_eps_r", "4.0"),
        ("custom_cells_m", "0.05,0.05,0.05"),
        ("domain_m", "60,16,7"),
        ("needs_sfcw", "true"),
        ("band_mhz", "10-100"),
        ("fidelity", "standard"),
        ("dimension", "3d"),
        ("run_env", "server"),
    ):
        wizard.answer(session, field, value)
    return session


def test_create_and_load_session(tmp_path: Path):
    session = wizard.create_session(tmp_path / "s")
    assert session.state_path.is_file()
    loaded = wizard.load_session(tmp_path / "s")
    assert loaded.answers == {}


def test_create_session_does_not_overwrite_existing(tmp_path: Path):
    first = wizard.create_session(tmp_path / "s")
    wizard.answer(first, "scenario_type", "tunnel")
    with pytest.raises(wizard.WizardError):
        wizard.create_session(tmp_path / "s")
    # force resets
    second = wizard.create_session(tmp_path / "s", force=True)
    assert second.answers == {}


def test_answer_validates_types(tmp_path: Path):
    session = wizard.create_session(tmp_path / "s")
    with pytest.raises(wizard.WizardError):
        wizard.answer(session, "target_depth_m", "-5")
    with pytest.raises(wizard.WizardError):
        wizard.answer(session, "scenario_type", "not_a_scenario")
    with pytest.raises(wizard.WizardError):
        wizard.answer(session, "needs_sfcw", "maybe")


def test_answer_rejects_non_numeric_number(tmp_path: Path):
    """Regression: float('abc') must surface as WizardError, not a bare ValueError."""
    session = wizard.create_session(tmp_path / "s")
    with pytest.raises(wizard.WizardError):
        wizard.answer(session, "target_depth_m", "abc")
    with pytest.raises(wizard.WizardError):
        wizard.answer(session, "medium_eps_r", "not-a-number")


def test_answer_rejects_fractional_int(tmp_path: Path):
    """Regression: pml_layers=3.7 must be rejected, not silently truncated to 3."""
    session = wizard.create_session(tmp_path / "s")
    with pytest.raises(wizard.WizardError):
        wizard.answer(session, "pml_layers", 3.7)


def test_answer_validates_band_format(tmp_path: Path):
    session = wizard.create_session(tmp_path / "s")
    with pytest.raises(wizard.WizardError):
        wizard.answer(session, "band_mhz", "not-a-band")
    with pytest.raises(wizard.WizardError):
        wizard.answer(session, "band_mhz", "100-10")  # low > high
    with pytest.raises(wizard.WizardError):
        wizard.answer(session, "band_mhz", "-10-100")
    value = wizard.answer(session, "band_mhz", "10-100")
    assert value == "10-100"


def test_answer_parses_triple_and_factors(tmp_path: Path):
    session = wizard.create_session(tmp_path / "s")
    assert wizard.answer(session, "domain_m", "60, 16, 7") == (60.0, 16.0, 7.0)
    assert wizard.answer(session, "scan_factors", "target_depth_m, band_mhz") == [
        "target_depth_m",
        "band_mhz",
    ]


def test_back_removes_latest_answer(tmp_path: Path):
    session = wizard.create_session(tmp_path / "s")
    wizard.answer(session, "scenario_type", "other")
    wizard.answer(session, "target_depth_m", "10")
    removed = wizard.back(session, 1)
    assert removed == ["target_depth_m"]
    assert "scenario_type" in session.answers


def test_back_empty_raises(tmp_path: Path):
    session = wizard.create_session(tmp_path / "s")
    with pytest.raises(wizard.WizardError):
        wizard.back(session)


def test_status_tracks_required_progress(tmp_path: Path):
    session = _complete_session(tmp_path)
    state = wizard.status(session)
    assert state["complete"] is True
    assert state["remaining_required_fields"] == []


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
    assert contract["waveform"]["excitation_mode"] == "unit_impulse"
    assert contract["waveform"]["solver_excitation"] == "unit_impulse"
    assert contract["waveform"]["measurement_mode"] == "sfcw_equivalent"
    assert contract["waveform"]["processing_route"] == "impulse_lti"
    assert contract["geometry"]["target_level"] == "L3"


def test_dump_requires_complete_session(tmp_path: Path):
    session = wizard.create_session(tmp_path / "s")
    wizard.answer(session, "scenario_type", "other")
    with pytest.raises(wizard.WizardError):
        wizard.dump(session)


def test_dump_rejects_hand_edited_bad_band(tmp_path: Path):
    session = _complete_session(tmp_path)
    session.answers["band_mhz"] = "garbage"
    session.state_path.write_text(
        json.dumps({"answers": session.answers}, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(wizard.WizardError):
        wizard.dump(session)


def test_dump_without_numeric_inputs_marks_unknown(tmp_path: Path):
    session = wizard.create_session(tmp_path / "s")
    for field, value in (
        ("scenario_type", "other"),
        ("target_depth_m", "20"),
        ("target_material", "unknown"),
        ("medium_material", "unknown"),
        ("needs_sfcw", "false"),
        ("band_mhz", "20-200"),
        ("fidelity", "quick"),
        ("dimension", "2d"),
        ("run_env", "local"),
    ):
        wizard.answer(session, field, value)
    payload = wizard.dump(session)
    # numeric inputs were never confirmed -> no silent placeholders
    assert payload["numerics"] is None
    assert payload["numerics_unknown_reason"] is not None
    assert "medium_eps_r" in payload["numerics_unknown_reason"]


def test_contract_factors_strictly_explicit(tmp_path: Path):
    session = _complete_session(tmp_path)
    payload = wizard.dump(session)
    # No scan factors means a single controlled case, not a one-factor sweep.
    assert payload["contract_draft"]["project"]["design_type"] == "single_variable"
    assert payload["contract_draft"]["project"]["design_subtype"] == "single_case"
    assert payload["contract_draft"]["project"]["factors"] == []

    wizard.answer(session, "scan_factors", "target_depth_m")
    payload = wizard.dump(session)
    assert payload["contract_draft"]["project"]["design_type"] == "single_variable"
    assert payload["contract_draft"]["project"]["design_subtype"] == "one_factor"
    assert payload["contract_draft"]["project"]["factors"] == ["target_depth_m"]

    wizard.answer(session, "scan_factors", "target_depth_m,band_mhz")
    payload = wizard.dump(session)
    assert payload["contract_draft"]["project"]["design_type"] == "multi_factor"
    assert payload["contract_draft"]["project"]["design_subtype"] == "factorial"


def test_dump_does_not_invent_pml_default(tmp_path: Path):
    session = _complete_session(tmp_path)
    session.answers.pop("pml_layers", None)
    wizard.save_session(session)
    payload = wizard.dump(session)
    assert payload["numerics"]["pml"]["status"] == "UNKNOWN"
    assert payload["numerics"]["pml"]["layers"] is None
    assert payload["contract_draft"]["numerics"]["pml_layers"] == "unknown"


def test_dump_blocks_unaligned_domain_instead_of_silently_rounding(tmp_path: Path):
    session = _complete_session(tmp_path)
    wizard.answer(session, "domain_m", "60.01,16,7")
    with pytest.raises(wizard.WizardError, match="integer multiple"):
        wizard.dump(session)


def test_dump_to_yaml_serialises(tmp_path: Path):
    session = _complete_session(tmp_path)
    text = wizard.dump_to_yaml(session)
    assert "recommendations" in text
    assert "contract_draft" in text


def test_unknown_field_raises(tmp_path: Path):
    session = wizard.create_session(tmp_path / "s")
    with pytest.raises(wizard.WizardError):
        wizard.answer(session, "no_such_field", "x")


def test_dimension_required_for_dump(tmp_path: Path):
    session = wizard.create_session(tmp_path / "s")
    for field, value in (
        ("scenario_type", "other"),
        ("target_depth_m", "20"),
        ("target_material", "unknown"),
        ("medium_material", "unknown"),
        ("needs_sfcw", "false"),
        ("band_mhz", "20-200"),
        ("fidelity", "quick"),
        ("run_env", "local"),
    ):
        wizard.answer(session, field, value)
    # dimension is required: dump without it must block
    with pytest.raises(wizard.WizardError):
        wizard.dump(session)


def test_dimension_invalid_choice_rejected(tmp_path: Path):
    session = wizard.create_session(tmp_path / "s")
    with pytest.raises(wizard.WizardError):
        wizard.answer(session, "dimension", "4d")


def test_dump_contract_carries_model_dimension(tmp_path: Path):
    session = _complete_session(tmp_path)
    contract = wizard.dump(session)["contract_draft"]
    assert contract["model"]["dimension"] == "3d"
