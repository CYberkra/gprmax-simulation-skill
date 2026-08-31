from pathlib import Path

import pytest

from scripts.scaffold import (
    STANDARD_DIRECTORIES,
    STANDARD_FILES,
    ScaffoldError,
    audit_layout,
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


# --------------------------------------------------------------------------
# layout discipline audit
# --------------------------------------------------------------------------

def _severity(findings: list[dict], check: str) -> str:
    severities = [f["severity"] for f in findings if f["check"] == check]
    if not severities:
        raise AssertionError(f"no finding for check {check!r} in {findings}")
    # Return the highest severity for the check
    return max(severities, key=lambda s: {"OK": 0, "WARN": 1, "BLOCK": 2}[s])


def test_audit_layout_fresh_skeleton_all_ok(tmp_path: Path):
    root = tmp_path / "01_20260830_SFCW_SLIDE_WET"
    create_study_skeleton(root, name=root.name)
    (root / "outputs" / "case.out").write_text("x", encoding="utf-8")
    findings = audit_layout(root)
    assert findings
    assert all(f["severity"] != "BLOCK" for f in findings)
    assert _severity(findings, "layout") == "OK"
    assert _severity(findings, "outputs") == "OK"


def test_audit_layout_missing_directory_blocks(tmp_path: Path):
    root = tmp_path / "study"
    create_study_skeleton(root)
    (root / "outputs" / ".gitkeep").unlink()
    (root / "outputs").rmdir()
    findings = audit_layout(root)
    assert _severity(findings, "layout") == "BLOCK"
    assert _severity(findings, "outputs") == "BLOCK"


def test_audit_layout_stray_input_warns(tmp_path: Path):
    root = tmp_path / "study"
    create_study_skeleton(root)
    (root / "rogue.in").write_text("# stray\n", encoding="utf-8")
    findings = audit_layout(root)
    assert _severity(findings, "stray") == "WARN"


def test_audit_layout_outputs_forbidden_material_blocks(tmp_path: Path):
    root = tmp_path / "study"
    create_study_skeleton(root)
    (root / "outputs" / "run_case.py").write_text("print(1)\n", encoding="utf-8")
    findings = audit_layout(root)
    assert _severity(findings, "outputs") == "BLOCK"


def test_audit_layout_broken_contract_blocks(tmp_path: Path):
    root = tmp_path / "study"
    create_study_skeleton(root)
    (root / "simulation_contract.yaml").write_text("task: [unclosed\n", encoding="utf-8")
    findings = audit_layout(root)
    assert _severity(findings, "contract") == "BLOCK"


def test_audit_layout_non_mapping_contract_blocks(tmp_path: Path):
    root = tmp_path / "study"
    create_study_skeleton(root)
    (root / "simulation_contract.yaml").write_text("- just\n- a list\n", encoding="utf-8")
    findings = audit_layout(root)
    assert _severity(findings, "contract") == "BLOCK"