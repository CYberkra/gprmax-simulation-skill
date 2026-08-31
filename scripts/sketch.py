"""Geometry cross-section sketch for the guided setup.

Renders a simple 2-D side-view sketch of the study from a contract: the
domain outline, host medium background, target box at its declared depth,
and Tx/Rx markers on the surface. This is a *conceptual* aid for the wizard
dialogue — it shows the user what the model will look like before any mesh
or simulation exists. It is display-only and never feeds quantitative claims.

Styling follows the taste-skill §3 guide: low-saturation material fills, a
restrained palette, faded gridlines, clear markers, and dimension callouts.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

# taste-skill §1 readability: prefer a CJK-capable font so Chinese labels
# render instead of tofu boxes; fall back gracefully where unavailable.
matplotlib.rcParams["font.sans-serif"] = [
    "Microsoft YaHei",
    "Noto Sans SC",
    "SimHei",
    "SimSun",
    "DejaVu Sans",
]
matplotlib.rcParams["axes.unicode_minus"] = False


class SketchError(ValueError):
    """Invalid contract or geometry for a cross-section sketch."""


# taste-skill §1 restrained palette (neutral + one accent).
_FACE_BG = "#f8fafc"
_HOST_FILL = "#cbd5e1"  # low-saturation host medium
_TARGET_FILL = "#0ea5e9"  # single accent for the target
_TARGET_EDGE = "#0369a1"
_GRID = "#e2e8f0"
_TX_COLOR = "#dc2626"
_RX_COLOR = "#16a34a"
_TEXT = "#1e293b"


def _positive(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise SketchError(f"{name} must be a number, got {value!r}") from error
    if not np.isfinite(number) or number <= 0:
        raise SketchError(f"{name} must be positive, got {value!r}")
    return number


def _domain_xy(contract: Mapping[str, Any]) -> tuple[float, float]:
    """Return (x_extent, z_extent) in metres from the contract."""
    project = contract.get("project") or {}
    target_depth = project.get("target_depth_m")
    if target_depth is None:
        raise SketchError("project.target_depth_m is required for the sketch")
    depth = _positive(target_depth, "project.target_depth_m")
    domain = contract.get("domain_m")
    if isinstance(domain, (list, tuple)) and len(domain) == 3:
        x = _positive(domain[0], "domain_m[0]")
        z = _positive(domain[2], "domain_m[2]")
        if z < depth:
            raise SketchError(
                f"domain z-extent ({z} m) is smaller than target depth ({depth} m)"
            )
        return x, z
    # No domain declared: draw a sketch window sized to the target depth.
    return depth * 1.5, depth * 1.5


def _target_box(contract: Mapping[str, Any], depth: float) -> tuple[float, float, float, float]:
    """Return a nominal target box (x, z, w, h) centred on the declared depth."""
    project = contract.get("project") or {}
    size = project.get("target_size_m")
    if isinstance(size, (int, float)) and size > 0:
        side = float(size)
    else:
        side = max(depth * 0.05, 0.5)  # nominal 5% of depth, display-only
    x = 0.5  # centred horizontally in the sketch window
    return (x - side / 2, depth - side / 2, side, side)


def plot_geometry_sketch(
    contract: Mapping[str, Any],
    out_path: Any,
    *,
    title: str | None = None,
    dpi: int = 150,
) -> Any:
    """Render a side-view geometry sketch and save it to *out_path*.

    ``contract`` needs at least ``project.target_depth_m``; an optional
    ``domain_m`` (x, y, z) and ``project.target_size_m`` refine the sketch.
    Returns the output path.
    """
    from pathlib import Path

    out_path = Path(out_path)
    if not isinstance(contract, Mapping):
        raise SketchError("contract must be a mapping")

    project = contract.get("project") or {}
    depth = _positive(project.get("target_depth_m"), "project.target_depth_m")
    x_extent, z_extent = _domain_xy(contract)
    box_x, box_z, box_w, box_h = _target_box(contract, depth)

    fig, ax = plt.subplots(figsize=(9, 5), facecolor=_FACE_BG)
    ax.set_facecolor(_FACE_BG)

    # Domain outline + host medium fill.
    ax.add_patch(
        Rectangle((0, 0), x_extent, z_extent, facecolor=_HOST_FILL, edgecolor=_TEXT, lw=1.2)
    )
    # Target box (single accent).
    ax.add_patch(
        Rectangle(
            (box_x, box_z),
            box_w,
            box_h,
            facecolor=_TARGET_FILL,
            edgecolor=_TARGET_EDGE,
            lw=1.5,
            zorder=3,
        )
    )
    # Tx / Rx on the surface.
    tx_x = x_extent * 0.35
    rx_x = x_extent * 0.65
    ax.plot(tx_x, 0, marker="^", markersize=11, color=_TX_COLOR, zorder=4, label="Tx")
    ax.plot(rx_x, 0, marker="v", markersize=11, color=_RX_COLOR, zorder=4, label="Rx")
    ax.annotate(
        f"Tx ({tx_x:.2f}, 0)",
        (tx_x, 0),
        xytext=(tx_x, -z_extent * 0.14),
        ha="center",
        fontsize=8,
        color=_TEXT,
    )
    ax.annotate(
        f"Rx ({rx_x:.2f}, 0)",
        (rx_x, 0),
        xytext=(rx_x, -z_extent * 0.14),
        ha="center",
        fontsize=8,
        color=_TEXT,
    )
    # Depth callout.
    ax.annotate(
        f"目标深度 {depth:.2f} m",
        xy=(box_x + box_w / 2, box_z),
        xytext=(box_x + box_w / 2 + x_extent * 0.08, box_z + z_extent * 0.1),
        arrowprops=dict(arrowstyle="->", color=_TEXT, lw=0.9),
        fontsize=9,
        color=_TEXT,
    )
    # Faded gridlines + clean axes. z=0 (surface, Tx/Rx) sits at the TOP;
    # depth increases downward — the physical convention for radar sketches.
    ax.grid(True, color=_GRID, alpha=0.6, lw=0.6)
    ax.set_xlim(0, x_extent)
    ax.set_ylim(z_extent, -z_extent * 0.18)
    ax.set_xlabel("x (m)", color=_TEXT)
    ax.set_ylabel("深度 z (m) ↓", color=_TEXT)
    ax.set_title(title or "几何截面草图（向导期，示意）", color=_TEXT, fontsize=12)
    ax.legend(loc="upper right", fontsize=8, frameon=False)
    for spine in ax.spines.values():
        spine.set_color(_TEXT)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=dpi)
    plt.close(fig)
    return out_path
