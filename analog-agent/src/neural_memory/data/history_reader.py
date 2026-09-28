from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from ..contracts import METRIC_NAMES, SampleRecord, validate_metric_schema


class HistoryReader:
    """Read-only adapter from the sampling SQLite contract to neural records."""

    def __init__(self, database_path: Path | str, topology_id: str) -> None:
        self.database_path = Path(database_path).resolve()
        self.topology_id = topology_id
        if not self.database_path.is_file():
            raise FileNotFoundError(self.database_path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(f"file:{self.database_path.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    def schema(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM dataset_schema WHERE id=1").fetchone()
        if row is None:
            raise ValueError(f"缺少 dataset_schema：{self.database_path}")
        parameters = tuple(json.loads(row["parameter_names_json"]))
        metrics = validate_metric_schema(json.loads(row["metric_names_json"]))
        return parameters, metrics

    def read(
        self,
        *,
        access_levels: Iterable[str] = ("train_visible",),
        include_all_missing: bool = False,
    ) -> list[SampleRecord]:
        levels = tuple(dict.fromkeys(access_levels))
        if not levels:
            return []
        if "final_blind" in levels and set(levels) != {"final_blind"}:
            raise PermissionError("final_blind 必须单独读取，不能与训练/验证分区混合")
        parameters, _ = self.schema()
        placeholders = ",".join("?" for _ in levels)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT sample_id, design_values_json, metric_values_json, access_level "
                f"FROM samples WHERE access_level IN ({placeholders}) ORDER BY sample_id",
                levels,
            ).fetchall()
        result: list[SampleRecord] = []
        for row in rows:
            design = tuple(float(value) for value in json.loads(row["design_values_json"]))
            raw_metrics = json.loads(row["metric_values_json"])
            metrics = tuple(None if value is None else float(value) for value in raw_metrics)
            if len(design) != len(parameters) or len(metrics) != len(METRIC_NAMES):
                raise ValueError(f"样本 {row['sample_id']} 的向量长度与 schema 不一致")
            if not include_all_missing and all(value is None for value in metrics):
                continue
            result.append(SampleRecord(
                topology_id=self.topology_id,
                sample_id=int(row["sample_id"]),
                parameter_names=parameters,
                design_values=design,
                metric_values=metrics,
                access_level=row["access_level"],
                database_path=self.database_path,
            ))
        return result

    def statistics(self, *, access_levels: Iterable[str]) -> dict[str, int]:
        levels = tuple(dict.fromkeys(access_levels))
        if not levels:
            return {"rows": 0, "usable_rows": 0, "real_spice_calls": 0}
        placeholders = ",".join("?" for _ in levels)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT metric_values_json, is_real_spice_call FROM samples "
                f"WHERE access_level IN ({placeholders})",
                levels,
            ).fetchall()
        usable = sum(any(value is not None for value in json.loads(row["metric_values_json"])) for row in rows)
        return {
            "rows": len(rows),
            "usable_rows": int(usable),
            "real_spice_calls": sum(int(row["is_real_spice_call"]) for row in rows),
        }

    def assert_ready(self, expected_usable_points: int, *, access_levels: Iterable[str]) -> None:
        statistics = self.statistics(access_levels=access_levels)
        if statistics["usable_rows"] < expected_usable_points:
            raise ValueError(
                f"{self.topology_id} 只有 {statistics['usable_rows']} 个可用唯一点，"
                f"冻结协议要求至少 {expected_usable_points}"
            )
        if statistics["real_spice_calls"] < expected_usable_points:
            raise ValueError(
                f"{self.topology_id} 的真实 SPICE 调用只有 {statistics['real_spice_calls']}，"
                f"不能用缓存命中凑足 {expected_usable_points} 点预算"
            )
