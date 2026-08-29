from pathlib import Path

import pytest

from scripts.scaffold import (
    STANDARD_DIRECTORIES,
    STANDARD_FILES,
    ScaffoldError,
    create_study_skeleton,
    describe_layout,
    validate_study_name,
)


def test_validate_study_name_accepts_convention():
    assert (
        validate_study_name("01_20260830_SFCW_SLIDE_WET")
        == "01_20260830_SFCW_SLIDE_WET"
    )


def test_validate_study_name_rejects_bad_names():
    for bad in ("bad", "20260830_SFCW", "01_20260830", "01_20260830_slide wet"):
        with pytest.raises(ScaffoldError):
            validate_study_name(bad)


def test_create_study_skeleton_creates_full_layout(tmp_path: Path):
    root = tmp_path / "study"
    created = create_study_skeleton(root, name="01_20260830_SFCW_SLIDE_WET")

    for directory in STANDARD_DIRECTORIES:
        assert (root / directory).is_dir()
    for filename in STANDARD_FILES:
        assert (root / filename).is_file()

    # The outputs/ directory is marked to survive git.
    assert (root / "outputs" / ".gitkeep").exists()
    # Contract template is copied.
    assert "task:" in (root / "simulation_contract.yaml").read_text(encoding="utf-8")
    # Manifest skeleton is valid JSON.
    import json

    json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    # README carries the study name.
    assert "01_20260830_SFCW_SLIDE_WET" in (root / "README.md").read_text(
        encoding="utf-8"
    )


def test_create_study_skeleton_does_not_overwrite_existing_files(tmp_path: Path):
    root = tmp_path / "study"
    create_study_skeleton(root, name="01_20260830_SFCW_SLIDE_WET")
    original = (root / "simulation_contract.yaml").read_text(encoding="utf-8")

    (root / "simulation_contract.yaml").write_text("custom: true\n", encoding="utf-8")
    create_study_skeleton(root, name="01_20260830_SFCW_SLIDE_WET")

    assert (root / "simulation_contract.yaml").read_text(encoding="utf-8") == (
        "custom: true\n"
    )


def test_create_study_skeleton_no_name_still_builds(tmp_path: Path):
    root = tmp_path / "s"
    create_study_skeleton(root)
    for directory in STANDARD_DIRECTORIES:
        assert (root / directory).is_dir()
    assert (root / "README.md").is_file()


def test_describe_layout_lists_all_paths(tmp_path: Path):
    root = tmp_path / "study"
    create_study_skeleton(root)
    layout = describe_layout(root)
    expected = len(STANDARD_DIRECTORIES) + len(STANDARD_FILES)
    assert len(layout) == expected
    assert str(root / "outputs") in layout
    assert str(root / "simulation_contract.yaml") in layout