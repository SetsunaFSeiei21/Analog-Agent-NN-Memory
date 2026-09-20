from __future__ import annotations

import csv
import json
import logging
import sqlite3
import sys
import tempfile
import unittest

from pathlib import Path

import numpy as np


ANALOG_AGENT_PATH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ANALOG_AGENT_PATH))

from src.sample_optimize import (  # noqa: E402
    LHS_Sampler,
    Random_Sampler,
    SamplingHistoryStore,
    Sampling_Controller,
    Sobol_Sampler,
)
from src.utils import parse_spice_instances, read_parameter_names, rewrite_parameter_values  # noqa: E402


class ParserAndSamplerTest(unittest.TestCase):
    def test_multiple_parameters_are_rewritten_without_losing_comments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "params.sp"
            path.write_text(
                "* keep this comment\n.param WN=1 LN=0.5 $ inline comment\n"
                ".param CLOAD=1e-12\n",
                encoding="utf-8",
            )
            self.assertEqual(read_parameter_names(path), ["WN", "LN", "CLOAD"])
            rewrite_parameter_values(path, {"WN": 2.5, "LN": 0.35, "CLOAD": 2e-12})
            content = path.read_text(encoding="utf-8")
            self.assertIn("* keep this comment", content)
            self.assertIn("$ inline comment", content)
            self.assertIn("WN=2.5", content)
            self.assertIn("LN=0.35", content)

    def test_control_block_is_not_parsed_as_circuit_instances(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "circuit.sp"
            path.write_text(
                ".control\nrun\nmeas ac result FIND v(out) AT=1\n.endc\n"
                "RLOAD out 0 {RVAL}\n",
                encoding="utf-8",
            )
            instances = parse_spice_instances(path)
            self.assertEqual([instance.instance_name for instance in instances], ["RLOAD"])

    def test_samplers_return_exact_count_and_legal_grid(self) -> None:
        bounds = [(0.0, 1.0, 0.35), (1.0, 2.0, 0.25)]
        names = ["A", "B"]
        samplers = [
            (Random_Sampler(Path("unused"), names, bounds, 42), 7, 3),
            (LHS_Sampler(Path("unused"), names, bounds, 42), 7, None),
            (Sobol_Sampler(Path("unused"), names, bounds, 42), 8, None),
        ]

        for sampler, count, workers in samplers:
            points = sampler.generate_sample_point(count, workers)
            self.assertEqual(points.shape, (count, 2))
            self.assertTrue(set(np.round(points[:, 0], 12)).issubset({0.0, 0.35, 0.7}))
            self.assertTrue(set(np.round(points[:, 1], 12)).issubset({1.0, 1.25, 1.5, 1.75, 2.0}))


class HistoryStoreTest(unittest.TestCase):
    def test_sqlite_is_canonical_and_exports_both_csv_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            circuit_path = Path(temporary_directory)
            store = SamplingHistoryStore(
                circuit_path,
                "demo",
                "single_ended_opamp",
                ["W", "L"],
                ["Gain", "Power"],
            )
            run_id = store.create_run(2, 1, {"random": 2}, {"seed": 42})
            designs = np.asarray([[1.0, 0.5], [2.0, 0.5]])
            metrics = np.asarray([[60.0, 10.0], [np.nan, np.nan]])
            failures = [{"sample_index": 1, "error_type": "TestFailure", "error": "failed"}]
            store.write_batch(run_id, designs, metrics, ["random", "random"], failures)
            store.mark_run_completed(run_id, 1)
            store.export_csv()

            with store.design_csv_path.open("r", encoding="utf-8") as file:
                design_rows = list(csv.reader(file))
            with store.metrics_csv_path.open("r", encoding="utf-8") as file:
                metric_rows = list(csv.reader(file))
            self.assertEqual(len(design_rows), 3)
            self.assertEqual(len(metric_rows), 3)
            self.assertIn("nan", metric_rows[2][0].lower())
            keys = [store.design_key(row) for row in designs]
            self.assertEqual(store.find_existing_keys(keys), set(keys))

            with sqlite3.connect(store.database_path) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM samples").fetchone()[0], 2)

    def test_legacy_csv_is_migrated_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            circuit_path = Path(temporary_directory)
            (circuit_path / "design_parameters.csv").write_text(
                "W,L\n1.0,0.5\n2.0,0.5\n", encoding="utf-8"
            )
            (circuit_path / "metrics.csv").write_text(
                "Gain,Power\n60.0,10.0\n55.0,12.0\n", encoding="utf-8"
            )
            store = SamplingHistoryStore(
                circuit_path,
                "demo",
                "single_ended_opamp",
                ["W", "L"],
                ["Gain", "Power"],
            )
            with sqlite3.connect(store.database_path) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM samples").fetchone()[0], 2)
            second_store = SamplingHistoryStore(
                circuit_path,
                "demo",
                "single_ended_opamp",
                ["W", "L"],
                ["Gain", "Power"],
            )
            with sqlite3.connect(second_store.database_path) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM samples").fetchone()[0], 2)


class ControllerIntegrationTest(unittest.TestCase):
    def _write_circuit(self, source_path: Path) -> None:
        source_path.mkdir()
        (source_path / "demo_params.sp").write_text(
            ".param WN=2\n.param LN=0.5\n",
            encoding="utf-8",
        )
        (source_path / "demo.sp").write_text(
            '.include "demo_params.sp"\n'
            ".subckt DUT VINP VINN VOUT VDD VSS IBIAS\n"
            "XMN VOUT VINP VSS VSS sky130_fd_pr__nfet_01v8 W={WN} L={LN}\n"
            ".ends DUT\n",
            encoding="utf-8",
        )

    def _write_conditions(self, condition_path: Path) -> None:
        condition_path.mkdir()
        condition = {
            "PDK_PATH": "/tmp/fake_pdk",
            "CORNER": "tt",
            "TEMP": 27,
            "VDD": 1.8,
            "VSS": 0.0,
            "VCM": 0.9,
            "IBIAS": "10u",
            "CL": "1p",
            "AC_POINTS_PER_DEC": 10,
            "AC_START": 1,
            "AC_STOP": "1G",
            "GAIN_MEASURE_FREQ": 1,
            "OUTPUT_PATH": "ac_response.txt",
        }
        (condition_path / "ac_condition.json").write_text(
            json.dumps(condition), encoding="utf-8"
        )

    def test_controller_samples_twice_without_history_duplicates(self) -> None:
        fake_ngspice = Path(__file__).with_name("fake_ngspice.py").resolve()
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_path = root / "source"
            target_path = root / "history"
            condition_path = root / "conditions"
            self._write_circuit(source_path)
            self._write_conditions(condition_path)

            controller = Sampling_Controller(
                src_path=source_path,
                circuit_name="demo",
                circuit_type="single_ended_opamp",
                target_path=target_path,
                metrics=["DC_GAIN", "UGF"],
                simulation_condition_path=condition_path,
                seed=42,
                log_level=logging.DEBUG,
                console_log=False,
                ngspice_command=str(fake_ngspice),
            )
            try:
                first_result = controller.sample(12, 2)
                second_result = controller.sample(12, 2)
            finally:
                controller.close()

            self.assertTrue(first_result.success)
            self.assertTrue(second_result.success)
            self.assertFalse(source_path.exists())
            self.assertEqual(first_result.target_path, target_path / "demo")

            with sqlite3.connect(first_result.database_path) as connection:
                sample_count = connection.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
                distinct_count = connection.execute(
                    "SELECT COUNT(DISTINCT design_key) FROM samples"
                ).fetchone()[0]
            self.assertEqual(sample_count, 24)
            self.assertEqual(distinct_count, 24)

            log_content = (target_path / "demo" / "logs" / "sampling.log").read_text(
                encoding="utf-8"
            )
            self.assertIn("sampler.random", log_content)
            self.assertIn("simulator", log_content)
            self.assertIn("history", log_content)


if __name__ == "__main__":
    unittest.main()
