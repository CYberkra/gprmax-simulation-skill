from pathlib import Path

import numpy as np
import pytest
import yaml

import scripts.sampling as sampling
import scripts.batch as batch
import scripts.dataset as dataset


# --------------------------------------------------------------------------
# sampling
# --------------------------------------------------------------------------

def _space_yaml(tmp_path: Path, **overrides) -> Path:
    payload = {
        "count": 10,
        "strategy": "random",
        "seed": 42,
        "dimensions": [
            {"name": "target_depth_m", "type": "uniform", "min": 60.0, "max": 95.0},
            {"name": "target_material", "type": "choice", "values": ["WET", "AIR"]},
            {"name": "antenna", "type": "constant", "value": "ideal_hertzian"},
        ],
    }
    payload.update(overrides)
    path = tmp_path / "space.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def test_load_space_and_sample_reproducible(tmp_path: Path):
    space = sampling.load_space(_space_yaml(tmp_path))
    cases1 = sampling.sample_cases(space)
    cases2 = sampling.sample_cases(space)
    assert cases1 == cases2  # seed reproducibility
    assert len(cases1) == 10
    assert all("case_id" in case for case in cases1)
    assert all(60.0 <= case["target_depth_m"] <= 95.0 for case in cases1)
    assert all(case["target_material"] in ("WET", "AIR") for case in cases1)
    assert all(case["antenna"] == "ideal_hertzian" for case in cases1)


def test_load_space_rejects_bad_dimension():
    with pytest.raises(sampling.SamplingError):
        sampling.parse_dimension({"name": "x", "type": "uniform"}, "d")


def test_grid_strategy_deterministic(tmp_path: Path):
    space = sampling.load_space(
        _space_yaml(tmp_path, count=3, strategy="grid")
    )
    cases = sampling.sample_cases(space)
    depths = [case["target_depth_m"] for case in cases]
    assert depths[0] == 60.0
    assert depths[-1] == 95.0
    assert len(set(depths)) == 3


def test_case_list_roundtrip(tmp_path: Path):
    space = sampling.load_space(_space_yaml(tmp_path))
    cases = sampling.sample_cases(space)
    path = sampling.write_case_list(cases, tmp_path / "cases.json")
    assert sampling.load_case_list(path) == cases


# --------------------------------------------------------------------------
# batch
# --------------------------------------------------------------------------

def _cases(n: int = 5) -> list[dict]:
    return [{"case_id": f"{i:05d}", "depth": float(i)} for i in range(n)]


def test_initialise_and_status(tmp_path: Path):
    batch.initialise_batch(tmp_path, _cases())
    dash = batch.status_dashboard(tmp_path)
    assert dash["total"] == 5
    assert dash["pending"] == 5


def test_mark_and_resume(tmp_path: Path):
    batch.initialise_batch(tmp_path, _cases())
    batch.mark(tmp_path, "00000", "done", output="o.out")
    batch.mark(tmp_path, "00001", "fail", error="boom")
    assert batch.pending_cases(tmp_path) == ["00002", "00003", "00004"]
    dash = batch.status_dashboard(tmp_path)
    assert dash["done"] == 1
    assert dash["failed"] == 1


def test_mark_unknown_case_raises(tmp_path: Path):
    batch.initialise_batch(tmp_path, _cases())
    with pytest.raises(batch.BatchError):
        batch.mark(tmp_path, "99999", "done")


def test_farm_shards(tmp_path: Path):
    batch.initialise_batch(tmp_path, _cases())
    shards = batch.farm_shards(tmp_path, gpu_count=2)
    assert sum(len(s) for s in shards) == 5
    assert set(shards[0]) | set(shards[1]) == set(
        [c["case_id"] for c in _cases()]
    )


def test_write_summary(tmp_path: Path):
    batch.initialise_batch(tmp_path, _cases())
    batch.mark(tmp_path, "00000", "done", output="o.out")
    path = batch.write_summary(tmp_path, _cases())
    text = path.read_text(encoding="utf-8")
    assert "case_id,status,output,error" in text
    assert "o.out" in text


def test_is_complete(tmp_path: Path):
    cases = _cases(2)
    batch.initialise_batch(tmp_path, cases)
    assert batch.is_complete(tmp_path) is False
    for case in cases:
        batch.mark(tmp_path, case["case_id"], "done", output="o.out")
    assert batch.is_complete(tmp_path) is True


# --------------------------------------------------------------------------
# dataset
# --------------------------------------------------------------------------

def test_pack_npz_roundtrip(tmp_path: Path):
    cases = _cases(3)
    arrays = {
        "ascan": [np.arange(10, dtype=float), np.arange(8, dtype=float), np.arange(12, dtype=float)],
    }
    path = dataset.pack_dataset(
        tmp_path / "ds.npz", cases=cases, arrays=arrays, backend="npz"
    )
    info = dataset.dataset_info(path)
    assert info["n_samples"] == 3
    assert info["backend"] == "npz"
    payload = np.load(path, allow_pickle=True)
    assert payload["x_ascan"].shape == (3, 12)  # padded to max
    assert list(payload["len_ascan"]) == [10, 8, 12]


def test_pack_h5(tmp_path: Path):
    cases = _cases(2)
    arrays = {"ascan": [np.arange(5, dtype=float), np.arange(5, dtype=float)]}
    path = dataset.pack_dataset(
        tmp_path / "ds.h5", cases=cases, arrays=arrays, backend="h5"
    )
    info = dataset.dataset_info(path)
    assert info["backend"] == "h5"
    assert info["n_samples"] == 2
    assert info["label_columns"] == ["depth"]


def test_pack_empty_raises(tmp_path: Path):
    with pytest.raises(dataset.DatasetError):
        dataset.pack_dataset(tmp_path / "x.h5", cases=[], arrays={})


def test_labels_categorical_encoding():
    cases = [
        {"case_id": "0", "mat": "WET", "depth": 70.0},
        {"case_id": "1", "mat": "AIR", "depth": 80.0},
        {"case_id": "2", "mat": "WET", "depth": 90.0},
    ]
    labels = dataset.labels_matrix(cases, ["mat", "depth"])
    # WET and AIR encoded deterministically (0/1 by sorted distinct)
    assert labels[0, 0] == labels[2, 0]
    assert labels[0, 0] != labels[1, 0]
    assert labels[0, 1] == 70.0
    assert labels[2, 1] == 90.0