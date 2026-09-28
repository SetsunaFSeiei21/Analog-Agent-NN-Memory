from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from ..contracts import LOG_METRICS, METRIC_NAMES, SLEW_METRICS


DEVICE_PARAMETER_ORDER = ("W", "L", "M", "R", "C", "I")
MISSING_POLICIES = frozenset({"masked", "sentinel"})


def transform_metric(name: str, value: float) -> float:
    value = abs(float(value)) if name in SLEW_METRICS else float(value)
    if name in LOG_METRICS:
        if value <= 0 or not math.isfinite(value):
            raise ValueError(f"{name} 的 log10 输入必须为有限正数：{value}")
        return math.log10(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} 必须有限")
    return value


def inverse_metric(name: str, value: float) -> float:
    return 10.0**float(value) if name in LOG_METRICS else float(value)


@dataclass(frozen=True)
class TargetScaler:
    mean: tuple[float, ...]
    std: tuple[float, ...]
    missing_policy: str = "masked"
    z_missing: float = -20.0
    fitted_on: str = "initial_train_only"

    def __post_init__(self) -> None:
        if len(self.mean) != len(METRIC_NAMES) or len(self.std) != len(METRIC_NAMES):
            raise ValueError("TargetScaler 维度必须等于 9")
        if self.missing_policy not in MISSING_POLICIES:
            raise ValueError(f"missing_policy 必须是 {sorted(MISSING_POLICIES)}")
        if any(value <= 0 or not math.isfinite(value) for value in self.std):
            raise ValueError("std 必须是有限正数")

    @classmethod
    def fit(
        cls,
        rows: Iterable[Sequence[float | None]],
        *,
        missing_policy: str = "masked",
        z_missing: float = -20.0,
    ) -> "TargetScaler":
        values: list[list[float]] = [[] for _ in METRIC_NAMES]
        for row in rows:
            if len(row) != len(METRIC_NAMES):
                raise ValueError("目标行必须包含 9 个指标")
            for index, (name, value) in enumerate(zip(METRIC_NAMES, row)):
                if value is None:
                    continue
                try:
                    values[index].append(transform_metric(name, value))
                except ValueError:
                    continue
        missing = [METRIC_NAMES[index] for index, metric in enumerate(values) if not metric]
        if missing:
            raise ValueError(f"初始训练集没有可用于拟合 scaler 的指标：{missing}")
        means = tuple(float(np.mean(metric)) for metric in values)
        stds = tuple(max(float(np.std(metric)), 1e-8) for metric in values)
        return cls(means, stds, missing_policy, float(z_missing))

    def transform(self, row: Sequence[float | None]) -> tuple[np.ndarray, np.ndarray]:
        target = np.full(len(METRIC_NAMES), self.z_missing if self.missing_policy == "sentinel" else 0.0, dtype=np.float32)
        mask = np.zeros(len(METRIC_NAMES), dtype=bool)
        for index, (name, value) in enumerate(zip(METRIC_NAMES, row)):
            if value is None:
                continue
            try:
                transformed = transform_metric(name, value)
            except ValueError:
                continue
            target[index] = (transformed - self.mean[index]) / self.std[index]
            mask[index] = True
        return target, mask

    def inverse(self, standardized: np.ndarray) -> np.ndarray:
        array = np.asarray(standardized, dtype=float)
        if array.shape[-1] != len(METRIC_NAMES):
            raise ValueError("预测最后一维必须为 9")
        transformed = array * np.asarray(self.std) + np.asarray(self.mean)
        result = transformed.copy()
        for index, name in enumerate(METRIC_NAMES):
            if name in LOG_METRICS:
                result[..., index] = np.power(10.0, transformed[..., index])
        return result

    def to_dict(self) -> dict[str, object]:
        return {
            "metric_names": list(METRIC_NAMES), "mean": list(self.mean), "std": list(self.std),
            "missing_policy": self.missing_policy, "z_missing": self.z_missing, "fitted_on": self.fitted_on,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "TargetScaler":
        if tuple(payload["metric_names"]) != METRIC_NAMES:  # type: ignore[arg-type]
            raise ValueError("scaler metric schema 不匹配")
        return cls(
            tuple(float(v) for v in payload["mean"]),  # type: ignore[arg-type]
            tuple(float(v) for v in payload["std"]),  # type: ignore[arg-type]
            str(payload["missing_policy"]), float(payload["z_missing"]), str(payload.get("fitted_on", "unknown")),
        )

    def save(self, path: Path | str) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")


def transform_device_parameters(parameters: dict[str, float]) -> tuple[np.ndarray, np.ndarray]:
    values = np.zeros(len(DEVICE_PARAMETER_ORDER), dtype=np.float32)
    mask = np.zeros(len(DEVICE_PARAMETER_ORDER), dtype=bool)
    for index, name in enumerate(DEVICE_PARAMETER_ORDER):
        if name not in parameters:
            continue
        value = float(parameters[name])
        if value <= 0 or not math.isfinite(value):
            raise ValueError(f"器件参数 {name} 必须为有限正数")
        values[index] = math.log1p(value) if name == "M" else math.log10(value)
        mask[index] = True
    return values, mask
