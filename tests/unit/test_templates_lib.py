from pathlib import Path

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