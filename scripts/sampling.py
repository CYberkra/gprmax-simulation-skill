"""Sampling engine for the data-factory batch pipeline.

The wizard establishes a model template; this module turns a *sampling
space* into a deterministic list of case parameter snapshots. Each snapshot
is simultaneously the model-generation input and the supervised label (the
ground-truth is the sampled parameter itself), so a dataset for training is
produced without any manual labelling.

Design:
- ``SamplingSpace`` is declared as YAML: a count, a strategy (random | grid),
  a seed, and a list of dimensions.
- Each dimension has a ``type``: ``uniform`` (min/max), ``normal`` (mu/sigma),
  ``choice`` (discrete values), or ``constant`` (fixed value).
- Sampling is seeded and fully reproducible: the same space + seed yields the
  same case list.
- A case list is persisted as JSON (the manifest of the batch); every case
  carries ``case_id`` plus the parameter snapshot (the label).
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import yaml

VALID_STRATEGIES = {"random", "grid"}
VALID_TYPES = {"uniform", "normal", "choice", "constant"}


class SamplingError(ValueError):
    """Invalid sampling space or dimension definition."""


@dataclass(frozen=True)
class Dimension:
    name: str
    type: str
    min: float | None = None
    max: float | None = None
    mu: float | None = None
    sigma: float | None = None
    values: tuple[Any, ...] = ()
    value: Any = None

    def __post_init__(self) -> None:
        if self.type not in VALID_TYPES:
            raise SamplingError(
                f"dimension {self.name!r}: type must be one of {sorted(VALID_TYPES)}"
            )
        if self.type == "uniform" and not (
            isinstance(self.min, (int, float))
            and isinstance(self.max, (int, float))
            and self.min < self.max
        ):
            raise SamplingError(
                f"dimension {self.name!r}: uniform needs min < max"
            )
        if self.type == "normal" and not (
            isinstance(self.mu, (int, float))
            and isinstance(self.sigma, (int, float))
            and self.sigma > 0
        ):
            raise SamplingError(
                f"dimension {self.name!r}: normal needs mu and sigma > 0"
            )
        if self.type == "choice" and not self.values:
            raise SamplingError(f"dimension {self.name!r}: choice needs values")
        if self.type == "constant" and self.value is None:
            raise SamplingError(f"dimension {self.name!r}: constant needs value")


@dataclass(frozen=True)
class SamplingSpace:
    count: int
    strategy: str
    seed: int
    dimensions: tuple[Dimension, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.count, int) or self.count < 1:
            raise SamplingError("count must be a positive integer")
        if self.strategy not in VALID_STRATEGIES:
            raise SamplingError(
                f"strategy must be one of {sorted(VALID_STRATEGIES)}"
            )
        if not isinstance(self.seed, int):
            raise SamplingError("seed must be an integer")
        names = [dim.name for dim in self.dimensions]
        if len(names) != len(set(names)):
            raise SamplingError("dimension names must be unique")


def parse_dimension(raw: Mapping[str, Any], path: str) -> Dimension:
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise SamplingError(f"{path}: dimension 'name' is required")
    dim_type = raw.get("type")
    if not isinstance(dim_type, str):
        raise SamplingError(f"{path}: dimension 'type' is required")
    return Dimension(
        name=name.strip(),
        type=dim_type,
        min=raw.get("min"),
        max=raw.get("max"),
        mu=raw.get("mu"),
        sigma=raw.get("sigma"),
        values=tuple(raw["values"]) if isinstance(raw.get("values"), list) else (),
        value=raw.get("value"),
    )


def load_space(path: Path) -> SamplingSpace:
    """Load and validate a sampling space from YAML."""
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        raise SamplingError(f"{path}: unreadable YAML ({error})") from error
    if not isinstance(raw, Mapping):
        raise SamplingError(f"{path}: sampling space must be a mapping")
    dimensions_raw = raw.get("dimensions")
    if not isinstance(dimensions_raw, list) or not dimensions_raw:
        raise SamplingError(f"{path}: 'dimensions' must be a non-empty list")
    dimensions = tuple(
        parse_dimension(item, f"{path}.dimensions[{i}]")
        for i, item in enumerate(dimensions_raw)
    )
    count_raw = raw.get("count", 100)
    if count_raw is None:
        raise SamplingError(f"{path}: 'count' must not be null")
    if isinstance(count_raw, float):
        raise SamplingError(
            f"{path}: 'count' must be an integer, got float {count_raw}"
        )
    seed_raw = raw.get("seed", 0)
    if seed_raw is None:
        raise SamplingError(f"{path}: 'seed' must not be null")
    try:
        count = int(count_raw)
        seed = int(seed_raw)
    except (TypeError, ValueError) as error:
        raise SamplingError(f"{path}: invalid count or seed value ({error})") from error
    return SamplingSpace(
        count=count,
        strategy=str(raw.get("strategy", "random")),
        seed=seed,
        dimensions=dimensions,
    )


def _sample_dimension(rng: np.random.Generator, dim: Dimension) -> Any:
    if dim.type == "constant":
        return dim.value
    if dim.type == "uniform":
        return float(rng.uniform(dim.min, dim.max))
    if dim.type == "normal":
        return float(rng.normal(dim.mu, dim.sigma))
    if dim.type == "choice":
        return dim.values[int(rng.integers(0, len(dim.values)))]
    raise SamplingError(f"unhandled dimension type: {dim.type}")  # pragma: no cover


def _grid_values(dim: Dimension, count: int) -> list[Any]:
    if dim.type == "constant":
        return [dim.value] * count
    if dim.type == "choice":
        values = list(dim.values)
        return [values[i % len(values)] for i in range(count)]
    if dim.type in ("uniform", "normal"):
        lo = dim.min if dim.type == "uniform" else dim.mu - 3 * dim.sigma
        hi = dim.max if dim.type == "uniform" else dim.mu + 3 * dim.sigma
        if count == 1:
            return [float((lo + hi) / 2)]
        return [float(lo + i * (hi - lo) / (count - 1)) for i in range(count)]
    raise SamplingError(f"unhandled dimension type: {dim.type}")  # pragma: no cover


def sample_cases(
    space: SamplingSpace, rng: np.random.Generator | None = None
) -> list[dict[str, Any]]:
    """Generate the case list for a sampling space.

    Each case is ``{"case_id": ..., **parameters}``; the parameters are the
    supervised label. ``case_id`` is zero-padded and ordered by index.
    """
    if rng is None:
        rng = np.random.default_rng(space.seed)
    cases: list[dict[str, Any]] = []
    for index in range(space.count):
        snapshot: dict[str, Any] = {}
        for dim in space.dimensions:
            if space.strategy == "grid":
                snapshot[dim.name] = _grid_values(dim, space.count)[index]
            else:
                snapshot[dim.name] = _sample_dimension(rng, dim)
        snapshot["case_id"] = f"{index:05d}"
        cases.append(snapshot)
    return cases


def write_case_list(cases: Sequence[Mapping[str, Any]], path: Path) -> Path:
    """Persist the case list as JSON (the batch manifest)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(list(cases), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def load_case_list(path: Path) -> list[dict[str, Any]]:
    """Load a persisted case list."""
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise SamplingError(f"{path}: case list must be a JSON array of objects")
    return value


def render_space(space: SamplingSpace) -> str:
    """Human-readable description of a sampling space."""
    lines = [
        f"采样空间: {space.count} cases, {space.strategy}, seed={space.seed}",
    ]
    for dim in space.dimensions:
        if dim.type == "uniform":
            lines.append(f"  - {dim.name}: uniform [{dim.min}, {dim.max}]")
        elif dim.type == "normal":
            lines.append(f"  - {dim.name}: normal (mu={dim.mu}, sigma={dim.sigma})")
        elif dim.type == "choice":
            lines.append(f"  - {dim.name}: choice {dim.values}")
        else:
            lines.append(f"  - {dim.name}: constant {dim.value}")
    return "\n".join(lines)