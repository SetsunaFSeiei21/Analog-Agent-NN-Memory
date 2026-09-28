from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..contracts import METRIC_NAMES, ProbeMetrics


@dataclass(frozen=True)
class RegressionMetrics:
    per_metric_r2: dict[str, float | None]
    per_metric_nrmse: dict[str, float | None]
    per_metric_count: dict[str, int]
    macro_r2: float | None
    macro_nrmse: float | None

    def as_probe_metrics(self) -> ProbeMetrics:
        return ProbeMetrics(
            self.per_metric_r2, self.per_metric_nrmse, self.per_metric_count,
            self.macro_r2, self.macro_nrmse,
        )


def evaluate_predictions(
    prediction: np.ndarray,
    target: np.ndarray,
    valid_mask: np.ndarray,
) -> RegressionMetrics:
    prediction = np.asarray(prediction, dtype=float)
    target = np.asarray(target, dtype=float)
    valid_mask = np.asarray(valid_mask, dtype=bool)
    if prediction.shape != target.shape or prediction.shape != valid_mask.shape or prediction.shape[-1] != 9:
        raise ValueError("评估数组形状必须一致且最后一维为 9")
    r2: dict[str, float | None] = {}
    nrmse: dict[str, float | None] = {}
    counts: dict[str, int] = {}
    for index, name in enumerate(METRIC_NAMES):
        mask = valid_mask[..., index] & np.isfinite(prediction[..., index]) & np.isfinite(target[..., index])
        actual = target[..., index][mask]
        estimated = prediction[..., index][mask]
        counts[name] = int(mask.sum())
        if len(actual) == 0:
            r2[name] = None
            nrmse[name] = None
            continue
        residual = float(np.sum((actual - estimated) ** 2))
        centered = float(np.sum((actual - np.mean(actual)) ** 2))
        r2[name] = 1.0 - residual / centered if len(actual) >= 2 and centered > 1e-20 else None
        scale = float(np.max(actual) - np.min(actual))
        if scale <= 1e-20:
            scale = max(abs(float(np.mean(actual))), 1e-12)
        nrmse[name] = float(np.sqrt(np.mean((actual - estimated) ** 2)) / scale)
    valid_r2 = [value for value in r2.values() if value is not None and np.isfinite(value)]
    valid_nrmse = [value for value in nrmse.values() if value is not None and np.isfinite(value)]
    return RegressionMetrics(
        r2, nrmse, counts,
        float(np.mean(valid_r2)) if valid_r2 else None,
        float(np.mean(valid_nrmse)) if valid_nrmse else None,
    )
