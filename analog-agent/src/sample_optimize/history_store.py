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
from contextlib import contextmanager
from itertools import chain, groupby
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

import numpy as np

from .operating_point_contract import DEVICE_FIELDS, device_values, finite_or_none


__all__ = ["ACCESS_LEVELS", "SamplingHistoryStore"]


ACCESS_LEVELS = frozenset({"train_visible", "hidden_eval", "final_blind"})


def _validate_access_level(value: str) -> str:
    if value not in ACCESS_LEVELS:
        raise ValueError(f"access_level 必须是 {sorted(ACCESS_LEVELS)} 之一")
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SamplingHistoryStore:
    """SQLite 是历史数据源，设计、指标和工作点 CSV 是兼容视图。"""

    def __init__(
        self,
        circuit_path: Path,
        circuit_name: str,
        circuit_type: str,
        parameter_names: Sequence[str],
        metric_names: Sequence[str],
        logger: Optional[logging.Logger] = None,
        journal_mode: str = "WAL",
    ) -> None:
        self.circuit_path = Path(circuit_path)
        self.circuit_name = circuit_name
        self.circuit_type = circuit_type
        self.parameter_names = list(parameter_names)
        self.metric_names = list(metric_names)
        self.logger = logger or logging.getLogger(__name__)
        if journal_mode not in {"WAL", "DELETE"}:
            raise ValueError("journal_mode must be WAL or DELETE")
        self.journal_mode = journal_mode

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
        self.operating_points_csv_path = self.circuit_path / "dc_operating_points.csv"
        self.failure_path = self.circuit_path / "simulation_failures.jsonl"

        self._initialize_database()
        self._migrate_legacy_csv()
        self._migrate_operating_points()
        self.logger.info("历史数据库已就绪：%s", self.database_path)

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA journal_mode = {self.journal_mode}")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

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
                    error_message TEXT,
                    source TEXT NOT NULL DEFAULT 'batch',
                    task_id TEXT,
                    arrival_step INTEGER,
                    access_level TEXT NOT NULL DEFAULT 'train_visible',
                    metadata_json TEXT NOT NULL DEFAULT '{}'
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
                    access_level TEXT NOT NULL DEFAULT 'train_visible',
                    is_real_spice_call INTEGER NOT NULL DEFAULT 1,
                    cache_hit_sample_id INTEGER,
                    backbone_version TEXT,
                    adapter_version TEXT,
                    FOREIGN KEY (run_id) REFERENCES sampling_runs(run_id)
                );

                CREATE INDEX IF NOT EXISTS idx_samples_run_id ON samples(run_id);
                CREATE INDEX IF NOT EXISTS idx_samples_method ON samples(sample_method);

                CREATE TABLE IF NOT EXISTS sampling_state (
                    run_id TEXT PRIMARY KEY REFERENCES sampling_runs(run_id),
                    state_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS spice_invocations (
                    invocation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    design_key TEXT NOT NULL,
                    category TEXT NOT NULL,
                    bench TEXT NOT NULL,
                    status TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_spice_run ON spice_invocations(run_id);
                """
            )

            self._ensure_columns(connection, "samples", {
                "observation_json": "TEXT", "proposal_json": "TEXT",
            })

            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS dc_operating_points (
                    sample_id INTEGER PRIMARY KEY REFERENCES samples(sample_id) ON DELETE CASCADE,
                    schema_version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    converged INTEGER,
                    feasible INTEGER,
                    condition_json TEXT NOT NULL,
                    bias_topology TEXT,
                    reasons_json TEXT NOT NULL,
                    missing_fields_json TEXT NOT NULL,
                    node_voltages_json TEXT NOT NULL,
                    follower_error_v REAL,
                    vout_v REAL
                );
                """
                + "CREATE TABLE IF NOT EXISTS dc_device_operating_points ("
                + "sample_id INTEGER NOT NULL REFERENCES dc_operating_points(sample_id) ON DELETE CASCADE,"
                + "device_name TEXT NOT NULL,device_type TEXT,model_name TEXT,primitive_path TEXT,"
                + ",".join(f"{name} REAL" for name in DEVICE_FIELDS)
                + ",PRIMARY KEY(sample_id,device_name)) WITHOUT ROWID;"
            )

            self._ensure_columns(
                connection,
                "sampling_runs",
                {
                    "source": "TEXT NOT NULL DEFAULT 'batch'",
                    "task_id": "TEXT",
                    "arrival_step": "INTEGER",
                    "access_level": "TEXT NOT NULL DEFAULT 'train_visible'",
                    "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
                },
            )
            self._ensure_columns(
                connection,
                "samples",
                {
                    "access_level": "TEXT NOT NULL DEFAULT 'train_visible'",
                    "is_real_spice_call": "INTEGER NOT NULL DEFAULT 1",
                    "cache_hit_sample_id": "INTEGER",
                    "backbone_version": "TEXT",
                    "adapter_version": "TEXT",
                },
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_samples_access_level ON samples(access_level)"
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

    @staticmethod
    def _ensure_columns(
        connection: sqlite3.Connection,
        table: str,
        definitions: Mapping[str, str],
    ) -> None:
        existing = {
            row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for name, definition in definitions.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    @staticmethod
    def _write_operating_point(connection, sample_id, observation):
        observation = {} if observation is None else dict(observation)
        version = int(observation.get("schema_version", 1))
        converged = observation.get("converged")
        feasible = observation.get("feasible")
        status = observation.get("status")
        if status is None:
            status = "not_recorded" if not observation else ("failed" if converged is False else "legacy_partial")
        encode = lambda value: json.dumps(value, ensure_ascii=False, allow_nan=False)
        connection.execute(
            """INSERT INTO dc_operating_points VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sample_id, version, status,
             None if converged is None else int(bool(converged)),
             None if feasible is None else int(bool(feasible)),
             encode(observation.get("condition", {})), observation.get("bias_topology"),
             encode(observation.get("reasons", [])), encode(observation.get("missing_fields", {})),
             encode(observation.get("node_voltages_v", {})),
             finite_or_none(observation.get("follower_error_v")), finite_or_none(observation.get("vout_v"))),
        )
        columns = ("sample_id", "device_name", "device_type", "model_name", "primitive_path") + DEVICE_FIELDS
        statement = (f"INSERT INTO dc_device_operating_points ({','.join(columns)}) "
                     f"VALUES ({','.join('?' for _ in columns)})")
        connection.executemany(statement, (
            (sample_id, name.upper(), fields.get("device_type"), fields.get("model_name"), fields.get("primitive_path"))
            + device_values(fields) for name, fields in observation.get("devices", {}).items()
        ))

    def _migrate_operating_points(self):
        """Copy existing recorded values once; never simulate or invent labels."""
        with self._connect() as connection:
            rows = connection.execute("""SELECT s.sample_id,s.observation_json FROM samples s
                LEFT JOIN dc_operating_points o USING(sample_id) WHERE o.sample_id IS NULL ORDER BY s.sample_id""")
            for row in rows:
                self._write_operating_point(connection, row["sample_id"],
                    None if row["observation_json"] is None else json.loads(row["observation_json"]))

    def fetch_operating_point(self, sample_id: int, *, access_levels=("train_visible",)):
        """Structured OP inherits its parent sample's access partition."""
        levels = tuple(dict.fromkeys(access_levels))
        for level in levels:
            _validate_access_level(level)
        if not levels:
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT o.*,s.access_level,s.design_key FROM dc_operating_points o JOIN samples s USING(sample_id) "
                f"WHERE s.sample_id=? AND s.access_level IN ({','.join('?' for _ in levels)})",
                (sample_id, *levels),
            ).fetchone()
            if row is None:
                return None
            result = dict(row)
            for name in ("condition", "reasons", "missing_fields", "node_voltages"):
                result[name] = json.loads(result.pop(name + "_json"))
            result["devices"] = {
                device["device_name"]: {key: device[key] for key in device.keys() if key not in {"sample_id", "device_name"}}
                for device in connection.execute("SELECT * FROM dc_device_operating_points WHERE sample_id=? ORDER BY device_name", (sample_id,))
            }
            return result

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

    def fetch_by_design_keys(
        self,
        design_keys: Iterable[str],
        *,
        access_levels: Iterable[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        unique_keys = list(dict.fromkeys(design_keys))
        levels = None if access_levels is None else tuple(dict.fromkeys(access_levels))
        if levels is not None:
            for level in levels:
                _validate_access_level(level)
        result: dict[str, dict[str, Any]] = {}
        with self._connect() as connection:
            for start in range(0, len(unique_keys), 850):
                chunk = unique_keys[start:start + 850]
                if not chunk:
                    continue
                clauses = [f"design_key IN ({','.join('?' for _ in chunk)})"]
                arguments: list[Any] = list(chunk)
                if levels is not None:
                    if not levels:
                        continue
                    clauses.append(f"access_level IN ({','.join('?' for _ in levels)})")
                    arguments.extend(levels)
                rows = connection.execute(
                    "SELECT * FROM samples WHERE " + " AND ".join(clauses) + " ORDER BY sample_id",
                    arguments,
                ).fetchall()
                for row in rows:
                    result[row["design_key"]] = dict(row)
        return result

    def create_run(
        self,
        requested_points: int,
        n_workers: int,
        allocation: Mapping[str, int],
        config: Mapping[str, Any],
        *,
        source: str = "batch",
        task_id: str | None = None,
        arrival_step: int | None = None,
        access_level: str = "train_visible",
        metadata: Mapping[str, Any] | None = None,
        initial_state: Mapping[str, Any] | None = None,
    ) -> str:
        _validate_access_level(access_level)
        if not source.strip():
            raise ValueError("source 不能为空")
        run_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sampling_runs (
                    run_id, started_at, completed_at, status, requested_points,
                    n_workers, allocation_json, config_json, error_message,
                    source, task_id, arrival_step, access_level, metadata_json
                ) VALUES (?, ?, NULL, 'RUNNING', ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    _utc_now(),
                    requested_points,
                    n_workers,
                    json.dumps(dict(allocation), ensure_ascii=False, allow_nan=False),
                    json.dumps(dict(config), ensure_ascii=False, allow_nan=False),
                    source,
                    task_id,
                    arrival_step,
                    access_level,
                    json.dumps(dict(metadata or {}), ensure_ascii=False, allow_nan=False),
                ),
            )
            if initial_state is not None:
                connection.execute("INSERT INTO sampling_state VALUES (?,?)", (run_id, json.dumps(initial_state, allow_nan=False)))
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
        *,
        access_level: str = "train_visible",
        is_real_spice_call: bool = True,
        cache_hit_sample_ids: Sequence[int | None] | None = None,
        backbone_version: str | None = None,
        adapter_version: str | None = None,
        observations: Sequence[Mapping[str, Any]] | None = None,
        proposals: Sequence[Mapping[str, Any]] | None = None,
        next_state: Mapping[str, Any] | None = None,
    ) -> list[int]:
        _validate_access_level(access_level)
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
        if cache_hit_sample_ids is None:
            cache_hit_sample_ids = [None] * design_array.shape[0]
        if len(cache_hit_sample_ids) != design_array.shape[0]:
            raise ValueError("cache_hit_sample_ids 与样本数量不一致")

        failure_by_index = {int(record["sample_index"]): record for record in failure_records}
        if observations is not None and len(observations) != len(design_array):
            raise ValueError("observations 与样本数量不一致")
        if proposals is not None and len(proposals) != len(design_array):
            raise ValueError("proposals 与样本数量不一致")

        sample_ids: list[int] = []
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            offset = connection.execute("SELECT COALESCE(MAX(sample_index)+1,0) FROM samples WHERE run_id=?", (run_id,)).fetchone()[0]
            for sample_index, (design_row, metric_row, method, cache_hit_sample_id) in enumerate(
                zip(design_array, metric_array, sampling_methods, cache_hit_sample_ids)
            ):
                failure = failure_by_index.get(sample_index)
                stored_metrics = [
                    float(value) if math.isfinite(float(value)) else None
                    for value in metric_row
                ]
                # ``success`` keeps its legacy meaning (all requested metrics valid).
                # Neural readers still consume partial rows through the per-metric mask.
                success = int(failure is None and all(value is not None for value in stored_metrics))
                error_type = None if failure is None else str(failure.get("error_type", ""))
                error_message = None if failure is None else str(failure.get("error", ""))[:20000]

                try:
                    cursor = connection.execute(
                        """
                        INSERT INTO samples (
                            run_id, sample_index, sample_method, design_key,
                            design_values_json, metric_values_json, success,
                            error_type, error_message, created_at, access_level,
                            is_real_spice_call, cache_hit_sample_id, backbone_version,
                            adapter_version
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            sample_index + offset,
                            method,
                            self.design_key(design_row),
                            json.dumps(design_row.tolist(), ensure_ascii=False, allow_nan=False),
                            json.dumps(stored_metrics, ensure_ascii=False, allow_nan=False),
                            success,
                            error_type,
                            error_message,
                            _utc_now(),
                            access_level,
                            int(is_real_spice_call),
                            cache_hit_sample_id,
                            backbone_version,
                            adapter_version,
                        ),
                    )
                    sample_ids.append(int(cursor.lastrowid))
                    connection.execute("UPDATE samples SET observation_json=?, proposal_json=? WHERE sample_id=?", (
                        None if observations is None else json.dumps(observations[sample_index], allow_nan=False),
                        None if proposals is None else json.dumps(proposals[sample_index], allow_nan=False),
                        cursor.lastrowid,
                    ))
                    self._write_operating_point(connection, cursor.lastrowid,
                                                None if observations is None else observations[sample_index])
                except sqlite3.IntegrityError as exc:
                    raise RuntimeError(
                        "写入历史数据库时发现重复 design point，可能存在并发采样冲突"
                    ) from exc

            if next_state is not None:
                connection.execute("INSERT OR REPLACE INTO sampling_state VALUES (?,?)",
                                   (run_id, json.dumps(next_state, allow_nan=False)))

        self.logger.info("批次结果已写入 SQLite：run_id=%s, samples=%d", run_id, len(design_array))
        return sample_ids

    def export_csv(self) -> None:
        with self._connect() as connection:
            # All three CSVs use one read snapshot and the identical sample order.
            connection.execute("BEGIN")
            rows = connection.execute(
                """
                SELECT sample_id, run_id, sample_index, sample_method,
                       design_values_json, metric_values_json, success,
                       error_type, error_message
                FROM samples ORDER BY sample_id
                """
            ).fetchall()
            design_rows = (json.loads(row["design_values_json"]) for row in rows)
            metric_rows = (
                [float("nan") if value is None else value for value in json.loads(row["metric_values_json"])]
                for row in rows
            )
            self._atomic_write_csv(self.design_csv_path, self.parameter_names, design_rows)
            self._atomic_write_csv(self.metrics_csv_path, self.metric_names, metric_rows)
            names = [row[0] for row in connection.execute("SELECT DISTINCT device_name FROM dc_device_operating_points ORDER BY device_name")]
            metadata = ("csv_row_index", "sample_id", "design_key", "access_level", "op_schema_version", "op_status",
                        "op_converged", "op_feasible", "op_bias_topology", "op_reasons", "op_missing_fields",
                        "op_pdk_path", "op_corner", "op_temperature_c", "op_vdd_v", "op_vss_v", "op_vcm_v",
                        "op_follower_error_v", "op_vout_v")
            device_columns = ("device_type", "model_name") + DEVICE_FIELDS
            header = metadata + tuple(f"{name}.{field}" for name in names for field in device_columns)
            self._atomic_write_csv(self.operating_points_csv_path, header,
                                   self._operating_point_csv_rows(connection, names, device_columns))

        failures = []
        for row in rows:
            if row["success"] and not row["error_type"]:
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
    def _operating_point_csv_rows(connection, names, device_columns):
        # A streaming join avoids loading the potentially large wide OP dataset
        # into memory or running one SQL query per sample.
        cursor = connection.execute("""SELECT s.sample_id,s.design_key,s.access_level,o.*,d.* FROM samples s
            LEFT JOIN dc_operating_points o USING(sample_id)
            LEFT JOIN dc_device_operating_points d USING(sample_id)
            ORDER BY s.sample_id,d.device_name""")
        nan = float("nan")
        for row_index, (_, group) in enumerate(groupby(cursor, key=lambda row: row["sample_id"])):
            first = next(group)
            condition = json.loads(first["condition_json"] or "{}")
            metadata = [row_index, first["sample_id"], first["design_key"], first["access_level"], first["schema_version"],
                        first["status"], first["converged"], first["feasible"], first["bias_topology"],
                        first["reasons_json"], first["missing_fields_json"],
                        condition.get("PDK_PATH"), condition.get("CORNER"), condition.get("TEMP"),
                        condition.get("VDD"), condition.get("VSS"), condition.get("VCM"),
                        first["follower_error_v"], first["vout_v"]]
            devices = {row["device_name"]: row for row in chain((first,), group) if row["device_name"] is not None}
            values = [devices[name][field] if name in devices else None for name in names for field in device_columns]
            yield [nan if value is None else value for value in metadata + values]

    @staticmethod
    def _atomic_write_csv(path: Path, header: Sequence[str], rows: Iterable[Sequence[Any]]) -> None:
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
