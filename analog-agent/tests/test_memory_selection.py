from __future__ import annotations

from pathlib import Path

import numpy as np

from src.neural_memory.contracts import METRIC_NAMES, SampleRecord
from src.neural_memory.memory.selection import R2MemorySelector
from src.neural_memory.memory.sequential import select_probe_indices


def test_selector_uses_physical_space_r2_and_stable_tie_break() -> None:
    target = np.arange(180, dtype=float).reshape(20, 9) + 1.0
    mask = np.ones_like(target, dtype=bool)
    predictions = {
        "global": target + 10.0,
        "good": target + 0.1,
        "good_later": target + 0.1,
    }
    result = R2MemorySelector().select(
        predictions, target, mask, {"global": 0, "good": 1, "good_later": 2}
    )
    assert result.selected_memory_id == "good"
    assert result.selected_score.macro_r2 is not None
    assert set(result.selected_score.per_metric_r2) == set(METRIC_NAMES)


def test_selector_falls_back_to_nrmse_when_r2_undefined() -> None:
    target = np.ones((1, 9))
    mask = np.ones_like(target, dtype=bool)
    result = R2MemorySelector().select(
        {"bad": target + 2, "better": target + 1}, target, mask, {"bad": 0, "better": 1}
    )
    assert result.selected_memory_id == "better"
    assert result.selected_score.used_nrmse_fallback


def test_probe_indices_depend_on_order_seed_not_model_seed() -> None:
    records = [
        SampleRecord("t", index, ("W",), (float(index),), (1.0,) * 9, "train_visible", Path("x"))
        for index in range(100)
    ]
    first = select_probe_indices(records, k=20, order_seed=3, topology_id="t")
    same = select_probe_indices(records, k=20, order_seed=3, topology_id="t")
    other = select_probe_indices(records, k=20, order_seed=4, topology_id="t")
    assert first == same
    assert first != other
