"""Model-card report generation.

Turns a simulation contract (plus optional diagnostics, sensitivity,
processing-chain, and environment-probe results) into a single Markdown
model card — the deliverable that documents what the model is, why it was
built this way, and what its numerical gates say.

The layout follows the taste-skill §2 guide: H1 → metadata line → sections
with tables, symbol-marked gate results (⛔/⚠️/✅), and a restrained palette.
Nothing here invents values: every field comes from the supplied inputs.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def _text(value: Any, default: str = "—") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _medium_row(contract: Mapping[str, Any]) -> list[tuple[str, str]]:
    medium = contract.get("medium") or {}
    if not isinstance(medium, Mapping):
        return []
    return [
        ("目标材料", _text(medium.get("target_material"))),
        ("围岩介质", _text(medium.get("medium_material"))),
        ("色散模型", _text(medium.get("model_type"))),
        ("参数来源", _text(medium.get("parameter_source"))),
    ]


def _geometry_rows(contract: Mapping[str, Any]) -> list[tuple[str, str]]:
    geometry = contract.get("geometry") or {}
    model = contract.get("model") or {}
    if not isinstance(geometry, Mapping):
        return []
    return [
        ("模型维度", _text(model.get("dimension")) if isinstance(model, Mapping) else "—"),
        ("目标几何层级", _text(geometry.get("target_level"))),
        ("天线模型", _text(geometry.get("antenna"))),
        ("模型加噪", _text(geometry.get("noise"))),
    ]


def render_diagnostics_section(
    diagnostics: Sequence[Mapping[str, Any]] | None,
) -> list[str]:
    if not diagnostics:
        return ["_未运行预诊断。_"]
    lines: list[str] = []
    markers = {"BLOCK": "⛔", "WARN": "⚠️", "OK": "✅"}
    for finding in diagnostics:
        severity = str(finding.get("severity", "?")).upper()
        marker = markers.get(severity, "·")
        lines.append(
            f"- {marker} **[{severity}]** {_text(finding.get('check'))}: "
            f"{_text(finding.get('message'))}"
        )
    return lines


def render_sensitivity_section(
    results: Sequence[Mapping[str, Any]] | None, top: int = 5
) -> list[str]:
    if not results:
        return ["_未运行敏感性分析。_"]
    lines = ["| 参数 | 检查 | 相对变化 |", "|---|---|---|"]
    for item in results[:top]:
        relative = item.get("relative_change")
        pct = f"{float(relative):.2%}" if isinstance(relative, (int, float)) else "—"
        lines.append(
            f"| {_text(item.get('parameter'))} | {_text(item.get('check'))} | {pct} |"
        )
    return lines


def render_chain_section(chain: Mapping[str, Any] | None) -> list[str]:
    if not chain:
        return ["_未选择处理链。_"]
    parameters = chain.get("parameters") or {}
    param_text = ", ".join(
        f"{key}={value}" for key, value in sorted(parameters.items())
    ) or "—"
    return [
        f"- **链**: {_text(chain.get('chain'))}",
        f"- **模式**: {_text(chain.get('mode'))}",
        f"- **仅显示**: {'是' if chain.get('display_only') else '否'}",
        f"- **参数**: {param_text}",
        f"- **依据**: {_text(chain.get('rationale'))}",
    ]


def render_environment_section(probe: Mapping[str, Any] | None) -> list[str]:
    if not probe:
        return ["_未探测环境。_"]
    lines: list[str] = []
    gpus = probe.get("gpu") or []
    if gpus:
        for gpu in gpus[:2]:
            lines.append(
                f"- GPU: {_text(gpu.get('name'))} {_text(gpu.get('memory_total'))}"
            )
    else:
        lines.append("- GPU: 未检测到 NVIDIA GPU")
    memory = probe.get("memory_total_gb")
    lines.append(f"- 系统内存: {memory:.1f} GB" if memory else "- 系统内存: 未知")
    disk = probe.get("disk") or {}
    if disk:
        lines.append(
            f"- 磁盘: 总量 {_text(disk.get('total_gb'))} GB / 剩余 {_text(disk.get('free_gb'))} GB"
        )
    gprmax = probe.get("gprmax")
    lines.append(
        f"- gprMax: {_text(gprmax.get('version')) if isinstance(gprmax, Mapping) else '未安装'}"
    )
    return lines


def render_model_card(
    contract: Mapping[str, Any],
    *,
    title: str | None = None,
    diagnostics: Sequence[Mapping[str, Any]] | None = None,
    sensitivity: Sequence[Mapping[str, Any]] | None = None,
    chain: Mapping[str, Any] | None = None,
    probe: Mapping[str, Any] | None = None,
) -> str:
    """Assemble a Markdown model card from the contract and optional evidence."""
    project = contract.get("project") or {}
    task = contract.get("task") or {}
    waveform = contract.get("waveform") or {}
    numerics = contract.get("numerics") or {}

    name = title or _text(project.get("name"), "未命名模型")
    lines: list[str] = [f"# 模型卡 {name}", ""]
    # Metadata line (taste-skill: H1 → metadata, then sections)
    meta = " · ".join(
        filter(
            None,
            [
                f"目标深度 {_text(project.get('target_depth_m'))} m",
                f"频带 {_text(waveform.get('band_mhz'))} MHz",
                f"{_text(waveform.get('measurement_mode'))}",
            ],
        )
    )
    lines.append(f"> {meta}")
    lines.append("")

    # 1. Task and claims
    lines.append("## 任务与声明")
    lines.append("")
    lines.append(
        f"- **场景**: {_text(task.get('objective'))} — 声明范围 {_text(task.get('claim_scope'))}"
    )
    design_type = project.get("design_type")
    design_subtype = project.get("design_subtype")
    if design_type:
        lines.append(f"- **试验设计**: {design_type}（{design_subtype}）")
    factors = project.get("factors")
    if isinstance(factors, list) and factors:
        lines.append(f"- **扫描因素**: {', '.join(map(str, factors))}")
    lines.append("")

    # 2. Configuration tables
    def _section(title: str, rows: list[tuple[str, str]]) -> None:
        lines.append(f"## {title}")
        lines.append("")
        lines.append("| 项 | 值 |")
        lines.append("|---|---|")
        for key, value in rows:
            lines.append(f"| {key} | {value} |")
        lines.append("")

    _section("介质与材料", _medium_row(contract))
    _section("几何与表示层", _geometry_rows(contract))
    _section(
        "数值配置",
        [
            ("精度要求", _text(numerics.get("precision_requirement"))),
            ("PML 层数", _text(numerics.get("pml_layers"))),
            ("激励", _text(waveform.get("excitation_mode"))),
            ("处理路线", _text(waveform.get("processing_route"))),
        ],
    )

    # 3. Numerical gates
    lines.append("## 数值门（预诊断）")
    lines.append("")
    lines.extend(render_diagnostics_section(diagnostics))
    lines.append("")

    # 4. Sensitivity
    lines.append("## 参数敏感性")
    lines.append("")
    lines.extend(render_sensitivity_section(sensitivity))
    lines.append("")

    # 5. Processing chain
    lines.append("## 处理链")
    lines.append("")
    lines.extend(render_chain_section(chain))
    lines.append("")

    # 6. Environment
    lines.append("## 环境")
    lines.append("")
    lines.extend(render_environment_section(probe))
    lines.append("")

    return "\n".join(lines)
