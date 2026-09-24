from __future__ import annotations

import csv
import json
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

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
from src.utils import analyze_parameter_usage, parse_spice_instances, read_parameter_names, resolve_parameter_bounds, rewrite_parameter_values  # noqa: E402


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

    def test_current_source_is_classified_from_dc_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "circuit.sp"
            path.write_text(
                "* Independent current sources inside the DUT\n"
                ".subckt DUT VINP VINN VOUT VDD VSS\n"
                "IBIAS VDD BIAS DC {IBIAS_A}\n"
                "IREF VDD REF {IREF_A}\n"
                ".ends DUT\n",
                encoding="utf-8",
            )
            instances = parse_spice_instances(path)
            self.assertEqual([instance.positional_value for instance in instances], ["{IBIAS_A}", "{IREF_A}"])
            specs = analyze_parameter_usage(path, ["IBIAS_A", "IREF_A"])
            self.assertEqual([(spec.device_type, spec.control_parameter) for spec in specs],
                             [("CURRENT_SOURCE", "I"), ("CURRENT_SOURCE", "I")])

    def test_5t_ota_uses_one_shared_m_for_nmos_and_pmos(self) -> None:
        example = ANALOG_AGENT_PATH / "Sample_Optimizer_Circuit" / "5t_ota"
        names = read_parameter_names(example / "5t_ota_params.sp")
        specs = analyze_parameter_usage(example / "5t_ota.sp", names)
        m_specs = [spec for spec in specs if spec.control_parameter == "M"]
        self.assertEqual(len(m_specs), 1)
        self.assertEqual(m_specs[0].parameter_name, "M_FACTOR")
        self.assertEqual(m_specs[0].device_type, "MOS")
        self.assertEqual(len(m_specs[0].usages), 5)
        self.assertEqual(resolve_parameter_bounds(m_specs, {"M": (1, 10, 1)}), [(1.0, 10.0, 1.0)])

    def test_m_bounds_must_use_positive_integer_grid_even_for_overrides(self) -> None:
        example = ANALOG_AGENT_PATH / "Sample_Optimizer_Circuit" / "two_stage_opamp_otaf"
        names = read_parameter_names(example / "two_stage_opamp_otaf_params.sp")
        specs = analyze_parameter_usage(example / "two_stage_opamp_otaf.sp", names)
        m_specs = [spec for spec in specs if spec.control_parameter == "M"]
        self.assertEqual({spec.parameter_name for spec in m_specs},
                         {"M1_FACTOR", "M2_FACTOR"})
        self.assertTrue(all(spec.device_type == "MOS" for spec in m_specs))
        self.assertEqual(resolve_parameter_bounds(m_specs, {"M": (1, 10, 1)}), [(1.0, 10.0, 1.0)] * 2)
        with self.assertRaisesRegex(ValueError, "正整数网格"):
            resolve_parameter_bounds(m_specs, {"M": (1, 10, 1)}, parameter_overrides={"M1_FACTOR": (1, 10, 0.5)})

    def test_two_stage_folded_opamp_parameter_mapping(self) -> None:
        example = ANALOG_AGENT_PATH / "Sample_Optimizer_Circuit" / "two_stage_folded_opamp"
        names = read_parameter_names(example / "two_stage_folded_opamp_params.sp")
        specs = analyze_parameter_usage(example / "two_stage_folded_opamp.sp", names)
        self.assertEqual(len(names), 23)
        self.assertEqual(len(specs), 23)
        m_specs = {spec.parameter_name: spec for spec in specs if spec.control_parameter == "M"}
        self.assertEqual(set(m_specs), {"M1_FACTOR", "M2_FACTOR"})
        self.assertTrue(all(spec.device_type == "MOS" for spec in m_specs.values()))
        self.assertEqual(len(m_specs["M1_FACTOR"].usages), 13)
        self.assertEqual(len(m_specs["M2_FACTOR"].usages), 2)
        self.assertEqual(
            resolve_parameter_bounds(list(m_specs.values()), {"M": (1, 10, 1)}),
            [(1.0, 10.0, 1.0)] * 2,
        )

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
            ".param WN=2\n.param LN=0.5\n.param IBIAS_A=10e-6\n",
            encoding="utf-8",
        )
        (source_path / "demo.sp").write_text(
            '.include "demo_params.sp"\n'
            ".subckt DUT VINP VINN VOUT VDD VSS\n"
            "IBIAS_SRC VDD BIAS DC {IBIAS_A}\n"
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

    def test_circuit_metadata_on_move_and_history_reuse(self) -> None:
        fake_ngspice = Path(__file__).with_name("fake_ngspice.py").resolve()
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_path = root / "source"
            target_path = root / "history"
            condition_path = root / "conditions"
            self._write_circuit(source_path)
            self._write_conditions(condition_path)
            kwargs = dict(
                src_path=source_path,
                circuit_name="demo",
                circuit_type="single_ended_opamp",
                target_path=target_path,
                metrics=["DC_GAIN", "UGF"],
                simulation_condition_path=condition_path,
                ngspice_command=str(fake_ngspice),
                console_log=False,
            )

            with Sampling_Controller(**kwargs) as controller:
                self.assertFalse(controller.has_history)
            metadata_path = target_path / "demo" / "circuit_metadata.json"
            expected = {"circuit_name": "demo", "circuit_type": "single_ended_opamp"}
            self.assertEqual(json.loads(metadata_path.read_text(encoding="utf-8")), expected)

            metadata_path.unlink()
            with Sampling_Controller(**kwargs) as controller:
                self.assertTrue(controller.has_history)
            self.assertEqual(json.loads(metadata_path.read_text(encoding="utf-8")), expected)

            metadata_path.write_text(json.dumps({**expected, "circuit_type": "other"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "电路元数据与当前配置不一致"):
                Sampling_Controller(**kwargs)

    def test_integrated_bias_sampling_and_all_testbenches(self) -> None:
        fake_ngspice = Path(__file__).with_name("fake_ngspice.py").resolve()
        example = ANALOG_AGENT_PATH / "Sample_Optimizer_Circuit" / "5t_ota"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "5t_ota"
            shutil.copytree(example, source)
            with Sampling_Controller(
                src_path=source,
                circuit_name="5t_ota",
                circuit_type="single_ended_opamp",
                target_path=root / "history",
                metrics=["DC_GAIN", "UGF", "PM", "POWER", "CMRR", "P_PSRR", "N_PSRR", "P_SR", "N_SR"],
                ngspice_command=str(fake_ngspice),
                keep_workspace=True,
                console_log=False,
            ) as controller:
                self.assertEqual(controller.parameter_name_lst[0], "IBIAS_A")
                self.assertEqual(controller.parameter_spec_lst[0].device_type, "CURRENT_SOURCE")
                self.assertEqual(controller.parameter_spec_lst[0].control_parameter, "I")
                self.assertEqual(controller.bounds[0], (1e-7, 20e-6, 1e-7))
                m_index = controller.parameter_name_lst.index("M_FACTOR")
                self.assertEqual(controller.parameter_spec_lst[m_index].device_type, "MOS")
                self.assertEqual(controller.parameter_spec_lst[m_index].control_parameter, "M")
                self.assertEqual(controller.bounds[m_index], (1.0, 10.0, 1.0))
                result = controller.sample(n_points=6, n_workers=2)
                self.assertTrue(result.success)
                self.assertEqual(result.failed_num, 0)
                with result.design_csv_path.open(encoding="utf-8") as file:
                    rows = list(csv.reader(file))
                    self.assertEqual(rows[0][0], "IBIAS_A")
                    bias_values = [float(row[0]) for row in rows[1:]]
                    self.assertEqual(len(bias_values), 6)
                    self.assertTrue(all(1e-7 <= value <= 20e-6 for value in bias_values))

                workspaces = list((result.target_path / ".workspaces").glob("run_*/workspace_*"))
                self.assertEqual(len(workspaces), 2)
                for workspace in workspaces:
                    params = (workspace / "5t_ota_params.sp").read_text(encoding="utf-8")
                    self.assertIn(".param IBIAS_A=", params)
                    rewritten_bias = float(next(line.split("=", 1)[1] for line in params.splitlines()
                                               if line.startswith(".param IBIAS_A=")))
                    self.assertTrue(any(np.isclose(rewritten_bias, value, rtol=1e-12, atol=0)
                                        for value in bias_values))
                    rewritten_m = float(next(line.split("=", 1)[1] for line in params.splitlines()
                                             if line.startswith(".param M_FACTOR=")))
                    self.assertTrue(rewritten_m.is_integer() and 1 <= rewritten_m <= 10)
                    circuit = (workspace / "5t_ota.sp").read_text(encoding="utf-8")
                    self.assertIn("IBIAS_SRC VDD N_BIAS DC {IBIAS_A}", circuit)
                    self.assertIn("m={2*M_FACTOR}", circuit)
                    self.assertEqual(circuit.count("m={M_FACTOR}"), 4)
                    for testbench in ["ac", "stability", "power", "cmrr", "psrr", "slew"]:
                        text = (workspace / f"tb_{testbench}.cir").read_text(encoding="utf-8")
                        self.assertNotIn("{{IBIAS}}", text)
                        self.assertNotIn("IBIAS_SRC", text)

    def test_two_stage_opamp_otaf_samples_integer_m_and_rewrites_workspace(self) -> None:
        fake_ngspice = Path(__file__).with_name("fake_ngspice.py").resolve()
        example = ANALOG_AGENT_PATH / "Sample_Optimizer_Circuit" / "two_stage_opamp_otaf"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "two_stage_opamp_otaf"
            shutil.copytree(example, source)
            with Sampling_Controller(
                src_path=source,
                circuit_name="two_stage_opamp_otaf",
                circuit_type="single_ended_opamp",
                target_path=root / "history",
                metrics=["DC_GAIN", "UGF", "PM", "POWER"],
                ngspice_command=str(fake_ngspice),
                keep_workspace=True,
                console_log=False,
            ) as controller:
                m_indices = [index for index, spec in enumerate(controller.parameter_spec_lst)
                             if spec.control_parameter == "M"]
                self.assertEqual(len(m_indices), 2)
                self.assertTrue(all(controller.bounds[index] == (1.0, 10.0, 1.0) for index in m_indices))
                result = controller.sample(n_points=6, n_workers=2, continue_on_error=False)
                self.assertTrue(result.success)
                with result.design_csv_path.open(encoding="utf-8") as file:
                    rows = list(csv.DictReader(file))
                self.assertEqual(len(rows), 6)
                for row in rows:
                    for index in m_indices:
                        m_value = float(row[controller.parameter_name_lst[index]])
                        self.assertTrue(m_value.is_integer() and 1 <= m_value <= 10)

                workspaces = list((result.target_path / ".workspaces").glob("run_*/workspace_*"))
                self.assertEqual(len(workspaces), 2)
                for workspace in workspaces:
                    params_path = workspace / "two_stage_opamp_otaf_params.sp"
                    params = params_path.read_text(encoding="utf-8")
                    for index in m_indices:
                        name = controller.parameter_name_lst[index]
                        value = next(float(line.split("=", 1)[1]) for line in params.splitlines()
                                     if line.startswith(f".param {name}="))
                        self.assertTrue(value.is_integer() and 1 <= value <= 10)
                    circuit = (workspace / "two_stage_opamp_otaf.sp").read_text(encoding="utf-8")
                    self.assertIn("m={2*M1_FACTOR}", circuit)
                    self.assertEqual(circuit.count("m={M1_FACTOR}"), 4)
                    self.assertEqual(circuit.count("m={(2*M1_FACTOR)*M2_FACTOR}"), 2)

    def test_two_stage_folded_opamp_samples_integer_m_and_rewrites_workspace(self) -> None:
        fake_ngspice = Path(__file__).with_name("fake_ngspice.py").resolve()
        example = ANALOG_AGENT_PATH / "Sample_Optimizer_Circuit" / "two_stage_folded_opamp"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "two_stage_folded_opamp"
            shutil.copytree(example, source)
            with Sampling_Controller(
                src_path=source,
                circuit_name="two_stage_folded_opamp",
                circuit_type="single_ended_opamp",
                target_path=root / "history",
                metrics=["DC_GAIN", "UGF", "PM", "POWER"],
                ngspice_command=str(fake_ngspice),
                keep_workspace=True,
                console_log=False,
            ) as controller:
                self.assertEqual(len(controller.parameter_name_lst), 23)
                m_indices = [index for index, spec in enumerate(controller.parameter_spec_lst)
                             if spec.control_parameter == "M"]
                self.assertEqual(len(m_indices), 2)
                self.assertTrue(all(controller.bounds[index] == (1.0, 10.0, 1.0)
                                    for index in m_indices))
                result = controller.sample(n_points=6, n_workers=2, continue_on_error=False)
                self.assertTrue(result.success)

                with result.design_csv_path.open(encoding="utf-8") as file:
                    rows = list(csv.DictReader(file))
                self.assertEqual(len(rows), 6)
                for row in rows:
                    for index in m_indices:
                        value = float(row[controller.parameter_name_lst[index]])
                        self.assertTrue(value.is_integer() and 1 <= value <= 10)

                workspaces = list((result.target_path / ".workspaces").glob("run_*/workspace_*"))
                self.assertEqual(len(workspaces), 2)
                for workspace in workspaces:
                    circuit = (workspace / "two_stage_folded_opamp.sp").read_text(encoding="utf-8")
                    self.assertEqual(circuit.count("m={2*M1_FACTOR}"), 3)
                    self.assertEqual(circuit.count("m={M1_FACTOR}"), 8)
                    self.assertEqual(circuit.count("m={M1_FACTOR*M2_FACTOR}"), 2)

    def test_partial_metrics_preserve_available_values_and_store_missing_as_nan(self) -> None:
        fake_ngspice = Path(__file__).with_name("fake_ngspice.py").resolve()
        example = ANALOG_AGENT_PATH / "Sample_Optimizer_Circuit" / "5t_ota"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "5t_ota"
            shutil.copytree(example, source)
            with patch.dict(os.environ, {"ANALOG_FAKE_PARTIAL_METRICS": "1"}):
                with Sampling_Controller(
                    src_path=source,
                    circuit_name="5t_ota",
                    circuit_type="single_ended_opamp",
                    target_path=root / "history",
                    metrics=["DC_GAIN", "UGF", "PM", "CMRR", "P_PSRR", "N_PSRR", "P_SR", "N_SR", "POWER"],
                    ngspice_command=str(fake_ngspice),
                    console_log=False,
                ) as controller:
                    result = controller.sample(n_points=3, n_workers=1, continue_on_error=True)

            self.assertFalse(result.success)
            self.assertEqual(result.failed_num, 3)
            with result.metrics_csv_path.open(encoding="utf-8") as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(len(rows), 3)
            for row in rows:
                self.assertAlmostEqual(float(row["DC_Gain_dB"]), -59.62694)
                self.assertTrue(np.isnan(float(row["UGF_Hz"])))
                self.assertEqual(float(row["Phase_Margin_deg"]), 68.0)
                self.assertEqual(float(row["CMRR_dB"]), 92.0)
                self.assertEqual(float(row["PSRR_Plus_dB"]), 80.0)
                self.assertEqual(float(row["PSRR_Minus_dB"]), 76.0)
                self.assertEqual(float(row["Slew_Rise_V_us"]), 12.0)
                self.assertEqual(float(row["Slew_Fall_V_us"]), 10.0)
                self.assertEqual(float(row["Power_Quiescent_uW"]), 150.0)

            with sqlite3.connect(result.database_path) as connection:
                database_rows = connection.execute(
                    "SELECT metric_values_json, success, error_type FROM samples ORDER BY sample_index"
                ).fetchall()
            self.assertEqual(len(database_rows), 3)
            for metric_values_json, success, error_type in database_rows:
                metric_values = json.loads(metric_values_json)
                self.assertAlmostEqual(metric_values[0], -59.62694)
                self.assertIsNone(metric_values[1])
                self.assertEqual(success, 0)
                self.assertEqual(error_type, "PartialSimulationFailure")

            failure_records = [
                json.loads(line)
                for line in (result.target_path / "simulation_failures.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(failure_records), 3)
            self.assertTrue(all("UGF" in record["error"] for record in failure_records))

    def test_stale_external_bias_condition_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "demo"
            conditions = root / "conditions"
            self._write_circuit(source)
            self._write_conditions(conditions)
            path = conditions / "ac_condition.json"
            config = json.loads(path.read_text(encoding="utf-8"))
            config["IBIAS"] = "10u"
            path.write_text(json.dumps(config), encoding="utf-8")
            with Sampling_Controller(
                src_path=source, circuit_name="demo", circuit_type="single_ended_opamp",
                target_path=root / "history", metrics=["DC_GAIN"],
                simulation_condition_path=conditions, console_log=False,
            ) as controller:
                with self.assertRaisesRegex(ValueError, "不应定义 IBIAS"):
                    controller.sample(n_points=3, n_workers=1)


if __name__ == "__main__":
    unittest.main()
