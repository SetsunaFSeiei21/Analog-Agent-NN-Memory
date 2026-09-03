from pathlib import Path
from simulator import simulate
from typing import List, Dict

import random
import numpy as np
import torch

from scipy.stats import norm
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import (
    Matern,
    ConstantKernel
)


SAMPLE_BOUNDARY = {
    "WIN_VAL": (2, 80),
    "WLOAD_VAL": (2, 80),
    "WTAIL_VAL": (2, 80)
}

STEP = 0.5

SEED = 42

SAMPLE_NUM = 40

BO_ITERATION = 30

CANDIDATE_NUM = 50000

SPICE_PATH = Path("./test/ota5")


# ============================================================
# 1. Random Seed
# ============================================================

def seed(seed_num: int):

    random.seed(seed_num)

    np.random.seed(seed_num)

    torch.manual_seed(seed_num)

    if torch.cuda.is_available():

        torch.cuda.manual_seed(seed_num)

        torch.cuda.manual_seed_all(seed_num)

    torch.backends.cudnn.deterministic = True

    torch.backends.cudnn.benchmark = False


# ============================================================
# 2. Build Discrete Grid
# ============================================================

def build_value_grid(
    low: float,
    high: float,
    step: float
) -> np.ndarray:

    n = int(
        round(
            (high - low) / step
        )
    )

    return (
        low
        +
        np.arange(n + 1) * step
    )


# ============================================================
# 3. Random Unique Sampling
# ============================================================

def sample(
    sample_num: int,
    rng: np.random.Generator,
    exclude: set | None = None
) -> List[Dict[str, float]]:

    if exclude is None:
        exclude = set()

    value_grid = {
        name: build_value_grid(
            low,
            high,
            STEP
        )
        for name, (low, high)
        in SAMPLE_BOUNDARY.items()
    }

    sample_points = []

    seen = set(exclude)

    while len(sample_points) < sample_num:

        params = {
            name: float(
                rng.choice(values)
            )
            for name, values
            in value_grid.items()
        }

        key = tuple(
            params[name]
            for name in SAMPLE_BOUNDARY
        )

        if key in seen:
            continue

        seen.add(key)

        sample_points.append(
            params
        )

    return sample_points


# ============================================================
# 4. Normalize X
# ============================================================

def normalize_x(
    X: np.ndarray
) -> np.ndarray:

    lower = np.asarray(
        [
            bound[0]
            for bound
            in SAMPLE_BOUNDARY.values()
        ],
        dtype=float
    )

    upper = np.asarray(
        [
            bound[1]
            for bound
            in SAMPLE_BOUNDARY.values()
        ],
        dtype=float
    )

    return (
        (X - lower)
        /
        (upper - lower)
    )


# ============================================================
# 5. Build Gaussian Process
# ============================================================

def build_gp(
    param_num: int
) -> GaussianProcessRegressor:

    kernel = (
        ConstantKernel(
            constant_value=1.0,
            constant_value_bounds=(
                1e-3,
                1e3
            )
        )
        *
        Matern(
            length_scale=np.ones(
                param_num
            ),
            length_scale_bounds=(
                1e-2,
                1e2
            ),
            nu=2.5
        )
    )

    gp = GaussianProcessRegressor(
        kernel=kernel,
        alpha=1e-6,
        normalize_y=True,
        n_restarts_optimizer=5,
        random_state=SEED
    )

    return gp


# ============================================================
# 6. Expected Improvement
# ============================================================

def expected_improvement(
    X_candidate: np.ndarray,
    gp: GaussianProcessRegressor,
    best_y: float,
    xi: float = 0.01
) -> np.ndarray:

    mu, sigma = gp.predict(
        X_candidate,
        return_std=True
    )

    improvement = (
        mu
        -
        best_y
        -
        xi
    )

    ei = np.zeros_like(
        mu
    )

    valid = (
        sigma > 1e-12
    )

    z = np.zeros_like(
        mu
    )

    z[valid] = (
        improvement[valid]
        /
        sigma[valid]
    )

    ei[valid] = (
        improvement[valid]
        *
        norm.cdf(
            z[valid]
        )
        +
        sigma[valid]
        *
        norm.pdf(
            z[valid]
        )
    )

    return ei


# ============================================================
# 7. Suggest Next Point
# ============================================================

def suggest_next_point(
    gp: GaussianProcessRegressor,
    best_y: float,
    rng: np.random.Generator,
    evaluated_points: set,
    candidate_num: int
) -> Dict[str, float]:

    candidates = sample(
        sample_num=candidate_num,
        rng=rng,
        exclude=evaluated_points
    )

    X_candidate = np.asarray(
        [
            [
                point[name]
                for name
                in SAMPLE_BOUNDARY
            ]
            for point
            in candidates
        ],
        dtype=float
    )

    X_candidate_norm = normalize_x(
        X_candidate
    )

    ei = expected_improvement(
        X_candidate=X_candidate_norm,
        gp=gp,
        best_y=best_y
    )

    best_index = int(
        np.argmax(ei)
    )

    return candidates[
        best_index
    ]


# ============================================================
# 8. Main
# ============================================================

def main():

    seed(SEED)

    rng = np.random.default_rng(
        SEED
    )

    # --------------------------------------------------------
    # Initial Sampling
    # --------------------------------------------------------

    start_points = sample(
        SAMPLE_NUM,
        rng
    )

    X = []

    Y = []

    for i, point in enumerate(
        start_points
    ):

        print(
            f"\n===== Initial "
            f"{i + 1}/{SAMPLE_NUM} ====="
        )

        print(
            "Parameters:",
            point
        )

        dc_gain = simulate(
            point,
            SPICE_PATH
        )

        print(
            f"DC Gain = "
            f"{dc_gain:.4f} dB"
        )

        x = [
            point[name]
            for name
            in SAMPLE_BOUNDARY
        ]

        X.append(x)

        Y.append(dc_gain)

    X = np.asarray(
        X,
        dtype=float
    )

    Y = np.asarray(
        Y,
        dtype=float
    )

    evaluated_points = {
        tuple(x)
        for x in X
    }

    # --------------------------------------------------------
    # Bayesian Optimization
    # --------------------------------------------------------

    for iteration in range(
        BO_ITERATION
    ):

        print(
            f"\n===== BO "
            f"{iteration + 1}/"
            f"{BO_ITERATION} ====="
        )

        # 1. Train GP

        gp = build_gp(
            param_num=X.shape[1]
        )

        X_norm = normalize_x(
            X
        )

        gp.fit(
            X_norm,
            Y
        )

        # 2. Current Best

        best_y = float(
            np.max(Y)
        )

        # 3. Acquisition

        next_point = suggest_next_point(
            gp=gp,
            best_y=best_y,
            rng=rng,
            evaluated_points=
                evaluated_points,
            candidate_num=
                CANDIDATE_NUM
        )

        print(
            "Suggested parameters:",
            next_point
        )

        # 4. Real ngspice

        next_gain = simulate(
            next_point,
            SPICE_PATH
        )

        print(
            f"New DC Gain = "
            f"{next_gain:.4f} dB"
        )

        # 5. Update Dataset

        next_x = np.asarray(
            [
                next_point[name]
                for name
                in SAMPLE_BOUNDARY
            ],
            dtype=float
        )

        X = np.vstack(
            [
                X,
                next_x
            ]
        )

        Y = np.append(
            Y,
            next_gain
        )

        evaluated_points.add(
            tuple(next_x)
        )

        # 6. Best So Far

        best_index = int(
            np.argmax(Y)
        )

        print(
            f"Best Gain So Far = "
            f"{Y[best_index]:.4f} dB"
        )

    # --------------------------------------------------------
    # Final Result
    # --------------------------------------------------------

    best_index = int(
        np.argmax(Y)
    )

    print(
        "\n===== Final Result ====="
    )

    print(
        "Best Parameters:"
    )

    for i, name in enumerate(
        SAMPLE_BOUNDARY
    ):

        print(
            f"{name}: "
            f"{X[best_index, i]}"
        )

    print(
        f"Best DC Gain: "
        f"{Y[best_index]:.4f} dB"
    )


if __name__ == "__main__":
    main()