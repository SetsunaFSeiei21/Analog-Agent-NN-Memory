from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


METRIC_NAMES: tuple[str, ...] = (
    "DC_Gain_dB",
    "UGF_Hz",
    "Phase_Margin_deg",
    "CMRR_dB",
    "PSRR_Plus_dB",
    "PSRR_Minus_dB",
    "Slew_Rise_V_us",
    "Slew_Fall_V_us",
    "Power_Quiescent_uW",
)
METRIC_INDEX = {name: index for index, name in enumerate(METRIC_NAMES)}
LOG_METRICS = frozenset({ # frozenset 代表不可变的集合
    "UGF_Hz", "Slew_Rise_V_us", "Slew_Fall_V_us", "Power_Quiescent_uW"
})
SLEW_METRICS = frozenset({"Slew_Rise_V_us", "Slew_Fall_V_us"})


@dataclass(frozen=True) # @dataclass(frozen=True) 表示这个数据类的实例创建后，字段不能再被重新赋值，可以理解为“只读数据对象”
class SampleRecord:
    topology_id: str
    sample_id: int
    parameter_names: tuple[str, ...]
    design_values: tuple[float, ...]
    metric_values: tuple[float | None, ...]
    access_level: str
    database_path: Path


@dataclass(frozen=True)
class MetricPrediction:
    topology_id: str
    metrics: Mapping[str, float]
    embedding: Sequence[float]
    backbone_version: str | None = None
    adapter_version: str | None = None


@dataclass(frozen=True)
class ProbeMetrics:
    per_metric_r2: Mapping[str, float | None]
    per_metric_nrmse: Mapping[str, float | None]
    per_metric_count: Mapping[str, int]
    macro_r2: float | None
    macro_nrmse: float | None


def validate_metric_schema(names: Sequence[str]) -> tuple[str, ...]:
    actual = tuple(names)
    if actual != METRIC_NAMES:
        raise ValueError(f"指标 schema 必须严格为 {METRIC_NAMES}，实际为 {actual}")
    return actual
