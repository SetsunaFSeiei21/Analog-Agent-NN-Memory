from __future__ import annotations

import numpy as np
import pytest

from src.neural_memory.contracts import METRIC_NAMES
from src.neural_memory.data.transforms import TargetScaler


ROWS = [
    (60.0, 1e6, 60.0, 70.0, 80.0, 75.0, 10.0, -12.0, 100.0),
    (40.0, None, 45.0, 60.0, 70.0, 65.0, 8.0, 9.0, 120.0),
]


def test_masked_and_sentinel_missing_target_contracts() -> None:
    masked = TargetScaler.fit(ROWS, missing_policy="masked")
    masked_target, masked_valid = masked.transform(ROWS[1])
    assert masked_target[1] == 0.0 and not masked_valid[1]
    sentinel = TargetScaler.fit(ROWS, missing_policy="sentinel", z_missing=-20.0)
    sentinel_target, sentinel_valid = sentinel.transform(ROWS[1])
    assert sentinel_target[1] == -20.0 and not sentinel_valid[1]


def test_target_transform_round_trip_and_slew_magnitude() -> None:
    scaler = TargetScaler.fit(ROWS)
    standardized, valid = scaler.transform(ROWS[0])
    restored = scaler.inverse(standardized[None])[0]
    expected = np.asarray([60.0, 1e6, 60.0, 70.0, 80.0, 75.0, 10.0, 12.0, 100.0])
    assert valid.all()
    assert np.allclose(restored, expected)
    assert len(METRIC_NAMES) == 9


def test_scaler_refuses_metric_without_initial_train_observation() -> None:
    with pytest.raises(ValueError, match="没有可用于拟合"):
        TargetScaler.fit([(None,) + ROWS[0][1:]])


def test_sentinel_value_is_frozen_at_minus_twenty() -> None:
    with pytest.raises(ValueError, match="-20.0"):
        TargetScaler.fit(ROWS, missing_policy="sentinel", z_missing=-5.0)
