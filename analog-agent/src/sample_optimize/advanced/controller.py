from __future__ import annotations

import fcntl
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.stats import qmc

from ...circuit_ir import parse_circuit
from ..sampling_controller import Sampling_Controller
from .bayesian import ConstrainedBayesianSampler
from .config import DesignDomain, METHODS, allocate, load_config
from .context import bind_context, digest, simulation_context, source_identity
from .gmid import GmidSampler
from .lut import MosLUT
from .profiles import make_profile


@dataclass(frozen=True)
class DatasetSamplingResult:
    run_id: str
    database_path: Path
    design_csv_path: Path
    metrics_csv_path: Path
    requested_num: int
    allocation: dict
    metric_complete_num: int
    electrically_feasible_num: int
    budgets: dict


class DatasetSamplingController(Sampling_Controller):
    """Five methods, sequential feedback, context isolation and atomic resume."""
    def __init__(self, *, sampling_config_path=None, lut_cache_path=None, **kwargs):
        self.sampling_config = load_config(sampling_config_path)
        # Rollback journaling avoids WAL shared-memory assumptions on HPC
        # shared storage. Writes are brief and serialized by SQLite.
        self._history_journal_mode = "DELETE"
        if set(kwargs.get("metrics", ())) != {"DC_GAIN", "UGF", "PM", "CMRR", "P_PSRR", "N_PSRR", "P_SR", "N_SR", "POWER"}:
            raise ValueError("Dataset sampling requires the canonical nine metrics")
        canonical = ["DC_GAIN", "UGF", "PM", "CMRR", "P_PSRR", "N_PSRR", "P_SR", "N_SR", "POWER"]
        kwargs["metrics"] = canonical
        root = Path(kwargs["target_path"]).resolve()
        root.mkdir(parents=True, exist_ok=True)
        self._dataset_lock = (root / f".{kwargs['circuit_name']}.dataset.lock").open("a")
        try:
            fcntl.flock(self._dataset_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            super().__init__(**kwargs)
            self.context = simulation_context(self.src_path, self.circuit_name, self.simulator)
            self.context_fingerprint = bind_context(self.history_store.database_path, self.context)
            self.ir = parse_circuit(self.circuit_path, self.parameter_path)
            self.domain = DesignDomain(self.parameter_name_lst, self.bounds)
            self.groups, self.signal_devices, self.gmid_targets = make_profile(self.circuit_name, self.ir, self.sampling_config["gmid"])
            self.lut_cache_path = Path(lut_cache_path) if lut_cache_path else root / ".lut_cache"
            self.simulator.operating_point_config = {
                "circuit": self.ir, "condition": {**self.context["conditions"]["power"], "MOS_PRIMITIVES": self.context["mos_primitives"]},
                "constraints": self.sampling_config["constraints"], "signal_devices": self.signal_devices}
        except BaseException:
            self.close()
            raise

    def _find_history(self):
        source = self.src_path.resolve()
        history = (self.target_path / self.circuit_name).resolve()
        self._validate_circuit_directory(source, "源电路目录")
        if history.exists():
            self._validate_circuit_directory(history, "历史电路目录")
            if source_identity(source, self.circuit_name) != source_identity(history, self.circuit_name):
                raise ValueError("Source netlist/parameters/initialization differ from archived history; choose a new target directory")
        else:
            if source in history.parents:
                raise ValueError("Target cannot be inside the source directory")
            shutil.copytree(source, history)
        self.has_history = history.exists()
        self.src_path = history
        self._set_circuit_paths()

    def _save_state(self, run_id, state):
        with self.history_store._connect() as con:
            con.execute("INSERT OR REPLACE INTO sampling_state VALUES (?,?)", (run_id, json.dumps(state, allow_nan=False)))

    def _observed(self):
        # Restrict label reads in SQL, before deserialization. Unknown OPs are not negative labels.
        with self.history_store._connect() as con:
            rows = con.execute("SELECT design_values_json,observation_json FROM samples WHERE access_level='train_visible' AND observation_json IS NOT NULL ORDER BY sample_id").fetchall()
            all_keys = {r[0] for r in con.execute("SELECT design_key FROM samples")}
        designs, feasible = [], []
        for row in rows:
            obs = json.loads(row[1])
            designs.append(json.loads(row[0]))
            feasible.append(bool(obs["feasible"]))
        return designs, feasible, all_keys

    def sample(self, n_points, n_workers, continue_on_error=True, *, resume_run_id=None):
        if not isinstance(n_workers, int) or isinstance(n_workers, bool) or n_workers <= 0:
            raise ValueError("n_workers must be a positive integer")
        if continue_on_error is not True:
            raise ValueError("Dataset mode preserves partial labels: use --continue_on_error")
        if self.sample_access_level != "train_visible":
            raise ValueError("Adaptive dataset mode accepts train_visible only; hidden/final evaluation labels must never guide proposals")
        allocation = allocate(n_points, self.sampling_config["method_weights"])
        configuration = {"schema_version": 1, "sampling": self.sampling_config, "bounds": self.bounds,
                         "names": self.parameter_name_lst, "metrics": self.simulator.metrics,
                         "seed": self.seed, "access_level": self.sample_access_level,
                         "context_fingerprint": self.context_fingerprint,
                         "implementation": {p.name: digest(p.read_text()) for p in Path(__file__).parent.glob("*.py")}}
        fingerprint = digest(configuration)
        with self.history_store._connect() as con:
            if resume_run_id == "latest":
                row = con.execute("SELECT r.run_id FROM sampling_runs r JOIN sampling_state s USING(run_id) WHERE r.status IN ('RUNNING','FAILED') ORDER BY r.started_at DESC LIMIT 1").fetchone()
                if row is None:
                    raise ValueError("No unfinished resumable run")
                resume_run_id = row[0]
            unfinished = con.execute("SELECT run_id FROM sampling_runs WHERE source='five_method' AND status IN ('RUNNING','FAILED') ORDER BY started_at").fetchall()
            if resume_run_id is None and unfinished:
                raise ValueError(f"An unfinished run exists: {unfinished[-1][0]}; use --resume_run_id latest")
            if resume_run_id is not None:
                row = con.execute("SELECT r.*,s.state_json FROM sampling_runs r JOIN sampling_state s USING(run_id) WHERE r.run_id=?", (resume_run_id,)).fetchone()
                if row is None:
                    raise ValueError("Unknown resumable run")
                state = json.loads(row["state_json"])
                if state["config_fingerprint"] != fingerprint or row["requested_points"] != n_points:
                    raise ValueError("Resume configuration/seed/context/n_points differs from original run")
                run_id = resume_run_id
                con.execute("UPDATE sampling_runs SET status='RUNNING', completed_at=NULL,error_message=NULL,n_workers=? WHERE run_id=?", (n_workers, run_id))
        if resume_run_id is None:
            generators = {name: np.random.default_rng(seed) for name, seed in zip(METHODS, np.random.SeedSequence(self.seed).spawn(5))}
            state = {"schema_version": 1, "config_fingerprint": fingerprint, "allocation": allocation,
                     "completed": {m: 0 for m in METHODS}, "proposals": {m: 0 for m in METHODS},
                     "rejections": {}, "duplicates": 0, "pending": None, "draft": None,
                     "rng": {name: rng.bit_generator.state for name, rng in generators.items()}}
            run_id = self.history_store.create_run(n_points, n_workers, allocation, configuration,
                                                 source="five_method", access_level=self.sample_access_level,
                                                 initial_state=state)
        generators = {m: np.random.default_rng() for m in METHODS}
        for name, rng in generators.items():
            rng.bit_generator.state = state["rng"][name]
        self.simulator.invocation_ledger = (str(self.history_store.database_path), run_id)
        gmid = None
        limits = {m: state["proposals"][m] + self.sampling_config["max_proposals_per_point"] * (allocation[m]-state["completed"][m]) for m in METHODS}
        bayesian = ConstrainedBayesianSampler(self.domain, self.sampling_config["bayesian"])
        try:
            if allocation["gmid"] > state["completed"]["gmid"]:
                lut, lut_key = MosLUT.ensure(self.lut_cache_path, self.context, self.domain, self.groups,
                    self.sampling_config["gmid"]["lut"], self.simulator.ngspice_command,
                    self.simulator.timeout_seconds, str(self.history_store.database_path), run_id, self.logger)
                gmid = GmidSampler(self.ir, self.domain, self.groups, self.gmid_targets, lut,
                                  self.context["conditions"]["power"], self.sampling_config["gmid"])
                state["lut_key"] = lut_key
            while sum(state["completed"].values()) < n_points:
                if state["pending"] is None:
                    # Weighted round-robin: every round feeds Bayesian selection fresh OPs.
                    remaining = [m for m in METHODS if state["completed"][m] < allocation[m]]
                    draft = state.get("draft")
                    method = draft["method"] if draft else min(remaining, key=lambda m: (state["completed"][m] / allocation[m], METHODS.index(m)))
                    count = draft["count"] if draft else min(self.sampling_config["batch_size"], allocation[method] - state["completed"][method])
                    designs, feasible, excluded = self._observed()
                    points, proposals = (draft["points"], draft["proposals"]) if draft else ([], [])
                    excluded.update(self.history_store.design_key(p) for p in points)
                    state["draft"] = {"method": method, "count": count, "points": points, "proposals": proposals}
                    limit = limits[method]
                    rng = generators[method]
                    while len(points) < count:
                        if state["proposals"][method] >= limit:
                            raise RuntimeError(f"{method} exhausted proposal limit; progress saved. Review domain/LUT/grids or reduce requested quota; no method substitution.")
                        needed = count-len(points)
                        metadata = []
                        if method == "gmid":
                            point, info = gmid.propose(rng)
                            state["proposals"][method] += 1
                            if point is None:
                                reason = info["rejection"]
                                state["last_gmid_rejection"] = info
                                state["rejections"][reason] = state["rejections"].get(reason, 0)+1
                                if state["proposals"][method] % 100 == 0:
                                    state["rng"] = {m: gen.bit_generator.state for m, gen in generators.items()}
                                    self._save_state(run_id, state)
                                    self.logger.info("gm/ID proposals=%d; accepted draft=%d/%d; latest rejection=%s", state["proposals"][method], len(points), count, reason)
                                continue
                            candidates, metadata = [point], [{**info, "lut_key": state["lut_key"]}]
                        elif method == "bayesian":
                            candidates, metadata = bayesian.propose(rng, designs, feasible, excluded, needed)
                            state["proposals"][method] += self.sampling_config["bayesian"]["candidate_pool_size"]
                        else:
                            seed = int(rng.integers(0, 2**32))
                            if method == "sobol":
                                unit = qmc.Sobol(len(self.domain.names), scramble=True, seed=seed).random_base2(int(np.ceil(np.log2(max(needed, 1)))))
                            elif method == "lhs":
                                unit = qmc.LatinHypercube(len(self.domain.names), seed=seed).random(needed)
                            else:
                                unit = rng.random((needed, len(self.domain.names)))
                            candidates = self.domain.project(unit)
                            state["proposals"][method] += len(candidates)
                            metadata = [{"proposal_seed": seed}] * len(candidates)
                        for candidate, info in zip(candidates, metadata):
                            key = self.history_store.design_key(candidate)
                            if key in excluded:
                                state["duplicates"] += 1
                                continue
                            excluded.add(key)
                            points.append(np.asarray(candidate).tolist())
                            proposals.append(info)
                            if len(points) == count:
                                break
                    state["rng"] = {m: gen.bit_generator.state for m, gen in generators.items()}
                    state["draft"] = None
                    state["pending"] = {"method": method, "points": points, "proposals": proposals}
                    self._save_state(run_id, state)  # Before launching: redraws cannot change probes.
                pending = state["pending"]
                points = np.asarray(pending["points"])
                result = self.simulator.simulate_batch(self.src_path, n_workers, points, continue_on_error=True)
                if len(result.observations) != len(points):
                    raise RuntimeError("Missing operating-point observations")
                state["completed"][pending["method"]] += len(points)
                state["pending"] = None
                self.history_store.write_batch(run_id, points, result.metrics, [pending["method"]]*len(points), result.failure_records,
                                              access_level=self.sample_access_level, observations=result.observations,
                                              proposals=pending["proposals"], next_state=state)
                self.history_store.export_csv()
                self.logger.info("Five-method progress: %s / %s", state["completed"], allocation)
            with self.history_store._connect() as con:
                rows = con.execute("SELECT success,observation_json FROM samples WHERE run_id=?", (run_id,)).fetchall()
            complete = sum(row[0] for row in rows)
            good = sum(json.loads(row[1])["feasible"] for row in rows)
            self.history_store.mark_run_completed(run_id, n_points-complete)
            self.history_store.export_csv()
            budgets = self.budget(run_id)
            return DatasetSamplingResult(run_id, self.history_store.database_path,
                self.history_store.design_csv_path, self.history_store.metrics_csv_path,
                n_points, allocation, complete, good, budgets)
        except BaseException as exc:
            # If a result transaction committed, load it before changing status.
            # The saved pending batch otherwise remains eligible for rerun.
            if state["pending"] is None:
                with self.history_store._connect() as con:
                    current = con.execute("SELECT state_json FROM sampling_state WHERE run_id=?", (run_id,)).fetchone()
                persisted = json.loads(current[0])
                if persisted.get("pending") is None and persisted["completed"] == state["completed"]:
                    state["rng"] = {m: gen.bit_generator.state for m, gen in generators.items()}
                    self._save_state(run_id, state)
            self.history_store.mark_run_failed(run_id, exc)
            self.history_store.export_csv()
            raise

    def budget(self, run_id):
        with self.history_store._connect() as con:
            invocations = con.execute("SELECT category,status,COUNT(*) FROM spice_invocations WHERE run_id=? GROUP BY category,status", (run_id,)).fetchall()
            state = json.loads(con.execute("SELECT state_json FROM sampling_state WHERE run_id=?", (run_id,)).fetchone()[0])
            count = con.execute("SELECT COUNT(*) FROM samples WHERE run_id=?", (run_id,)).fetchone()[0]
            attempts = con.execute("SELECT COUNT(*) FROM spice_invocations WHERE run_id=? AND category='design' AND bench='operating_point'", (run_id,)).fetchone()[0]
        return {"saved_unique_designs": count, "design_evaluation_attempts": attempts,
                "extra_or_unsaved_evaluation_attempts": max(attempts-count, 0),
                "spice_invocations": {f"{r[0]}:{r[1]}": r[2] for r in invocations},
                "proposal_counts": state["proposals"], "pre_spice_rejections": state["rejections"],
                "duplicate_proposals": state["duplicates"]}

    def close(self):
        if hasattr(self, "logger"):
            super().close()
        lock = getattr(self, "_dataset_lock", None)
        if lock and not lock.closed:
            lock.close()
