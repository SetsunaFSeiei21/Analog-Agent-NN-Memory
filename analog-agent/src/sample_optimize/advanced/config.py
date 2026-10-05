from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import numpy as np

METHODS = ("random", "lhs", "sobol", "gmid", "bayesian")
DEFAULTS = {
    "schema_version": 1,
    "method_weights": {name: 0.2 for name in METHODS},
    "batch_size": 32,
    "max_proposals_per_point": 2000,
    "gmid": {
        "default_range": [8.0, 20.0, 0.5],
        "group_gmid_overrides": {},
        "max_solver_evaluations": 120,
        "solver_tolerance": 0.08,
        "condition_lengths_on_width": True,
        "lut": {"vgs": [0.0, 1.8, 0.02], "vds": [0.0, 1.8, 0.05],
                "reverse_body_bias": [0.0, 1.8, 0.3], "max_lengths": 12,
                "reference_width_um": 10.0},
    },
    "constraints": {"follower_error_max_v": 0.05, "saturation_margin_min_v": 0.0,
                    "min_signal_current_a": 1e-12},
    "bayesian": {"warmup_points": 32, "candidate_pool_size": 1024,
                 "max_training_points": 256, "length_scale": 0.25,
                 "noise_variance": 0.02, "exploration_fraction": 0.2,
                 "boundary_weight": 0.25, "coverage_weight": 0.2},
}


def grid(triplet):
    if not isinstance(triplet, (list, tuple)) or len(triplet) != 3:
        raise ValueError("Grid must be [minimum, maximum, step]")
    if any(isinstance(v, bool) or not isinstance(v, (float, int)) for v in triplet):
        raise ValueError("Grid entries must be numbers")
    lo, hi, step = map(float, triplet)
    if not np.isfinite([lo, hi, step]).all() or hi < lo or step <= 0:
        raise ValueError(f"Invalid grid: {triplet}")
    return lo + step * np.arange(int(np.floor((hi - lo) / step + 1e-9)) + 1)


def _merge(default, value, location="config"):
    if not isinstance(value, dict):
        raise ValueError(f"{location} must be an object")
    result = deepcopy(default)
    for key, val in value.items():
        if key not in default:
            raise ValueError(f"Unknown setting: {location}.{key}")
        if key in {"group_gmid_overrides", "method_weights"}:
            result[key] = {} if val is None else deepcopy(val)
        elif isinstance(default[key], dict):
            result[key] = _merge(default[key], val, f"{location}.{key}")
        else:
            result[key] = val
    return result


def load_config(path=None):
    config = _merge(DEFAULTS, {} if path is None else json.loads(Path(path).read_text()))
    if config["schema_version"] != 1:
        raise ValueError("Unsupported sampling schema version")
    weights = config["method_weights"]
    if not isinstance(weights, dict) or set(weights) != set(METHODS):
        raise ValueError(f"method_weights must specify {METHODS}")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or
           not np.isfinite(v) or v < 0 for v in weights.values()) or sum(weights.values()) <= 0:
        raise ValueError("Method weights must be finite, nonnegative, with positive total")
    for key in ("batch_size", "max_proposals_per_point"):
        _positive_int(config[key], key)
    gmid, bayes = config["gmid"], config["bayesian"]
    if grid(gmid["default_range"])[0] <= 0:
        raise ValueError("gm/ID must be positive")
    if not isinstance(gmid["group_gmid_overrides"], dict):
        raise ValueError("group_gmid_overrides must be an optional object")
    for key in ("warmup_points", "candidate_pool_size", "max_training_points"):
        _positive_int(bayes[key], key)
    _positive_int(gmid["max_solver_evaluations"], "max_solver_evaluations")
    if not isinstance(gmid["condition_lengths_on_width"], bool):
        raise ValueError("condition_lengths_on_width must be boolean")
    _positive_int(gmid["lut"]["max_lengths"], "max_lengths")
    for key in ("vgs", "vds", "reverse_body_bias"):
        values = grid(gmid["lut"][key])
        if len(values) < 2 or values[0] != 0:
            raise ValueError(f"LUT {key} must start at zero and have at least two values")
    for value in [gmid["solver_tolerance"], gmid["lut"]["reference_width_um"],
                  bayes["length_scale"], bayes["noise_variance"]]:
        if not isinstance(value, (int, float)) or not np.isfinite(value) or value <= 0:
            raise ValueError("Solver/LUT/kernel settings must be finite and positive")
    for key in ("exploration_fraction", "boundary_weight", "coverage_weight"):
        if not isinstance(bayes[key], (int, float)) or not 0 <= bayes[key] <= 1:
            raise ValueError(f"{key} must be in [0, 1]")
    for key, value in config["constraints"].items():
        if not isinstance(value, (int, float)) or not np.isfinite(value):
            raise ValueError(f"Invalid constraint: {key}")
    if config["constraints"]["follower_error_max_v"] <= 0 or config["constraints"]["min_signal_current_a"] < 0:
        raise ValueError("Follower tolerance must be positive; minimum current nonnegative")
    return config


def _positive_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def allocate(count, weights):
    _positive_int(count, "n_points")
    raw = count * np.array([weights[m] for m in METHODS]) / sum(weights.values())
    numbers = np.floor(raw).astype(int)
    for i in np.argsort(-(raw - numbers), kind="stable")[:count - numbers.sum()]:
        numbers[i] += 1
    return dict(zip(METHODS, numbers.tolist()))


class DesignDomain:
    """The same discrete physical domain for every proposal method."""
    def __init__(self, names, bounds):
        self.names = tuple(names)
        self.axes = [grid(b) for b in bounds]
        self.bounds = np.asarray(bounds, dtype=float)
        self.sizes = np.asarray([len(a) for a in self.axes])

    def project(self, unit):
        unit = np.asarray(unit)
        indices = np.minimum((np.clip(unit, 0, 1) * self.sizes).astype(int), self.sizes - 1)
        return np.column_stack([axis[indices[..., i]] for i, axis in enumerate(self.axes)])

    def random(self, rng, count):
        return self.project(rng.random((count, len(self.names))))

    def normalize(self, designs):
        lo = self.bounds[:, 0]
        hi = np.array([a[-1] for a in self.axes])
        return (np.asarray(designs) - lo) / np.maximum(hi - lo, 1e-30)

    def quantize_width(self, name, value):
        i = self.names.index(name)
        axis = self.axes[i]
        if not np.isfinite(value) or value < axis[0] - 1e-10 or value > axis[-1] + 1e-10:
            raise ValueError(f"Computed width {name}={value} is outside its physical range")
        return float(axis[np.argmin(abs(axis - value))])
