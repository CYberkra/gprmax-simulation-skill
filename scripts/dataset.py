"""Dataset packing for the training-data factory.

Takes the executed batch (per-case processed arrays + the case parameter
snapshots, which are the supervised labels) and packs them into a single
training-ready dataset. Two backends are supported:

- HDF5 (``.h5``): ``/x`` (samples), ``/y`` (labels), ``/case_id``, and
  per-label column metadata — the recommended form for large batches;
- NPZ (``.npz``): ``x``, ``y``, ``case_ids`` — convenient for small sets.

Variable-length per-case arrays are padded to the batch maximum along the
last axis and a ``lengths`` vector records true lengths. The label matrix is
built from the case parameter snapshots (minus ``case_id``) with a column
order recorded in the dataset, so the mapping is reproducible.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


class DatasetError(ValueError):
    """Invalid dataset packing request."""


def _label_columns(cases: Sequence[Mapping[str, Any]]) -> list[str]:
    columns: list[str] = []
    for case in cases:
        for key in case:
            if key == "case_id":
                continue
            if key not in columns:
                columns.append(key)
    return columns


def labels_matrix(
    cases: Sequence[Mapping[str, Any]], columns: Sequence[str]
) -> np.ndarray:
    """Build the label matrix (n_samples × n_columns).

    Numeric values are kept as float. Categorical values are encoded by the
    index of their distinct value within the column (sorted, deterministic);
    the mapping is recoverable from the case list itself.
    """
    # Precompute a deterministic categorical encoding per column. None is
    # excluded from the categorical set — it is always mapped to NaN in the
    # matrix, so it must not shift the categorical indices.
    encodings: dict[str, dict[Any, float]] = {}
    for col in columns:
        distinct = sorted(
            {
                case.get(col)
                for case in cases
                if case.get(col) is not None
                and not isinstance(case.get(col), (int, float))
            },
            key=str,
        )
        encodings[col] = {value: float(index) for index, value in enumerate(distinct)}

    rows: list[list[float]] = []
    for case in cases:
        row: list[float] = []
        for col in columns:
            value = case.get(col)
            if value is None:
                row.append(float("nan"))
            elif isinstance(value, (int, float)):
                row.append(float(value))
            else:
                row.append(encodings[col].get(value, float("nan")))
        rows.append(row)
    return np.asarray(rows, dtype=np.float32)


def _pack_array(
    arrays: Sequence[np.ndarray], dtype: str = "float32"
) -> tuple[np.ndarray, np.ndarray]:
    """Pad variable-length arrays to common shape; return (stack, lengths).

    Supports 1-D (A-scan) and N-D (B-scan, multi-channel) arrays. All inputs
    must share the same shape except the last axis, which is padded to the
    batch maximum. The ``lengths`` vector records the true last-axis length
    per sample.
    """
    converted = [np.asarray(a, dtype=np.float64) for a in arrays]
    if not converted:
        raise DatasetError("cannot pack an empty list of arrays")
    for i, a in enumerate(converted):
        if a.ndim < 1:
            raise DatasetError(
                f"array at index {i} is scalar (ndim=0); "
                "a non-empty 1-D or N-D array is required"
            )
    max_len = max(a.shape[-1] for a in converted)
    ref_shape = converted[0].shape[:-1]
    for i, a in enumerate(converted):
        if a.shape[:-1] != ref_shape:
            raise DatasetError(
                f"array at index {i} has shape {a.shape} "
                f"but expected (..., {ref_shape[-1] if ref_shape else ''}, *)"
            )
    out = np.zeros((len(converted), *ref_shape, max_len), dtype=dtype)
    lengths = np.zeros(len(converted), dtype=np.int64)
    for i, a in enumerate(converted):
        n = a.shape[-1]
        out[(i, ..., slice(None, n))] = a
        lengths[i] = n
    return out, lengths


def pack_dataset(
    out_path: Path,
    *,
    cases: Sequence[Mapping[str, Any]],
    arrays: Mapping[str, Sequence[np.ndarray]],
    column_order: Sequence[str] | None = None,
    backend: str = "h5",
) -> Path:
    """Pack per-case arrays and labels into a training dataset file.

    ``arrays`` maps a sample name (``ascan``, ``bscan``, ...) to a list of
    per-case arrays. ``cases`` carries the labels. Returns the written path.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if len(cases) == 0:
        raise DatasetError("no cases to pack")
    columns = list(column_order) if column_order else _label_columns(cases)
    labels = labels_matrix(cases, columns)
    packed: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for name, values in arrays.items():
        packed[name] = _pack_array(list(values))

    if backend == "npz":
        payload: dict[str, Any] = {
            "y": labels,
            "case_ids": np.asarray([c["case_id"] for c in cases], dtype=object),
            "label_columns": np.asarray(columns, dtype=object),
        }
        for name, (stack, lengths) in packed.items():
            payload[f"x_{name}"] = stack
            payload[f"len_{name}"] = lengths
        np.savez(out_path, **payload)
        return out_path

    if backend == "h5":
        try:
            import h5py
        except ImportError as error:  # pragma: no cover
            raise DatasetError("h5py is required for the h5 backend") from error
        with h5py.File(out_path, "w") as handle:
            handle.create_dataset("y", data=labels)
            handle.create_dataset(
                "case_id",
                data=np.asarray([c["case_id"] for c in cases], dtype="S32"),
            )
            handle.create_dataset(
                "label_columns", data=np.asarray(columns, dtype="S64")
            )
            for name, (stack, lengths) in packed.items():
                handle.create_dataset(f"x_{name}", data=stack)
                handle.create_dataset(f"len_{name}", data=lengths)
            handle.attrs["n_samples"] = len(cases)
        return out_path

    raise DatasetError(f"unknown backend: {backend}")  # pragma: no cover


def dataset_info(path: Path) -> dict[str, Any]:
    """Summarise a packed dataset (sizes, shapes, columns)."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".npz":
        payload = np.load(path, allow_pickle=True)
        y = payload["y"]
        return {
            "backend": "npz",
            "n_samples": int(y.shape[0]),
            "n_labels": int(y.shape[1]),
            "label_columns": list(payload["label_columns"]),
            "sample_names": [k[2:] for k in payload.files if k.startswith("x_")],
        }
    if suffix == ".h5":
        try:
            import h5py
        except ImportError as error:  # pragma: no cover
            raise DatasetError("h5py is required to inspect h5 datasets") from error
        with h5py.File(path, "r") as handle:
            return {
                "backend": "h5",
                "n_samples": int(handle.attrs.get("n_samples", handle["y"].shape[0])),
                "n_labels": int(handle["y"].shape[1]),
                "label_columns": [
                    col.decode() for col in handle["label_columns"][...]
                ],
                "sample_names": [
                    name for name in handle.keys() if name.startswith("x_")
                ],
            }
    raise DatasetError(f"unsupported dataset suffix: {suffix}")  # pragma: no cover