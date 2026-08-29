from pathlib import Path
import json

import scripts.probe_environment as probe


def test_collect_probe_returns_expected_keys(tmp_path: Path):
    result = probe.collect_probe(output_volume=tmp_path)

    assert "gpu" in result
    assert "memory_total_gb" in result
    assert "disk" in result
    assert "python" in result
    assert "gprmax" in result
    assert isinstance(result["gpu"], list)
    assert isinstance(result["disk"], dict)


def test_probe_gpu_never_raises():
    # The probe must tolerate a machine without an NVIDIA GPU/driver.
    gpus = probe.probe_gpu()
    assert isinstance(gpus, list)
    for gpu in gpus:
        assert set(gpu) >= {"name", "memory_total", "driver_version"}


def test_probe_disk_returns_gb_dict(tmp_path: Path):
    disk = probe.probe_disk(tmp_path)
    assert set(disk) == {"total_gb", "used_gb", "free_gb"}
    assert disk["total_gb"] > 0


def test_probe_python_has_version_and_executable():
    info = probe.probe_python()
    assert "version" in info
    assert "executable" in info


def test_version_comparison():
    assert probe._version_ge("3.12.1", "3.11") is True
    assert probe._version_ge("3.10.9", "3.11") is False
    assert probe._version_ge("3.12", "3.11.4") is True


def test_format_report_is_human_readable():
    report = probe.collect_probe(output_volume=Path.cwd())
    text = probe.format_report(report)

    assert "GPU" in text
    assert "Python" in text
    assert "gprMax" in text
    assert "不决定运行环境" in text


def test_probe_to_json_is_valid_json():
    report = probe.collect_probe(output_volume=Path.cwd())
    payload = json.loads(probe.probe_to_json(report))
    assert payload["gpu"] == report["gpu"]