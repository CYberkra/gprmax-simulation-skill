from __future__ import annotations

import json

import numpy as np

from scripts.cli import main


def _config() -> dict:
    return {
        "tones_hz": [50e6, 60e6, 70e6],
        "requested_max_delay_s": 50e-9,
        "source": {
            "dt_s": 1e-9,
            "minimum_support_ratio": 0.01,
            "max_dc_ratio": 0.5,
            "max_tail_energy_fraction": 0.1,
        },
        "processing": {
            "processing_id": "cli-test",
            "mode": "impulse_lti",
            "frequency_extraction": "quadrature_mixing",
            "tone_source": "declared_list",
            "nfft": 24,
            "window": {"kind": "rectangular"},
            "zero_padding": {
                "factor": 8,
                "claims_physical_resolution_gain": False,
            },
            "quantitative_normalization": "none",
            "source_delay": {
                "artificial_delay_s": 0.0,
                "correction_count": 0,
                "residual_group_delay_abs_s": 0.0,
                "tolerance_s": 0.0,
            },
            "reference": {
                "class": "none",
                "requested_use": "none",
                "field_available": False,
            },
        },
        "acquisition": {
            "motion_during_sweep": False,
            "positions_change_per_tone": False,
            "tones_completed_per_position": True,
        },
    }


def _write_inputs(tmp_path, config):
    config_path = tmp_path / "sfcw.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    source_path = tmp_path / "source.npy"
    np.save(source_path, np.array([0.0, 1.0, 0.0]))
    return config_path, source_path


def test_validate_source_cli_writes_pass_gate_and_details(tmp_path):
    config_path, source_path = _write_inputs(tmp_path, _config())
    rc = main(
        [
            "validate-source",
            str(config_path),
            "--project-root",
            str(tmp_path),
            "--source-array",
            str(source_path),
        ]
    )
    assert rc == 0
    report = json.loads((tmp_path / "gates" / "validate-source.json").read_text())
    assert [item["state"] for item in report["results"]] == ["PASS", "PASS"]
    details = json.loads(
        (tmp_path / "gates" / "validate-source-details.json").read_text()
    )
    assert details["sfcw_audit"]["processing_id"] == "cli-test"


def test_validate_source_cli_blocks_policy_defect_and_returns_two(tmp_path):
    config = _config()
    config["processing"]["quantitative_normalization"] = "per_trace"
    config_path, source_path = _write_inputs(tmp_path, config)
    rc = main(
        [
            "validate-source",
            str(config_path),
            "--project-root",
            str(tmp_path),
            "--source-array",
            str(source_path),
        ]
    )
    assert rc == 2
    report = json.loads((tmp_path / "gates" / "validate-source.json").read_text())
    assert report["results"][-1]["code"] == "BLOCK_QUANTITATIVE_NORMALIZATION"


def test_validate_source_cli_blocks_bad_npz_key(tmp_path):
    config_path, _ = _write_inputs(tmp_path, _config())
    source_path = tmp_path / "source.npz"
    np.savez(source_path, first=np.ones(3), second=np.zeros(3))
    rc = main(
        [
            "validate-source",
            str(config_path),
            "--project-root",
            str(tmp_path),
            "--source-array",
            str(source_path),
        ]
    )
    assert rc == 2
    report = json.loads((tmp_path / "gates" / "validate-source.json").read_text())
    assert report["results"][0]["code"] == "BLOCK_SOURCE_CONFIG"
