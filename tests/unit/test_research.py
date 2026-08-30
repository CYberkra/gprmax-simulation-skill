from pathlib import Path

import pytest
import yaml

import scripts.research as research
import scripts.templates_lib as tl


def _contract(**overrides) -> dict:
    contract = {
        "task": {"objective": "landslide"},
        "medium": {"medium_material": "风化泥岩", "target_material": "unknown"},
        "waveform": {"measurement_mode": "time_domain"},
    }
    contract.update(overrides)
    return contract


def _write_material(dirpath: Path, name: str) -> None:
    (dirpath / "rock").mkdir(parents=True, exist_ok=True)
    (dirpath / "rock" / f"{name}.yaml").write_text(
        yaml.safe_dump(
            {
                "name": name,
                "category": "rock",
                "properties": {"eps_r": 4.0, "sigma_s_m": 1e-4, "model": "none"},
                "source": {"kind": "literature", "ref": "test"},
                "confidence": 3,
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )


def _write_verified_template(dirpath: Path, scenario: str, needs_sfcw: bool) -> None:
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / "t.yaml").write_text(
        yaml.safe_dump(
            {
                "name": f"{scenario}_tpl",
                "scenario": scenario,
                "status": "verified",
                "verified_by": ["pkg"],
                "match": {"scenario_type": scenario, "needs_sfcw": needs_sfcw},
                "frozen_parameters": {"medium": {"model": "debye"}},
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )


def test_unknown_target_raises_material_need(tmp_path: Path):
    mats = tmp_path / "materials"
    mats.mkdir()
    needs = research.identify_research_needs(_contract(), materials_dir=mats)
    kinds = {need.kind for need in needs}
    assert "material" in kinds
    assert any("目标材料" in need.topic for need in needs)


def test_missing_material_entry_raises_need(tmp_path: Path):
    mats = tmp_path / "materials"
    _write_material(mats, "砂岩")
    contract = _contract(medium={"medium_material": "石英岩", "target_material": "砂岩"})
    needs = research.identify_research_needs(contract, materials_dir=mats)
    # 石英岩 not in library -> need; 砂岩 in library -> no need
    assert any("石英岩" in need.topic for need in needs)
    assert not any("砂岩" in need.topic for need in needs)


def test_material_present_means_no_need(tmp_path: Path):
    mats = tmp_path / "materials"
    _write_material(mats, "砂岩")
    contract = _contract(medium={"medium_material": "砂岩", "target_material": "砂岩"})
    needs = research.identify_research_needs(contract, materials_dir=mats)
    assert not any(need.kind == "material" for need in needs)


def test_scenario_convention_need_when_no_match(tmp_path: Path):
    mats = tmp_path / "materials"
    mats.mkdir()
    scenarios = tmp_path / "scenarios"
    _write_verified_template(scenarios, "tunnel", False)
    # study is landslide -> no verified match -> scenario convention need
    needs = research.identify_research_needs(
        _contract(), materials_dir=mats, scenarios_dir=scenarios
    )
    assert any(need.kind == "scenario_convention" for need in needs)


def test_no_scenario_need_when_match(tmp_path: Path):
    mats = tmp_path / "materials"
    _write_material(mats, "砂岩")
    scenarios = tmp_path / "scenarios"
    _write_verified_template(scenarios, "landslide", False)
    contract = _contract(
        medium={"medium_material": "砂岩", "target_material": "砂岩"}
    )
    needs = research.identify_research_needs(
        contract, materials_dir=mats, scenarios_dir=scenarios
    )
    assert needs == []


def test_render_needs_empty_and_nonempty():
    assert "无需调研" in research.render_needs([])
    from scripts.research import ResearchNeed

    text = research.render_needs(
        [ResearchNeed("material", "含水滑带", "未知材料", "required")]
    )
    assert "调研需求清单" in text
    assert "含水滑带" in text


def test_render_mentions_user_confirmation():
    from scripts.research import ResearchNeed

    text = research.render_needs(
        [ResearchNeed("scenario_convention", "滑坡", "无模板", "required")]
    )
    assert "用户确认" in text