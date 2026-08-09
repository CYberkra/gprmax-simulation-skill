from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import json
from pathlib import Path
from typing import Any, Mapping


class GateState(StrEnum):
    PASS = "PASS"
    PASS_WITH_LIMITATION = "PASS_WITH_LIMITATION"
    BLOCK = "BLOCK"
    STALE = "STALE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ClaimState(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    CONDITIONAL = "CONDITIONAL"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    STALE = "STALE"


@dataclass(frozen=True)
class GateResult:
    gate_id: str
    state: GateState
    code: str
    summary: str
    evidence: tuple[str, ...] = ()
    invalidates: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["state"] = self.state.value
        value["evidence"] = list(self.evidence)
        value["invalidates"] = list(self.invalidates)
        return value


@dataclass
class GateContext:
    project_root: Path
    contract: Mapping[str, Any]
    artifacts: dict[str, Any] = field(default_factory=dict)


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
