from pathlib import Path

import pytest
import yaml

import scripts.materials as materials


def _valid_entry(**overrides) -> dict:
    entry = {
        "name": "砂岩（干燥）",
        "category": "rock",
        "properties": {"eps_r": 4.5, "sigma_s_m": 1e-4, "model": "none"},
        "frequency_valid": [10, 1000],
        "source": {"kind": "measured", "ref": "Knight & Nur 1987"},
        "confidence": 4,
    }
    entry.update(overrides)
    return entry


def test_validate_entry_accepts_valid():
    entry = materials.validate_entry(_valid_entry())
    assert entry["name"] == "砂岩（干燥）"
    assert entry["category"] == "rock"
    assert entry["confidence"] == 4


def test_validate_entry_requires_name():
    with pytest.raises(materials.MaterialError):
        materials.validate_entry(_valid_entry(name=""))


def test_validate_entry_requires_known_category():
    with pytest.raises(materials.MaterialError):
        materials.validate_entry(_valid_entry(category="grass"))


def test_validate_entry_requires_permittivity():
    with pytest.raises(materials.MaterialError):
        materials.validate_entry(
            _valid_entry(properties={"sigma_s_m": 1e-4, "model": "none"})
        )


def test_validate_entry_accepts_debye_properties():
    entry = materials.validate_entry(
        _valid_entry(
            properties={
                "model": "debye",
                "eps_inf": 2.8,
                "delta_eps": 0.2,
                "tau_s": 3.4e-10,
                "sigma_s_m": 1.4e-4,
            }
        )
    )
    assert entry["properties"]["model"] == "debye"


def test_validate_entry_requires_provenance():
    with pytest.raises(materials.MaterialError):
        materials.validate_entry(_valid_entry(source={}))


def test_validate_entry_rejects_unknown_source_kind():
    with pytest.raises(materials.MaterialError):
        materials.validate_entry(_valid_entry(source={"kind": "guess", "ref": "x"}))


def test_write_yaml_roundtrip(tmp_path: Path):
    path = tmp_path / "sandstone.yaml"
    path.write_text(
        yaml.safe_dump(_valid_entry(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    entry = materials.load_material(path)
    assert entry["name"] == "砂岩（干燥）"
    assert entry["properties"]["eps_r"] == 4.5


def test_build_index_and_resolve(tmp_path: Path):
    library = tmp_path / "materials"
    (library / "rock").mkdir(parents=True)
    entry_path = library / "rock" / "sandstone.yaml"
    entry_path.write_text(
        yaml.safe_dump(_valid_entry(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    index = materials.build_index(library)
    assert "砂岩（干燥）" in index
    assert index["砂岩（干燥）"]["category"] == "rock"

    resolved = materials.resolve_entry("砂岩（干燥）", library)
    assert resolved is not None
    assert resolved == entry_path


def test_build_index_skips_invalid_entries(tmp_path: Path):
    library = tmp_path / "materials"
    library.mkdir()
    (library / "broken.yaml").write_text("name: x\n", encoding="utf-8")
    index = materials.build_index(library)
    assert "_invalid" in index


def test_resolve_entry_prefers_override(tmp_path: Path):
    library = tmp_path / "materials"
    (library / "rock").mkdir(parents=True)
    (library / "rock" / "sandstone.yaml").write_text(
        yaml.safe_dump(_valid_entry(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    override = tmp_path / "materials_override"
    override.mkdir()
    (override / "sandstone_local.yaml").write_text(
        yaml.safe_dump(
            _valid_entry(name="砂岩（干燥）", confidence=2),
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    resolved = materials.resolve_entry("砂岩（干燥）", library, override_dir=override)
    assert resolved is not None
    assert "materials_override" in str(resolved)


def test_list_entries_merges_override(tmp_path: Path):
    library = tmp_path / "materials"
    (library / "rock").mkdir(parents=True)
    (library / "rock" / "a.yaml").write_text(
        yaml.safe_dump(_valid_entry(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    override = tmp_path / "materials_override"
    override.mkdir()
    (override / "b.yaml").write_text(
        yaml.safe_dump(
            _valid_entry(name="混凝土", category="concrete"),
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    names = materials.list_entries(library, override_dir=override)
    assert "砂岩（干燥）" in names
    assert "混凝土" in names


def test_write_index_json(tmp_path: Path):
    target = tmp_path / "index.json"
    materials.write_index({"a": {"path": "a.yaml", "category": "rock"}}, target)
    import json

    assert json.loads(target.read_text(encoding="utf-8")) == {
        "a": {"path": "a.yaml", "category": "rock"}
    }