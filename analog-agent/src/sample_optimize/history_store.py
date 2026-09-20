from __future__ import annotations

import csv
import hashlib
import json
import logging
import math
import os
import sqlite3
import tempfile
import uuid

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

import numpy as np


__all__ = ["SamplingHistoryStore"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SamplingHistoryStore:
    """SQLite 是历史数据源，两个 CSV 是由 SQLite 生成的兼容视图。"""

    def __init__(
        self,
        circuit_path: Path,
        circuit_name: str,
        circuit_type: str,
        parameter_names: Sequence[str],
        metric_names: Sequence[str],
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.circuit_path = Path(circuit_path)
        self.circuit_name = circuit_name
        self.circuit_type = circuit_type
        self.parameter_names = list(parameter_names)
        self.metric_names = list(metric_names)
        self.logger = logger or logging.getLogger(__name__)

        if not self.parameter_names:
            raise ValueError("parameter_names 不能为空")
        if not self.metric_names:
            raise ValueError("metric_names 不能为空")
        if len({name.casefold() for name in self.parameter_names}) != len(self.parameter_names):
            raise ValueError("parameter_names 中存在重复名称")
        if len({name.casefold() for name in self.metric_names}) != len(self.metric_names):
            raise ValueError("metric_names 中存在重复名称")

        self.circuit_path.mkdir(parents=True, exist_ok=True)
        self.database_path = self.circuit_path / "sampling_history.sqlite3"
        self.design_csv_path = self.circuit_path / "design_parameters.csv"
        self.metrics_csv_path = self.circuit_path / "metrics.csv"
        self.failure_path = self.circuit_path / "simulation_failures.jsonl"

        self._initialize_database()
        self._migrate_legacy_csv()
        self.logger.info("历史数据库已就绪：%s", self.database_path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize_database(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS dataset_schema (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    circuit_name TEXT NOT NULL,
                    circuit_type TEXT NOT NULL,
                    parameter_names_json TEXT NOT NULL,
                    metric_names_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sampling_runs (
                    run_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    status TEXT NOT NULL,
                    requested_points INTEGER NOT NULL,
                    n_workers INTEGER NOT NULL,
                    allocation_json TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    error_message TEXT
                );

                CREATE TABLE IF NOT EXISTS samples (
                    sample_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    sample_index INTEGER NOT NULL,
                    sample_method TEXT NOT NULL,
                    design_key TEXT NOT NULL UNIQUE,
                    design_values_json TEXT NOT NULL,
                    metric_values_json TEXT NOT NULL,
                    success INTEGER NOT NULL CHECK (success IN (0, 1)),
                    error_type TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES sampling_runs(run_id)
                );

                CREATE INDEX IF NOT EXISTS idx_samples_run_id ON samples(run_id);
                CREATE INDEX IF NOT EXISTS idx_samples_method ON samples(sample_method);
                """
            )

            row = connection.execute("SELECT * FROM dataset_schema WHERE id = 1").fetchone()
            expected_parameters = json.dumps(self.parameter_names, ensure_ascii=False)
            expected_metrics = json.dumps(self.metric_names, ensure_ascii=False)

            if row is None:
                connection.execute(
                    """
                    INSERT INTO dataset_schema (
                        id, circuit_name, circuit_type, parameter_names_json,
                        metric_names_json, created_at
                    ) VALUES (1, ?, ?, ?, ?, ?)
                    """,
                    (
                        self.circuit_name,
                        self.circuit_type,
                        expected_parameters,
                        expected_metrics,
                        _utc_now(),
                    ),
                )
                return

            actual = (
                row["circuit_name"],
                row["circuit_type"],
                row["parameter_names_json"],
                row["metric_names_json"],
            )
            expected = (
                self.circuit_name,
                self.circuit_type,
                expected_parameters,
                expected_metrics,
            )
            if actual != expected:
                raise ValueError(
                    "历史数据库的数据结构与当前电路配置不一致："
                    f"expected={expected}, actual={actual}"
                )

    def _migrate_legacy_csv(self) -> None:
        with self._connect() as connection:
            sample_count = int(connection.execute("SELECT COUNT(*) FROM samples").fetchone()[0])

        design_exists = self.design_csv_path.exists()
        metrics_exists = self.metrics_csv_path.exists()

        if sample_count > 0:
            return
        if not design_exists and not metrics_exists:
            return
        if design_exists != metrics_exists:
            raise ValueError("历史目录中的 design_parameters.csv 和 metrics.csv 必须同时存在")

        with self.design_csv_path.open("r", newline="", encoding="utf-8") as file:
            design_rows = list(csv.reader(file))
        with self.metrics_csv_path.open("r", newline="", encoding="utf-8") as file:
            metric_rows = list(csv.reader(file))

        if not design_rows or not metric_rows:
            raise ValueError("历史 CSV 缺少表头")
        if design_rows[0] != self.parameter_names:
            raise ValueError("历史 design_parameters.csv 表头与当前参数名称不一致")
        if metric_rows[0] != self.metric_names:
            raise ValueError("历史 metrics.csv 表头与当前指标名称不一致")
        if len(design_rows) != len(metric_rows):
            raise ValueError(
                "历史双 CSV 行数不一致："
                f"design={len(design_rows) - 1}, metrics={len(metric_rows) - 1}"
            )

        if len(design_rows) == 1:
            return

        run_id = f"legacy-{uuid.uuid4().hex}"
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sampling_runs (
                    run_id, started_at, completed_at, status, requested_points,
                    n_workers, allocation_json, config_json, error_message
                ) VALUES (?, ?, ?, 'MIGRATED', ?, 1, '{}', '{}', NULL)
                """,
                (run_id, _utc_now(), _utc_now(), len(design_rows) - 1),
            )

            migrated = 0
            duplicates = 0
            for sample_index, (design_row, metric_row) in enumerate(
                zip(design_rows[1:], metric_rows[1:])
            ):
                if len(design_row) != len(self.parameter_names):
                    raise ValueError(f"历史设计参数第 {sample_index + 2} 行列数不正确")
                if len(metric_row) != len(self.metric_names):
                    raise ValueError(f"历史指标第 {sample_index + 2} 行列数不正确")

                design_values = [float(value) for value in design_row]
                metric_values = [float(value) for value in metric_row]
                stored_metrics = [value if math.isfinite(value) else None for value in metric_values]
                success = int(all(value is not None for value in stored_metrics))

                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO samples (
                        run_id, sample_index, sample_method, design_key,
                        design_values_json, metric_values_json, success,
                        error_type, error_message, created_at
                    ) VALUES (?, ?, 'legacy', ?, ?, ?, ?, NULL, NULL, ?)
                    """,
                    (
                        run_id,
                        sample_index,
                        self.design_key(design_values),
                        json.dumps(design_values, ensure_ascii=False, allow_nan=False),
                        json.dumps(stored_metrics, ensure_ascii=False, allow_nan=False),
                        success,
                        _utc_now(),
                    ),
                )
                if cursor.rowcount == 1:
                    migrated += 1
                else:
                    duplicates += 1

        self.logger.info(
            "历史 CSV 已迁移到 SQLite：migrated=%d, duplicate_skipped=%d",
            migrated,
            duplicates,
        )

    @staticmethod
    def design_key(values: Sequence[float]) -> str:
        array = np.asarray(values, dtype=float)
        if array.ndim != 1:
            raise ValueError("设计参数必须是一维数组")
        if not np.all(np.isfinite(array)):
            raise ValueError("设计参数必须全部为有限数值")
        payload = "|".join(float(value).hex() for value in array)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def find_existing_keys(self, design_keys: Iterable[str]) -> set[str]:
        unique_keys = list(dict.fromkeys(design_keys))
        existing: set[str] = set()

        with self._connect() as connection:
            for start in range(0, len(unique_keys), 900):
                chunk = unique_keys[start:start + 900]
                if not chunk:
                    continue
                placeholders = ",".join("?" for _ in chunk)
                rows = connection.execute(
                    f"SELECT design_key FROM samples WHERE design_key IN ({placeholders})",
                    chunk,
                ).fetchall()
                existing.update(row["design_key"] for row in rows)

        return existing

    def create_run(
        self,
        requested_points: int,
        n_workers: int,
        allocation: Mapping[str, int],
        config: Mapping[str, Any],
    ) -> str:
        run_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sampling_runs (
                    run_id, started_at, completed_at, status, requested_points,
                    n_workers, allocation_json, config_json, error_message
                ) VALUES (?, ?, NULL, 'RUNNING', ?, ?, ?, ?, NULL)
                """,
                (
                    run_id,
                    _utc_now(),
                    requested_points,
                    n_workers,
                    json.dumps(dict(allocation), ensure_ascii=False, allow_nan=False),
                    json.dumps(dict(config), ensure_ascii=False, allow_nan=False),
                ),
            )
        self.logger.info("创建采样运行记录：run_id=%s", run_id)
        return run_id

    def mark_run_completed(self, run_id: str, failed_count: int) -> None:
        status = "COMPLETED_WITH_FAILURES" if failed_count else "COMPLETED"
        with self._connect() as connection:
            connection.execute(
                "UPDATE sampling_runs SET status = ?, completed_at = ? WHERE run_id = ?",
                (status, _utc_now(), run_id),
            )
        self.logger.info("采样运行完成：run_id=%s, status=%s", run_id, status)

    def mark_run_failed(self, run_id: str, error: BaseException) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE sampling_runs
                SET status = 'FAILED', completed_at = ?, error_message = ?
                WHERE run_id = ?
                """,
                (_utc_now(), str(error)[:20000], run_id),
            )
        self.logger.error("采样运行失败：run_id=%s, error=%s", run_id, error)

    def write_batch(
        self,
        run_id: str,
        design_parameters: np.ndarray,
        metrics: np.ndarray,
        sampling_methods: Sequence[str],
        failure_records: Sequence[Mapping[str, Any]],
    ) -> None:
        design_array = np.asarray(design_parameters, dtype=float)
        metric_array = np.asarray(metrics, dtype=float)

        if design_array.ndim != 2 or design_array.shape[1] != len(self.parameter_names):
            raise ValueError("design_parameters 的形状与参数名称不一致")
        if metric_array.ndim != 2 or metric_array.shape[1] != len(self.metric_names):
            raise ValueError("metrics 的形状与指标名称不一致")
        if design_array.shape[0] != metric_array.shape[0]:
            raise ValueError("design_parameters 与 metrics 的样本数量不一致")
        if len(sampling_methods) != design_array.shape[0]:
            raise ValueError("sampling_methods 与样本数量不一致")
        if not np.all(np.isfinite(design_array)):
            raise ValueError("design_parameters 中存在 NaN 或 Inf")

        failure_by_index = {int(record["sample_index"]): record for record in failure_records}

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for sample_index, (design_row, metric_row, method) in enumerate(
                zip(design_array, metric_array, sampling_methods)
            ):
                failure = failure_by_index.get(sample_index)
                stored_metrics = [
                    float(value) if math.isfinite(float(value)) else None
                    for value in metric_row
                ]
                success = int(failure is None and all(value is not None for value in stored_metrics))
                error_type = None if failure is None else str(failure.get("error_type", ""))
                error_message = None if failure is None else str(failure.get("error", ""))[:20000]

                try:
                    connection.execute(
                        """
                        INSERT INTO samples (
                            run_id, sample_index, sample_method, design_key,
                            design_values_json, metric_values_json, success,
                            error_type, error_message, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            sample_index,
                            method,
                            self.design_key(design_row),
                            json.dumps(design_row.tolist(), ensure_ascii=False, allow_nan=False),
                            json.dumps(stored_metrics, ensure_ascii=False, allow_nan=False),
                            success,
                            error_type,
                            error_message,
                            _utc_now(),
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise RuntimeError(
                        "写入历史数据库时发现重复 design point，可能存在并发采样冲突"
                    ) from exc

        self.logger.info("批次结果已写入 SQLite：run_id=%s, samples=%d", run_id, len(design_array))

    def export_csv(self) -> None:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT sample_id, run_id, sample_index, sample_method,
                       design_values_json, metric_values_json, success,
                       error_type, error_message
                FROM samples ORDER BY sample_id
                """
            ).fetchall()

        design_rows = [json.loads(row["design_values_json"]) for row in rows]
        metric_rows = [
            [float("nan") if value is None else value for value in json.loads(row["metric_values_json"])]
            for row in rows
        ]
        self._atomic_write_csv(self.design_csv_path, self.parameter_names, design_rows)
        self._atomic_write_csv(self.metrics_csv_path, self.metric_names, metric_rows)

        failures = []
        for row in rows:
            if row["success"]:
                continue
            failures.append(
                {
                    "sample_id": row["sample_id"],
                    "run_id": row["run_id"],
                    "sample_index": row["sample_index"],
                    "sample_method": row["sample_method"],
                    "design_parameters": json.loads(row["design_values_json"]),
                    "error_type": row["error_type"],
                    "error": row["error_message"],
                }
            )
        self._atomic_write_jsonl(self.failure_path, failures)
        self.logger.info("SQLite 兼容导出完成：samples=%d", len(rows))

    @staticmethod
    def _atomic_write_csv(path: Path, header: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, mode="w", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                writer.writerow(header)
                writer.writerows(rows)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _atomic_write_jsonl(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, mode="w", encoding="utf-8") as file:
                for record in records:
                    file.write(json.dumps(dict(record), ensure_ascii=False, allow_nan=False) + "\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
