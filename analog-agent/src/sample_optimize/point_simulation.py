from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from .history_store import SamplingHistoryStore, _validate_access_level
from .simulating import Simulator


OBSERVATION_SOURCES = frozenset({"probe", "agent", "active_sample", "validation"})


@dataclass(frozen=True)
class PointSimulationResult:
    sample_id: int
    design_key: str
    design_parameters: Mapping[str, float]
    metrics: Mapping[str, float | None]
    cache_hit: bool
    real_spice_call: bool
    access_level: str


class PointSimulator:
    """One-point, budget-accountable simulation API for the agent loop."""

    def __init__(
        self,
        *,
        history_store: SamplingHistoryStore,
        simulator: Simulator,
        circuit_path: Any,
        parameter_names: Sequence[str],
        bounds: Sequence[tuple[float, float, float]],
    ) -> None:
        self.history_store = history_store
        self.simulator = simulator
        self.circuit_path = circuit_path
        self.parameter_names = tuple(parameter_names)
        self.bounds = tuple(bounds)
        if len(self.parameter_names) != len(self.bounds):
            raise ValueError("parameter_names 与 bounds 长度不一致")

    def _design_row(self, parameters: Mapping[str, float]) -> np.ndarray:
        supplied = {name.casefold(): (name, value) for name, value in parameters.items()}
        expected = {name.casefold(): name for name in self.parameter_names}
        if set(supplied) != set(expected):
            raise ValueError(
                f"设计参数必须精确匹配 schema：missing={sorted(set(expected)-set(supplied))}, "
                f"extra={sorted(set(supplied)-set(expected))}"
            )
        values: list[float] = []
        for name, (lower, upper, step) in zip(self.parameter_names, self.bounds):
            raw = supplied[name.casefold()][1]
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise TypeError(f"{name} 必须是数值")
            value = float(raw)
            if not math.isfinite(value) or value < lower - 1e-12 or value > upper + 1e-12:
                raise ValueError(f"{name}={value} 超出范围 [{lower}, {upper}]")
            grid = (value - lower) / step
            if not math.isclose(grid, round(grid), rel_tol=0, abs_tol=1e-7):
                raise ValueError(f"{name}={value} 不在步长 {step} 的网格上")
            values.append(value)
        return np.asarray(values, dtype=float)

    @staticmethod
    def _visible_levels(access_level: str) -> set[str]:
        if access_level == "train_visible":
            return {"train_visible"}
        if access_level == "hidden_eval":
            return {"train_visible", "hidden_eval"}
        return {"final_blind"}

    def simulate(
        self,
        parameters: Mapping[str, float],
        *,
        source: str,
        task_id: str | None = None,
        arrival_step: int | None = None,
        access_level: str = "train_visible",
        backbone_version: str | None = None,
        adapter_version: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        continue_on_error: bool = True,
    ) -> PointSimulationResult:
        if source not in OBSERVATION_SOURCES:
            raise ValueError(f"source 必须是 {sorted(OBSERVATION_SOURCES)} 之一")
        _validate_access_level(access_level)
        row = self._design_row(parameters)
        design_key = self.history_store.design_key(row)
        existing_any = self.history_store.fetch_by_design_keys([design_key])
        run_id = self.history_store.create_run(
            requested_points=1,
            n_workers=1,
            allocation={source: 1},
            config={"continue_on_error": continue_on_error},
            source=source,
            task_id=task_id,
            arrival_step=arrival_step,
            access_level=access_level,
            metadata={
                **dict(metadata or {}),
                "design_key": design_key,
                "cache_hit": design_key in existing_any,
                "real_spice_call": design_key not in existing_any,
            },
        )
        if design_key in existing_any:
            existing = existing_any[design_key]
            if existing["access_level"] not in self._visible_levels(access_level):
                error = PermissionError(
                    "该 design point 已存在于当前调用不可见的数据分区；为防止盲测泄漏，拒绝复用或重跑"
                )
                self.history_store.mark_run_failed(run_id, error)
                raise error
            self.history_store.mark_run_completed(run_id, 0)
            metric_values = __import__("json").loads(existing["metric_values_json"])
            return PointSimulationResult(
                sample_id=int(existing["sample_id"]), design_key=design_key,
                design_parameters=dict(zip(self.parameter_names, row.tolist())),
                metrics=dict(zip(self.history_store.metric_names, metric_values)),
                cache_hit=True, real_spice_call=False, access_level=existing["access_level"],
            )
        try:
            result = self.simulator.simulate_batch(
                circuit_path=self.circuit_path,
                n_workers=1,
                design_parameters_array=row.reshape(1, -1),
                continue_on_error=continue_on_error,
            )
            ids = self.history_store.write_batch(
                run_id=run_id,
                design_parameters=row.reshape(1, -1),
                metrics=result.metrics,
                sampling_methods=[source],
                failure_records=result.failure_records,
                access_level=access_level,
                is_real_spice_call=True,
                backbone_version=backbone_version,
                adapter_version=adapter_version,
            )
            self.history_store.mark_run_completed(run_id, len(result.failure_records))
            self.history_store.export_csv()
            values = [None if not math.isfinite(float(value)) else float(value) for value in result.metrics[0]]
            return PointSimulationResult(
                sample_id=ids[0], design_key=design_key,
                design_parameters=dict(zip(self.parameter_names, row.tolist())),
                metrics=dict(zip(self.history_store.metric_names, values)),
                cache_hit=False, real_spice_call=True, access_level=access_level,
            )
        except Exception as exc:
            self.history_store.mark_run_failed(run_id, exc)
            raise
