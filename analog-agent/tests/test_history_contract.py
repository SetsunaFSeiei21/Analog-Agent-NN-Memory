from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from src.sample_optimize.history_store import SamplingHistoryStore
from src.sample_optimize.point_simulation import PointSimulator
from src.sample_optimize.simulating import SimulationBatchResult


def make_store(path: Path) -> SamplingHistoryStore:
    return SamplingHistoryStore(path, "demo", "single_ended_opamp", ["W", "M"], ["Gain", "UGF"])


def test_schema_migrates_old_database_in_place(tmp_path: Path) -> None:
    db = tmp_path / "sampling_history.sqlite3"
    with sqlite3.connect(db) as connection:
        connection.executescript(
            """
            CREATE TABLE dataset_schema (
              id INTEGER PRIMARY KEY, circuit_name TEXT, circuit_type TEXT,
              parameter_names_json TEXT, metric_names_json TEXT, created_at TEXT);
            CREATE TABLE sampling_runs (
              run_id TEXT PRIMARY KEY, started_at TEXT, completed_at TEXT, status TEXT,
              requested_points INTEGER, n_workers INTEGER, allocation_json TEXT,
              config_json TEXT, error_message TEXT);
            CREATE TABLE samples (
              sample_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, sample_index INTEGER,
              sample_method TEXT, design_key TEXT UNIQUE, design_values_json TEXT,
              metric_values_json TEXT, success INTEGER, error_type TEXT, error_message TEXT,
              created_at TEXT);
            """
        )
        connection.execute(
            "INSERT INTO dataset_schema VALUES (1,?,?,?,?,?)",
            ("demo", "single_ended_opamp", json.dumps(["W", "M"]), json.dumps(["Gain", "UGF"]), "now"),
        )
    make_store(tmp_path)
    with sqlite3.connect(db) as connection:
        run_columns = {row[1] for row in connection.execute("PRAGMA table_info(sampling_runs)")}
        sample_columns = {row[1] for row in connection.execute("PRAGMA table_info(samples)")}
    assert {"source", "task_id", "arrival_step", "access_level", "metadata_json"} <= run_columns
    assert {"access_level", "is_real_spice_call", "backbone_version", "adapter_version"} <= sample_columns


class FakeSimulator:
    metrics = ["Gain", "UGF"]

    def __init__(self) -> None:
        self.calls = 0

    def simulate_batch(self, **_: object) -> SimulationBatchResult:
        self.calls += 1
        return SimulationBatchResult(np.asarray([[60.0, np.nan]]), ())


def test_point_api_validates_grid_caches_and_preserves_partial_metrics(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    simulator = FakeSimulator()
    api = PointSimulator(
        history_store=store,
        simulator=simulator,  # type: ignore[arg-type]
        circuit_path=tmp_path,
        parameter_names=["W", "M"],
        bounds=[(1.0, 3.0, 0.5), (1.0, 4.0, 1.0)],
    )
    first = api.simulate({"W": 2.0, "M": 3}, source="probe")
    second = api.simulate({"M": 3, "W": 2.0}, source="agent")
    assert first.real_spice_call and not first.cache_hit
    assert second.cache_hit and not second.real_spice_call
    assert first.metrics == {"Gain": 60.0, "UGF": None}
    assert simulator.calls == 1
    with pytest.raises(ValueError, match="网格"):
        api.simulate({"W": 2.1, "M": 3}, source="probe")


def test_point_api_does_not_leak_hidden_collision(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    simulator = FakeSimulator()
    api = PointSimulator(
        history_store=store,
        simulator=simulator,  # type: ignore[arg-type]
        circuit_path=tmp_path,
        parameter_names=["W", "M"],
        bounds=[(1.0, 3.0, 0.5), (1.0, 4.0, 1.0)],
    )
    api.simulate({"W": 1.5, "M": 2}, source="validation", access_level="hidden_eval")
    with pytest.raises(PermissionError, match="盲测泄漏"):
        api.simulate({"W": 1.5, "M": 2}, source="probe", access_level="train_visible")
