"""Tests for ``scripts.report`` — model-card generation."""

import pytest

from scripts import report


def _contract(**overrides):
    contract = {
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
        "geometry": {"target_level": "L3", "antenna": "ideal_hertzian", "noise": "none"},
        "acceptance": {"negative_controls": [], "sensitivity_tests": []},
        "evidence": {"required_outputs": ["rxs/rx1/Ez"], "provenance_level": "strict"},
    }
    contract.update(overrides)
    return contract


def test_render_model_card_has_sections():
    text = report.render_model_card(_contract())
    for section in (
        "## 任务与声明",
        "## 介质与材料",
        "## 几何与表示层",
        "## 数值配置",
        "## 数值门",
        "## 参数敏感性",
        "## 处理链",
        "## 环境",
    ):
        assert section in text, f"missing section {section}"
    assert "# 模型卡" in text


def test_render_model_card_diagnostics_markers():
    diagnostics = [
        {"check": "mesh", "severity": "OK", "message": "cells/λ fine"},
        {"check": "pml", "severity": "WARN", "message": "fewer layers"},
        {"check": "vram", "severity": "BLOCK", "message": "not enough VRAM"},
    ]
    text = report.render_model_card(_contract(), diagnostics=diagnostics)
    assert "✅" in text and "OK" in text
    assert "⚠️" in text and "WARN" in text
    assert "⛔" in text and "BLOCK" in text
    assert "cells/λ fine" in text


def test_render_model_card_sensitivity_table():
    results = [
        {"parameter": "eps_r", "check": "cells_per_wavelength", "relative_change": 0.2},
        {"parameter": "dx", "check": "cfl_fraction", "relative_change": 0.1},
    ]
    text = report.render_model_card(_contract(), sensitivity=results)
    assert "| eps_r | cells_per_wavelength | 20.00% |" in text
    assert "| dx | cfl_fraction | 10.00% |" in text


def test_render_model_card_chain():
    chain = {
        "chain": "advanced",
        "mode": "impulse_lti",
        "parameters": {"zero_pad_factor": 16},
        "display_only": False,
        "rationale": "user-specified chain 'advanced'",
    }
    text = report.render_model_card(_contract(), chain=chain)
    assert "**链**: advanced" in text
    assert "zero_pad_factor=16" in text
    assert "user-specified chain" in text


def test_render_model_card_empty_inputs():
    text = report.render_model_card({})
    assert "未命名模型" in text
    assert "未运行预诊断" in text
    assert "未运行敏感性分析" in text
    assert "未选择处理链" in text
    assert "未探测环境" in text


def test_render_model_card_missing_values_use_dash():
    text = report.render_model_card(
        {"project": {"target_depth_m": 20.0}, "task": {"objective": "landslide"}}
    )
    assert "landslide" in text
    assert "—" in text  # missing values render as em-dash
