"""Concurrency, incremental reads and CSV snapshots must preserve labels/RNG."""
from __future__ import annotations

import json
import logging
import re
import subprocess
from collections import Counter
from pathlib import Path
from threading import Event, Lock
from time import sleep
from types import MethodType, SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from src.circuit_ir import parse_circuit
from src.sample_optimize.advanced.config import DesignDomain, load_config
from src.sample_optimize.advanced.context import record_invocation
from src.sample_optimize.advanced.gmid import GmidSampler
from src.sample_optimize.advanced.lut import MosLUT
from src.sample_optimize.advanced.profiles import make_profile
from src.sample_optimize.history_store import SamplingHistoryStore
from src.sample_optimize.simulating import Simulator
from src.utils.spice_parser import read_parameter_names
from test_advanced_sampling import bare_controller, store

PROJECT = Path(__file__).resolve().parents[1]


class Characterizer:
    """An independent numeric oracle at the ngspice subprocess boundary."""
    def __init__(self):
        self.lock = Lock()
        self.active = self.peak = self.calls = 0
        self.fail = False

    def __call__(self, args, *, cwd, **kwargs):
        deck = (Path(cwd) / "lut.cir").read_text()
        length = float(re.search(r"L=([\d.]+)", deck)[1])
        body = abs(float(re.search(r"(?m)^VB B 0 ([\d.-]+)", deck)[1]))
        is_pmos = "sky130_fd_pr__pfet" in deck
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.calls += 1
        try:
            sleep(.03)  # Models waiting for an external ngspice process.
            if self.fail and not is_pmos and length == .2 and body == 0:
                raise subprocess.TimeoutExpired(args, 1)
            current = np.arange(1., 10.)*1e-6*(2 if is_pmos else 1) + length*1e-8 + body*1e-9
            np.savetxt(Path(cwd) / "table.txt", np.column_stack([np.arange(9), current, 10*current, np.full(9, .25)]))
            return subprocess.CompletedProcess(args, 0, "", "")
        finally:
            with self.lock:
                self.active -= 1


def lut_inputs(tmp_path):
    history = store(tmp_path / "history")
    run = history.create_run(1, 3, {"gmid": 1}, {})
    config = load_config()["gmid"]["lut"]
    config.update(vgs=[0, 1.8, .9], vds=[0, 1.8, .9], reverse_body_bias=[0, 1.8, 1.8], max_lengths=2)
    context = {"conditions": {"power": {"PDK_PATH": "unused.lib", "CORNER": "tt", "TEMP": 27, "VDD": 1.8, "VSS": 0}},
               "models": {}, "ngspice_version": "oracle", "initialization": "", "global_initialization": {},
               "spice_scripts": None,
               "mos_primitives": {"sky130_fd_pr__nfet_01v8": "m0", "sky130_fd_pr__pfet_01v8": "m0"}}
    domain = DesignDomain(["L"], [[.2, .4, .2]])
    args = (context, domain, [SimpleNamespace(length="L")], config, "unused", 1,
            str(history.database_path), run, logging.getLogger("test-lut"))
    return history, run, args


def test_parallel_lut_same_values_cache_and_budget(tmp_path):
    history, run, args = lut_inputs(tmp_path)
    oracle = Characterizer()
    with patch("src.sample_optimize.advanced.lut.subprocess.run", oracle):
        serial, serial_key = MosLUT.ensure(tmp_path / "serial", *args, workers=1)
        assert oracle.peak == 1
        parallel, key = MosLUT.ensure(tmp_path / "parallel", *args, workers=3)
    assert 2 <= oracle.peak <= 3
    assert oracle.calls == 16  # Both cold builds have eight slices.
    assert serial_key == key and serial.metadata == parallel.metadata
    for kind in ("NMOS", "PMOS"):
        assert np.array_equal(serial.functions[kind].values, parallel.functions[kind].values)
    assert parallel.lookup("NMOS", .2, 0, 0, 0)[0, 0] == pytest.approx(1.002e-6/10e-6)
    with patch("src.sample_optimize.advanced.lut.subprocess.run", side_effect=AssertionError("cache hit launched SPICE")):
        cached, cached_key = MosLUT.ensure(tmp_path / "parallel", *args, workers=8)
    assert key == cached_key
    assert np.array_equal(cached.functions["PMOS"].values, parallel.functions["PMOS"].values)
    with history._connect() as con:
        assert [tuple(r) for r in con.execute("SELECT category,status,COUNT(*) FROM spice_invocations WHERE run_id=? GROUP BY category,status", (run,))] == [("lut", "finished", 16)]


def test_parallel_lut_failure_resumes_only_missing_slices(tmp_path):
    history, run, args = lut_inputs(tmp_path)
    oracle = Characterizer()
    oracle.fail = True
    cache = tmp_path / "cache"
    with patch("src.sample_optimize.advanced.lut.subprocess.run", oracle):
        with pytest.raises(subprocess.TimeoutExpired):
            MosLUT.ensure(cache, *args, workers=3)
        assert not list(cache.glob("*.npz"))  # No incomplete final table.
        saved = list(cache.glob(".build-*/*.npy"))
        with history._connect() as con:
            statuses = Counter(r[0] for r in con.execute("SELECT status FROM spice_invocations"))
        assert statuses["failed"] == 1 and statuses["reserved"] == 0
        assert statuses["finished"] == len(saved)
        before = oracle.calls
        oracle.fail = False
        table, _ = MosLUT.ensure(cache, *args, workers=3)
    assert oracle.calls-before == 8-len(saved)
    assert oracle.calls == 9  # Eight successful slices plus the failed launch.
    assert np.isfinite(table.functions["NMOS"].values).all()


def test_incremental_history_never_rereads_labels_or_keeps_draft_keys(tmp_path):
    controller = bare_controller(tmp_path)
    for value, level, obs in [(1., "train_visible", {"feasible": True}),
                              (2., "hidden_eval", {"secret": "not an OP label"}),
                              (3., "final_blind", {"secret": "not an OP label"}),
                              (4., "train_visible", None)]:
        run = controller.history_store.create_run(1, 1, {"random": 1}, {}, access_level=level)
        controller.history_store.write_batch(run, [[value]], [[value]], ["random"], [], access_level=level,
                                            observations=None if obs is None else [obs])
    with patch("src.sample_optimize.advanced.controller.json.loads", wraps=json.loads) as read:
        designs, labels, excluded = controller._observed()
        assert designs == [[1.]] and labels == [True] and len(excluded) == 4
        assert read.call_count == 2  # One visible observation and one design.
        draft_key = controller.history_store.design_key([90.])
        excluded.add(draft_key)
        assert draft_key not in controller._observed()[2]
        assert read.call_count == 2
        run = controller.history_store.create_run(1, 1, {"random": 1}, {})
        controller.history_store.write_batch(run, [[5.]], [[5.]], ["random"], [], observations=[{"feasible": False}])
        read.reset_mock()
        designs, labels, excluded = controller._observed()
        assert designs == [[1.], [5.]] and labels == [True, False] and len(excluded) == 5
        assert read.call_count == 2


@pytest.mark.parametrize("mode,conditioned", [("nominal_lut", True), ("nominal_lut", False), ("coupled_lut", True)])
def test_gmid_curve_cache_preserves_points_rejections_and_rng(mode, conditioned):
    ir = parse_circuit(PROJECT / "Sample_Optimizer_Circuit/5t_ota/5t_ota.sp")
    names = list(ir.parameter_defaults)
    bounds = [[1e-7, 20e-6, 1e-7] if n == "IBIAS_A" else [1, 3, 1] if n == "M_FACTOR"
              else [.15, 1., .05] if n.startswith("L") else [1., 10., .1] for n in names]
    domain = DesignDomain(names, bounds)
    config = load_config()["gmid"]
    config.update(sizing_mode=mode, condition_lengths_on_width=conditioned)
    groups, _, targets = make_profile("5t_ota", ir, config)
    metadata = {"length_m": domain.axes[names.index("LIN")]*1e-6,
                "reverse_body_bias_v": np.linspace(0, 1.8, 7),
                "vgs_v": np.linspace(0, 1.8, 91), "vds_v": np.linspace(0, 1.8, 37)}
    length, body, vg, vd = np.meshgrid(*metadata.values(), indexing="ij")
    overdrive = np.maximum(vg-.35-.1*body, 0.)
    current = 50e-6/length*np.where(vd < overdrive, overdrive*vd-.5*vd**2, .5*overdrive**2)
    gm = 50e-6/length*np.minimum(overdrive, vd)
    values = np.stack([current, gm, overdrive], axis=-1)
    lut = MosLUT(metadata, {"NMOS": values, "PMOS": values})

    class UncachedSampler(GmidSampler):
        def _initial_curve(self, kind, length, diode, supply):
            vg = self.lut.axes[2]
            values = self.lut.lookup(kind, length, 0., vg, vg if diode else min(.9, supply))
            return values, values[:, 1]/np.maximum(values[:, 0], 1e-30)
        def _length_table(self, kind, parameter, supply):
            axis = self.domain.axes[self.domain.names.index(parameter)]
            vg = self.lut.axes[2]
            values = self.lut.lookup(kind, axis[:, None], 0., vg[None, :], min(.9, supply))
            return values, values[..., 1]/np.maximum(values[..., 0], 1e-30)

    args = (ir, domain, groups, targets, lut, {"VDD": 1.8, "VSS": 0, "VCM": .9}, config)
    uncached, cached = UncachedSampler(*args), GmidSampler(*args)
    before_rng, after_rng = np.random.default_rng(9), np.random.default_rng(9)
    with patch.object(lut, "lookup", wraps=lut.lookup) as lookup:
        reference = [uncached.propose(before_rng) for _ in range(12)]
        old_calls = lookup.call_count
        lookup.reset_mock()
        actual = [cached.propose(after_rng) for _ in range(12)]
        assert lookup.call_count < old_calls
    assert before_rng.bit_generator.state == after_rng.bit_generator.state
    for (point, info), (expected, original_info) in zip(actual, reference):
        assert (point is None) == (expected is None)
        if point is not None:
            assert np.array_equal(point, expected)
        assert info == original_info


def full_history(self):
    """The pre-optimization algorithm, for a same-seed comparison."""
    with self.history_store._connect() as con:
        rows = con.execute("SELECT design_values_json,observation_json FROM samples WHERE access_level='train_visible' AND observation_json IS NOT NULL ORDER BY sample_id").fetchall()
        keys = {r[0] for r in con.execute("SELECT design_key FROM samples")}
    return [json.loads(r[0]) for r in rows], [bool(json.loads(r[1])["feasible"]) for r in rows], keys


def test_csv_interval_and_incremental_reads_preserve_proposals_and_final_files(tmp_path):
    reference = bare_controller(tmp_path / "reference")
    reference._observed = MethodType(full_history, reference)
    reference.csv_export_interval_batches = 1
    optimized = bare_controller(tmp_path / "optimized")
    with patch.object(reference.history_store, "export_csv", wraps=reference.history_store.export_csv) as old_exports:
        reference.sample(28, 1)
    with patch.object(optimized.history_store, "export_csv", wraps=optimized.history_store.export_csv) as new_exports:
        result = optimized.sample(28, 8)
    assert old_exports.call_count == 16
    assert new_exports.call_count == 2  # Batch ten and final, not sixteen full rewrites.
    for name in ("design_parameters.csv", "metrics.csv"):
        assert (reference.src_path / name).read_bytes() == (optimized.src_path / name).read_bytes()
    def saved(controller):
        with controller.history_store._connect() as con:
            return [tuple(r) for r in con.execute("SELECT design_key,sample_method,proposal_json,observation_json FROM samples ORDER BY sample_id")]
    assert saved(reference) == saved(optimized)
    assert result.timings_seconds["wall"] >= result.timings_seconds["simulation"] > 0


def test_exception_exports_committed_rows_with_deferred_csv(tmp_path):
    controller = bare_controller(tmp_path)
    simulate = controller.simulator.simulate_batch
    batches = 0
    def stop(*args, **kwargs):
        nonlocal batches
        batches += 1
        if batches == 3:
            raise KeyboardInterrupt("third batch not committed")
        return simulate(*args, **kwargs)
    with patch.object(controller.simulator, "simulate_batch", stop):
        with pytest.raises(KeyboardInterrupt):
            controller.sample(12, 2)
    assert len(controller.history_store.design_csv_path.read_text().splitlines()) == 5
    assert len(controller.history_store.metrics_csv_path.read_text().splitlines()) == 5
    controller.sample(12, 8, resume_run_id="latest")
    assert len(controller.history_store.design_csv_path.read_text().splitlines()) == 13


def test_dynamic_workers_keep_params_metrics_op_failures_and_ledger_paired(tmp_path):
    source = PROJECT / "Sample_Optimizer_Circuit/5t_ota"
    ir = parse_circuit(source / "5t_ota.sp")
    names = read_parameter_names(source / "5t_ota_params.sp")
    designs = np.asarray([[value if name == "WBIAS" else ir.parameter_defaults[name] for name in names]
                          for value in range(1, 7)])
    simulator = Simulator(["DC_GAIN", "UGF", "POWER"], "single_ended_opamp", "5t_ota", output_path=tmp_path)
    simulator.operating_point_config = {"circuit": ir, "condition": {}, "constraints": {}, "signal_devices": ()}
    history = SamplingHistoryStore(tmp_path / "history", "5t_ota", "single_ended_opamp", names, simulator.metrics, journal_mode="DELETE")
    run = history.create_run(6, 2, {"random": 6}, {})
    simulator.invocation_ledger = (str(history.database_path), run)
    release = Event()
    lock = Lock()
    fast_done = 0
    assignments = {}
    def parameter(workspace):
        return float(re.search(r"(?im)^\.param WBIAS=([^\s]+)", (Path(workspace)/"5t_ota_params.sp").read_text())[1])
    def op(workspace, circuit, condition, constraints, signal, command, timeout, ledger):
        value = parameter(workspace)
        expected = designs[int(value)-1]
        assert ledger[-1] == SamplingHistoryStore.design_key(expected)
        with lock:
            assignments.setdefault(Path(workspace).name, []).append(value)
        record_invocation(*ledger, "design", "operating_point", lambda: None)
        return {"feasible": value % 2 == 0, "design_value": value}
    def spice(args, *, cwd, **kwargs):
        nonlocal fast_done
        value = parameter(cwd)
        bench = Path(args[-1]).stem
        if bench == "tb_ac" and value == 1:
            assert release.wait(5), "an idle worker did not consume the next points"
        assert parameter(cwd) == value  # Workspace was never concurrently rewritten.
        if bench == "tb_ac":
            text = f"dc_gain_db = {40+value}\n" + ("Error: measure gbw_hz when(WHEN) : out of interval\n" if value == 3 else f"gbw_hz = {value*1e6}\n")
        else:
            text = f"power_uw = {value*100}\n"
            if value != 1:
                with lock:
                    fast_done += 1
                    if fast_done >= 3:
                        release.set()
        (Path(cwd)/args[args.index("-o")+1]).write_text(text)
        return subprocess.CompletedProcess(args, 0, "")
    with patch("src.sample_optimize.advanced.operating_point.run_operating_point", op), patch("src.sample_optimize.simulating.subprocess.run", spice):
        result = simulator.simulate_batch(source, 2, designs, continue_on_error=True)
    expected = np.column_stack([np.arange(41., 47.), np.arange(1., 7.)*1e6, np.arange(1., 7.)*100])
    expected[2, 1] = np.nan
    assert np.array_equal(result.metrics, expected, equal_nan=True)
    assert [o["design_value"] for o in result.observations] == list(range(1, 7))
    assert [f["sample_index"] for f in result.failure_records] == [2]
    assert result.failure_records[0]["design_parameters"] == designs[2].tolist()
    assert len(assignments) == 2 and max(map(len, assignments.values())) >= 3
    assert not hasattr(simulator, "_point_ledger")  # Mutable state was worker-local.
    with history._connect() as con:
        calls = Counter((r[0], r[1]) for r in con.execute("SELECT design_key,bench FROM spice_invocations WHERE status='finished'"))
    assert calls == Counter({(SamplingHistoryStore.design_key(row), bench): 1 for row in designs
                            for bench in ("operating_point", "ac", "power")})
