"""Configuration axes and recommendation logic for the guided setup.

Each axis offers options with human-readable labels; recommendation logic maps
the user's scenario and fidelity intent (plus explicit needs) onto a suggested
option with a rationale. Dependencies between axes are surfaced as markers so
the wizard can show consequences (for example SFCW-on implies meshing by the
highest tone).

This is generic: no project band, distance, permittivity, or threshold value
is hard-coded here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

SCENARIOS = (
    "tunnel",
    "landslide",
    "archaeology",
    "geotechnical",
    "inspection",
    "other",
)
FIDELITY_INTENTS = ("quick", "standard", "publication")


@dataclass(frozen=True)
class Option:
    id: str
    label: str
    summary: str


@dataclass(frozen=True)
class Axis:
    id: str
    label: str
    question: str
    options: tuple[Option, ...]
    dependents: tuple[str, ...] = ()
    marker: str | None = None


AXES: tuple[Axis, ...] = (
    Axis(
        id="antenna",
        label="天线模型",
        question="用什么天线模型？",
        options=(
            Option("ideal_hertzian", "理想赫兹偶极", "点源近似，最低成本，适合趋势研究"),
            Option("physical", "实体天线", "物理天线（如宽带折叠/贴片），成本高，接近实装"),
            Option("plane_wave", "平面波注入", "无天线，只关心体传播，不关心收发耦合"),
        ),
    ),
    Axis(
        id="sfcw",
        label="SFCW 等效",
        question="需要 SFCW 体制结论吗？",
        options=(
            Option("off", "关（宽带直出）", "时域宽带脉冲，直接看 Ascan/Bscan"),
            Option("on", "开（LTI 冲激响应法）", "对齐刘2021：单次 impulse 正演 + 时域卷积合成频点"),
        ),
        dependents=("mesh", "waveform"),
        marker="SFCW=on → 网格必须按最高频点划分，且用内置 impulse 波形",
    ),
    Axis(
        id="dispersion",
        label="色散模型",
        question="介质用什么色散模型？（通常由材料调研决定）",
        options=(
            Option("none", "常数 ε_r", "频带内介电常数基本平坦时用"),
            Option("debye", "Debye", "含水/极性地层常用单极 Debye"),
            Option("lorentz", "Lorentz", "有共振吸收特性时"),
            Option("drude", "Drude", "导电介质/金属类"),
            Option("measured", "实测复介电", "有实验数据时直接加载"),
        ),
        dependents=("numerics",),
        marker="色散介质需检查 τ/dt 与频带内 cells/λ 随频率变化",
    ),
    Axis(
        id="noise",
        label="模型加噪",
        question="要加噪声或干扰目标体吗？",
        options=(
            Option("none", "无", "理想无噪模型"),
            Option("awgn", "加性高斯噪声", "按 SNR 或动态范围 D 注入，过同一条处理链"),
            Option("clutter", "干扰目标体", "场景常见非检测目标（锚杆/钢筋/碎石等），依据调研清单"),
        ),
        dependents=("processing",),
        marker="AWGN 必须过同一处理链；干扰体清单依据场景模板库",
    ),
    Axis(
        id="geometry",
        label="目标体几何",
        question="目标体几何怎么建？",
        options=(
            Option("L1", "规则体（box/cylinder）", "最简单，成本最低"),
            Option("L2", "规则+粗糙界面", "高斯粗糙度（参数可调），破坏平整界面相干伪影"),
            Option("L3", "非规则轮廓", "掩膜 HDF5，样条截面沿 x 拉伸"),
            Option("L4", "逼真自然", "分形粗糙 + 材料渐变 + 内部异质，成本最高"),
        ),
        dependents=("mesh", "geometry_files"),
        marker="判分辨类结论时，平整界面是相干上限；L2 起可规避规则振荡",
    ),
    Axis(
        id="precision",
        label="数值精度",
        question="fp32 还是 fp64？",
        options=(
            Option("fp32", "fp32", "默认；适用常规动态范围（以精度试验为准）"),
            Option("fp64", "fp64", "高动态范围/弱信号场景；按精度试验与硬件决定"),
        ),
        dependents=("resources",),
        marker="fp32 数值地板与所需动态范围由匹配的精度试验和具体硬件决定，不留常数",
    ),
)


def _validate_option(axis_id: str, option: str) -> str:
    axis = axis_by_id(axis_id)
    ids = {item.id for item in axis.options}
    if option not in ids:
        raise ValueError(
            f"axis {axis_id!r}: unknown option {option!r} (choose from {sorted(ids)})"
        )
    return option


def axis_by_id(axis_id: str) -> Axis:
    for axis in AXES:
        if axis.id == axis_id:
            return axis
    raise KeyError(f"unknown axis: {axis_id}")


def _fidelity_option(axis_id: str, fidelity: str) -> str:
    quick = {"antenna": "ideal_hertzian", "geometry": "L1", "noise": "none"}
    standard = {"antenna": "ideal_hertzian", "geometry": "L3", "noise": "none"}
    publication = {"antenna": "physical", "geometry": "L4", "noise": "awgn"}
    table = {"quick": quick, "standard": standard, "publication": publication}
    return table.get(fidelity, standard).get(axis_id, "")


def recommend(
    scenario: str,
    fidelity: str,
    explicit: Mapping[str, str] | None = None,
    needs_sfcw: bool | None = None,
) -> dict[str, dict[str, str]]:
    """Return per-axis recommendations: {axis_id: {option, rationale}}.

    ``explicit`` may pin an axis (a user's own choice wins) and is validated
    against the axis options. Special needs: ``needs_sfcw`` pins the sfcw
    axis and strengthens geometry for coherence.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario must be one of {SCENARIOS}")
    if fidelity not in FIDELITY_INTENTS:
        raise ValueError(f"fidelity must be one of {FIDELITY_INTENTS}")
    explicit = explicit or {}
    for axis_id, option in explicit.items():
        _validate_option(axis_id, option)

    recommended: dict[str, dict[str, str]] = {}
    for axis in AXES:
        if axis.id in explicit:
            recommended[axis.id] = {
                "option": explicit[axis.id],
                "rationale": "用户明确指定，优先执行",
            }
            continue
        if axis.id == "sfcw" and needs_sfcw is not None:
            option = "on" if needs_sfcw else "off"
            rationale = (
                "用户要求 SFCW 体制结论" if needs_sfcw else "不需要 SFCW 体制结论"
            )
        elif axis.id == "precision":
            option = "fp32"
            rationale = (
                "默认 fp32；动态范围需求改 fp64 需由精度试验与硬件决定（无固定常数）"
            )
        elif axis.id == "sfcw":
            option = _fidelity_option(axis.id, fidelity) or "off"
            rationale = f"{fidelity} 档默认"
        else:
            option = _fidelity_option(axis.id, fidelity) or axis.options[0].id
            rationale = f"{fidelity} 档默认"
            if (
                axis.id == "geometry"
                and option in ("L1", "L2")
                and (scenario in ("landslide", "tunnel") or needs_sfcw)
            ):
                option = "L3"
                rationale = "深部/判分辨场景建议非规则轮廓以规避平整界面相干伪影"
        recommended[axis.id] = {"option": option, "rationale": rationale}
    return recommended


def dependencies_of(axis_id: str) -> tuple[str, ...]:
    return axis_by_id(axis_id).dependents


def markers_for(chosen: Mapping[str, str]) -> list[str]:
    """Return dependency markers for the chosen options."""
    markers: list[str] = []
    for axis_id, option in chosen.items():
        axis = axis_by_id(axis_id)
        if axis.marker and _marker_applies(axis_id, option):
            markers.append(axis.marker)
    return markers


def _marker_applies(axis_id: str, option: str) -> bool:
    if axis_id == "sfcw":
        return option == "on"
    if axis_id == "dispersion":
        return option in ("debye", "lorentz", "drude", "measured")
    if axis_id == "noise":
        return option in ("awgn", "clutter")
    if axis_id == "geometry":
        return option in ("L2", "L3", "L4")
    if axis_id == "precision":
        return option == "fp64"
    return False