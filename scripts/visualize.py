"""Result processing and visualisation for the guided SFCW chains.

Turns a gprMax receiver output (``.out``) into viewable A-scan / B-scan
figures through one of the declared SFCW chains (see ``scripts.sfcw``), and
records the processing parameters so every figure is reproducible.

Uses the Agg backend so figure generation works headless (CI / server). All
figure paths and parameter sidecars are deterministic outputs of the inputs;
nothing here mutates raw evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from scripts import sfcw  # noqa: E402


class ProcessingError(ValueError):
    """Invalid output file, chain parameters, or figure inputs."""


def read_ez_from_out(path: Path, dataset_key: str = "rxs/rx1/Ez") -> tuple[np.ndarray, float | None]:
    """Read the Ez receiver dataset from a gprMax ``.out`` file.

    Returns ``(ez, dt_s)`` where ``dt_s`` comes from the HDF5 root attribute
    ``dt`` (where gprMax writes it, see ``fields_outputs.py``), falling back
    to the dataset attributes (``dt_s`` / ``dt``) for compatibility with
    non-gprMax producers. The time series is the last axis of the dataset.
    """
    try:
        import h5py
    except ImportError as error:  # pragma: no cover - dependency not installed
        raise ProcessingError("h5py is required to read .out files") from error

    path = Path(path)
    try:
        with h5py.File(path, "r") as handle:
            if dataset_key not in handle:
                raise ProcessingError(
                    f"{path}: dataset {dataset_key!r} not found "
                    f"(available: {sorted(handle.keys())})"
                )
            data = handle[dataset_key][...]
    except OSError as error:
        raise ProcessingError(f"{path}: cannot open .out file ({error})") from error

    ez = np.asarray(data, dtype=float)
    if ez.size == 0:
        raise ProcessingError(f"{path}: {dataset_key} is empty")
    if not np.all(np.isfinite(ez)):
        raise ProcessingError(f"{path}: {dataset_key} contains non-finite values")
    samples = ez.reshape(-1, ez.shape[-1])

    dt_s: float | None = None
    try:
        with h5py.File(path, "r") as handle:
            # gprMax writes dt as a root attribute (fields_outputs.py);
            # prefer it over dataset attrs.
            root_attrs = dict(handle.attrs)
            for key in ("dt", "dt_s"):
                if key in root_attrs:
                    dt_s = float(root_attrs[key])
                    break
            if dt_s is None:
                attrs = dict(handle[dataset_key].attrs)
                for key in ("dt_s", "dt"):
                    if key in attrs:
                        dt_s = float(attrs[key])
                        break
    except (OSError, KeyError, TypeError, ValueError):
        dt_s = None
    return samples, dt_s


def process_trace(
    mode: str,
    receiver: np.ndarray,
    *,
    dt_s: float | None,
    frequencies_mhz: Sequence[float],
    impulse_response: np.ndarray | None = None,
    source_waveform: np.ndarray | None = None,
    band_mhz: tuple[float, float] | None = None,
    zero_pad_factor: int = 8,
    window: np.ndarray | None = None,
    regularisation: float = 1e-10,
    ramp_k: float = 0.1,
    integration_cycles: float = 4.0,
    settling_samples: int = 0,
    source_delay_s: float = 0.0,
) -> dict[str, Any]:
    """Run one SFCW chain on a single receiver trace and return the result.

    ``receiver`` is one Ez time series; ``dt_s`` must be provided unless the
    mode only needs per-tone traces.
    """
    if dt_s is None:
        raise ProcessingError("dt_s is required to process a time-domain receiver")
    frequencies_hz = np.asarray([f * 1e6 for f in frequencies_mhz], dtype=float)

    if mode == "impulse_lti":
        if impulse_response is None:
            raise ProcessingError("impulse_lti needs impulse_response (h[n])")
        return sfcw.run_chain(
            "impulse_lti",
            dt_s=dt_s,
            frequencies=frequencies_hz,
            impulse_response=impulse_response,
            zero_pad_factor=zero_pad_factor,
            window=window,
            ramp_k=ramp_k,
            integration_cycles=integration_cycles,
            settling_samples=settling_samples,
            source_delay_s=source_delay_s,
        )
    if mode == "broadband_deconvolution":
        if source_waveform is None:
            raise ProcessingError("broadband_deconvolution needs source_waveform")
        return sfcw.run_chain(
            "broadband_deconvolution",
            dt_s=dt_s,
            frequencies=frequencies_hz,
            receiver_ez=receiver,
            source_waveform=source_waveform,
            band_hz=(band_mhz[0] * 1e6, band_mhz[1] * 1e6) if band_mhz else None,
            zero_pad_factor=zero_pad_factor,
            window=window,
            regularisation=regularisation,
            source_delay_s=source_delay_s,
        )
    if mode == "direct_per_tone":
        raise ProcessingError(
            "direct_per_tone needs per-tone traces; use process_bscan or pass "
            "per_tone_traces explicitly"
        )
    raise ProcessingError(
        f"mode must be direct_per_tone | impulse_lti | broadband_deconvolution"
    )


def _time_axis(result: Mapping[str, Any]) -> np.ndarray:
    """Delay/time axis (seconds) for a reconstructed A-scan."""
    n = len(result["ascan"])
    return np.arange(n) * result["delay_bin_s"]


def plot_ascan(
    result: Mapping[str, Any],
    out_path: Path,
    title: str | None = None,
    *,
    distance_velocity_mps: float | None = None,
    show_envelope: bool = True,
    reference_line_s: float | None = None,
) -> Path:
    """Render an A-scan figure (complex magnitude or envelope vs delay).

    When ``distance_velocity_mps`` is given the x axis is shown as distance
    (round-trip / 2); otherwise it is delay in ns.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    t = _time_axis(result)
    env = result["envelope"]
    real = np.asarray(result["ascan"]).real

    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(t * 1e9, real, lw=0.8, color="#334155", label="A-scan (real)")
    if show_envelope:
        ax.plot(t * 1e9, env, lw=1.6, color="#dc2626", label="Envelope")
    if reference_line_s is not None:
        ax.axvline(reference_line_s * 1e9, color="#16a34a", ls="--", lw=1, label="Reference")
    ax.set_xlabel("Delay (ns)")
    ax.set_ylabel("Amplitude")
    ax.set_title(title or f"A-scan — {result['mode']}")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    return out_path


def plot_bscan(
    traces: Sequence[np.ndarray],
    out_path: Path,
    *,
    delay_bin_s: float,
    title: str = "B-scan",
    db_scale: bool = True,
    vmin_db: float = -60.0,
) -> Path:
    """Render a B-scan heat map (trace index × delay)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    matrix = np.stack([np.asarray(t, dtype=float) for t in traces])
    n, m = matrix.shape
    t = np.arange(m) * delay_bin_s

    fig, ax = plt.subplots(figsize=(9, 5))
    if db_scale:
        amplitude = np.abs(matrix)
        scale = amplitude.max() if amplitude.max() > 0 else 1.0
        display = 20 * np.log10(amplitude / scale + 1e-12)
        im = ax.imshow(
            display.T,
            aspect="auto",
            origin="lower",
            extent=[0, n - 1, t[0] * 1e9, t[-1] * 1e9],
            cmap="viridis",
            vmin=vmin_db,
            vmax=0,
        )
        cbar_label = "dB (relative to max)"
    else:
        im = ax.imshow(
            np.abs(matrix).T,
            aspect="auto",
            origin="lower",
            extent=[0, n - 1, t[0] * 1e9, t[-1] * 1e9],
            cmap="viridis",
        )
        cbar_label = "|amplitude|"
    ax.set_xlabel("Trace index")
    ax.set_ylabel("Delay (ns)")
    ax.set_title(title)
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label(cbar_label)
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    return out_path


def plot_bscan_pair(
    before: Sequence[np.ndarray],
    after: Sequence[np.ndarray],
    out_path: Path,
    *,
    delay_bin_s: float,
    title: str = "B-scan — before / after",
    db_scale: bool = True,
    vmin_db: float = -60.0,
) -> Path:
    """Render a before/after B-scan comparison (two stacked panels).

    Shows the raw traces on top and the processed traces below, sharing the
    same delay axis so the effect of the processing chain is visible at a
    glance. Display-only — never feeds quantitative claims.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def _matrix(traces: Sequence[np.ndarray]) -> np.ndarray:
        return np.stack([np.asarray(t, dtype=float) for t in traces])

    before_matrix = _matrix(before)
    after_matrix = _matrix(after)
    if before_matrix.shape != after_matrix.shape:
        raise ProcessingError(
            "plot_bscan_pair requires before/after traces of identical shape "
            f"({before_matrix.shape} vs {after_matrix.shape})"
        )
    n, m = before_matrix.shape
    t = np.arange(m) * delay_bin_s
    extent = [0, n - 1, t[0] * 1e9, t[-1] * 1e9]

    fig, axes = plt.subplots(2, 1, figsize=(9, 9), sharex=True)
    panels = [("before", before_matrix), ("after", after_matrix)]
    for ax, (label, matrix) in zip(axes, panels):
        if db_scale:
            amplitude = np.abs(matrix)
            scale = amplitude.max() if amplitude.max() > 0 else 1.0
            display = 20 * np.log10(amplitude / scale + 1e-12)
            im = ax.imshow(
                display.T, aspect="auto", origin="lower", extent=extent,
                cmap="viridis", vmin=vmin_db, vmax=0,
            )
        else:
            im = ax.imshow(
                np.abs(matrix).T, aspect="auto", origin="lower", extent=extent,
                cmap="viridis",
            )
        ax.set_title(f"{label}", fontsize=10)
        ax.set_ylabel("Delay (ns)")
    axes[-1].set_xlabel("Trace index")
    fig.suptitle(title, fontsize=11)
    fig.colorbar(im, ax=axes, shrink=0.9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    return out_path


# ---------------------------------------------------------------------------
# processing chain catalogue & recommendation
# ---------------------------------------------------------------------------

# The five chain families from the design (docs §8). ``display_only`` chains
# are for viewing only and must never feed quantitative claims; ``mode`` is
# the SFCW chain used by ``process_trace`` (None = direct plotting, no
# synthesis). ``parameters`` are the defaults handed to ``process_trace``.
CHAIN_CATALOGUE: dict[str, dict[str, Any]] = {
    "raw_visual": {
        "mode": None,
        "display_only": True,
        "parameters": {},
        "purpose": "Ascan/Bscan 直接绘制（时间-幅度），快速查看原始结果",
    },
    "standard": {
        "mode": "impulse_lti",
        "display_only": False,
        "parameters": {"zero_pad_factor": 8, "ramp_k": 0.1, "integration_cycles": 4.0},
        "purpose": "标准链：去直达波 / 背景相减（诊断）/ SFCW 融合（对齐刘2021）",
    },
    "advanced": {
        "mode": "impulse_lti",
        "display_only": False,
        "parameters": {
            "zero_pad_factor": 16,
            "window": None,
            "regularisation": 1e-10,
            "ramp_k": 0.1,
            "integration_cycles": 4.0,
        },
        "purpose": "高级链：去卷积(Wiener) + 加窗(Blackman) + zero-padded IFFT + Hilbert 包络",
    },
    "imaging": {
        "mode": "impulse_lti",
        "display_only": False,
        "optional": True,
        "parameters": {"zero_pad_factor": 16},
        "purpose": "成像：BP/Kirchhoff 孔径聚焦（可选，按需启用）",
    },
    "display_enhancement": {
        "mode": None,
        "display_only": True,
        "parameters": {},
        "purpose": "显示增强：归一化 / AGC / 裁剪，仅显示，不参与定量",
    },
}


def recommend_chain(
    requirements: Mapping[str, Any] | None, contract: Mapping[str, Any]
) -> dict[str, Any]:
    """Pick a processing chain, honouring an explicit user request first.

    ``requirements`` may carry ``chain`` (one of :data:`CHAIN_CATALOGUE`),
    ``need_imaging`` (bool), ``quality`` ("quick" | "standard" | "high").
    An explicit ``chain`` always wins (user-specified priority). Otherwise
    the choice is derived from the contract: SFCW-equivalent studies get the
    standard/advanced chain, time-domain studies get raw visualisation, and
    ``need_imaging`` flags the optional imaging chain.

    Returns ``{chain, mode, parameters, display_only, rationale}``.
    """
    req = dict(requirements or {})
    contract = dict(contract or {})

    requested = req.get("chain")
    if requested is not None:
        if requested not in CHAIN_CATALOGUE:
            raise ProcessingError(
                f"unknown chain {requested!r}; expected one of {sorted(CHAIN_CATALOGUE)}"
            )
        spec = dict(CHAIN_CATALOGUE[requested])
        return {
            "chain": requested,
            "mode": spec.get("mode"),
            "parameters": dict(spec.get("parameters", {})),
            "display_only": bool(spec.get("display_only", False)),
            "rationale": f"user-specified chain {requested!r}",
        }

    waveform = contract.get("waveform", {})
    measurement = (
        waveform.get("measurement_mode", "time_domain")
        if isinstance(waveform, Mapping)
        else "time_domain"
    )
    quality = req.get("quality", "standard")
    chain_name = "raw_visual"
    rationale = "time-domain study → raw visualisation"
    if measurement == "sfcw_equivalent":
        chain_name = "advanced" if quality == "high" else "standard"
        rationale = (
            "SFCW-equivalent study → "
            + ("advanced chain (high quality)" if quality == "high" else "standard chain")
        )
    if req.get("need_imaging"):
        rationale += "; imaging chain available on request"
        return {
            "chain": "imaging",
            "mode": CHAIN_CATALOGUE["imaging"].get("mode"),
            "parameters": dict(CHAIN_CATALOGUE["imaging"].get("parameters", {})),
            "display_only": False,
            "rationale": rationale,
        }
    spec = CHAIN_CATALOGUE[chain_name]
    return {
        "chain": chain_name,
        "mode": spec.get("mode"),
        "parameters": dict(spec.get("parameters", {})),
        "display_only": bool(spec.get("display_only", False)),
        "rationale": rationale,
    }


def save_processing_parameters(result: Mapping[str, Any], out_path: Path) -> Path:
    """Persist the processing parameters (and small result summary) as JSON."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(result.get("processing_parameters", {}))
    payload["mode"] = result.get("mode")
    payload["delay_bin_s"] = result.get("delay_bin_s")
    payload["unambiguous_delay_s"] = result.get("unambiguous_delay_s")
    payload["fdtd_dt_s"] = result.get("fdtd_dt_s")
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return out_path


def process_and_plot(
    out_file: Path,
    *,
    mode: str,
    frequencies_mhz: Sequence[float],
    dt_s: float | None = None,
    output_dir: Path,
    impulse_response: np.ndarray | None = None,
    source_waveform: np.ndarray | None = None,
    band_mhz: tuple[float, float] | None = None,
    zero_pad_factor: int = 8,
    window: np.ndarray | None = None,
    regularisation: float = 1e-10,
    ramp_k: float = 0.1,
    integration_cycles: float = 4.0,
    settling_samples: int = 0,
    source_delay_s: float = 0.0,
) -> dict[str, Path]:
    """Full pipeline: read one ``.out``, process, plot A-scan, save parameters.

    Returns a mapping of artifact paths: ``ascan_png``, ``parameters_json``,
    and the result mapping (``result``). ``dt_s`` may be omitted to read it
    from the file attrs.
    """
    out_file = Path(out_file)
    traces, file_dt = read_ez_from_out(out_file)
    if dt_s is None:
        dt_s = file_dt
    result = process_trace(
        mode,
        traces[0],
        dt_s=dt_s,
        frequencies_mhz=frequencies_mhz,
        impulse_response=impulse_response,
        source_waveform=source_waveform,
        band_mhz=band_mhz,
        zero_pad_factor=zero_pad_factor,
        window=window,
        regularisation=regularisation,
        ramp_k=ramp_k,
        integration_cycles=integration_cycles,
        settling_samples=settling_samples,
        source_delay_s=source_delay_s,
    )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    base = output_dir / f"{out_file.stem}_{mode}"
    ascan_png = plot_ascan(result, base.with_suffix(".ascan.png"), title=f"{out_file.name} — {mode}")
    params_json = save_processing_parameters(result, base.with_suffix(".params.json"))
    return {"ascan_png": ascan_png, "parameters_json": params_json, "result": result}