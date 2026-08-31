"""Research-need identification for the guided setup.

After the wizard produces a contract draft, the agent must know *what* to
research and *why* before dispatching an external research capability (for
example agent-reach / web search). This module turns the contract against the
local material library and the verified scene template library into a small,
explicit list of needs:

- a material need when the study names a medium/target not present in the
  local material library (dispersion parameters included);
- a scenario-convention need when no *verified* scene template strictly
  matches the study (never a partial/nearest reference).

The actual web research is executed by the agent layer; this module only
produces the task list and renders it for hand-off.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from scripts import materials, templates_lib


@dataclass(frozen=True)
class ResearchNeed:
    kind: str  # "material" | "scenario_convention"
    topic: str
    reason: str
    priority: str  # "required" | "recommended"

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "topic": self.topic,
            "reason": self.reason,
            "priority": self.priority,
        }


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    return value


def identify_research_needs(
    contract: Mapping[str, Any],
    materials_dir: Path | None = None,
    scenarios_dir: Path | None = None,
) -> list[ResearchNeed]:
    """Return the research needs for a contract draft, given local libraries.

    ``materials_dir`` and ``scenarios_dir`` default to ``materials/`` and
    ``templates/scenarios/`` relative to the current directory when absent.
    """
    medium = _mapping(contract.get("medium"), "contract.medium")

    materials_root = Path(materials_dir) if materials_dir else Path("materials")
    scenarios_root = Path(scenarios_dir) if scenarios_dir else Path("templates") / "scenarios"
    known_materials = set(materials.list_entries(materials_root))

    needs: list[ResearchNeed] = []

    for field, label in (("medium_material", "围岩介质"), ("target_material", "目标材料")):
        raw = medium.get(field)
        if raw is None:
            needs.append(
                ResearchNeed(
                    kind="material",
                    topic=f"{label}（{field}）",
                    reason="未提供材料，需调研确立介电/色散参数",
                    priority="required",
                )
            )
        elif not isinstance(raw, str) or raw.strip().lower() in ("unknown", ""):
            needs.append(
                ResearchNeed(
                    kind="material",
                    topic=f"{label}（{field}）",
                    reason="向导中标记为未知，需调研确立介电/色散参数",
                    priority="required",
                )
            )
        elif raw not in known_materials:
            needs.append(
                ResearchNeed(
                    kind="material",
                    topic=f"{label}：{raw}",
                    reason=f"本地材料库无该条目（{field}），需调研以入库",
                    priority="required",
                )
            )

    signature = templates_lib.signature_from_contract(contract)
    matched = (
        templates_lib.match_scenario(signature, scenarios_root)
        if scenarios_root.is_dir()
        else None
    )
    if matched is None:
        needs.append(
            ResearchNeed(
                kind="scenario_convention",
                topic=f"场景惯例：{signature['scenario_type']}（SFCW={'是' if signature['needs_sfcw'] else '否'}）",
                reason="无已验证场景模板严格匹配，需调研该场景的常规建模方式（天线/网格/频段）",
                priority="required",
            )
        )
    return needs


def render_needs(needs: Sequence[ResearchNeed]) -> str:
    """Render the need list as a hand-off task list for the agent's research."""
    if not needs:
        return "无需调研：材料库与已验证模板已覆盖全部需求。"
    lines = ["## 调研需求清单（research needs）"]
    for index, need in enumerate(needs, start=1):
        lines.append(
            f"{index}. [{need.priority}] {need.kind}: {need.topic}\n"
            f"   原因：{need.reason}"
        )
    lines.append(
        "\n> 以需求为方向展开调研；结果呈现来源/置信度/最优-折中-不推荐，"
        "经用户确认后再入库。"
    )
    return "\n".join(lines)


from typing import Sequence  # noqa: E402