"""Probe the local machine's simulation resources.

Informational only: the probe reports what the local environment has
(GPU, memory, disk, Python, gprMax) so a model plan can be matched to real
resources. It never decides whether to run locally or on a server; that
decision belongs to the user.

Nothing here requires network access, and nothing outside process-inspection
commands (nvidia-smi) is ever run.
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

try:
    import ctypes
    _HAS_CTYPES = True
except Exception:  # pragma: no cover - unusual platform
    _HAS_CTYPES = False


def probe_gpu() -> list[dict[str, str]]:
    """Probe NVIDIA GPUs via nvidia-smi (if present). Never raises."""
    import shutil as _shutil

    nvidia_smi = _shutil.which("nvidia-smi")
    if nvidia_smi is None:
        return []
    try:
        completed = subprocess.run(
            [
                nvidia_smi,
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    gpus: list[dict[str, str]] = []
    for line in completed.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 3:
            gpus.append(
                {
                    "name": parts[0],
                    "memory_total": parts[1],
                    "driver_version": parts[2],
                }
            )
    return gpus


def probe_memory_total_gb() -> float | None:
    """Return total physical memory in GB, or None if it cannot be read."""
    if _HAS_CTYPES and sys.platform.startswith("win"):
        try:
            class _MemoryStatus(ctypes.Structure):  # type: ignore[no-redef]
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _MemoryStatus()
            status.dwLength = ctypes.sizeof(_MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
                return status.ullTotalPhys / (1024**3)
        except Exception:  # pragma: no cover - ctypes availability
            pass
    return None


def probe_disk(volume: Path) -> dict[str, float]:
    """Return disk usage in GB for the volume containing *volume*."""
    try:
        usage = shutil.disk_usage(volume)
        return {
            "total_gb": round(usage.total / (1024**3), 1),
            "used_gb": round(usage.used / (1024**3), 1),
            "free_gb": round(usage.free / (1024**3), 1),
        }
    except OSError:
        return {"total_gb": 0.0, "used_gb": 0.0, "free_gb": 0.0}


def probe_python() -> dict[str, str]:
    return {"version": platform.python_version(), "executable": sys.executable}


def probe_gprmax() -> dict[str, str] | None:
    """Return gprMax version if importable, else None."""
    try:
        import gprMax  # type: ignore[import-not-found]
    except Exception:
        return None
    version = getattr(gprMax, "__version__", None)
    if version is None:  # pragma: no cover - depends on build
        try:
            import importlib.metadata

            version = importlib.metadata.version("gprMax")
        except Exception:
            version = "unknown"
    return {"version": str(version), "import_path": str(Path(gprMax.__file__).resolve())}


def collect_probe(output_volume: Path | None = None) -> dict[str, Any]:
    """Collect a full environment probe as a plain mapping."""
    output_volume = output_volume or Path.cwd()
    return {
        "gpu": probe_gpu(),
        "memory_total_gb": probe_memory_total_gb(),
        "disk": probe_disk(output_volume),
        "python": probe_python(),
        "gprmax": probe_gprmax(),
    }


def format_report(probe: Mapping[str, Any]) -> str:
    """Render the probe as a human-readable report."""
    lines: list[str] = ["## 本机环境探测（Local environment probe）"]

    gpus = probe.get("gpu") or []
    if gpus:
        for gpu in gpus:
            lines.append(
                f"- GPU: {gpu.get('name')} {gpu.get('memory_total')} "
                f"(driver {gpu.get('driver_version')})"
            )
    else:
        lines.append("- GPU: 未检测到 NVIDIA GPU（无 nvidia-smi 或驱动不可用）")

    memory = probe.get("memory_total_gb")
    lines.append(f"- 系统内存: {memory:.1f} GB" if memory else "- 系统内存: 未知")

    disk = probe.get("disk") or {}
    if disk:
        lines.append(
            f"- 磁盘: 总量 {disk.get('total_gb')} GB / 剩余 {disk.get('free_gb')} GB"
        )

    python = probe.get("python") or {}
    version = python.get("version", "未知")
    ok = "（OK ≥3.11）" if _version_ge(version, "3.11") else "（需 ≥3.11 才能跑 skill 引擎）"
    lines.append(f"- Python: {version} {ok}")

    gprmax = probe.get("gprmax")
    if gprmax:
        lines.append(
            f"- gprMax: {gprmax.get('version')} 已安装（{gprmax.get('import_path')}）"
        )
    else:
        lines.append("- gprMax: 未安装")

    lines.append("")
    lines.append("> 探测只提供信息，不决定运行环境；本机 or 服务器由用户选择。")
    return "\n".join(lines)


def _version_ge(version: str, minimum: str) -> bool:
    try:
        current = tuple(int(part) for part in version.split(".")[:2])
        required = tuple(int(part) for part in minimum.split(".")[:2])
        return current >= required
    except (TypeError, ValueError):  # pragma: no cover - unexpected version string
        return False


def probe_to_json(probe: Mapping[str, Any]) -> str:
    return json.dumps(probe, indent=2, sort_keys=True, ensure_ascii=False) + "\n"