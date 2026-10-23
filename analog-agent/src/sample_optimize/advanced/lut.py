from __future__ import annotations

import json
import os
import fcntl
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter

import numpy as np
from scipy.interpolate import RegularGridInterpolator

from .config import grid
from .context import digest, record_invocation


class MosLUT:
    """Safe numeric NPZ tables; signed PMOS bias is normalized at the boundary.

    Uses medwatt/gmid's multidimensional ID/W and gm/ID lookup approach.
    No pickle, inverse extrapolation, or assumption that bodies equal sources.
    """
    def __init__(self, metadata, arrays):
        self.metadata = metadata
        self.vgs_axis = np.asarray(metadata["vgs_v"])
        voltage_axes = [np.asarray(metadata[k]) for k in ("reverse_body_bias_v", "vgs_v", "vds_v")]
        self.axes = {model: [np.asarray(spec["length_m"]), *voltage_axes]
                     for model, spec in metadata["model_tables"].items()}
        self.functions = {model: RegularGridInterpolator(axes, arrays[model], bounds_error=False,
                                                        fill_value=np.nan) for model, axes in self.axes.items()}

    def lookup(self, model, length_um, body, vgs, vds):
        model = model.lower()
        coordinates = np.broadcast_arrays(np.atleast_1d(length_um)*1e-6, body, vgs, vds)
        shape = coordinates[0].shape
        point = np.stack(coordinates, axis=-1).reshape(-1, 4)
        for i, axis in enumerate(self.axes[model]):
            # Correct floating-point endpoint noise only, never extrapolate bias.
            close = (point[:, i] >= axis[0]-1e-12) & (point[:, i] <= axis[-1]+1e-12)
            point[close, i] = np.clip(point[close, i], axis[0], axis[-1])
        return self.functions[model](point).reshape(*shape, 3)

    @classmethod
    def ensure(cls, cache, context, domain, groups, config, command, timeout, database, run_id, logger, *, circuit, workers=1):
        if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
            raise ValueError("LUT workers must be a positive integer")
        Path(cache).mkdir(parents=True, exist_ok=True)
        with (Path(cache) / ".build.lock").open("a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            return cls._build(cache, context, domain, groups, config, command, timeout, database, run_id, logger,
                              circuit=circuit, workers=workers)

    @classmethod
    def _build(cls, cache, context, domain, groups, config, command, timeout, database, run_id, logger, *, circuit, workers=1):
        started = perf_counter()
        cache = Path(cache)
        cache.mkdir(parents=True, exist_ok=True)
        # The netlist is the authority for both model flavor and its L domain.
        # Combining all NMOS/PMOS lengths can request nonexistent PMOS LVT bins.
        devices = {d.name.upper(): d for d in circuit.devices}
        model_tables, model_lengths = {}, {}
        for group in groups:
            for member_index, member in enumerate(group.members):
                device = devices[member]
                model = device.model.lower()
                spec = {"device_type": device.device_type.value,
                        "subcircuit": device.name.lower().startswith("x")}
                if model in model_tables and model_tables[model] != spec:
                    raise ValueError(f"Inconsistent MOS model usage: {model}")
                model_tables[model] = spec
                member_lengths = getattr(group, "member_lengths", ())
                length_parameter = member_lengths[member_index] if member_lengths else group.length
                model_lengths.setdefault(model, set()).update(
                    float(v) for v in domain.axes[domain.names.index(length_parameter)])
        limit = config["max_lengths"]
        model_tables = dict(sorted(model_tables.items()))
        for model, spec in model_tables.items():
            lengths = sorted(model_lengths[model])
            if len(lengths) > limit:
                lengths = [lengths[i] for i in np.unique(np.rint(np.linspace(0, len(lengths)-1, limit)).astype(int))]
            spec["length_m"] = (np.asarray(lengths) * 1e-6).tolist()
        condition = context["conditions"]["power"]
        metadata = {"schema_version": 2, "implementation": "sky130-model-grid-v2",
                    "models": context["models"], "ngspice_version": context["ngspice_version"],
                    "corner": condition["CORNER"], "temperature_c": condition["TEMP"],
                    "source_initialization": context["initialization"],
                    "global_initialization": context["global_initialization"],
                    "spice_scripts": context["spice_scripts"],
                    "mos_primitives": context["mos_primitives"],
                    "model_tables": model_tables,
                    "reverse_body_bias_v": grid(config["reverse_body_bias"]).tolist(),
                    "vgs_v": grid(config["vgs"]).tolist(), "vds_v": grid(config["vds"]).tolist(),
                    "reference_width_m": config["reference_width_um"] * 1e-6,
                    "fields": ["id_per_width_a_m", "gm_per_width_s_m", "vdsat_v"]}
        supply = float(condition["VDD"]) - float(condition["VSS"])
        if any(metadata[k][-1] < supply-1e-9 for k in ("vgs_v", "vds_v", "reverse_body_bias_v")):
            raise ValueError("LUT voltage axes must cover the actual supply span")
        key = digest(metadata)
        path = cache / f"sky130-{key}.npz"
        if path.exists():
            with np.load(path, allow_pickle=False) as saved:
                if json.loads(str(saved["metadata"])) != metadata:
                    raise ValueError("LUT cache metadata mismatch")
                logger.info("Reuse gm/ID LUT: %s", path)
                return cls(metadata, {model: saved[model] for model in model_tables}), key
        bias_shape = tuple(len(metadata[k]) for k in ("reverse_body_bias_v", "vgs_v", "vds_v")) + (3,)
        arrays = {model: np.empty((len(spec["length_m"]), *bias_shape)) for model, spec in model_tables.items()}
        # A partial build is reusable only when every saved slice is keyed to this metadata.
        slices = cache / f".build-{key}"
        slices.mkdir(exist_ok=True)
        pending = []
        reused = 0
        for model, spec in model_tables.items():
            for li, length_m in enumerate(spec["length_m"]):
                for bi, body in enumerate(metadata["reverse_body_bias_v"]):
                    slice_path = slices / f"{model}-{li}-{bi}.npy"
                    if slice_path.exists():
                        values = np.load(slice_path, allow_pickle=False)
                        if values.shape != bias_shape[1:] or not np.isfinite(values).all():
                            raise ValueError("Invalid partial LUT slice")
                        arrays[model][li, bi] = values
                        reused += 1
                    else:
                        pending.append((model, li, bi, length_m * 1e6, body, slice_path))
        effective_workers = min(workers, len(pending))
        logger.info("Build gm/ID LUT: pending=%d, reused=%d, workers=%d, models=%d, body biases=%d",
                    len(pending), reused, effective_workers, len(model_tables), len(metadata["reverse_body_bias_v"]))

        def characterize(task):
            model, li, bi, length, body, slice_path = task
            slice_started = perf_counter()
            spec = model_tables[model]
            sign = 1 if spec["device_type"] == "NMOS" else -1
            instance = "XREF" if spec["subcircuit"] else "MREF"
            symbol = "m.xref." + context["mos_primitives"][model] if spec["subcircuit"] else "mref"
            with tempfile.TemporaryDirectory(prefix="lut_", dir=cache) as tmp:
                directory = Path(tmp)
                if context["initialization"]:
                    (directory / ".spiceinit").write_text(context["initialization"])
                vg, vd = config["vgs"], config["vds"]
                deck = f'''* gm/ID characterization; numeric W/L are um
.lib "{condition['PDK_PATH']}" {condition['CORNER']}
.option scale=1u
.temp {condition['TEMP']}
{instance} D G 0 B {model} W={config['reference_width_um']} L={length:.15g} m=1
VG G 0 0
VD D 0 0
VB B 0 {-sign * body}
.control
set wr_singlescale
option numdgt=15
save v(g) v(d) i(vd) @{symbol}[gm] @{symbol}[vdsat]
dc VD {sign*vd[0]} {sign*grid(vd)[-1]} {sign*vd[2]} VG {sign*vg[0]} {sign*grid(vg)[-1]} {sign*vg[2]}
let current = abs(i(vd))
let transconductance = abs(@{symbol}[gm])
let saturation = abs(@{symbol}[vdsat])
wrdata table.txt current transconductance saturation
quit
.endc
.end
'''
                (directory / "lut.cir").write_text(deck)
                def launch():
                    return subprocess.run([command, "-b", "-o", "lut.log", "lut.cir"], cwd=directory,
                                          capture_output=True, text=True, timeout=timeout)
                process = record_invocation(database, run_id, key, "lut", f"{model}:{li}:{bi}", launch)
                table = directory / "table.txt"
                if process.returncode != 0 or not table.exists():
                    log = directory / "lut.log"
                    detail = log.read_text(errors="replace") if log.exists() else process.stderr or process.stdout
                    raise RuntimeError(f"LUT characterization failed ({model}:{li}:{bi}): {detail[-3000:]}")
                raw = np.loadtxt(table, ndmin=2)
                if raw.shape != (bias_shape[1] * bias_shape[2], 4) or not np.isfinite(raw).all():
                    raise RuntimeError(f"Unexpected LUT shape/data: {raw.shape}")
                values = raw[:, 1:].reshape(bias_shape[1:])
                values[..., :2] /= metadata["reference_width_m"]
            temporary = slice_path.with_suffix(".tmp.npy")
            np.save(temporary, values, allow_pickle=False)
            os.replace(temporary, slice_path)
            logger.debug("LUT slice timing: %s:%d:%d elapsed=%.3fs", model, li, bi, perf_counter()-slice_started)
            return model, li, bi, values

        if pending:
            # Threads only orchestrate independent ngspice processes. Each slice has
            # its own workspace, durable invocation record and atomic cache file.
            with ThreadPoolExecutor(max_workers=effective_workers) as executor:
                futures = [executor.submit(characterize, task) for task in pending]
                try:
                    for done, future in enumerate(as_completed(futures), 1):
                        model, li, bi, values = future.result()
                        arrays[model][li, bi] = values
                        if done % effective_workers == 0 or done == len(pending):
                            logger.info("LUT progress: %d/%d new slices, elapsed=%.3fs", done, len(pending), perf_counter()-started)
                except BaseException:
                    # Finish active launches before releasing the build lock; keep
                    # their completed slices so the next call only fills gaps.
                    for future in futures:
                        future.cancel()
                    raise
        temporary = path.with_suffix(".tmp.npz")
        np.savez_compressed(temporary, metadata=json.dumps(metadata, sort_keys=True), **arrays)
        os.replace(temporary, path)
        logger.info("LUT ready: %s, elapsed=%.3fs", path, perf_counter()-started)
        return cls(metadata, arrays), key
