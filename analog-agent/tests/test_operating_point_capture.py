"""DC capture must preserve physics, sample pairing, access and cache identity."""
from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from src.circuit_ir import parse_circuit, resolve_circuit
from src.sample_optimize.advanced.context import (
    LEGACY_OP_IMPLEMENTATION, bind_context, digest, model_identity, resolve_mos_primitives,
)
from src.sample_optimize.advanced.operating_point import run_operating_point
from src.sample_optimize.history_store import SamplingHistoryStore
from src.sample_optimize.point_simulation import PointSimulator
from src.sample_optimize.simulating import SimulationBatchResult, Simulator
from src.utils.spice_parser import read_parameter_names
from test_advanced_sampling import bare_controller

PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "Sample_Optimizer_Circuit/5t_ota"
CONDITION = {"PDK_PATH": "test.lib", "CORNER": "tt", "TEMP": 27, "VDD": 1.8, "VSS": 0., "VCM": .9,
             "MOS_PRIMITIVES": {"sky130_fd_pr__nfet_01v8": "m0", "sky130_fd_pr__pfet_01v8": "m0"}}


def observed(gm=1e-5):
    return {"schema_version": 2, "status": "complete", "converged": True, "feasible": True,
            "condition": {k: v for k, v in CONDITION.items() if k != "MOS_PRIMITIVES"},
            "bias_topology": "unity_gain_follower", "node_voltages_v": {"vout": .9},
            "reasons": [], "missing_fields": {}, "vout_v": .9, "follower_error_v": 0.,
            "devices": {
                "XN": {"device_type": "NMOS", "model_name": "n", "id": 1e-6, "gm": gm,
                       "vgs_raw_v": .7, "vgs_v": .7, "cgs": -2e-15, "w_um": 5., "l_um": .5, "multiplicity": 3.},
                "XP": {"device_type": "PMOS", "model_name": "p", "id": 1e-6, "gm": gm*2,
                       "vgs_raw_v": -.8, "vgs_v": .8, "cgs": -4e-15, "w_um": 7., "l_um": .6, "multiplicity": 3.},
            }}


def make_store(path):
    return SamplingHistoryStore(path, "demo", "single_ended_opamp", ["W"], ["Gain", "UGF"], journal_mode="DELETE")


def test_wide_csv_sql_pairing_partial_metrics_and_atomic_rollback(tmp_path):
    store = make_store(tmp_path)
    run = store.create_run(3, 2, {"random": 3}, {})
    ids = store.write_batch(run, [[2.], [3.]], [[60., 1e6], [50., np.nan]], ["random"]*2, [],
                            observations=[observed(2e-5), observed(3e-5)])
    store.write_batch(run, [[4.]], [[40., 2e6]], ["random"], [])
    store.export_csv()
    with store.design_csv_path.open() as file:
        designs = list(csv.DictReader(file))
    with store.metrics_csv_path.open() as file:
        metrics = list(csv.DictReader(file))
    with store.operating_points_csv_path.open() as file:
        ops = list(csv.DictReader(file))
    assert list(designs[0]) == ["W"] and list(metrics[0]) == ["Gain", "UGF"]
    assert len(designs) == len(metrics) == len(ops) == 3
    assert [int(row["csv_row_index"]) for row in ops] == [0, 1, 2]
    assert [int(row["sample_id"]) for row in ops[:2]] == ids
    for design, op in zip(designs[:2], ops[:2]):
        assert float(op["XN.gm_s"]) == pytest.approx(float(design["W"])*1e-5)
        assert op["op_status"] == "complete" and float(op["op_temperature_c"]) == 27
        assert float(op["XP.vgs_v"]) == -.8 and float(op["XP.vgs_normalized_v"]) == .8
        assert float(op["XP.cgs_f"]) == -4e-15
    assert metrics[1]["UGF"] == "nan" and ops[1]["op_converged"] == "1"
    assert ops[2]["op_status"] == "not_recorded" and ops[2]["XN.gm_s"] == "nan"
    with pytest.raises(RuntimeError, match="重复"):
        store.write_batch(run, [[5.], [2.]], [[1., 1.], [1., 1.]], ["random"]*2, [],
                          observations=[observed(), observed()])
    with store._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM dc_operating_points").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM dc_device_operating_points").fetchone()[0] == 4


def test_old_observations_migrate_without_simulation_or_invented_fields(tmp_path):
    store = make_store(tmp_path)
    run = store.create_run(2, 1, {"random": 2}, {})
    store.write_batch(run, [[1.], [2.]], [[1., 1.], [2., 2.]], ["random"]*2, [],
        observations=[{"converged": True, "feasible": True, "devices": {"XP": {"gm": 2e-5, "vgs_v": .8}}}, {}])
    with store._connect() as connection:
        connection.execute("DROP TABLE dc_device_operating_points")
        connection.execute("DROP TABLE dc_operating_points")
    migrated = make_store(tmp_path)
    result = migrated.fetch_operating_point(1)
    assert result["status"] == "legacy_partial"
    assert result["devices"]["XP"]["gm_s"] == 2e-5
    assert result["devices"]["XP"]["vgs_normalized_v"] == .8
    assert result["devices"]["XP"]["vgs_v"] is None
    assert result["devices"]["XP"]["cgs_f"] is None
    assert migrated.fetch_operating_point(2)["status"] == "not_recorded"
    make_store(tmp_path)  # Migration is idempotent.
    with migrated._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM dc_device_operating_points").fetchone()[0] == 1


def test_cached_point_reuses_full_op_and_inherits_access_partition(tmp_path):
    class Simulator:
        calls = 0
        def simulate_batch(self, **kwargs):
            self.calls += 1
            return SimulationBatchResult(np.asarray([[60., np.nan]]), (), (observed(),))
    store = make_store(tmp_path)
    simulator = Simulator()
    api = PointSimulator(history_store=store, simulator=simulator, circuit_path=tmp_path,
                         parameter_names=["W"], bounds=[(1., 5., 1.)])
    first = api.simulate({"W": 2.}, source="agent")
    cached = api.simulate({"W": 2.}, source="probe")
    assert simulator.calls == 1 and cached.cache_hit
    assert cached.sample_id == first.sample_id and cached.operating_point == first.operating_point
    assert cached.operating_point["devices"]["XP"]["vgs_v"] == -.8
    hidden = api.simulate({"W": 3.}, source="validation", access_level="hidden_eval")
    assert store.fetch_operating_point(hidden.sample_id) is None
    assert store.fetch_operating_point(hidden.sample_id, access_levels=["hidden_eval"])["devices"]
    with pytest.raises(PermissionError):
        api.simulate({"W": 3.}, source="probe")
    assert simulator.calls == 2


def test_optional_field_missing_retains_signs_sizes_and_feasibility(monkeypatch, tmp_path):
    ir = resolve_circuit(parse_circuit(SOURCE / "5t_ota.sp"), {"M_FACTOR": 3.})
    def spice(args, *, cwd, **kwargs):
        deck = (Path(cwd) / args[-1]).read_text()
        voltages = {"out": .9, "inp": .9, "vdd": 1.8, "vss": 0., "xdut.n_bias": .6, "xdut.ntail": .2, "xdut.n1": .9}
        text = []
        for name, node in re.findall(r"let (n\d+) = v\(([^)]+)\)", deck):
            text.append(f"{name} = {voltages[node]}")
        values = {"id": 2e-6, "gm": 1e-5, "gds": 1e-7, "gmbs": 2e-6, "vth": .5, "vdsat": .1,
                  "vgs": .7, "vds": .9, "vbs": 0., "cgs": -2e-15}
        for name, field in re.findall(r"let (d\d+_\w+) = @[^\[]+\[(\w+)\]", deck):
            if field != "cgb":
                text.append(f"{name} = {values.get(field, 1e-15)}")
        (Path(cwd) / "operating_point.log").write_text("\n".join(text))
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr("src.sample_optimize.advanced.operating_point.subprocess.run", spice)
    result = run_operating_point(tmp_path, ir, CONDITION, {}, (), "unused", 1)
    assert result["converged"] and result["feasible"] and result["status"] == "partial"
    assert result["missing_fields"]["XMP_OUT"] == ["cgb"]
    assert result["devices"]["XMP_OUT"]["vgs_raw_v"] == -.9
    assert result["devices"]["XMP_OUT"]["vgs_v"] == .9
    assert result["devices"]["XMP_OUT"]["cgs"] == -2e-15
    assert result["devices"]["XMTAIL"]["multiplicity"] == 6.
    assert result["devices"]["XMBIAS"]["multiplicity"] == 1.


def test_op_timeout_retains_all_mos_and_records_failure(monkeypatch, tmp_path):
    ir = parse_circuit(SOURCE / "5t_ota.sp")
    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired("ngspice", 1)
    monkeypatch.setattr("src.sample_optimize.advanced.operating_point.subprocess.run", fail)
    result = run_operating_point(tmp_path, ir, CONDITION, {}, (), "unused", 1)
    assert not result["converged"] and result["status"] == "failed"
    assert "TimeoutExpired" in result["reasons"][0]
    assert len(result["devices"]) == 6 and result["devices"]["XMBIAS"]["w_um"] == 8.
    store = make_store(tmp_path / "history")
    run = store.create_run(1, 1, {"random": 1}, {})
    store.write_batch(run, [[1.]], [[1., np.nan]], ["random"], [], observations=[result])
    store.export_csv()
    with store.operating_points_csv_path.open() as file:
        row = next(csv.DictReader(file))
    assert row["op_status"] == "failed" and row["XMBIAS.gm_s"] == "nan"


def test_only_known_field_upgrade_reuses_verified_context(tmp_path):
    store = make_store(tmp_path)
    old = {"op_implementation": LEGACY_OP_IMPLEMENTATION, "conditions": {"power": {"VCM": .9}}, "models": "original"}
    bind_context(store.database_path, old)
    current = {**old, "op_implementation": "new-field-collector", "op_schema_version": 2}
    assert bind_context(store.database_path, current) == digest(current)
    with pytest.raises(ValueError, match="context changed"):
        bind_context(store.database_path, {**current, "conditions": {"power": {"VCM": .8}}})
    another = make_store(tmp_path / "unknown")
    bind_context(another.database_path, {**old, "op_implementation": "unrecognized"})
    with pytest.raises(ValueError, match="context changed"):
        bind_context(another.database_path, current)


def test_large_wide_table_can_defer_csv_until_exit(tmp_path):
    controller = bare_controller(tmp_path)
    controller.csv_export_interval_batches = 0
    with patch.object(controller.history_store, "export_csv", wraps=controller.history_store.export_csv) as export:
        controller.sample(12, 2)
    assert export.call_count == 1
    for file in (controller.history_store.design_csv_path, controller.history_store.metrics_csv_path,
                 controller.history_store.operating_points_csv_path):
        with file.open() as stream:
            assert len(list(csv.DictReader(stream))) == 12


def test_real_legacy_save_reuses_only_matching_snapshot(tmp_path):
    command, pdk = os.environ.get("ANALOG_TEST_NGSPICE"), os.environ.get("ANALOG_TEST_SKY130_LIBRARY")
    if not command or not pdk:
        pytest.skip("real ngspice and Sky130 TT library required")
    conditions = tmp_path / "conditions"
    conditions.mkdir()
    (conditions / "power_condition.json").write_text(json.dumps({
        **{k: v for k, v in CONDITION.items() if k != "MOS_PRIMITIVES"},
        "PDK_PATH": pdk, "OUTPUT_PATH": "power_result.txt",
    }))
    names = read_parameter_names(SOURCE / "5t_ota_params.sp")
    defaults = parse_circuit(SOURCE / "5t_ota.sp").parameter_defaults
    design = np.asarray([[defaults[name] for name in names]])
    simulator = Simulator(["POWER"], "single_ended_opamp", "5t_ota", simulate_condition_path=conditions,
                          output_path=tmp_path / "history", ngspice_command=command)
    with patch("src.sample_optimize.simulating.subprocess.run", wraps=subprocess.run) as calls:
        metrics = simulator.simulate(SOURCE, 1, design, True)
        simulator.write_simulate_result(design, metrics, names)
        other = design.copy()
        other[0, names.index("WBIAS")] += 1.
        simulator.write_simulate_result(other, metrics, names)
    assert calls.call_count == 2  # One OP and one power call; persistence never re-runs SPICE.
    store = SamplingHistoryStore(simulator.circuit_result_path, "5t_ota", "single_ended_opamp", names, simulator.metrics)
    assert len(store.fetch_operating_point(1)["devices"]) == 6
    assert store.fetch_operating_point(1)["status"] == "complete"
    assert store.fetch_operating_point(2)["status"] == "not_recorded"


@pytest.mark.parametrize("name", ["5t_ota", "Opamp0", "Opamp1", "two_stage_opamp_otaf", "two_stage_folded_opamp"])
def test_real_sky130_capture_all_mos_and_capacitances(tmp_path, name):
    command, pdk = os.environ.get("ANALOG_TEST_NGSPICE"), os.environ.get("ANALOG_TEST_SKY130_LIBRARY")
    if not command or not pdk:
        pytest.skip("Set ANALOG_TEST_NGSPICE and ANALOG_TEST_SKY130_LIBRARY for real Sky130 smoke tests")
    source = PROJECT / "Sample_Optimizer_Circuit" / name
    workspace = tmp_path / name
    shutil.copytree(source, workspace)
    ir = parse_circuit(workspace / f"{name}.sp")
    condition = {**CONDITION, "PDK_PATH": pdk, "MOS_PRIMITIVES": resolve_mos_primitives(model_identity([pdk]))}
    result = run_operating_point(workspace, ir, condition, {}, (), command, 30)
    assert result["status"] == "complete" and result["converged"]
    assert len(result["devices"]) == sum(d.device_type.value in {"NMOS", "PMOS"} for d in ir.devices)
    for fields in result["devices"].values():
        assert fields["gm"] is not None and fields["gmbs"] is not None and fields["vth"] is not None
        assert fields["cgs"] is not None and fields["capbs"] is not None
        assert fields["vgs_raw_v"] == pytest.approx(fields["vg_v"]-fields["vs_v"])
        assert fields["multiplicity"] >= 1 and fields["w_um"] > 0
