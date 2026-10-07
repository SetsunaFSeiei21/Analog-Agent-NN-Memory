#!/usr/bin/env python3
"""Regenerate aligned design/metric/DC CSVs from an existing SQLite history."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.sample_optimize.history_store import SamplingHistoryStore


def main():
    parser = argparse.ArgumentParser(description="从 SQLite 导出设计、指标和工作点宽表；不启动 SPICE。")
    parser.add_argument("--circuit-path", type=Path, required=True, help="包含 sampling_history.sqlite3 的电路数据目录。")
    args = parser.parse_args()
    database = args.circuit_path / "sampling_history.sqlite3"
    if not database.is_file():
        parser.error(f"数据库不存在：{database}")
    with closing(sqlite3.connect(database)) as connection:
        connection.row_factory = sqlite3.Row
        schema = connection.execute("SELECT * FROM dataset_schema WHERE id=1").fetchone()
    if schema is None:
        parser.error("数据库中缺少 dataset_schema")
    store = SamplingHistoryStore(args.circuit_path, schema["circuit_name"], schema["circuit_type"],
        json.loads(schema["parameter_names_json"]), json.loads(schema["metric_names_json"]), journal_mode="DELETE")
    store.export_csv()
    for path in (store.design_csv_path, store.metrics_csv_path, store.operating_points_csv_path):
        print(path)


if __name__ == "__main__":
    main()
