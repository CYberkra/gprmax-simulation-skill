from pathlib import Path

import json

import pytest
import yaml

import scripts.templates_lib as tl


def _valid_entry(**overrides) -> dict:
    entry = {
        "name": "coal_tunnel_sfcw",
        "scenario": "煤矿巷道",
        "status": "draft",
        "verified_by": [],
        "match": {"scenario_type": "tunnel", "needs_sfcw": True, "depth_range_m": [50, 100]},
        "frozen_parameters": {"medium": {"model": "debye"}, "grid": {"dx_m": 0.04}},
    }
    entry.update(overrides)
    return entry


def test_validate_entry_accepts_valid():
    entry = tl.validate_entry(_valid_entry())
    assert entry["name"] == "coal_tunnel_sfcw"
    assert entry["status"] == "draft"


def test_validate_entry_requires_name():
    with pytest.raises(tl.TemplateError):
        tl.validate_entry(_valid_entry(name=""))


def test_validate_entry_requires_match_scenario_type():
    with pytest.raises(tl.TemplateError):
        tl.validate_entry(_valid_entry(match={"scenario_type": ""}))


def test_validate_entry_requires_match_bool_sfcw():
    with pytest.raises(tl.TemplateError):
        tl.validate_entry(_valid_entry(match={"scenario_type": "tunnel", "needs_sfcw": "yes"}))


def test_validate_entry_verified_needs_by():
    with pytest.raises(tl.TemplateError):
        tl.validate_entry(_valid_entry(status="verified", verified_by=[]))


def test_load_and_roundtrip(tmp_path: Path):
    path = tmp_path / "t.yaml"
    path.write_text(
        yaml.safe_dump(_valid_entry(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    entry = tl.load_template(path)
    assert entry["name"] == "coal_tunnel_sfcw"


def test_build_index(tmp_path: Path):
    (tmp_path / "s.yaml").write_text(
        yaml.safe_dump(_valid_entry(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    index = tl.build_index(tmp_path)
    assert "coal_tunnel_sfcw" in index


def test_build_index_skips_invalid(tmp_path: Path):
    (tmp_path / "bad.yaml").write_text("name: x\n", encoding="utf-8")
    index = tl.build_index(tmp_path)
    assert "x" not in index


def test_match_scenario_returns_none_for_no_match(tmp_path: Path):
    verified = _valid_entry(
        status="verified",
        verified_by=["pkg"],
        match={"scenario_type": "tunnel", "needs_sfcw": True, "depth_range_m": [50, 100]},
    )
    (tmp_path / "t.yaml").write_text(
        yaml.safe_dump(verified, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    # different scenario_type
    assert tl.match_scenario({"scenario_type": "landslide", "needs_sfcw": True}, tmp_path) is None
    # different sfcw flag
    assert tl.match_scenario({"scenario_type": "tunnel", "needs_sfcw": False}, tmp_path) is None
    # depth out of range
    assert tl.match_scenario({"scenario_type": "tunnel", "needs_sfcw": True, "target_depth_m": 20}, tmp_path) is None


def test_match_scenario_returns_on_exact_match(tmp_path: Path):
    verified = _valid_entry(
        status="verified",
        verified_by=["pkg"],
        match={"scenario_type": "tunnel", "needs_sfcw": True, "depth_range_m": [50, 100]},
    )
    (tmp_path / "t.yaml").write_text(
        yaml.safe_dump(verified, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    entry = tl.match_scenario(
        {"scenario_type": "tunnel", "needs_sfcw": True, "target_depth_m": 80}, tmp_path
    )
    assert entry is not None
    assert entry["name"] == "coal_tunnel_sfcw"


def test_match_scenario_ignores_draft(tmp_path: Path):
    (tmp_path / "t.yaml").write_text(
        yaml.safe_dump(
            _valid_entry(match={"scenario_type": "tunnel", "needs_sfcw": True}),
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    entry = tl.match_scenario({"scenario_type": "tunnel", "needs_sfcw": True}, tmp_path)
    assert entry is None  # draft templates are not consulted


def _write_verified_pair(tmp_path: Path) -> None:
    """Write a base template and a more-specific irregular template."""
    base = _valid_entry(
        status="verified",
        verified_by=["pkg"],
        match={"scenario_type": "tunnel", "needs_sfcw": True, "depth_range_m": [50, 100]},
    )
    irregular = _valid_entry(
        name="coal_tunnel_irregular_fp64",
        status="verified",
        verified_by=["pkg2"],
        match={
            "scenario_type": "tunnel",
            "needs_sfcw": True,
            "depth_range_m": [50, 100],
            "geometry_type": "irregular",
        },
    )
    (tmp_path / "coal_tunnel_sfcw.yaml").write_text(
        yaml.safe_dump(base, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    (tmp_path / "coal_tunnel_irregular_fp64.yaml").write_text(
        yaml.safe_dump(irregular, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def test_match_scenario_prefers_specific_template(tmp_path: Path):
    """Regression: when two templates match, the more specific one wins."""
    _write_verified_pair(tmp_path)
    # irregular signature -> the irregular-specific template wins
    entry = tl.match_scenario(
        {
            "scenario_type": "tunnel",
            "needs_sfcw": True,
            "target_depth_m": 80,
            "geometry_type": "irregular",
        },
        tmp_path,
    )
    assert entry is not None
    assert entry["name"] == "coal_tunnel_irregular_fp64"


def test_match_scenario_falls_back_to_generic(tmp_path: Path):
    """Regression: a regular (or geometry-unspecified) study gets the base."""
    _write_verified_pair(tmp_path)
    # no geometry_type in the signature -> base template wins
    entry = tl.match_scenario(
        {"scenario_type": "tunnel", "needs_sfcw": True, "target_depth_m": 80}, tmp_path
    )
    assert entry is not None
    assert entry["name"] == "coal_tunnel_sfcw"
    # explicit regular geometry -> irregular template is excluded, base wins
    entry = tl.match_scenario(
        {
            "scenario_type": "tunnel",
            "needs_sfcw": True,
            "target_depth_m": 80,
            "geometry_type": "regular",
        },
        tmp_path,
    )
    assert entry is not None
    assert entry["name"] == "coal_tunnel_sfcw"


def test_signature_from_contract_geometry_type():
    base = {
        "task": {"objective": "tunnel"},
        "waveform": {"measurement_mode": "sfcw_equivalent"},
    }
    assert tl.signature_from_contract(base).get("geometry_type") is None
    assert (
        tl.signature_from_contract(
            {**base, "geometry": {"target_level": "L1"}}
        )["geometry_type"]
        == "regular"
    )
    assert (
        tl.signature_from_contract(
            {**base, "geometry": {"target_level": "L3"}}
        )["geometry_type"]
        == "irregular"
    )


def test_verify_promotes(tmp_path: Path):
    (tmp_path / "t.yaml").write_text(
        yaml.safe_dump(_valid_entry(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    tl.verify_template("coal_tunnel_sfcw", tmp_path, ["pkg1", "pkg2"])
    entry = tl.load_template(tmp_path / "t.yaml")
    assert entry["status"] == "verified"
    assert entry["verified_by"] == ["pkg1", "pkg2"]


def test_list_templates(tmp_path: Path):
    (tmp_path / "a.yaml").write_text(
        yaml.safe_dump(_valid_entry(name="a"), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    items = tl.list_templates(tmp_path)
    assert any(item["name"] == "a" for item in items)


def test_signature_from_contract():
    contract = {
        "task": {"objective": "tunnel"},
        "waveform": {"measurement_mode": "sfcw_equivalent"},
    }
    sig = tl.signature_from_contract(contract)
    assert sig["scenario_type"] == "tunnel"
    assert sig["needs_sfcw"] is True


# --------------------------------------------------------------------------
# extract_from_study / extract_study_auto (progressive accumulation)
# --------------------------------------------------------------------------

def _study_dir(tmp_path: Path, name: str = "01_20260830_SFCW_SLIDE_WET", **manifest_overrides) -> Path:
    root = tmp_path / name
    root.mkdir()
    (root / "simulation_contract.yaml").write_text(
        yaml.safe_dump(
            {
                "project": {"target_depth_m": 20.0},
                "task": {"objective": "landslide", "claim_scope": "numerical"},
                "medium": {"model_type": "nondispersive", "parameter_source": "literature", "eps_r": 4.0},
                "waveform": {"excitation_mode": "pulse_broadband", "measurement_mode": "sfcw_equivalent"},
                "numerics": {"precision_requirement": "auto", "dx_m": 0.05},
                "acceptance": {"negative_controls": [], "sensitivity_tests": []},
                "evidence": {"required_outputs": [], "provenance_level": "strict"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    manifest = {"study": name, "cases": []}
    manifest.update(manifest_overrides)
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def test_extract_from_study_draft(tmp_path: Path):
    root = _study_dir(tmp_path)
    entry = tl.extract_from_study(root)
    assert entry["name"] == "01_20260830_sfcw_slide_wet"
    assert entry["scenario"] == "landslide"
    assert entry["status"] == "draft"  # manifest has no verified_by
    assert entry["match"]["needs_sfcw"] is True
    assert entry["match"]["depth_range_m"] is None
    assert "medium" in entry["frozen_parameters"]
    assert entry["frozen_parameters"]["waveform"]["measurement_mode"] == "sfcw_equivalent"
    assert entry["provenance"]["study_root"] == str(root)


def test_extract_from_study_verified_from_manifest(tmp_path: Path):
    root = _study_dir(tmp_path, verified_by=["pkgA", "pkgB"])
    entry = tl.extract_from_study(root)
    assert entry["status"] == "verified"
    assert entry["verified_by"] == ["pkgA", "pkgB"]


def test_extract_from_study_missing_contract_raises(tmp_path: Path):
    root = _study_dir(tmp_path)
    (root / "simulation_contract.yaml").unlink()
    with pytest.raises(tl.TemplateError):
        tl.extract_from_study(root)


def test_extract_from_study_missing_manifest_raises(tmp_path: Path):
    root = _study_dir(tmp_path)
    (root / "manifest.json").unlink()
    with pytest.raises(tl.TemplateError):
        tl.extract_from_study(root)


def test_extract_from_study_bad_manifest_raises(tmp_path: Path):
    root = _study_dir(tmp_path)
    (root / "manifest.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(tl.TemplateError):
        tl.extract_from_study(root)


def test_extract_study_auto_stores_and_matches(tmp_path: Path):
    root = _study_dir(tmp_path)
    scenarios = tmp_path / "scenarios"
    target = tl.extract_study_auto(root, scenarios)
    assert target.is_file()
    stored = tl.load_template(target)
    assert stored["status"] == "draft"
    # extracted template must be matched by a study with the same signature
    entry = tl.match_scenario(
        {"scenario_type": "landslide", "needs_sfcw": True, "target_depth_m": 20},
        scenarios,
    )
    assert entry is None  # draft is not consulted
    tl.verify_template(stored["name"], scenarios, ["pkgA"])
    entry = tl.match_scenario(
        {"scenario_type": "landslide", "needs_sfcw": True, "target_depth_m": 20},
        scenarios,
    )
    assert entry is not None and entry["name"] == stored["name"]


def test_extract_study_auto_refuses_verified_overwrite(tmp_path: Path):
    root = _study_dir(tmp_path)
    scenarios = tmp_path / "scenarios"
    tl.extract_study_auto(root, scenarios)
    tl.verify_template("01_20260830_sfcw_slide_wet", scenarios, ["pkgA"])
    with pytest.raises(tl.TemplateError):
        tl.extract_study_auto(root, scenarios)  # verified template must not be clobbered


def test_extract_generic_name_falls_back_to_readme(tmp_path: Path):
    root = _study_dir(tmp_path, name="study")
    entry = tl.extract_from_study(root)
    assert entry["name"]  # derived from README heading or non-empty fallback