"""End-to-end integration tests: invoke the CLI like a real user.

Each test runs multiple ``main()`` calls in sequence, simulating a project
flow: ``init → probe → template → layout → sfcw process → dataset check-model``.
This catches wiring bugs (missing dispatch branches, argument parsing errors,
import chain failures) that unit tests cannot see.
"""

from pathlib import Path
import json

import pytest
import yaml

from scripts.cli import main

FIXTURE_OUT = Path("tests/fixtures/real_out/mini_3d_rx1.out")
FIXTURE_CONTRACT = Path("tests/fixtures/contracts/minimal_valid.yaml")
SCENARIOS = Path("templates/scenarios")


def test_e2e_init_probe_template_layout(tmp_path: Path):
    """New project: init → probe → template list/match → layout audit → hash."""
    study = tmp_path / "01_20260830_E2E_TEST"

    # 1. init
    rc = main(["init", str(study), "--name", study.name])
    assert rc == 0, f"init failed: {rc}"
    assert (study / "simulation_contract.yaml").is_file()
    assert (study / "manifest.json").is_file()

    # 2. probe — even without GPU, must not crash
    rc = main(["probe", "--output-dir", str(study)])
    assert rc == 0, f"probe failed: {rc}"

    # 3. template list — must find the built-in coal_tunnel_sfcw template
    rc = main(["template", "list", "--scenarios-dir", str(SCENARIOS)])
    assert rc == 0, f"template list failed: {rc}"

    # 4. template match — the minimal contract is archaeology, not tunnel
    rc = main(["template", "match", str(FIXTURE_CONTRACT), "--scenarios-dir", str(SCENARIOS)])
    # Should produce "no verified template" (rc=0) because the contract is not tunnel
    assert rc == 0, f"template match failed: {rc}"

    # 5. layout audit — fresh skeleton passes (no BLOCK)
    rc = main(["layout", "audit", str(study)])
    assert rc == 0, f"layout audit on fresh skeleton failed: {rc}"

    # 6. layout hash — needs outputs/ with evidence
    (study / "outputs" / "dummy.out").write_bytes(b"dummy evidence")
    rc = main(["layout", "hash", str(study)])
    assert rc == 0, f"layout hash failed: {rc}"
    manifest = json.loads((study / "manifest.json").read_text(encoding="utf-8"))
    assert "outputs_sha256" in manifest
    assert "dummy.out" in manifest["outputs_sha256"]

    # 7. layout audit after hash — must pass
    rc = main(["layout", "audit", str(study)])
    assert rc == 0, f"layout audit after hash failed: {rc}"

    # 8. dataset check-model — BLOCK because no contract with model.dimension
    rc = main(["dataset", "check-model", "--study", str(study)])
    assert rc == 2, f"dataset check-model should block: {rc}"


def test_e2e_sfcw_process_real_output(tmp_path: Path):
    """Process a real gprMax output with the sfcw process command."""
    if not FIXTURE_OUT.is_file():
        pytest.skip("real gprMax fixture missing; regenerate with gprMax")

    import h5py
    import numpy as np

    # Extract Ez from the .out and save as .npy (the impulse_response parameter
    # expects a stand-alone array, not a gprMax output file).
    with h5py.File(FIXTURE_OUT, "r") as handle:
        ez = np.asarray(handle["rxs/rx1/Ez"])
    impulse_path = tmp_path / "impulse.npy"
    np.save(impulse_path, ez)

    out_dir = tmp_path / "results"
    rc = main(
        [
            "sfcw",
            "process",
            str(FIXTURE_OUT),
            "--mode", "impulse_lti",
            "--band", "200-350",
            "--df-mhz", "50",
            "--impulse-response", str(impulse_path),
            "--output-dir", str(out_dir),
        ]
    )
    assert rc == 0, f"sfcw process failed: {rc}"
    assert out_dir.is_dir()
    pngs = list(out_dir.glob("*.png"))
    assert len(pngs) >= 1, f"no PNG produced in {out_dir}"
    assert pngs[0].stat().st_size > 1000, "empty PNG"


def test_e2e_template_extract_and_match(tmp_path: Path):
    """Build a study, make it extractable, then match it."""
    import shutil

    study = tmp_path / "01_20260830_EXTRACT_TEST"
    rc = main(["init", str(study), "--name", study.name])
    assert rc == 0

    # Write a contract that matches the coal_tunnel_sfcw template
    contract = {
        "project": {"target_depth_m": 80.0},
        "task": {"objective": "tunnel", "claim_scope": "numerical"},
        "medium": {"model_type": "nondispersive", "parameter_source": "literature"},
        "waveform": {
            "excitation_mode": "pulse_broadband",
            "measurement_mode": "sfcw_equivalent",
            "band_mhz": "30-240",
        },
        "numerics": {"precision_requirement": "auto"},
        "acceptance": {"negative_controls": [], "sensitivity_tests": []},
        "evidence": {"required_outputs": [], "provenance_level": "strict"},
    }
    (study / "simulation_contract.yaml").write_text(
        yaml.safe_dump(contract, sort_keys=False), encoding="utf-8"
    )

    # Add manifest and dummy outputs for extract
    manifest = {"study": study.name, "cases": []}
    (study / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    (study / "outputs").mkdir(parents=True, exist_ok=True)
    (study / "outputs" / "run.out").write_bytes(b"evidence")

    # Extract template
    scenarios = tmp_path / "scenarios"
    scenarios.mkdir()
    # Copy the built-in coal_tunnel template so the lib has something
    shutil.copy(SCENARIOS / "coal_tunnel_sfcw.yaml", scenarios / "coal_tunnel_sfcw.yaml")

    rc = main(["template", "extract", str(study), "--scenarios-dir", str(scenarios)])
    # Should succeed (create draft) or fail if verified template of same name exists
    # The extracted name depends on the study name
    assert rc == 0, f"template extract failed: {rc}"


def test_e2e_dataset_flow(tmp_path: Path):
    """dataset sample blocks without model, --force works, check-model reports."""
    study = tmp_path / "study"
    study.mkdir()
    (study / "outputs").mkdir()

    # 1. check-model without contract
    rc = main(["dataset", "check-model", "--study", str(study)])
    assert rc == 2

    # 2. sample without model
    space = tmp_path / "space.yaml"
    space.write_text(
        yaml.safe_dump(
            {
                "count": 3,
                "strategy": "random",
                "seed": 42,
                "dimensions": [
                    {"name": "depth_m", "type": "uniform", "min": 60.0, "max": 95.0}
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    rc = main(["dataset", "sample", str(space), "--study", str(study)])
    assert rc == 2, "dataset sample without model must block"

    # 3. sample with --force
    rc = main(["dataset", "sample", str(space), "--study", str(study), "--force"])
    assert rc == 0, f"dataset sample --force failed: {rc}"
    assert (study / "cases.json").is_file()


def test_e2e_report_model_card_and_sketch(tmp_path: Path):
    """report model-card and sketch geometry run end-to-end on a contract."""
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(
        yaml.safe_dump(
            {
                "project": {"target_depth_m": 80.0, "target_size_m": 4.0},
                "model": {"dimension": "3d"},
                "task": {"objective": "tunnel", "claim_scope": "numerical"},
                "medium": {
                    "target_material": "WET",
                    "medium_material": "coal",
                    "model_type": "debye",
                    "parameter_source": "literature",
                },
                "waveform": {
                    "excitation_mode": "unit_impulse",
                    "measurement_mode": "sfcw_equivalent",
                    "processing_route": "impulse_lti",
                    "band_mhz": "30-240",
                },
                "numerics": {"precision_requirement": "fp32", "pml_layers": 20},
                "geometry": {
                    "target_level": "L3",
                    "antenna": "ideal_hertzian",
                    "noise": "none",
                },
                "acceptance": {"negative_controls": [], "sensitivity_tests": []},
                "evidence": {"required_outputs": ["rxs/rx1/Ez"], "provenance_level": "strict"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    # 1. report model-card
    card_path = tmp_path / "model_card.md"
    rc = main(
        ["report", "model-card", str(contract_path), "--out", str(card_path), "--chain", "advanced"]
    )
    assert rc == 0, f"report model-card failed: {rc}"
    assert card_path.is_file()
    card_text = card_path.read_text(encoding="utf-8")
    assert "## 任务与声明" in card_text
    assert "## 处理链" in card_text

    # 2. sketch geometry
    png_path = tmp_path / "sketch.png"
    rc = main(["sketch", "geometry", str(contract_path), "--out", str(png_path)])
    assert rc == 0, f"sketch geometry failed: {rc}"
    assert png_path.is_file()
    assert png_path.stat().st_size > 5000

    # 3. missing target depth blocks the sketch
    bad_path = tmp_path / "bad.yaml"
    bad_path.write_text(
        yaml.safe_dump(
            {
                "task": {"objective": "tunnel", "claim_scope": "numerical"},
                "medium": {"model_type": "nondispersive", "parameter_source": "assumed"},
                "waveform": {
                    "excitation_mode": "pulse_broadband",
                    "measurement_mode": "time_domain",
                },
                "numerics": {"precision_requirement": "auto"},
                "acceptance": {"negative_controls": [], "sensitivity_tests": []},
                "evidence": {"required_outputs": [], "provenance_level": "strict"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    rc = main(["sketch", "geometry", str(bad_path), "--out", str(tmp_path / "bad.png")])
    assert rc == 2, "sketch without target depth must block"


def test_e2e_full_realdata_chain(tmp_path: Path):
    """Real fixture: init → hash → audit → extract → report → sketch → check-model."""
    import shutil

    study = tmp_path / "01_20260831_FULLCHAIN"
    rc = main(["init", str(study), "--name", study.name])
    assert rc == 0, "init failed"

    # Real contract
    contract = {
        "project": {"design_type": "single_variable", "design_subtype": "single_case",
                     "factors": [], "invariants": [], "target_depth_m": 80.0, "target_size_m": 4.0},
        "model": {"dimension": "3d"},
        "task": {"objective": "tunnel", "claim_scope": "numerical"},
        "medium": {"target_material": "WET", "medium_material": "coal",
                   "model_type": "debye", "parameter_source": "literature"},
        "waveform": {"excitation_mode": "unit_impulse", "solver_excitation": "unit_impulse",
                     "measurement_mode": "sfcw_equivalent", "processing_route": "impulse_lti",
                     "band_mhz": "30-240"},
        "numerics": {"precision_requirement": "fp32", "pml_layers": 20},
        "geometry": {"target_level": "L3", "antenna": "ideal_hertzian", "noise": "none"},
        "acceptance": {"negative_controls": [], "sensitivity_tests": []},
        "evidence": {"required_outputs": ["rxs/rx1/Ez"], "provenance_level": "strict"},
    }
    (study / "simulation_contract.yaml").write_text(
        yaml.safe_dump(contract, sort_keys=False), encoding="utf-8"
    )

    # Copy real .out fixture
    fixture = Path("tests/fixtures/real_out/mini_3d_rx1.out")
    if fixture.is_file():
        shutil.copy(fixture, study / "outputs" / "case.out")
    else:
        pytest.skip("real fixture missing")

    # layout hash
    rc = main(["layout", "hash", str(study)])
    assert rc == 0, f"hash failed: {rc}"

    # layout audit
    rc = main(["layout", "audit", str(study)])
    assert rc == 0, f"audit failed: {rc}"

    # template extract
    scenarios = tmp_path / "scenarios"
    scenarios.mkdir()
    rc = main(["template", "extract", str(study), "--scenarios-dir", str(scenarios)])
    assert rc == 0, f"extract failed: {rc}"

    # report model-card
    card = study / "analysis" / "card.md"
    rc = main(["report", "model-card", str(study / "simulation_contract.yaml"),
               "--out", str(card)])
    assert rc == 0, f"report failed: {rc}"
    assert "## 处理链" in card.read_text(encoding="utf-8")

    # sketch geometry
    png = study / "analysis" / "sketch.png"
    rc = main(["sketch", "geometry", str(study / "simulation_contract.yaml"),
               "--out", str(png)])
    assert rc == 0, f"sketch failed: {rc}"
    assert png.stat().st_size > 5000

    # dataset check-model — established
    rc = main(["dataset", "check-model", "--study", str(study)])
    assert rc == 0, f"check-model should pass: {rc}"


def test_e2e_wizard_dump_with_sketch(tmp_path: Path):
    """wizard dump --sketch renders a geometry sketch from the contract draft."""
    session = tmp_path / "sess"
    rc = main(["wizard", "init", str(session)])
    assert rc == 0

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
        rc = main(["wizard", "answer", str(session), field, value])
        assert rc == 0, f"answer {field} failed: {rc}"

    dump_path = tmp_path / "dump.yaml"
    sketch_path = tmp_path / "sketch.png"
    rc = main(
        [
            "wizard", "dump", str(session),
            "--out", str(dump_path),
            "--sketch", str(sketch_path),
        ]
    )
    assert rc == 0, f"wizard dump failed: {rc}"
    assert dump_path.is_file(), "dump file missing"
    assert sketch_path.is_file(), "sketch PNG missing"
    assert sketch_path.stat().st_size > 5000, "empty sketch"