from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from src.circuit_ir import parse_circuit
from src.sample_optimize.advanced.bayesian import ConstrainedBayesianSampler
from src.sample_optimize.advanced.config import DesignDomain, METHODS, allocate, load_config
from src.sample_optimize.advanced.context import bind_context, record_invocation
from src.sample_optimize.advanced.controller import DatasetSamplingController
from src.sample_optimize.advanced.lut import MosLUT
from src.sample_optimize.advanced.gmid import GmidSampler
from src.sample_optimize.advanced.profiles import REFERENCES, make_profile
from src.sample_optimize.history_store import SamplingHistoryStore
from src.sample_optimize.simulating import SimulationBatchResult

PROJECT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", REFERENCES)
@pytest.mark.parametrize("override", [None, {}, {"default": False}])
def test_profiles_cover_shared_mos_groups(name, override):
    ir = parse_circuit(PROJECT / "Sample_Optimizer_Circuit" / name / f"{name}.sp")
    config = load_config()["gmid"]
    if override != {"default": False}:
        config["group_gmid_overrides"] = override
    groups, signal, targets = make_profile(name, ir, config)
    assert len({m for g in groups for m in g.members}) == sum(d.model is not None for d in ir.devices)
    assert all(np.allclose(t, np.arange(8., 20.01, .5)) for t in targets.values())
    if name == "Opamp0":
        assert "XNM6" not in signal and "XNM5" not in signal
    if name == "Opamp1":
        assert "XPM10" not in signal and "XNM10" not in signal


def test_partial_gmid_override_and_unknown_group():
    ir = parse_circuit(PROJECT / "Sample_Optimizer_Circuit/5t_ota/5t_ota.sp")
    cfg = load_config()["gmid"]
    cfg["group_gmid_overrides"] = {"5t_ota": {"WIN": [10, 15, 1]}}
    _, _, targets = make_profile("5t_ota", ir, cfg)
    assert targets["WIN"].tolist() == list(range(10, 16))
    assert targets["WBIAS"][0] == 8
    cfg["group_gmid_overrides"] = {"BAD_W": [8, 20, .5]}
    with pytest.raises(ValueError, match="Unknown gm/ID groups"):
        make_profile("5t_ota", ir, cfg)


def test_physical_grids_no_width_clipping_and_quota_rounding():
    domain = DesignDomain(["W", "L", "M"], [[1., 10., .1], [.15, 5., .05], [1, 50, 1]])
    values = domain.random(np.random.default_rng(1), 100)
    assert np.all(values[:, 2] == values[:, 2].round())
    assert domain.quantize_width("W", 3.17) == pytest.approx(3.2)
    with pytest.raises(ValueError):
        domain.quantize_width("W", 10.2)
    for count in [1, 7, 60000]:
        result = allocate(count, load_config()["method_weights"])
        assert sum(result.values()) == count
        assert max(result.values())-min(result.values()) <= 1


def test_bayesian_gp_reproducible_distinct_and_no_performance_objective():
    domain = DesignDomain(["W", "L"], [[1., 10., .1], [.15, 5., .05]])
    config = load_config()["bayesian"]
    config.update(warmup_points=4, candidate_pool_size=200, max_training_points=12)
    sampler = ConstrainedBayesianSampler(domain, config)
    train = domain.random(np.random.default_rng(4), 20)
    keys = {SamplingHistoryStore.design_key(row) for row in train}
    labels = (train[:, 0] > 5).tolist()
    result, meta = sampler.propose(np.random.default_rng(22), train, labels, keys, 8)
    same, _ = sampler.propose(np.random.default_rng(22), train, labels, keys, 8)
    assert np.array_equal(result, same)
    assert len({SamplingHistoryStore.design_key(row) for row in result}) == 8
    assert not any(SamplingHistoryStore.design_key(row) in keys for row in result)
    assert all(0 <= item["probability_feasible"] <= 1 for item in meta)
    assert len(result) == 8


def test_lut_si_units_body_axis_and_no_extrapolation():
    metadata = {"length_m": [1e-6, 2e-6], "reverse_body_bias_v": [0., 1.],
                "vgs_v": [0., 1.], "vds_v": [0., 1.]}
    values = np.ones((2, 2, 2, 2, 3))
    values[1] *= 2
    values[:, 1] *= 3
    table = MosLUT(metadata, {"NMOS": values, "PMOS": values})
    assert table.lookup("NMOS", 1., 0., .5, .5)[0, 0] == 1
    assert table.lookup("PMOS", 2., 1., .5, .5)[0, 0] == 6
    assert np.isnan(table.lookup("NMOS", 3., 0., .5, .5)).all()


def store(tmp_path):
    return SamplingHistoryStore(tmp_path, "demo", "single_ended_opamp", ["W"], ["gain"])


def test_atomic_batch_state_partial_metrics_offsets_and_launch_accounting(tmp_path):
    history = store(tmp_path)
    state = {"pending": True}
    run = history.create_run(2, 1, {"random": 2}, {}, initial_state=state)
    for value in (1., 2.):
        history.write_batch(run, [[value]], [[np.nan]], ["random"], [],
                            observations=[{"feasible": False, "reasons": ["follower_error"]}],
                            proposals=[{"gmid_targets": {}}], next_state={"completed": int(value)})
    with history._connect() as con:
        rows = con.execute("SELECT sample_index,metric_values_json,success FROM samples").fetchall()
        assert [row[0] for row in rows] == [0, 1]
        assert all(row[1] == "[null]" and row[2] == 0 for row in rows)
        assert json.loads(con.execute("SELECT state_json FROM sampling_state").fetchone()[0])["completed"] == 2
    def fail():
        raise TimeoutError()
    with pytest.raises(TimeoutError):
        record_invocation(history.database_path, run, "key", "design", "op", fail)
    with history._connect() as con:
        assert con.execute("SELECT status FROM spice_invocations").fetchone()[0] == "failed"


def test_context_rejects_unknown_legacy_and_changed_context(tmp_path):
    history = store(tmp_path)
    bind_context(history.database_path, {"models": "tt", "netlist": "one"})
    with pytest.raises(ValueError, match="context changed"):
        bind_context(history.database_path, {"models": "tt", "netlist": "two"})
    run = history.create_run(1, 1, {"random": 1}, {})
    history.write_batch(run, [[1]], [[1]], ["random"], [])
    with history._connect() as con:
        con.execute("DELETE FROM sampling_context")
    with pytest.raises(ValueError, match="no verified"):
        bind_context(history.database_path, {"models": "tt"})


def bare_controller(tmp_path):
    """Exercise the real scheduler/store; replace only the costly SPICE boundary."""
    controller = object.__new__(DatasetSamplingController)
    controller.history_store = store(tmp_path)
    controller.src_path = tmp_path
    controller.sampling_config = load_config()
    controller.sampling_config["method_weights"] = dict(zip(METHODS, [1, 1, 1, 0, 1]))
    controller.sampling_config["batch_size"] = 2
    controller.sampling_config["bayesian"].update(warmup_points=2, candidate_pool_size=64)
    controller.bounds = [(1., 100., 1.)]
    controller.parameter_name_lst = ["W"]
    controller.domain = DesignDomain(["W"], controller.bounds)
    controller.context_fingerprint = "verified"
    controller.sample_access_level = "train_visible"
    controller.seed = 3
    controller.logger = logging.getLogger("test-scheduler")
    class Simulator:
        metrics = ["gain"]
        def simulate_batch(self, source, workers, designs, continue_on_error):
            for row in designs:
                record_invocation(controller.history_store.database_path, self.invocation_ledger[1],
                                  SamplingHistoryStore.design_key(row), "design", "operating_point", lambda: None)
            return SimulationBatchResult(np.asarray(designs), (), tuple({"feasible": bool(row[0] > 50)} for row in designs))
    controller.simulator = Simulator()
    return controller


def test_resume_pending_batch_keeps_quota_rng_and_saved_points(tmp_path):
    uninterrupted = bare_controller(tmp_path / "reference")
    uninterrupted.sample(12, 1)
    interrupted = bare_controller(tmp_path / "interrupted")
    actual = interrupted.simulator.simulate_batch
    count = [0]
    def stop(source, workers, designs, continue_on_error):
        count[0] += 1
        result = actual(source, workers, designs, continue_on_error)
        if count[0] == 3:
            raise KeyboardInterrupt("completed SPICE, not persisted yet")
        return result
    interrupted.simulator.simulate_batch = stop
    with pytest.raises(KeyboardInterrupt):
        interrupted.sample(12, 1)
    interrupted.simulator.simulate_batch = actual
    resumed = interrupted.sample(12, 3, resume_run_id="latest")
    def designs(controller):
        with controller.history_store._connect() as con:
            return [tuple(r) for r in con.execute("SELECT sample_method,design_values_json FROM samples ORDER BY sample_id")]
    assert designs(interrupted) == designs(uninterrupted)
    assert resumed.requested_num == 12
    assert sum(resumed.allocation.values()) == 12
    assert resumed.budgets["saved_unique_designs"] == 12
    assert resumed.budgets["extra_or_unsaved_evaluation_attempts"] == 2
    with pytest.raises(ValueError, match="differs"):
        interrupted.sample(13, 1, resume_run_id=resumed.run_id)


def test_bayesian_history_excludes_hidden_labels(tmp_path):
    controller = bare_controller(tmp_path)
    for value, level in [(1., "train_visible"), (2., "hidden_eval"), (3., "final_blind")]:
        run = controller.history_store.create_run(1, 1, {"random": 1}, {}, access_level=level)
        controller.history_store.write_batch(run, [[value]], [[100]], ["random"], [],
                                              access_level=level, observations=[{"feasible": True}])
    designs, labels, excluded = controller._observed()
    assert designs == [[1.]] and labels == [True]
    assert len(excluded) == 3  # Dedup uses keys only, never their labels.


def test_result_transaction_failure_keeps_old_pending_state(tmp_path):
    controller = bare_controller(tmp_path)
    actual = controller.history_store.write_batch
    with patch.object(controller.history_store, "write_batch", side_effect=sqlite3.OperationalError("disk full")):
        with pytest.raises(sqlite3.OperationalError):
            controller.sample(4, 1)
    with controller.history_store._connect() as con:
        saved = json.loads(con.execute("SELECT state_json FROM sampling_state").fetchone()[0])
        assert sum(saved["completed"].values()) == 0 and saved["pending"] is not None
    controller.history_store.write_batch = actual
    result = controller.sample(4, 1, resume_run_id="latest")
    assert result.budgets["saved_unique_designs"] == 4


def test_interrupt_during_gmid_generation_keeps_accepted_draft(tmp_path):
    def configure(controller):
        controller.sampling_config["method_weights"] = dict(zip(METHODS, [0, 0, 0, 1, 0]))
        controller.sampling_config["batch_size"] = 4
        controller.ir = controller.groups = controller.gmid_targets = None
        controller.context = {"conditions": {"power": {}}}
        controller.lut_cache_path = tmp_path
        controller.simulator.ngspice_command = "unused"
        controller.simulator.timeout_seconds = 1
        return controller
    class ProposalSampler:
        stop_at = None
        calls = 0
        def __init__(self, *args):
            self.domain = args[1]
        def propose(self, rng):
            type(self).calls += 1
            if self.calls == self.stop_at:
                raise KeyboardInterrupt()
            return self.domain.random(rng, 1)[0], {"gmid_targets": {"W": 12.}}
    with patch("src.sample_optimize.advanced.controller.MosLUT.ensure", return_value=(None, "lut")), patch("src.sample_optimize.advanced.controller.GmidSampler", ProposalSampler):
        original = configure(bare_controller(tmp_path / "original"))
        original.sample(4, 1)
        ProposalSampler.calls = 0
        ProposalSampler.stop_at = 3
        resumed = configure(bare_controller(tmp_path / "resumed"))
        with pytest.raises(KeyboardInterrupt):
            resumed.sample(4, 1)
        with resumed.history_store._connect() as con:
            saved = json.loads(con.execute("SELECT state_json FROM sampling_state").fetchone()[0])
            assert len(saved["draft"]["points"]) == 2
        ProposalSampler.stop_at = None
        resumed.sample(4, 1, resume_run_id="latest")
        assert original.history_store.design_csv_path.read_bytes() == resumed.history_store.design_csv_path.read_bytes()


def test_gmid_coupled_sizing_retains_engineering_grids():
    ir = parse_circuit(PROJECT / "Sample_Optimizer_Circuit/5t_ota/5t_ota.sp")
    names = list(ir.parameter_defaults)
    bounds = [[1e-7, 20e-6, 1e-7] if n == "IBIAS_A" else [1, 3, 1] if n == "M_FACTOR"
              else [.15, 1., .05] if n.startswith("L") else [1., 10., .1] for n in names]
    domain = DesignDomain(names, bounds)
    config = load_config()["gmid"]
    groups, _, targets = make_profile("5t_ota", ir, config)
    metadata = {"length_m": domain.axes[names.index("LIN")]*1e-6,
                "reverse_body_bias_v": np.linspace(0, 1.8, 7),
                "vgs_v": np.linspace(0, 1.8, 91), "vds_v": np.linspace(0, 1.8, 37)}
    length, body, vg, vd = np.meshgrid(*metadata.values(), indexing="ij")
    overdrive = np.maximum(vg-.35-.1*body, 0.)
    # Independent square-law oracle: ID/W is in A/m, W/L is dimensionless.
    current = 50e-6/length * np.where(vd < overdrive, overdrive*vd-.5*vd**2, .5*overdrive**2)
    gm = 50e-6/length * np.minimum(overdrive, vd)
    values = np.stack([current, gm, overdrive], axis=-1)
    lut = MosLUT(metadata, {"NMOS": values, "PMOS": values})
    sampler = GmidSampler(ir, domain, groups, targets, lut, {"VDD": 1.8, "VSS": 0, "VCM": .9}, config)
    rng = np.random.default_rng(9)
    accepted = None
    for _ in range(50):
        point, info = sampler.propose(rng)
        if point is not None:
            accepted = point
            break
    assert accepted is not None
    assert all(np.isclose(value, axis, atol=1e-12, rtol=1e-12).any() for value, axis in zip(accepted, domain.axes))
    assert info["lut_solver_error"] <= config["solver_tolerance"]
    assert all(value in targets[name] for name, value in info["gmid_targets"].items())
    assert info["nominal_reference_current_a"] == accepted[names.index("IBIAS_A")]


def test_quota_exhaustion_preserves_progress_without_substitution(tmp_path):
    controller = bare_controller(tmp_path)
    controller.sampling_config["method_weights"] = dict(zip(METHODS, [0, 0, 0, 1, 0]))
    controller.sampling_config["max_proposals_per_point"] = 1
    controller.ir = controller.groups = controller.gmid_targets = None
    controller.context = {"conditions": {"power": {}}}
    controller.lut_cache_path = tmp_path
    controller.simulator.ngspice_command = "unused"
    controller.simulator.timeout_seconds = 1
    class Reject:
        def __init__(self, *args): pass
        def propose(self, rng):
            return None, {"rejection": "width_out_of_range"}
    with patch("src.sample_optimize.advanced.controller.MosLUT.ensure", return_value=(None, "lut")), patch("src.sample_optimize.advanced.controller.GmidSampler", Reject):
        with pytest.raises(RuntimeError, match="no method substitution"):
            controller.sample(1, 1)
    with controller.history_store._connect() as con:
        assert con.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 0
        state = json.loads(con.execute("SELECT state_json FROM sampling_state").fetchone()[0])
        assert state["proposals"]["gmid"] == 1
        assert state["rejections"] == {"width_out_of_range": 1}
        assert state["draft"]["method"] == "gmid"
